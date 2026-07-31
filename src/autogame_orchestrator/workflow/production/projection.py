"""Runtime 结果到 StageReport 的白名单安全投影。"""

from __future__ import annotations

from collections.abc import Mapping

from autogame_orchestrator.config_model import MumuLifecycleMode
from autogame_orchestrator.models import ErrorCode, JsonValue, OutcomeKind, StageName, StageReport
from autogame_orchestrator.probes.models import ProbeErrorCode, ProbeStatus
from autogame_orchestrator.runtime.aalc_models import AALCRunResult, AALCRunStatus
from autogame_orchestrator.runtime.maa_models import MAARunResult, MAARunStatus
from autogame_orchestrator.runtime.models import MumuRuntimeResult, MumuRuntimeStatus
from autogame_orchestrator.runtime.starrail_models import StarRailRunResult, StarRailRunStatus

_PROBE_STEP_ALLOWLIST = {
    "tcp_probe",
    "adb_devices",
    "select_device",
    "adb_get_state",
    "adb_boot_completed",
    "adb_connect",
    "none",
}
_PROBE_STATUS_ALLOWLIST = {item.value for item in ProbeStatus}
_PROBE_ERROR_ALLOWLIST = {item.value for item in ProbeErrorCode}
_ADB_CONNECT_STATUS_ALLOWLIST = {"not_attempted", "connected", "already_connected", "failed"}


def _outcome(
    status: object, completed: object, failed: object, timeout: object, cancelled: object
) -> tuple[OutcomeKind, ErrorCode]:
    if status == completed:
        return OutcomeKind.SUCCESS, ErrorCode.OK
    if status == timeout:
        return OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT
    if status == cancelled:
        return OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED
    if status == failed:
        return OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED
    return OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_RESULT_INVALID


def project_starrail(stage: StageName, result: StarRailRunResult) -> StageReport:
    outcome, code = _outcome(
        result.status,
        StarRailRunStatus.COMPLETED,
        StarRailRunStatus.FAILED,
        StarRailRunStatus.TIMEOUT,
        StarRailRunStatus.CANCELLED,
    )
    diagnostics: Mapping[str, JsonValue] = {
        "source_error_code": result.error_code.value,
        "completion_mode": result.completion_mode.value,
        "owned_process_cleaned": result.owned_process_cleaned,
        "matched_keyword_present": bool(result.matched_keyword),
        "log_path_present": bool(result.log_path),
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
        "exit_code": result.exit_code,
    }
    return StageReport(
        stage, outcome, code, result.started_at, result.finished_at, result.duration_ms, diagnostics=diagnostics
    )


def project_maa(stage: StageName, result: MAARunResult) -> StageReport:
    outcome, code = _outcome(
        result.status,
        MAARunStatus.COMPLETED,
        MAARunStatus.FAILED,
        MAARunStatus.TIMEOUT,
        MAARunStatus.CANCELLED,
    )
    diagnostics: Mapping[str, JsonValue] = {
        "source_error_code": result.error_code.value,
        "termination_reason": result.termination_reason.value if result.termination_reason else None,
        "exit_code": result.exit_code,
        "owned_process_cleaned": result.owned_process_cleaned,
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
    }
    return StageReport(
        stage, outcome, code, result.started_at, result.finished_at, result.duration_ms, diagnostics=diagnostics
    )


def project_aalc(stage: StageName, result: AALCRunResult) -> StageReport:
    outcome, code = _outcome(
        result.status,
        AALCRunStatus.COMPLETED,
        AALCRunStatus.FAILED,
        AALCRunStatus.TIMEOUT,
        AALCRunStatus.CANCELLED,
    )
    last = result.attempt_results[-1] if result.attempt_results else None
    diagnostics: Mapping[str, JsonValue] = {
        "source_error_code": result.error_code.value,
        "completion_mode": result.completion_mode.value,
        "configured_attempts": result.configured_attempts,
        "attempts_started": result.attempts_started,
        "successful_attempt_number": result.successful_attempt_number,
        "owned_process_cleaned": last.owned_process_cleaned if last else False,
        "last_exit_code": last.exit_code if last else None,
    }
    duration_ms = max(0, int(result.duration_seconds * 1000))
    return StageReport(
        stage, outcome, code, result.started_at, result.finished_at, duration_ms, diagnostics=diagnostics
    )


def project_mumu(
    stage: StageName,
    result: MumuRuntimeResult,
    *,
    lifecycle_mode: MumuLifecycleMode = MumuLifecycleMode.MANAGED,
    ensure_running: bool = False,
    verify_stopped: bool = False,
) -> StageReport:
    diagnostics: dict[str, JsonValue] = {
        "source_error_code": result.error_code.value,
        "action": result.action.value,
        "changed": result.changed,
        "lifecycle_mode": lifecycle_mode.value,
    }
    probe_status = result.diagnostics.get("probe_status")
    probe_error = result.diagnostics.get("probe_error")
    probe_step = result.diagnostics.get("probe_step")
    if isinstance(probe_status, str) and probe_status in _PROBE_STATUS_ALLOWLIST:
        diagnostics["probe_status"] = probe_status
    if isinstance(probe_error, str) and probe_error in _PROBE_ERROR_ALLOWLIST:
        diagnostics["probe_error"] = probe_error
    if isinstance(probe_step, str) and probe_step in _PROBE_STEP_ALLOWLIST:
        diagnostics["probe_step"] = probe_step
    connect_attempted = result.diagnostics.get("adb_connect_attempted")
    if isinstance(connect_attempted, bool):
        diagnostics["adb_connect_attempted"] = connect_attempted
    connect_status = result.diagnostics.get("adb_connect_status")
    if isinstance(connect_status, str) and connect_status in _ADB_CONNECT_STATUS_ALLOWLIST:
        diagnostics["adb_connect_status"] = connect_status
    connect_error = result.diagnostics.get("adb_connect_error")
    if isinstance(connect_error, str) and (connect_error == "none" or connect_error in _PROBE_ERROR_ALLOWLIST):
        diagnostics["adb_connect_error"] = connect_error
    rechecked = result.diagnostics.get("readiness_rechecked_after_connect")
    if isinstance(rechecked, bool):
        diagnostics["readiness_rechecked_after_connect"] = rechecked
    if result.status == MumuRuntimeStatus.TIMEOUT:
        outcome, code = OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT
    elif result.status == MumuRuntimeStatus.CANCELLED:
        outcome, code = OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED
    elif verify_stopped and result.status == MumuRuntimeStatus.STOPPED:
        outcome, code = OutcomeKind.SUCCESS, ErrorCode.OK
    elif ensure_running and result.status == MumuRuntimeStatus.STOPPED:
        outcome, code = OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_BLOCKED
        diagnostics["blocker"] = (
            "mumu_external_not_ready" if lifecycle_mode == MumuLifecycleMode.EXTERNAL else "mumu_start_not_approved"
        )
    elif not verify_stopped and result.status == MumuRuntimeStatus.READY:
        outcome, code = OutcomeKind.SUCCESS, ErrorCode.OK
    else:
        outcome, code = OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED
    return StageReport(
        stage, outcome, code, result.started_at, result.finished_at, result.duration_ms, diagnostics=diagnostics
    )
