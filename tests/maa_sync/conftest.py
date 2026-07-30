from __future__ import annotations

import json
from pathlib import Path

import pytest

from autogame_orchestrator.config_model import MAASyncConfig


@pytest.fixture
def settings_object() -> dict[str, object]:
    return {
        "Current": "alpha",
        "Configurations": {
            "alpha": {
                "Connect.AdbPath": "X:/fictional/tool",
                "Connect.Address": "fake-local-endpoint",
                "Connect.ConnectConfig": "FictionalConfig",
                "Connect.TouchMode": "maatouch",
                "Connect.AdbLiteEnabled": True,
                "Connect.KillAdbOnExit": False,
                "Start.ClientType": "FictionalClient",
                "Start.StartGame": False,
                "Recruit.AutoSetTime": True,
            },
            "beta": {"Connect.TouchMode": "adb"},
        },
    }


@pytest.fixture
def tasks_object() -> dict[str, object]:
    return {
        "Current": "tasks",
        "Configurations": {
            "tasks": {"TaskQueue": [{"TaskType": "Award", "IsEnable": True}]},
        },
    }


@pytest.fixture
def sync_config(tmp_path: Path, settings_object: dict[str, object], tasks_object: dict[str, object]) -> MAASyncConfig:
    settings = tmp_path / "settings.json"
    tasks = tmp_path / "tasks.json"
    settings.write_text(json.dumps(settings_object), encoding="utf-8")
    tasks.write_text(json.dumps(tasks_object), encoding="utf-8")
    return MAASyncConfig(
        enabled=True,
        gui_settings_source=str(settings),
        gui_tasks_source=str(tasks),
        cli_profile_destination=str(tmp_path / "output" / "profile.json"),
        cli_tasks_destination=str(tmp_path / "output" / "tasks.json"),
    )
