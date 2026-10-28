"""Desktop failure notification policy tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from autogame_orchestrator.failure_notification import (
    FailureNotificationDependencies,
    notify_interactive_run_failure,
)
from autogame_orchestrator.models import (
    ErrorCode,
    OutcomeKind,
    RunReport,
    RunStatus,
    StageName,
    StageReport,
)
from autogame_orchestrator.run_application import RunCommandResult


def _stage(
    stage: StageName,
    outcome: OutcomeKind,
    error_code: ErrorCode,
) -> StageReport:
    now = datetime.now(UTC)
    return StageReport(stage, outcome, error_code, now, now, 0)


def _result(cleanup: OutcomeKind = OutcomeKind.SUCCESS) -> RunCommandResult:
    cleanup_error = ErrorCode.OK if cleanup == OutcomeKind.SUCCESS else ErrorCode.WORKFLOW_STAGE_TIMEOUT
    now = datetime.now(UTC)
    report = RunReport(
        1,
        "00000000-0000-0000-0000-000000000001",
        "0.1.0",
        "workflow_external",
        RunStatus.FAILURE,
        ErrorCode.WORKFLOW_STAGE_TIMEOUT,
        now,
        now,
        0,
        (
            _stage(
                StageName.ENSURE_MUMU_RUNNING,
                OutcomeKind.TIMEOUT,
                ErrorCode.WORKFLOW_STAGE_TIMEOUT,
            ),
            _stage(StageName.RUN_STARRAIL, OutcomeKind.SKIPPED, ErrorCode.SKIPPED),
            _stage(StageName.SHUTDOWN_MUMU, cleanup, cleanup_error),
            _stage(StageName.WRITE_RUN_REPORT, OutcomeKind.SUCCESS, ErrorCode.OK),
        ),
    )
    return RunCommandResult(
        4,
        report.status.value,
        report.error_code.value,
        report.run_id,
        report,
    )


@pytest.mark.parametrize("frozen", [False, True])
def test_interactive_failure_shows_safe_dialog_after_report(frozen: bool) -> None:
    shown: list[tuple[str, str]] = []
    dependencies = FailureNotificationDependencies(
        platform="win32",
        frozen=frozen,
        stdin_isatty=lambda: True,
        stdout_isatty=lambda: True,
        show_dialog=lambda title, message: shown.append((title, message)),
    )

    assert notify_interactive_run_failure(_result(), dependencies=dependencies) is True
    assert len(shown) == 1
    title, message = shown[0]
    assert title == "OrchestratoRRR 执行失败"
    assert "ensure_mumu_running" in message
    assert "WORKFLOW_STAGE_TIMEOUT" in message
    assert "MuMu 清理：\n成功" in message
    assert "RunReport" in message
    for forbidden in (
        "I_UNDERSTAND_THIS_RUNS_REAL_PROGRAMS",
        "127.0.0.1",
        "stdout",
        "stderr",
        "ProcessId",
    ):
        assert forbidden not in message
    json.dumps(message, ensure_ascii=False)


def test_cleanup_failure_does_not_replace_original_dialog_error() -> None:
    shown: list[str] = []
    dependencies = FailureNotificationDependencies(
        platform="win32",
        frozen=True,
        stdin_isatty=lambda: True,
        stdout_isatty=lambda: True,
        show_dialog=lambda _title, message: shown.append(message),
    )

    assert (
        notify_interactive_run_failure(
            _result(OutcomeKind.TIMEOUT),
            dependencies=dependencies,
        )
        is True
    )
    assert "失败阶段：\nensure_mumu_running" in shown[0]
    assert "错误：\nWORKFLOW_STAGE_TIMEOUT" in shown[0]
    assert "MuMu 清理：\n失败" in shown[0]


@pytest.mark.parametrize(
    ("platform", "frozen", "stdin_tty", "stdout_tty"),
    [
        ("linux", True, True, True),
        ("win32", False, False, True),
        ("win32", False, True, False),
        ("win32", True, False, True),
        ("win32", True, True, False),
    ],
)
def test_noninteractive_or_nonwindows_failure_never_shows_dialog(
    platform: str,
    frozen: bool,
    stdin_tty: bool,
    stdout_tty: bool,
) -> None:
    calls = 0

    def show(_title: str, _message: str) -> None:
        nonlocal calls
        calls += 1

    dependencies = FailureNotificationDependencies(
        platform=platform,
        frozen=frozen,
        stdin_isatty=lambda: stdin_tty,
        stdout_isatty=lambda: stdout_tty,
        show_dialog=show,
    )
    assert notify_interactive_run_failure(_result(), dependencies=dependencies) is False
    assert calls == 0


def test_dialog_failure_is_swallowed_and_exit_result_is_unchanged() -> None:
    result = _result()
    dependencies = FailureNotificationDependencies(
        platform="win32",
        frozen=True,
        stdin_isatty=lambda: True,
        stdout_isatty=lambda: True,
        show_dialog=lambda _title, _message: (_ for _ in ()).throw(OSError()),
    )

    assert notify_interactive_run_failure(result, dependencies=dependencies) is False
    assert result.exit_code == 4
