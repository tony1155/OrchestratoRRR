import json
from dataclasses import replace
from pathlib import Path

import pytest

from autogame_orchestrator.maafgo_config import MaaFgoConfigurationError
from autogame_orchestrator.maafgo_gui import sync_mxu_profile
from tests.fakes.maafgo_support import SERIAL, make_native_project


@pytest.fixture
def project(tmp_path):
    config = make_native_project(tmp_path / "project")
    root = tmp_path / "project"
    daily = root / "tasks/daily.json"
    daily.write_text(
        json.dumps(
            {
                "task": [{"name": "日常战斗", "option": ["battle_mode", "apple", "stages"]}],
                "option": {
                    "battle_mode": {"cases": [{"name": "bbc"}, {"name": "native", "option": ["count"]}]},
                    "count": {"type": "input", "inputs": [{"name": "times", "default": "1"}]},
                    "apple": {"type": "switch", "cases": [{"name": "No"}, {"name": "Yes"}]},
                    "stages": {"type": "checkbox", "cases": [{"name": "A"}, {"name": "B"}]},
                },
            }
        ),
        encoding="utf-8",
    )
    gui = {
        "lastActiveInstanceId": "daily",
        "instances": [
            {
                "id": "daily",
                "controllerName": "Synthetic Adb",
                "resourceName": "synthetic",
                "savedDevice": {"adbDeviceAddress": SERIAL},
                "tasks": [
                    {"taskName": "登录", "enabled": True, "optionValues": {}},
                    {
                        "taskName": "日常战斗",
                        "enabled": True,
                        "optionValues": {
                            "battle_mode": {"type": "select", "caseName": "native"},
                            "count": {"type": "input", "values": {"times": "3"}},
                            "apple": {"type": "switch", "value": False},
                            "stages": {"type": "checkbox", "caseNames": ["B"]},
                            "inactive": {"type": "select", "caseName": "ignored"},
                        },
                    },
                    {"taskName": "unknown", "enabled": False},
                ],
            }
        ],
    }
    source = root / "config/mxu-MaaFgo.json"
    source.write_text(json.dumps(gui), encoding="utf-8")
    return replace(config, gui_config_source=str(source), gui_instance_id="daily"), gui


def sync(config):
    return sync_mxu_profile(config, adb_path=str(config.profile_path.parents[1] / "adb.exe"), serial=SERIAL)


def test_gui_selection_is_converted_atomically_without_changing_source(project):
    config, _ = project
    before = config.profile_path.read_bytes()
    source = Path(config.gui_config_source)
    gui_before = source.read_bytes()
    assert sync(config)
    config.check_profile(SERIAL)
    config.check_profile_policy()
    output = json.loads(config.profile_path.read_bytes())
    assert [task["name"] for task in output["task"]] == ["登录", "日常战斗"]
    options = {o["name"]: o for o in output["task"][1]["option"]}
    assert options["battle_mode"]["value"] == "native"
    assert options["count"]["inputs"] == {"times": "3"}
    assert options["apple"]["value"] == "No"
    assert options["stages"]["values"] == ["B"]
    assert "inactive" not in options
    assert config.profile_path.with_suffix(".json.bak").read_bytes() == before
    assert source.read_bytes() == gui_before
    assert not sync(config)


def test_detected_device_identity_and_forward_slash_adb_path_are_preserved(project):
    config, gui = project
    gui["instances"][0]["savedDevice"]["adbDeviceName"] = "detected-device"
    Path(config.gui_config_source).write_text(json.dumps(gui), encoding="utf-8")
    assert sync(config)
    profile = json.loads(config.profile_path.read_bytes())
    assert profile["adb"]["name"] == "detected-device"
    assert "\\" not in profile["adb"]["adb_path"]
    config.check_profile(SERIAL)


@pytest.mark.parametrize("problem", ["endpoint", "resource", "instance", "bbc", "unknown-task", "bad-input"])
def test_invalid_gui_keeps_last_cli_profile(project, problem):
    config, gui = project
    instance = gui["instances"][0]
    if problem == "endpoint":
        instance["savedDevice"]["adbDeviceAddress"] = "127.0.0.1:16416"
    elif problem == "resource":
        instance["resourceName"] = "unknown"
    elif problem == "instance":
        instance["id"] = "other"
    elif problem == "bbc":
        instance["tasks"][1]["optionValues"]["battle_mode"]["caseName"] = "bbc"
    elif problem == "unknown-task":
        instance["tasks"][2]["enabled"] = True
    elif problem == "bad-input":
        instance["tasks"][1]["optionValues"]["count"]["values"] = {"times": 3}
    Path(config.gui_config_source).write_text(json.dumps(gui), encoding="utf-8")
    before = config.profile_path.read_bytes()
    with pytest.raises(MaaFgoConfigurationError):
        sync(config)
    assert config.profile_path.read_bytes() == before


def test_gui_disabled_is_noop(project):
    config, _ = project
    assert not sync(replace(config, gui_config_source=""))


def test_large_real_world_option_document_is_supported(project):
    config, _ = project
    path = config.interface_path.parent / "tasks/daily.json"
    document = json.loads(path.read_bytes())
    document["description"] = "x" * (1800 * 1024)
    path.write_text(json.dumps(document), encoding="utf-8")
    assert sync(config)
    config.check_profile_policy()


def test_real_sized_distribution_inventory_is_supported(project):
    config, _ = project
    path = config.interface_path.parent / "distribution-manifest.json"
    document = json.loads(path.read_bytes())
    document["files"] = [{"path": "resource/" + str(i), "sha256": "a" * 64, "size": 1} for i in range(12418)]
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    assert path.stat().st_size > 1024 * 1024
    config.check_distribution()


def test_distribution_inventory_still_has_a_size_limit(project):
    from autogame_orchestrator.maafgo_config import MAX_MANIFEST_BYTES

    config, _ = project
    path = config.interface_path.parent / "distribution-manifest.json"
    path.write_bytes(b" " * (MAX_MANIFEST_BYTES + 1))
    with pytest.raises(MaaFgoConfigurationError):
        config.check_distribution()
