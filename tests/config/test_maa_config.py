"""MAA 配置模型及加载器的完整边界测试。"""

from __future__ import annotations

from pathlib import Path

from autogame_orchestrator.config_loader import _parse_maa
from autogame_orchestrator.config_model import MAAConfig
from autogame_orchestrator.models import ErrorCode

SCHEMA_ERROR = [ErrorCode.CONFIG_SCHEMA_ERROR]


def test_maa_config_accepts_complete_values() -> None:
    config = MAAConfig("maa.exe", "work", ("--run", "task"), (("A", "b"),), 12, 3)
    assert config.validate() == []
    assert config.executable == "maa.exe"
    assert config.working_directory == "work"
    assert config.arguments == ("--run", "task")
    assert config.environment_overrides == (("A", "b"),)
    assert config.timeout_seconds == 12
    assert config.stop_timeout_seconds == 3


def test_maa_config_allows_empty_arguments() -> None:
    assert MAAConfig("maa.exe", "work", arguments=()).validate() == []


def test_maa_config_rejects_blank_argument() -> None:
    assert MAAConfig("x", "y", arguments=(" ",)).validate() == SCHEMA_ERROR


def test_maa_config_rejects_non_string_argument() -> None:
    assert MAAConfig("x", "y", arguments=(1,)).validate() == SCHEMA_ERROR  # type: ignore[arg-type]


def test_maa_config_rejects_duplicate_environment_keys() -> None:
    config = MAAConfig("x", "y", environment_overrides=(("Token", "1"), ("TOKEN", "2")))
    assert config.validate() == SCHEMA_ERROR


def test_maa_config_rejects_non_string_environment_value() -> None:
    config = MAAConfig("x", "y", environment_overrides=(("Token", 1),))  # type: ignore[arg-type]
    assert config.validate() == SCHEMA_ERROR


def test_maa_config_rejects_malformed_environment_entry() -> None:
    config = MAAConfig("x", "y", environment_overrides=(("Token", "1", "extra"),))  # type: ignore[arg-type]
    assert config.validate() == SCHEMA_ERROR


def test_maa_config_rejects_bool_timeout() -> None:
    assert MAAConfig("x", "y", timeout_seconds=True).validate() == SCHEMA_ERROR


def test_maa_config_rejects_bool_stop_timeout() -> None:
    assert MAAConfig("x", "y", stop_timeout_seconds=False).validate() == SCHEMA_ERROR


def test_loader_parses_maa_arguments() -> None:
    config, errors = _parse_maa({"executable": "maa.exe", "working_directory": "work", "arguments": ["a", "b"]})
    assert errors == []
    assert config == MAAConfig("maa.exe", "work", ("a", "b"), (), 1800, 10)


def test_loader_parses_maa_environment() -> None:
    raw = {"executable": "maa.exe", "working_directory": "work", "environment": {"A": "1", "B": "2"}}
    config, errors = _parse_maa(raw)
    assert errors == []
    assert config == MAAConfig("maa.exe", "work", (), (("A", "1"), ("B", "2")), 1800, 10)


def test_loader_defaults_optional_arguments_and_environment() -> None:
    config, errors = _parse_maa({"executable": "maa.exe", "working_directory": "work"})
    assert errors == []
    assert config == MAAConfig("maa.exe", "work", (), (), 1800, 10)


def test_loader_rejects_non_string_executable() -> None:
    assert _parse_maa({"executable": 1, "working_directory": "work"}) == (None, SCHEMA_ERROR)


def test_loader_rejects_non_string_working_directory() -> None:
    assert _parse_maa({"executable": "maa.exe", "working_directory": 1}) == (None, SCHEMA_ERROR)


def test_loader_rejects_invalid_arguments() -> None:
    assert _parse_maa({"executable": "x", "working_directory": "y", "arguments": ["a", 1]}) == (
        None,
        SCHEMA_ERROR,
    )


def test_loader_rejects_invalid_environment() -> None:
    assert _parse_maa({"executable": "x", "working_directory": "y", "environment": {"A": 1}}) == (
        None,
        SCHEMA_ERROR,
    )


def test_loader_rejects_bool_timeout() -> None:
    assert _parse_maa({"executable": "x", "working_directory": "y", "timeout_seconds": True}) == (
        None,
        SCHEMA_ERROR,
    )


def test_loader_rejects_bool_stop_timeout() -> None:
    assert _parse_maa({"executable": "x", "working_directory": "y", "stop_timeout_seconds": False}) == (
        None,
        SCHEMA_ERROR,
    )


def test_check_paths_requires_executable_file(tmp_path: Path) -> None:
    assert MAAConfig(str(tmp_path / "missing.exe"), str(tmp_path)).check_paths() == [ErrorCode.CONFIG_PATH_NOT_FOUND]


def test_check_paths_rejects_executable_directory(tmp_path: Path) -> None:
    assert MAAConfig(str(tmp_path), str(tmp_path)).check_paths() == [ErrorCode.CONFIG_PATH_NOT_FILE]


def test_check_paths_requires_working_directory(tmp_path: Path) -> None:
    executable = tmp_path / "maa.exe"
    executable.write_text("fake", encoding="utf-8")
    assert MAAConfig(str(executable), str(tmp_path / "missing")).check_paths() == [ErrorCode.CONFIG_PATH_NOT_FOUND]


def test_check_paths_rejects_working_directory_file(tmp_path: Path) -> None:
    executable = tmp_path / "maa.exe"
    executable.write_text("fake", encoding="utf-8")
    assert MAAConfig(str(executable), str(executable)).check_paths() == [ErrorCode.CONFIG_PATH_NOT_DIRECTORY]
