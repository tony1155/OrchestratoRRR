"""Unit tests for config_loader."""

from __future__ import annotations

from pathlib import Path

from autogame_orchestrator.config_loader import load_config
from autogame_orchestrator.models import ErrorCode


def test_load_valid_config(valid_config: Path) -> None:
    cfg, errs = load_config(valid_config)
    assert errs == []
    assert cfg is not None
    assert cfg.orchestrator.log_dir == "logs"
    assert cfg.mumu.executable != ""
    assert cfg.aalc.attempts == 3


def test_config_file_not_found() -> None:
    _, errs = load_config(Path("Z:\\nonexistent\\file.toml"))
    assert ErrorCode.CONFIG_FILE_NOT_FOUND in errs


def test_invalid_toml_syntax(invalid_toml: Path) -> None:
    _, errs = load_config(invalid_toml)
    assert ErrorCode.CONFIG_PARSE_ERROR in errs


def test_missing_sections(missing_fields_config: Path) -> None:
    _, errs = load_config(missing_fields_config)
    assert len(errs) > 0
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_invalid_values(invalid_values_config: Path) -> None:
    _, errs = load_config(invalid_values_config)
    assert len(errs) > 0
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_does_not_check_paths_by_default(valid_config: Path) -> None:
    cfg, errs = load_config(valid_config)
    assert errs == []
    assert cfg is not None


def test_check_paths_finds_missing_file(tmp_workdir: Path) -> None:
    config = tmp_workdir / "test.toml"
    config.write_text(
        """\
[orchestrator]
log_dir = "logs"
report_dir = "run-results"
heartbeat_interval_seconds = 10
poll_interval_seconds = 1

[mumu]
executable = "Z:/nonexistent/MuMuNxDevice.exe"
adb_executable = "Z:/nonexistent/adb.exe"
adb_serial = "127.0.0.1:16384"
start_timeout_seconds = 120
stop_timeout_seconds = 20

[starrail]
executable = "C:/path/to/python.exe"
working_directory = "C:/path/to/StarRailCopilot"
arguments = ["gui.py"]
log_path_template = 'log/{date}_src.txt'
success_keywords = ["No task pending"]
failure_keywords = ["ScriptError:"]
task_timeout_seconds = 3600
stop_timeout_seconds = 10

[starrail.environment]
PYTHONIOENCODING = "utf-8"

[maa]
executable = "C:/path/to/maa.exe"
working_directory = "C:/path/to/maa-cli"
timeout_seconds = 1800

[aalc]
executable = "C:/path/to/AALC.exe"
working_directory = "C:/path/to/AALC"
attempts = 3
attempt_timeout_seconds = 7200
""",
        encoding="utf-8",
    )
    _, errs = load_config(config, check_paths=True)
    assert ErrorCode.CONFIG_PATH_NOT_FOUND in errs


def test_starrail_arguments_not_list_gives_error(tmp_workdir: Path) -> None:
    config = tmp_workdir / "test.toml"
    config.write_text(
        """\
[orchestrator]
log_dir = "logs"
report_dir = "run-results"
heartbeat_interval_seconds = 10
poll_interval_seconds = 1

[mumu]
executable = "C:/MuMu.exe"
adb_executable = "C:/adb.exe"
adb_serial = "127.0.0.1:16384"
start_timeout_seconds = 120
stop_timeout_seconds = 20

[starrail]
executable = "C:/python.exe"
working_directory = "C:/srp"
arguments = "not-a-list"
log_path_template = 'log/{date}_src.txt'
task_timeout_seconds = 3600
stop_timeout_seconds = 10

[starrail.environment]
PYTHONIOENCODING = "utf-8"

[maa]
executable = "C:/maa.exe"
working_directory = "C:/maa-cli"
timeout_seconds = 1800

[aalc]
executable = "C:/AALC.exe"
working_directory = "C:/AALC"
attempts = 3
attempt_timeout_seconds = 7200
""",
        encoding="utf-8",
    )
    _, errs = load_config(config)
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs
