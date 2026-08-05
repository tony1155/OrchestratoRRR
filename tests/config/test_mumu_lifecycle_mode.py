"""MuMu 生命周期模式配置、加载和路径边界测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from autogame_orchestrator.config_loader import _parse_mumu
from autogame_orchestrator.config_model import MuMuConfig, MumuLifecycleMode
from autogame_orchestrator.models import ErrorCode


def _raw(mode: object = "managed") -> dict[str, object]:
    return {
        "lifecycle_mode": mode,
        "executable": "X:/fake/mumu.exe",
        "adb_executable": "X:/fake/adb.exe",
        "adb_serial": "127.0.0.1:16384",
        "start_timeout_seconds": 120,
        "stop_timeout_seconds": 20,
        "start_arguments": [],
        "stop_arguments": [],
    }


def test_managed_mode_is_model_default() -> None:
    assert MuMuConfig().lifecycle_mode == MumuLifecycleMode.MANAGED


def test_lifecycle_enum_values_are_stable() -> None:
    assert tuple(mode.value for mode in MumuLifecycleMode) == ("managed", "external")


def test_external_model_allows_empty_executable() -> None:
    config = MuMuConfig(
        lifecycle_mode=MumuLifecycleMode.EXTERNAL,
        executable="",
        adb_executable="X:/fake/adb.exe",
    )
    assert config.validate() == []


@pytest.mark.parametrize("value", ["unknown", "MANAGED", "External", "", 1, True, [], {}])
def test_loader_rejects_invalid_lifecycle_mode(value: object) -> None:
    config, errors = _parse_mumu(_raw(value))
    assert config is None
    assert errors == [ErrorCode.CONFIG_SCHEMA_ERROR]


def test_loader_defaults_to_managed() -> None:
    raw = _raw()
    raw.pop("lifecycle_mode")
    config, errors = _parse_mumu(raw)
    assert errors == []
    assert config is not None
    assert config.lifecycle_mode == MumuLifecycleMode.MANAGED


def test_loader_parses_external_and_all_fields() -> None:
    raw = _raw("external")
    raw["executable"] = ""
    config, errors = _parse_mumu(raw)
    assert errors == []
    assert config == MuMuConfig(
        lifecycle_mode=MumuLifecycleMode.EXTERNAL,
        executable="",
        adb_executable="X:/fake/adb.exe",
        adb_serial="127.0.0.1:16384",
        start_timeout_seconds=120,
        stop_timeout_seconds=20,
        start_arguments=(),
        stop_arguments=(),
    )


def test_managed_loader_requires_executable() -> None:
    raw = _raw("managed")
    raw["executable"] = ""
    config, errors = _parse_mumu(raw)
    assert config is None
    assert errors == [ErrorCode.CONFIG_SCHEMA_ERROR]


def test_external_loader_allows_empty_executable() -> None:
    raw = _raw("external")
    raw["executable"] = ""
    config, errors = _parse_mumu(raw)
    assert errors == []
    assert config is not None
    assert config.executable == ""


@pytest.mark.parametrize("field", ["adb_executable", "adb_serial"])
@pytest.mark.parametrize("value", [None, "", 7, True])
def test_external_loader_requires_adb_fields(field: str, value: object) -> None:
    raw = _raw("external")
    raw[field] = value
    config, errors = _parse_mumu(raw)
    assert config is None
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errors


@pytest.mark.parametrize("field", ["start_arguments", "stop_arguments"])
def test_external_loader_rejects_control_arguments(field: str) -> None:
    raw = _raw("external")
    raw[field] = ["forbidden-control"]
    config, errors = _parse_mumu(raw)
    assert config is None
    assert errors == [ErrorCode.CONFIG_SCHEMA_ERROR]


@pytest.mark.parametrize("field", ["start_arguments", "stop_arguments"])
@pytest.mark.parametrize("value", ["command", 1, True, {}])
def test_loader_rejects_non_array_control_arguments(field: str, value: object) -> None:
    raw = _raw()
    raw[field] = value
    config, errors = _parse_mumu(raw)
    assert config is None
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errors


@pytest.mark.parametrize("field", ["start_timeout_seconds", "stop_timeout_seconds"])
@pytest.mark.parametrize("value", [True, False, "20"])
def test_loader_rejects_non_integer_timeout(field: str, value: object) -> None:
    raw = _raw()
    raw[field] = value
    config, errors = _parse_mumu(raw)
    assert config is None
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errors


@pytest.mark.parametrize("field", ["start_arguments", "stop_arguments"])
def test_external_model_rejects_control_arguments(field: str) -> None:
    values = {field: ("forbidden-control",)}
    config = MuMuConfig(
        lifecycle_mode=MumuLifecycleMode.EXTERNAL,
        executable="",
        adb_executable="X:/fake/adb.exe",
        **values,
    )
    assert ErrorCode.CONFIG_SCHEMA_ERROR in config.validate()


@pytest.mark.parametrize("value", ["external", 1, True])
def test_model_rejects_non_enum_lifecycle_mode(value: object) -> None:
    config = MuMuConfig(lifecycle_mode=value)  # type: ignore[arg-type]
    assert config.validate() == [ErrorCode.CONFIG_SCHEMA_ERROR]


def test_external_check_paths_ignores_mumu_executable(tmp_path: Path) -> None:
    adb = tmp_path / "adb-placeholder.exe"
    adb.write_text("fake", encoding="utf-8")
    config = MuMuConfig(
        lifecycle_mode=MumuLifecycleMode.EXTERNAL,
        executable="Z:/missing/mumu.exe",
        adb_executable=str(adb),
    )
    assert config.check_paths() == []


def test_external_check_paths_requires_adb_executable() -> None:
    config = MuMuConfig(
        lifecycle_mode=MumuLifecycleMode.EXTERNAL,
        executable="",
        adb_executable="Z:/missing/adb.exe",
    )
    assert config.check_paths() == [ErrorCode.CONFIG_PATH_NOT_FOUND]


def test_managed_check_paths_still_checks_both_paths(tmp_path: Path) -> None:
    config = MuMuConfig(
        lifecycle_mode=MumuLifecycleMode.MANAGED,
        executable=str(tmp_path / "missing-mumu.exe"),
        adb_executable=str(tmp_path / "missing-adb.exe"),
    )
    assert config.check_paths() == [ErrorCode.CONFIG_PATH_NOT_FOUND, ErrorCode.CONFIG_PATH_NOT_FOUND]


def test_managed_check_paths_accepts_existing_paths(tmp_path: Path) -> None:
    executable = tmp_path / "mumu-placeholder.exe"
    adb = tmp_path / "adb-placeholder.exe"
    executable.write_text("fake", encoding="utf-8")
    adb.write_text("fake", encoding="utf-8")
    config = MuMuConfig(executable=str(executable), adb_executable=str(adb))
    assert config.check_paths() == []
