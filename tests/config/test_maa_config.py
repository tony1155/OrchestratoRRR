"""MAA 配置模型及加载器测试。"""

from __future__ import annotations

from pathlib import Path

from autogame_orchestrator.config_loader import _parse_maa
from autogame_orchestrator.config_model import MAAConfig
from autogame_orchestrator.models import ErrorCode


def test_complete_configuration_is_valid() -> None:
    config = MAAConfig("maa.exe", "work", ("--run",), (("A", "b"),), 12, 3)
    assert config.validate() == []
    assert config.arguments == ("--run",) and config.environment_overrides == (("A", "b"),)


def test_empty_arguments_are_valid() -> None:
    assert MAAConfig("maa.exe", "work").validate() == []


def test_invalid_values() -> None:
    assert ErrorCode.CONFIG_SCHEMA_ERROR in MAAConfig("x", "y", (" ",)).validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in MAAConfig("x", "y", (), (("A", "1"), ("a", "2"))).validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in MAAConfig("x", "y", timeout_seconds=True).validate()


def test_loader_defaults_and_type_errors() -> None:
    config, errors = _parse_maa({"executable": "maa.exe", "working_directory": "work"})
    assert errors == [] and config is not None and config.arguments == () and config.environment_overrides == ()
    _, errors = _parse_maa({"executable": "x", "working_directory": "y", "arguments": "bad", "environment": []})
    assert errors == [ErrorCode.CONFIG_SCHEMA_ERROR, ErrorCode.CONFIG_SCHEMA_ERROR]


def test_paths_require_file_and_directory(tmp_path: Path) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    file = tmp_path / "file"
    file.write_text("x", encoding="utf-8")
    assert ErrorCode.CONFIG_PATH_NOT_FILE in MAAConfig(str(directory), str(directory)).check_paths()
    assert ErrorCode.CONFIG_PATH_NOT_DIRECTORY in MAAConfig(str(file), str(file)).check_paths()
