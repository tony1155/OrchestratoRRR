import json
from dataclasses import replace

import pytest

from autogame_orchestrator.bettergi_config import BetterGIConfig
from autogame_orchestrator.config_loader import _parse_bettergi, load_config


def test_disabled_needs_no_install():
    config = BetterGIConfig()
    assert config.validate() == config.check_paths() == []
    assert _parse_bettergi(None) == (config, [])


@pytest.mark.parametrize(
    "raw",
    [[], True, {"enabled": 1}, {"timeout_seconds": True}, {"arguments": ["start"]}, {"mode": []}, {"config_name": 1}],
)
def test_strict_loader(raw):
    assert _parse_bettergi(raw)[1]


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "groups"),
        ("config_name", "../bad"),
        ("config_name", " Daily "),
        ("config_name", "bad\nname"),
        ("config_name", ""),
        ("timeout_seconds", 0),
        ("stop_timeout_seconds", True),
        ("executable", "relative.exe"),
    ],
)
def test_invalid_invocations(tmp_path, field, value):
    config = BetterGIConfig(True, str(tmp_path / "BetterGI.exe"), str(tmp_path))
    assert replace(config, **{field: value}).validate()


@pytest.mark.parametrize(
    "changes",
    [
        {"Name": "other"},
        {"CompletionAction": "关机"},
        {"CompletionAction": "关闭游戏和软件"},
        {"TaskEnabledList": {}},
        {"TaskEnabledList": {"mail": False}},
        {"NextTaskId": "resume"},
    ],
)
def test_reject_unsafe_or_ambiguous_profile(tmp_path, changes):
    config = BetterGIConfig(True, str(tmp_path / "BetterGI.exe"), str(tmp_path))
    profile = {"Name": config.config_name, "CompletionAction": "关闭软件", "TaskEnabledList": {"mail": True}}
    profile.update(changes)
    folder = tmp_path / "User" / "OneDragon"
    folder.mkdir(parents=True)
    (folder / f"{config.config_name}.json").write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError):
        config.check_profile()


def test_load_optional_section(tmp_path):
    from pathlib import Path

    source = Path("config/orchestrator.example.toml").read_text(encoding="utf-8")
    path = tmp_path / "config.toml"
    path.write_text(source, encoding="utf-8")
    config, errors = load_config(path)
    assert not errors and not config.bettergi.enabled
