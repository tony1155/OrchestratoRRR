from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from autogame_orchestrator.config_loader import _parse_maa_sync
from autogame_orchestrator.config_model import MAASyncConfig
from autogame_orchestrator.maa_sync.transformer import MAATransformError, transform_gui_configuration
from autogame_orchestrator.models import ErrorCode


def test_default_disabled() -> None:
    assert MAASyncConfig().enabled is False


def test_disabled_allows_empty_paths() -> None:
    assert MAASyncConfig().validate() == []
    assert MAASyncConfig().check_paths() == []


@pytest.mark.parametrize("value", ["true", 1, 0, [], {}])
def test_enabled_requires_strict_bool(value: object) -> None:
    assert MAASyncConfig(enabled=value).validate() == [ErrorCode.CONFIG_SCHEMA_ERROR]  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["true", 1, 0, [], {}])
def test_backup_requires_strict_bool(value: object) -> None:
    assert MAASyncConfig(backup_enabled=value).validate() == [ErrorCode.CONFIG_SCHEMA_ERROR]  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, False, 0, -1, "10", 1.5])
def test_max_source_bytes_requires_positive_integer(value: object) -> None:
    assert MAASyncConfig(max_source_bytes=value).validate() == [ErrorCode.CONFIG_SCHEMA_ERROR]  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    ["gui_settings_source", "gui_tasks_source", "cli_profile_destination", "cli_tasks_destination"],
)
def test_enabled_requires_each_path(field: str) -> None:
    values = {
        name: "X:/fictional/" + name
        for name in ("gui_settings_source", "gui_tasks_source", "cli_profile_destination", "cli_tasks_destination")
    }
    values[field] = ""
    assert ErrorCode.CONFIG_SCHEMA_ERROR in MAASyncConfig(enabled=True, **values).validate()


@pytest.mark.parametrize("pair", [(0, 1), (2, 3), (0, 2), (1, 3)])
def test_path_collision_is_rejected(pair: tuple[int, int]) -> None:
    values = ["X:/fictional/a", "X:/fictional/b", "X:/fictional/c", "X:/fictional/d"]
    values[pair[1]] = values[pair[0]]
    config = MAASyncConfig(True, *values)
    assert ErrorCode.CONFIG_SCHEMA_ERROR in config.validate()


def test_loader_defaults_missing_section() -> None:
    config, errors = _parse_maa_sync(None)
    assert errors == []
    assert config == MAASyncConfig()


def test_loader_parses_all_fields() -> None:
    raw = {
        "enabled": True,
        "gui_settings_source": "settings",
        "gui_tasks_source": "tasks",
        "cli_profile_destination": "profile",
        "cli_tasks_destination": "output-tasks",
        "backup_enabled": False,
        "max_source_bytes": 1234,
    }
    config, errors = _parse_maa_sync(raw)
    assert errors == []
    assert config == MAASyncConfig(True, "settings", "tasks", "profile", "output-tasks", False, 1234)


@pytest.mark.parametrize(
    "field,value", [("enabled", "false"), ("backup_enabled", 1), ("max_source_bytes", True), ("gui_tasks_source", 7)]
)
def test_loader_rejects_wrong_types(field: str, value: object) -> None:
    raw: dict[str, object] = {"enabled": False, field: value}
    assert _parse_maa_sync(raw) == (None, [ErrorCode.CONFIG_SCHEMA_ERROR])


def test_check_paths_requires_sources(tmp_path: Path) -> None:
    config = MAASyncConfig(
        True, str(tmp_path / "missing-a"), str(tmp_path / "missing-b"), str(tmp_path / "p"), str(tmp_path / "t")
    )
    assert config.check_paths() == [ErrorCode.CONFIG_PATH_NOT_FOUND, ErrorCode.CONFIG_PATH_NOT_FOUND]


def test_check_paths_rejects_source_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    other = tmp_path / "other"
    other.write_text("{}", encoding="utf-8")
    config = MAASyncConfig(True, str(source), str(other), str(tmp_path / "p"), str(tmp_path / "t"))
    assert config.check_paths() == [ErrorCode.CONFIG_PATH_NOT_FILE]


def test_check_paths_rejects_existing_target_directory(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    config = MAASyncConfig(True, str(first), str(second), str(target), str(tmp_path / "tasks"))
    assert config.check_paths() == [ErrorCode.CONFIG_PATH_NOT_FILE]


def test_current_selects_named_configuration(
    settings_object: dict[str, object], tasks_object: dict[str, object]
) -> None:
    profile, _ = transform_gui_configuration(settings_object, tasks_object)
    assert profile["instance_options"] == {
        "touch_mode": "MaaTouch",
        "deployment_with_pause": False,
        "adb_lite_enabled": True,
        "kill_adb_on_exit": False,
    }


def test_blank_current_falls_back_to_first(settings_object: dict[str, object], tasks_object: dict[str, object]) -> None:
    settings_object["Current"] = ""
    profile, _ = transform_gui_configuration(settings_object, tasks_object)
    assert profile["connection"] == {
        "type": "ADB",
        "adb_path": "X:/fictional/tool",
        "address": "fake-local-endpoint",
        "config": "FictionalConfig",
    }


@pytest.mark.parametrize("root_name", ["settings", "tasks"])
def test_missing_current_fails(
    root_name: str, settings_object: dict[str, object], tasks_object: dict[str, object]
) -> None:
    root = settings_object if root_name == "settings" else tasks_object
    root["Current"] = "missing"
    with pytest.raises(MAATransformError):
        transform_gui_configuration(settings_object, tasks_object)


@pytest.mark.parametrize("root_name", ["settings", "tasks"])
def test_empty_configurations_fail(
    root_name: str, settings_object: dict[str, object], tasks_object: dict[str, object]
) -> None:
    root = settings_object if root_name == "settings" else tasks_object
    root["Configurations"] = {}
    with pytest.raises(MAATransformError):
        transform_gui_configuration(settings_object, tasks_object)


def test_empty_task_queue_fails(settings_object: dict[str, object], tasks_object: dict[str, object]) -> None:
    tasks_object["Configurations"]["tasks"]["TaskQueue"] = []  # type: ignore[index]
    with pytest.raises(MAATransformError):
        transform_gui_configuration(settings_object, tasks_object)


@pytest.mark.parametrize("task_type", ["StartUp", "Recruit", "Infrast", "Mall", "Fight", "Award"])
def test_supported_task_types_are_converted(
    task_type: str, settings_object: dict[str, object], tasks_object: dict[str, object]
) -> None:
    task: dict[str, object] = {"TaskType": task_type, "IsEnable": True}
    if task_type == "Fight":
        task["StagePlan"] = ["FICTION-1"]
    if task_type == "Infrast":
        task.update({"Mode": "default", "RoomList": []})
    tasks_object["Configurations"]["tasks"]["TaskQueue"] = [task]  # type: ignore[index]
    _, output = transform_gui_configuration(settings_object, tasks_object)
    assert output["tasks"][0]["type"] == task_type  # type: ignore[index]


def test_disabled_unknown_task_is_skipped(settings_object: dict[str, object], tasks_object: dict[str, object]) -> None:
    tasks_object["Configurations"]["tasks"]["TaskQueue"] = [  # type: ignore[index]
        {"TaskType": "Unknown", "IsEnable": False},
        {"TaskType": "Award", "IsEnable": True},
    ]
    _, output = transform_gui_configuration(settings_object, tasks_object)
    assert [item["type"] for item in output["tasks"]] == ["Award"]  # type: ignore[union-attr]


def test_enabled_unknown_task_fails(settings_object: dict[str, object], tasks_object: dict[str, object]) -> None:
    tasks_object["Configurations"]["tasks"]["TaskQueue"] = [{"TaskType": "Unknown", "IsEnable": True}]  # type: ignore[index]
    with pytest.raises(MAATransformError):
        transform_gui_configuration(settings_object, tasks_object)


def test_unknown_fields_are_not_forwarded(settings_object: dict[str, object], tasks_object: dict[str, object]) -> None:
    settings_object["Unknown"] = "secret-value"
    tasks_object["Unknown"] = "secret-value"
    encoded = json.dumps(transform_gui_configuration(settings_object, tasks_object))
    assert "Unknown" not in encoded
    assert "secret-value" not in encoded


def test_transform_does_not_mutate_inputs(settings_object: dict[str, object], tasks_object: dict[str, object]) -> None:
    before = copy.deepcopy((settings_object, tasks_object))
    transform_gui_configuration(settings_object, tasks_object)
    assert (settings_object, tasks_object) == before


def test_transform_is_deterministic_and_json_serializable(
    settings_object: dict[str, object], tasks_object: dict[str, object]
) -> None:
    first = transform_gui_configuration(settings_object, tasks_object)
    second = transform_gui_configuration(settings_object, tasks_object)
    assert first == second
    json.dumps(first)
