"""run v1 纯门禁、参数和稳定退出码测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from autogame_orchestrator.config_model import (
    AALCConfig,
    AppConfig,
    MAASyncConfig,
    MAAUpdateConfig,
    MuMuConfig,
    MumuLifecycleMode,
)
from autogame_orchestrator.entry_runtime import EntryRuntime, EntryRuntimeKind
from autogame_orchestrator.models import ErrorCode, RunReport, RunStatus, StageName
from autogame_orchestrator.run_application import (
    ELEVATION_MARKER,
    EXTERNAL_RUN_STAGES,
    RUN_CONFIRMATION,
    RunRequest,
    build_relaunch_spec,
    execute_run_request,
    map_run_exit_code,
    validate_external_plan,
    validate_run_request,
    validate_run_v1_config,
)
from autogame_orchestrator.workflow.plan import ExecutionPlan
from tests.run_application.helpers import fake_dependencies, write_run_config


def _request(
    *,
    confirmation: object = RUN_CONFIRMATION,
    deadline: object = 30.0,
    elevation_child: bool = False,
) -> RunRequest:
    return RunRequest(
        Path("safe-reference.toml"),
        deadline,  # type: ignore[arg-type]
        confirmation,  # type: ignore[arg-type]
        elevation_child,
    )


def _external_config(**changes: object) -> AppConfig:
    values: dict[str, object] = {
        "mumu": MuMuConfig(lifecycle_mode=MumuLifecycleMode.EXTERNAL),
        "aalc": AALCConfig(attempts=1),
    }
    values.update(changes)
    return AppConfig(**values)  # type: ignore[arg-type]


def _report(status: RunStatus, error_code: ErrorCode) -> RunReport:
    now = datetime.now(UTC)
    return RunReport(
        1,
        "00000000-0000-0000-0000-000000000001",
        "test",
        "workflow_external",
        status,
        error_code,
        now,
        now,
        0,
    )


@pytest.mark.parametrize(
    "confirmation",
    [
        "",
        "i_understand_this_runs_real_programs",
        " I_UNDERSTAND_THIS_RUNS_REAL_PROGRAMS",
        "I_UNDERSTAND_THIS_RUNS_REAL_PROGRAMS ",
        "I_UNDERSTAND",
        True,
        None,
    ],
)
def test_confirmation_must_match_exactly(confirmation: object) -> None:
    assert validate_run_request(_request(confirmation=confirmation)) == "real_execution_confirmation_required"


def test_exact_confirmation_is_accepted() -> None:
    assert validate_run_request(_request()) is None


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), float("-inf"), 86400.1, True, False, "30", None])
def test_invalid_deadline_is_rejected(value: object) -> None:
    assert validate_run_request(_request(deadline=value)) == "invalid_deadline"


@pytest.mark.parametrize("value", [0.001, 1, 86399.9, 86400])
def test_finite_bounded_deadline_is_accepted(value: float) -> None:
    assert validate_run_request(_request(deadline=value)) is None


def test_managed_mode_is_rejected_by_run_v1() -> None:
    assert validate_run_v1_config(AppConfig(aalc=AALCConfig(attempts=1))) == "managed_mumu_not_supported"


def test_enabled_sync_is_rejected_by_run_v1() -> None:
    config = _external_config(maa_sync=MAASyncConfig(enabled=True))
    assert validate_run_v1_config(config) == "maa_sync_not_allowed_in_run_v1"


def test_enabled_update_is_rejected_by_run_v1() -> None:
    config = _external_config(maa_update=MAAUpdateConfig(enabled=True, allow_network=True))
    assert validate_run_v1_config(config) == "maa_update_not_allowed_in_run_v1"


@pytest.mark.parametrize("attempts", [2, 3])
def test_aalc_retry_is_rejected_by_run_v1(attempts: int) -> None:
    config = _external_config(aalc=AALCConfig(attempts=attempts))
    assert validate_run_v1_config(config) == "aalc_retries_not_allowed_in_run_v1"


def test_external_v1_config_is_accepted() -> None:
    assert validate_run_v1_config(_external_config()) is None


def test_exact_external_plan_is_accepted() -> None:
    assert validate_external_plan(ExecutionPlan(EXTERNAL_RUN_STAGES, False)) is None


@pytest.mark.parametrize(
    "stages",
    [
        (StageName.VALIDATE_CONFIG, StageName.WRITE_RUN_REPORT),
        EXTERNAL_RUN_STAGES[:-2] + (StageName.WRITE_RUN_REPORT,),
        EXTERNAL_RUN_STAGES[:8] + (StageName.STOP_MUMU,) + EXTERNAL_RUN_STAGES[8:],
        EXTERNAL_RUN_STAGES[:3] + EXTERNAL_RUN_STAGES[4:],
    ],
)
def test_non_exact_external_plan_is_rejected(stages: tuple[StageName, ...]) -> None:
    assert validate_external_plan(ExecutionPlan(stages, False)) == "external_plan_invalid"


def test_source_relaunch_spec_uses_module_entrypoint(tmp_path: Path) -> None:
    runtime = EntryRuntime(EntryRuntimeKind.SOURCE, tmp_path / "python.exe", tmp_path)
    spec = build_relaunch_spec(_request(), runtime)
    assert spec.executable == tmp_path / "python.exe"
    assert spec.working_directory == tmp_path
    assert spec.arguments == (
        "-m",
        "autogame_orchestrator",
        "run",
        "--config",
        str(Path("safe-reference.toml").resolve()),
        "--deadline-seconds",
        "30",
        "--confirm-real-execution",
        RUN_CONFIRMATION,
        ELEVATION_MARKER,
    )


def test_relaunch_spec_includes_only_allowed_cli_fields(tmp_path: Path) -> None:
    runtime = EntryRuntime(EntryRuntimeKind.SOURCE, tmp_path / "python.exe", tmp_path)
    arguments = build_relaunch_spec(_request(), runtime).arguments
    assert set(arguments[3::2]) >= {"--config", "--deadline-seconds", "--confirm-real-execution"}
    for forbidden in ("--stage", "--skip-stage", "--force", "--unsafe", "--mode"):
        assert forbidden not in arguments


def test_source_relaunch_spec_appends_marker_once(tmp_path: Path) -> None:
    runtime = EntryRuntime(EntryRuntimeKind.SOURCE, tmp_path / "python.exe", tmp_path)
    assert build_relaunch_spec(_request(), runtime).arguments.count(ELEVATION_MARKER) == 1


def test_elevation_child_does_not_append_marker_again(tmp_path: Path) -> None:
    runtime = EntryRuntime(EntryRuntimeKind.SOURCE, tmp_path / "python.exe", tmp_path)
    arguments = build_relaunch_spec(_request(elevation_child=True), runtime).arguments
    assert ELEVATION_MARKER not in arguments


def test_frozen_relaunch_spec_uses_executable_entrypoint(tmp_path: Path) -> None:
    runtime = EntryRuntime(EntryRuntimeKind.FROZEN, tmp_path / "OrchestratoRRR.exe", tmp_path)
    spec = build_relaunch_spec(_request(), runtime)
    assert spec.executable == tmp_path / "OrchestratoRRR.exe"
    assert spec.arguments == (
        "run",
        "--config",
        str(Path("safe-reference.toml").resolve()),
        "--deadline-seconds",
        "30",
        "--confirm-real-execution",
        RUN_CONFIRMATION,
        ELEVATION_MARKER,
    )


def test_relaunch_spec_keeps_unicode_config_path_as_one_argument(tmp_path: Path) -> None:
    config_path = tmp_path / "配置 目录" / "配置.toml"
    runtime = EntryRuntime(EntryRuntimeKind.SOURCE, tmp_path / "程序.exe", tmp_path / "工作 目录")
    request = RunRequest(config_path, 30, RUN_CONFIRMATION)

    spec = build_relaunch_spec(request, runtime)

    assert spec.arguments[4] == str(config_path.resolve())
    assert '"' not in spec.arguments[4]


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (RunStatus.SUCCESS, ErrorCode.OK, 0),
        (RunStatus.CANCELLED, ErrorCode.WORKFLOW_CANCELLED, 5),
        (RunStatus.FAILURE, ErrorCode.WORKFLOW_STAGE_TIMEOUT, 4),
        (RunStatus.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED, 3),
        (RunStatus.FAILURE, ErrorCode.INTERNAL_ERROR, 3),
        (RunStatus.FAILURE, ErrorCode.RUN_REPORT_WRITE_ERROR, 7),
    ],
)
def test_workflow_exit_code_mapping(status: RunStatus, code: ErrorCode, expected: int) -> None:
    assert map_run_exit_code(_report(status, code)) == expected


def test_confirmation_failure_does_not_read_missing_config() -> None:
    result = execute_run_request(_request(confirmation="wrong"))
    assert (result.exit_code, result.error_code) == (2, "real_execution_confirmation_required")


def test_deadline_failure_does_not_read_missing_config() -> None:
    result = execute_run_request(_request(deadline=0))
    assert (result.exit_code, result.error_code) == (2, "invalid_deadline")


def test_missing_config_is_stable_error(tmp_path: Path) -> None:
    result = execute_run_request(RunRequest(tmp_path / "missing.toml", 30, RUN_CONFIRMATION))
    assert (result.exit_code, result.error_code) == (2, ErrorCode.CONFIG_FILE_NOT_FOUND.value)


def test_invalid_toml_is_stable_error(tmp_path: Path) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text("not = [valid", encoding="utf-8")
    result = execute_run_request(RunRequest(path, 30, RUN_CONFIRMATION))
    assert (result.exit_code, result.error_code) == (2, ErrorCode.CONFIG_PARSE_ERROR.value)


@pytest.mark.parametrize(
    ("settings", "error"),
    [
        ({"lifecycle_mode": "managed"}, "managed_mumu_not_supported"),
        ({"sync_enabled": True}, "maa_sync_not_allowed_in_run_v1"),
        ({"update_enabled": True}, "maa_update_not_allowed_in_run_v1"),
        ({"aalc_attempts": 2}, "aalc_retries_not_allowed_in_run_v1"),
    ],
)
def test_run_v1_gate_stops_before_runtime(tmp_path: Path, settings: dict[str, object], error: str) -> None:
    config_path = write_run_config(tmp_path, **settings)  # type: ignore[arg-type]
    dependencies, counts, sink, logs, *_ = fake_dependencies()
    result = execute_run_request(
        RunRequest(config_path, 30, RUN_CONFIRMATION),
        dependencies=dependencies,
    )
    assert (result.exit_code, result.error_code) == (2, error)
    assert counts == {}
    assert sink.reports == []
    assert logs == []
