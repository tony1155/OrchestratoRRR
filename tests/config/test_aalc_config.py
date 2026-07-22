"""AALC 配置模型与 loader 的完整边界测试。"""

from __future__ import annotations

from pathlib import Path

from autogame_orchestrator.config_loader import _parse_aalc
from autogame_orchestrator.config_model import AALCConfig
from autogame_orchestrator.models import ErrorCode

E = [ErrorCode.CONFIG_SCHEMA_ERROR]


def test_aalc_config_accepts_complete_values() -> None:
    c = AALCConfig("a.exe", "work", ("x", "y"), (("A", "1"),), 2, 30, 4)
    assert c.validate() == []
    assert c == AALCConfig("a.exe", "work", ("x", "y"), (("A", "1"),), 2, 30, 4)


def test_aalc_config_allows_empty_arguments() -> None:
    assert AALCConfig("x", "y", arguments=()).validate() == []


def test_aalc_config_allows_empty_environment() -> None:
    assert AALCConfig("x", "y", environment_overrides=()).validate() == []


def test_aalc_config_rejects_blank_argument() -> None:
    assert AALCConfig("x", "y", arguments=(" ",)).validate() == E


def test_aalc_config_rejects_non_string_argument() -> None:
    assert AALCConfig("x", "y", arguments=(1,)).validate() == E  # type: ignore[arg-type]


def test_aalc_config_rejects_malformed_environment_entry() -> None:
    assert AALCConfig("x", "y", environment_overrides=(("A", "1", "x"),)).validate() == E  # type: ignore[arg-type]


def test_aalc_config_rejects_blank_environment_key() -> None:
    assert AALCConfig("x", "y", environment_overrides=((" ", "1"),)).validate() == E


def test_aalc_config_rejects_non_string_environment_value() -> None:
    assert AALCConfig("x", "y", environment_overrides=(("A", 1),)).validate() == E  # type: ignore[arg-type]


def test_aalc_config_rejects_duplicate_environment_keys() -> None:
    assert AALCConfig("x", "y", environment_overrides=(("A", "1"), ("a", "2"))).validate() == E


def test_aalc_config_rejects_bool_attempts() -> None:
    assert AALCConfig("x", "y", attempts=True).validate() == E


def test_aalc_config_rejects_attempts_below_one() -> None:
    assert AALCConfig("x", "y", attempts=0).validate() == E


def test_aalc_config_rejects_attempts_above_three() -> None:
    assert AALCConfig("x", "y", attempts=4).validate() == E


def test_aalc_config_rejects_bool_attempt_timeout() -> None:
    assert AALCConfig("x", "y", attempt_timeout_seconds=True).validate() == E


def test_aalc_config_rejects_bool_stop_timeout() -> None:
    assert AALCConfig("x", "y", stop_timeout_seconds=False).validate() == E


def test_loader_parses_all_aalc_fields() -> None:
    c, e = _parse_aalc(
        {
            "executable": "a",
            "working_directory": "w",
            "arguments": ["x"],
            "environment": {"A": "1"},
            "attempts": 2,
            "attempt_timeout_seconds": 30,
            "stop_timeout_seconds": 4,
        }
    )
    assert e == []
    assert c == AALCConfig("a", "w", ("x",), (("A", "1"),), 2, 30, 4)


def test_loader_defaults_optional_arguments_and_environment() -> None:
    c, e = _parse_aalc({"executable": "a", "working_directory": "w"})
    assert e == []
    assert c is not None
    assert c.arguments == () and c.environment_overrides == ()


def test_loader_defaults_retry_and_timeout_values() -> None:
    c, e = _parse_aalc({"executable": "a", "working_directory": "w"})
    assert e == []
    assert c is not None
    assert (c.attempts, c.attempt_timeout_seconds, c.stop_timeout_seconds) == (3, 7200, 10)


def test_loader_rejects_non_string_executable() -> None:
    assert _parse_aalc({"executable": 1, "working_directory": "w"}) == (None, E)


def test_loader_rejects_non_string_working_directory() -> None:
    assert _parse_aalc({"executable": "a", "working_directory": 1}) == (None, E)


def test_loader_rejects_invalid_arguments() -> None:
    assert _parse_aalc({"executable": "a", "working_directory": "w", "arguments": [1]}) == (None, E)


def test_loader_rejects_invalid_environment() -> None:
    assert _parse_aalc({"executable": "a", "working_directory": "w", "environment": {"A": 1}}) == (None, E)


def test_loader_rejects_bool_attempts() -> None:
    assert _parse_aalc({"executable": "a", "working_directory": "w", "attempts": True}) == (None, E)


def test_loader_rejects_bool_attempt_timeout() -> None:
    assert _parse_aalc({"executable": "a", "working_directory": "w", "attempt_timeout_seconds": True}) == (None, E)


def test_loader_rejects_bool_stop_timeout() -> None:
    assert _parse_aalc({"executable": "a", "working_directory": "w", "stop_timeout_seconds": False}) == (None, E)


def test_check_paths_requires_executable_file(tmp_path: Path) -> None:
    assert AALCConfig(str(tmp_path / "x"), str(tmp_path)).check_paths() == [ErrorCode.CONFIG_PATH_NOT_FOUND]


def test_check_paths_rejects_executable_directory(tmp_path: Path) -> None:
    assert AALCConfig(str(tmp_path), str(tmp_path)).check_paths() == [ErrorCode.CONFIG_PATH_NOT_FILE]


def test_check_paths_requires_working_directory(tmp_path: Path) -> None:
    f = tmp_path / "x"
    f.write_text("x")
    assert AALCConfig(str(f), str(tmp_path / "no")).check_paths() == [ErrorCode.CONFIG_PATH_NOT_FOUND]


def test_check_paths_rejects_working_directory_file(tmp_path: Path) -> None:
    f = tmp_path / "x"
    f.write_text("x")
    assert AALCConfig(str(f), str(f)).check_paths() == [ErrorCode.CONFIG_PATH_NOT_DIRECTORY]
