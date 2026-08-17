"""Safe desktop notification for a completed failed production run."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from dataclasses import dataclass

from autogame_orchestrator.models import OutcomeKind, RunStatus, StageName, StageReport
from autogame_orchestrator.run_application import RunCommandResult

_DIALOG_TITLE = "OrchestratoRRR 执行失败"
_MESSAGE_BOX_FLAGS = 0x00000000 | 0x00000010 | 0x00010000


@dataclass(frozen=True)
class FailureNotificationDependencies:
    platform: str
    frozen: bool
    stdin_isatty: Callable[[], bool]
    stdout_isatty: Callable[[], bool]
    show_dialog: Callable[[str, str], None]


def _show_windows_dialog(title: str, message: str) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    message_box = user32.MessageBoxW
    message_box.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint,
    ]
    message_box.restype = ctypes.c_int
    message_box(None, message, title, _MESSAGE_BOX_FLAGS)


def default_failure_notification_dependencies() -> FailureNotificationDependencies:
    return FailureNotificationDependencies(
        platform=sys.platform,
        frozen=bool(getattr(sys, "frozen", False)),
        stdin_isatty=sys.stdin.isatty,
        stdout_isatty=sys.stdout.isatty,
        show_dialog=_show_windows_dialog,
    )


def _original_failure(stages: tuple[StageReport, ...]) -> StageReport | None:
    for stage in stages:
        if stage.stage in {StageName.SHUTDOWN_MUMU, StageName.WRITE_RUN_REPORT}:
            continue
        if stage.outcome in {
            OutcomeKind.FAILURE,
            OutcomeKind.TIMEOUT,
            OutcomeKind.CANCELLED,
        }:
            return stage
    for stage in stages:
        if stage.outcome in {
            OutcomeKind.FAILURE,
            OutcomeKind.TIMEOUT,
            OutcomeKind.CANCELLED,
        }:
            return stage
    return None


def _cleanup_label(stages: tuple[StageReport, ...]) -> str:
    shutdown = next(
        (stage for stage in stages if stage.stage == StageName.SHUTDOWN_MUMU),
        None,
    )
    if shutdown is None or shutdown.outcome == OutcomeKind.SKIPPED:
        return "未需要"
    if shutdown.outcome == OutcomeKind.SUCCESS:
        return "成功"
    return "失败"


def notify_interactive_run_failure(
    result: RunCommandResult,
    *,
    dependencies: FailureNotificationDependencies | None = None,
) -> bool:
    """Show one bounded-information dialog after the RunReport has been written."""
    report = result.report
    if result.exit_code == 0 or report is None or report.status == RunStatus.SUCCESS:
        return False

    selected = default_failure_notification_dependencies() if dependencies is None else dependencies
    if (
        selected.platform != "win32"
        or not selected.frozen
        or not selected.stdin_isatty()
        or not selected.stdout_isatty()
    ):
        return False

    original = _original_failure(report.stages)
    failed_stage = original.stage.value if original is not None else "unknown"
    error_code = original.error_code.value if original is not None else report.error_code.value
    message = (
        "OrchestratoRRR 执行失败\n\n"
        f"失败阶段：\n{failed_stage}\n\n"
        f"错误：\n{error_code}\n\n"
        f"MuMu 清理：\n{_cleanup_label(report.stages)}\n\n"
        "详细诊断已写入 RunReport。"
    )
    try:
        selected.show_dialog(_DIALOG_TITLE, message)
    except Exception:
        return False
    return True


__all__ = [
    "FailureNotificationDependencies",
    "default_failure_notification_dependencies",
    "notify_interactive_run_failure",
]
