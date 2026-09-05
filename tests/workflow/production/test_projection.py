"""四类 Runtime 结果的白名单投影测试。"""

import json

import pytest

from autogame_orchestrator.models import ErrorCode, OutcomeKind, StageName
from autogame_orchestrator.runtime.aalc_models import AALCRunStatus
from autogame_orchestrator.runtime.maa_models import MAARunStatus
from autogame_orchestrator.runtime.models import MumuRuntimeStatus
from autogame_orchestrator.runtime.starrail_models import StarRailRunStatus
from autogame_orchestrator.workflow.production.projection import (
    project_aalc,
    project_maa,
    project_mumu,
    project_starrail,
)
from tests.workflow.production.fakes import aalc_result, maa_result, mumu_result, starrail_result


@pytest.mark.parametrize(
    ("status", "outcome", "code"),
    [
        (StarRailRunStatus.COMPLETED, OutcomeKind.SUCCESS, ErrorCode.OK),
        (StarRailRunStatus.FAILED, OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED),
        (StarRailRunStatus.TIMEOUT, OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT),
        (StarRailRunStatus.CANCELLED, OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED),
    ],
)
def test_starrail_status_mapping(status, outcome, code) -> None:
    report = project_starrail(StageName.RUN_STARRAIL, starrail_result(status))
    assert (report.outcome, report.error_code) == (outcome, code)


def test_starrail_projection_uses_allowlist() -> None:
    report = project_starrail(StageName.RUN_STARRAIL, starrail_result())
    assert set(report.diagnostics) == {
        "source_error_code",
        "completion_mode",
        "owned_process_cleaned",
        "matched_keyword_present",
        "log_path_present",
        "stdout_truncated",
        "stderr_truncated",
        "exit_code",
    }


def test_starrail_projection_preserves_runtime_time() -> None:
    result = starrail_result()
    report = project_starrail(StageName.RUN_STARRAIL, result)
    assert (report.started_at, report.finished_at, report.duration_ms) == (
        result.started_at,
        result.finished_at,
        result.duration_ms,
    )


def test_starrail_cleanup_failure_is_safely_projected() -> None:
    report = project_starrail(StageName.RUN_STARRAIL, starrail_result(StarRailRunStatus.FAILED))
    assert report.diagnostics["owned_process_cleaned"] is False


@pytest.mark.parametrize(
    ("status", "outcome", "code"),
    [
        (MAARunStatus.COMPLETED, OutcomeKind.SUCCESS, ErrorCode.OK),
        (MAARunStatus.FAILED, OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED),
        (MAARunStatus.TIMEOUT, OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT),
        (MAARunStatus.CANCELLED, OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED),
    ],
)
def test_maa_status_mapping(status, outcome, code) -> None:
    report = project_maa(StageName.RUN_MAA, maa_result(status))
    assert (report.outcome, report.error_code) == (outcome, code)


def test_maa_projection_uses_allowlist() -> None:
    report = project_maa(StageName.RUN_MAA, maa_result())
    assert set(report.diagnostics) == {
        "source_error_code",
        "termination_reason",
        "exit_code",
        "owned_process_cleaned",
        "stdout_truncated",
        "stderr_truncated",
        "stdout_present",
        "stderr_present",
        "failure_markers",
    }


def test_maa_projection_reports_output_presence() -> None:
    report = project_maa(StageName.RUN_MAA, maa_result())
    assert report.diagnostics["stdout_present"] is True
    assert report.diagnostics["stderr_present"] is True
    empty = project_maa(StageName.RUN_MAA, maa_result(stdout_excerpt="", stderr_excerpt=""))
    assert empty.diagnostics["stdout_present"] is False
    assert empty.diagnostics["stderr_present"] is False


def test_maa_projection_extracts_stable_failure_markers() -> None:
    """资源加载失败应当直接体现在报告里，而不需要翻 MaaCore 的 asst.log。"""
    result = maa_result(
        MAARunStatus.FAILED,
        stdout_excerpt="",
        stderr_excerpt=(
            "Error: MaaCore returned an error, check its log for details\n"
            "Failed to create Assistant: resources may not be loaded\n"
        ),
    )
    markers = project_maa(StageName.RUN_MAA, result).diagnostics["failure_markers"]
    assert markers == ["core_error", "resource_load_failed"]


def test_maa_projection_markers_are_empty_without_known_cause() -> None:
    result = maa_result(MAARunStatus.FAILED, stdout_excerpt="plain", stderr_excerpt="nothing recognisable")
    assert project_maa(StageName.RUN_MAA, result).diagnostics["failure_markers"] == []


def test_maa_failure_markers_never_leak_surrounding_text() -> None:
    result = maa_result(
        MAARunStatus.FAILED,
        stdout_excerpt="",
        stderr_excerpt="Failed to pull resource repository at E:\\private\\MaaResource",
    )
    report = project_maa(StageName.RUN_MAA, result)
    assert report.diagnostics["failure_markers"] == ["resource_repo_pull_failed"]
    assert "private" not in json.dumps(report.to_json_encodable(), ensure_ascii=False)


def test_maa_projection_preserves_runtime_time() -> None:
    result = maa_result()
    report = project_maa(StageName.RUN_MAA, result)
    assert report.duration_ms == result.duration_ms


@pytest.mark.parametrize(
    ("status", "outcome", "code"),
    [
        (AALCRunStatus.COMPLETED, OutcomeKind.SUCCESS, ErrorCode.OK),
        (AALCRunStatus.FAILED, OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED),
        (AALCRunStatus.TIMEOUT, OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT),
        (AALCRunStatus.CANCELLED, OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED),
    ],
)
def test_aalc_status_mapping(status, outcome, code) -> None:
    report = project_aalc(StageName.RUN_AALC, aalc_result(status))
    assert (report.outcome, report.error_code) == (outcome, code)


def test_aalc_projection_uses_allowlist() -> None:
    report = project_aalc(StageName.RUN_AALC, aalc_result())
    assert set(report.diagnostics) == {
        "source_error_code",
        "completion_mode",
        "configured_attempts",
        "attempts_started",
        "successful_attempt_number",
        "owned_process_cleaned",
        "last_exit_code",
    }


def test_aalc_duration_converts_to_milliseconds() -> None:
    assert project_aalc(StageName.RUN_AALC, aalc_result()).duration_ms == 2000


@pytest.mark.parametrize(
    ("status", "outcome", "code"),
    [
        (MumuRuntimeStatus.READY, OutcomeKind.SUCCESS, ErrorCode.OK),
        (MumuRuntimeStatus.NOT_READY, OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED),
        (MumuRuntimeStatus.TIMEOUT, OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT),
        (MumuRuntimeStatus.CANCELLED, OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED),
    ],
)
def test_mumu_wait_status_mapping(status, outcome, code) -> None:
    report = project_mumu(StageName.WAIT_MUMU_ADB_READY, mumu_result(status))
    assert (report.outcome, report.error_code) == (outcome, code)


def test_mumu_stopped_blocks_ensure_running() -> None:
    report = project_mumu(
        StageName.ENSURE_MUMU_RUNNING,
        mumu_result(MumuRuntimeStatus.STOPPED),
        ensure_running=True,
    )
    assert report.error_code == ErrorCode.WORKFLOW_STAGE_BLOCKED
    assert report.diagnostics["blocker"] == "mumu_start_not_approved"


@pytest.mark.parametrize(
    ("stage", "status", "ensure_running"),
    [
        (StageName.ENSURE_MUMU_RUNNING, MumuRuntimeStatus.STARTED, True),
        (StageName.START_MUMU, MumuRuntimeStatus.STARTED, False),
        (StageName.ENSURE_MUMU_RUNNING, MumuRuntimeStatus.RESTARTED, True),
    ],
)
def test_mumu_lifecycle_action_statuses_are_success(
    stage: StageName, status: MumuRuntimeStatus, ensure_running: bool
) -> None:
    """managed 生命周期动作成功时返回 STARTED/RESTARTED，投影层必须认作成功。

    回归保护：投影层原本只把只读探测的 READY 归为成功，而 ``MumuAdapter.start()``
    成功时返回 STARTED，因此真实启动成功的模拟器会被误判为 WORKFLOW_STAGE_FAILED。
    """
    report = project_mumu(stage, mumu_result(status), ensure_running=ensure_running)
    assert (report.outcome, report.error_code) == (OutcomeKind.SUCCESS, ErrorCode.OK)


def test_mumu_stopped_succeeds_verify_stopped() -> None:
    report = project_mumu(
        StageName.VERIFY_MUMU_STOPPED,
        mumu_result(MumuRuntimeStatus.STOPPED),
        expect_stopped=True,
    )
    assert report.outcome == OutcomeKind.SUCCESS


def test_mumu_stop_action_stopped_is_success() -> None:
    """``STOP_MUMU`` 以 STOPPED 为成功：managed 停止动作成功时就是返回 STOPPED。

    回归保护：STOPPED 原本仅在 VERIFY_MUMU_STOPPED 阶段被归为成功，导致真实停止
    成功的 STOP_MUMU 阶段被误判为 WORKFLOW_STAGE_FAILED。
    """
    report = project_mumu(
        StageName.STOP_MUMU,
        mumu_result(MumuRuntimeStatus.STOPPED),
        expect_stopped=True,
    )
    assert (report.outcome, report.error_code) == (OutcomeKind.SUCCESS, ErrorCode.OK)


def test_mumu_stop_stage_rejects_still_ready() -> None:
    """停止阶段拿到 READY 必须判失败——说明模拟器并未真正停下。"""
    report = project_mumu(
        StageName.STOP_MUMU,
        mumu_result(MumuRuntimeStatus.READY),
        expect_stopped=True,
    )
    assert report.outcome == OutcomeKind.FAILURE


def test_mumu_projection_uses_allowlist() -> None:
    report = project_mumu(StageName.WAIT_MUMU_ADB_READY, mumu_result(MumuRuntimeStatus.NOT_READY))
    assert set(report.diagnostics) == {"source_error_code", "action", "changed", "lifecycle_mode"}
    assert report.diagnostics["lifecycle_mode"] == "managed"


@pytest.mark.parametrize(
    "projected",
    [
        lambda: project_starrail(StageName.RUN_STARRAIL, starrail_result()),
        lambda: project_maa(StageName.RUN_MAA, maa_result()),
        lambda: project_aalc(StageName.RUN_AALC, aalc_result()),
        lambda: project_mumu(StageName.WAIT_MUMU_ADB_READY, mumu_result(MumuRuntimeStatus.NOT_READY)),
    ],
)
def test_projection_diagnostics_are_json_serializable(projected) -> None:
    json.dumps(dict(projected().diagnostics))
