"""StarRail 配置解析和验证测试。"""

from __future__ import annotations

from pathlib import Path

from autogame_orchestrator.config_loader import _to_string_mapping, load_config
from autogame_orchestrator.config_model import StarRailConfig
from autogame_orchestrator.models import ErrorCode


def _default_config() -> StarRailConfig:
    return StarRailConfig(
        executable="C:/python.exe",
        working_directory="C:/srp",
        arguments=("gui.py", "--run", "src", "--port", "22367"),
        log_path_template="log\\{date}_src.txt",
    )


def test_starrail_config_accepts_complete_values() -> None:
    cfg = _default_config()
    errs = cfg.validate()
    assert errs == []


def test_starrail_config_rejects_empty_arguments() -> None:
    cfg = StarRailConfig(
        executable="C:/python.exe",
        working_directory="C:/srp",
        arguments=(),
        log_path_template="log\\{date}_src.txt",
    )
    errs = cfg.validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_starrail_config_rejects_blank_argument() -> None:
    cfg = StarRailConfig(
        executable="C:/python.exe",
        working_directory="C:/srp",
        arguments=("gui.py", "  ", "--port", "22367"),
        log_path_template="log\\{date}_src.txt",
    )
    errs = cfg.validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_starrail_config_rejects_empty_success_keywords() -> None:
    cfg = StarRailConfig(
        executable="C:/python.exe",
        working_directory="C:/srp",
        arguments=("gui.py",),
        log_path_template="log\\{date}_src.txt",
        success_keywords=(),
    )
    errs = cfg.validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_starrail_config_rejects_blank_keyword() -> None:
    cfg = StarRailConfig(
        executable="C:/python.exe",
        working_directory="C:/srp",
        arguments=("gui.py",),
        log_path_template="log\\{date}_src.txt",
        success_keywords=("  ",),
    )
    errs = cfg.validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_starrail_config_rejects_unknown_template_placeholder() -> None:
    cfg = StarRailConfig(
        executable="C:/python.exe",
        working_directory="C:/srp",
        arguments=("gui.py",),
        log_path_template="log\\{unknown}_src.txt",
    )
    errs = cfg.validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_starrail_config_rejects_duplicate_environment_keys() -> None:
    cfg = StarRailConfig(
        executable="C:/python.exe",
        working_directory="C:/srp",
        arguments=("gui.py",),
        log_path_template="log\\{date}_src.txt",
        environment_overrides=(("KEY", "V1"), ("key", "V2")),
    )
    errs = cfg.validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_loader_parses_starrail_environment(tmp_path: Path) -> None:
    config = tmp_path / "starrail_test.toml"
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
arguments = ["gui.py", "--run", "src", "--port", "22367"]
log_path_template = "log-{date}_src.txt"
success_keywords = ["No task pending", "for task `Restart`"]
failure_keywords = ["ScriptError:", "Request human takeover"]
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
    cfg, errs = load_config(config)
    assert errs == []
    assert cfg is not None
    sr = cfg.starrail
    assert sr.executable == "C:/python.exe"
    assert sr.working_directory == "C:/srp"
    assert sr.arguments == ("gui.py", "--run", "src", "--port", "22367")
    assert sr.log_path_template == "log-{date}_src.txt"
    assert "No task pending" in sr.success_keywords
    assert "ScriptError:" in sr.failure_keywords
    overrides = dict(sr.environment_overrides)
    assert overrides.get("PYTHONIOENCODING") == "utf-8"


def test_loader_preserves_starrail_keywords(tmp_path: Path) -> None:
    config = tmp_path / "starrail_test2.toml"
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
arguments = ["gui.py"]
log_path_template = "log-{date}_src.txt"
success_keywords = ["No task pending"]
failure_keywords = ["ScriptError:"]
task_timeout_seconds = 3600
stop_timeout_seconds = 10

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
    cfg, errs = load_config(config)
    assert errs == []
    assert cfg is not None
    sr = cfg.starrail
    assert len(sr.success_keywords) >= 1
    assert len(sr.failure_keywords) >= 1


def test_check_paths_requires_executable_file(tmp_path: Path) -> None:
    cfg = StarRailConfig(
        executable=str(tmp_path / "nonexistent.exe"),
        working_directory=str(tmp_path),
        arguments=("gui.py",),
        log_path_template="log\\{date}_src.txt",
    )
    errs = cfg.check_paths()
    assert ErrorCode.CONFIG_PATH_NOT_FOUND in errs


def test_check_paths_requires_working_directory(tmp_path: Path) -> None:
    cfg = StarRailConfig(
        executable=str(tmp_path / "fake.exe"),
        working_directory=str(tmp_path / "nonexistent_dir"),
        arguments=("gui.py",),
        log_path_template="log\\{date}_src.txt",
    )
    errs = cfg.check_paths()
    assert ErrorCode.CONFIG_PATH_NOT_FOUND in errs


def test_to_string_mapping() -> None:
    result = _to_string_mapping({"A": "1", "B": "2"})
    assert result == (("A", "1"), ("B", "2"))


def test_to_string_mapping_rejects_non_dict() -> None:
    assert _to_string_mapping("not a dict") is None


def test_to_string_mapping_rejects_non_string_value() -> None:
    assert _to_string_mapping({"A": 1}) is None
