"""[game] / [mash] 配置段加载测试。"""

from __future__ import annotations

from pathlib import Path

from autogame_orchestrator.config_loader import load_config
from autogame_orchestrator.config_model import GameSelection, MashRepeatMode, MashServer

_BASE = """
game = "starrail"
[orchestrator]
log_dir = "logs"
report_dir = "run-results"
[mumu]
lifecycle_mode = "external"
executable = ""
adb_executable = "C:/adb.exe"
adb_serial = "127.0.0.1:16384"
[starrail]
executable = "C:/src/python.exe"
working_directory = "C:/src"
arguments = ["gui.py"]
log_path_template = "log/{date}.txt"
success_keywords = ["done"]
failure_keywords = ["err"]
environment = {}
[maa]
executable = "C:/maa/MAA.exe"
working_directory = "C:/maa"
"""

_MASH = """
[mash]
executable = "C:/Mash/mash-cli.exe"
working_directory = "C:/Mash"
project_id = "p-fgo-1"
server = "cn"
repeat_mode = "count"
repeat_count = 3
result_file = "C:/results/mash.json"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "orchestrator.local.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_game_defaults_to_starrail(tmp_path: Path) -> None:
    config, errors = load_config(_write(tmp_path, _BASE))
    assert errors == []
    assert config is not None
    assert config.game is GameSelection.STARRAIL
    assert config.mash.project_id == ""


def test_game_fgo_parses_mash_section(tmp_path: Path) -> None:
    config, errors = load_config(_write(tmp_path, _BASE.replace('game = "starrail"', 'game = "fgo"') + _MASH))
    assert errors == []
    assert config is not None
    assert config.game is GameSelection.FGO
    assert config.mash.project_id == "p-fgo-1"
    assert config.mash.server is MashServer.CN
    assert config.mash.repeat_mode is MashRepeatMode.COUNT
    assert config.mash.repeat_count == 3
    assert config.validate() == []


def test_game_fgo_without_mash_section_fails_validation(tmp_path: Path) -> None:
    config, errors = load_config(_write(tmp_path, _BASE.replace('game = "starrail"', 'game = "fgo"')))
    assert config is None
    assert errors  # [mash] 缺失 → AppConfig.validate 报错
    assert errors[0].value == "CONFIG_SCHEMA_ERROR"


def test_invalid_game_value_rejected(tmp_path: Path) -> None:
    _config, errors = load_config(_write(tmp_path, _BASE.replace('game = "starrail"', 'game = "genshin"') + _MASH))
    assert errors
    assert errors[0].value == "CONFIG_SCHEMA_ERROR"


def test_invalid_mash_repeat_count_rejected(tmp_path: Path) -> None:
    text = _BASE.replace('game = "starrail"', 'game = "fgo"') + _MASH.replace("repeat_count = 3", "repeat_count = 0")
    config, errors = load_config(_write(tmp_path, text))
    assert config is None
    assert errors  # count 模式下 repeat_count 必须 >= 1
