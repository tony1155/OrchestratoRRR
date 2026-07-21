"""Unit tests for configuration model validation."""

from __future__ import annotations

from autogame_orchestrator.config_model import (
    AALCConfig,
    AppConfig,
    MAAConfig,
    MuMuConfig,
    OrchestratorConfig,
    StarRailConfig,
)
from autogame_orchestrator.models import ErrorCode


def test_orchestrator_defaults_are_valid() -> None:
    cfg = OrchestratorConfig()
    assert cfg.validate() == []


def test_orchestrator_heartbeat_lt_poll_gives_error() -> None:
    cfg = OrchestratorConfig(heartbeat_interval_seconds=1, poll_interval_seconds=10)
    errs = cfg.validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_orchestrator_negative_poll_gives_error() -> None:
    cfg = OrchestratorConfig(poll_interval_seconds=0)
    errs = cfg.validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_mumu_empty_executable_gives_error() -> None:
    cfg = MuMuConfig(executable="")
    errs = cfg.validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_mumu_zero_start_timeout_gives_error() -> None:
    cfg = MuMuConfig(start_timeout_seconds=0)
    errs = cfg.validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_starrail_arguments_not_list_gives_error() -> None:
    cfg = StarRailConfig(
        executable="C:\\python.exe",
        working_directory="C:\\srp",
    )
    errs = cfg.validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR not in errs


def test_aalc_attempts_zero_gives_error() -> None:
    cfg = AALCConfig(attempts=0)
    errs = cfg.validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_aalc_attempts_over_3_gives_error() -> None:
    cfg = AALCConfig(attempts=5)
    errs = cfg.validate()
    assert ErrorCode.CONFIG_SCHEMA_ERROR in errs


def test_app_config_aggregates_errors() -> None:
    cfg = AppConfig(
        mumu=MuMuConfig(executable=""),
        aalc=AALCConfig(attempts=0),
    )
    errs = cfg.validate()
    assert len(errs) >= 2


def test_default_app_config_is_valid() -> None:
    cfg = AppConfig(
        orchestrator=OrchestratorConfig(),
        mumu=MuMuConfig(
            executable="C:\\MuMu.exe",
            adb_executable="C:\\adb.exe",
        ),
        starrail=StarRailConfig(
            executable="C:\\python.exe",
            working_directory="C:\\srp",
        ),
        maa=MAAConfig(
            executable="C:\\maa.exe",
            working_directory="C:\\maa-cli",
        ),
        aalc=AALCConfig(
            executable="C:\\AALC.exe",
            working_directory="C:\\AALC",
        ),
    )
    errs = cfg.validate()
    assert errs == []
