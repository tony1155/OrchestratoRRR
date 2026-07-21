"""ProcessResult：进程执行的最终不可变结果。

冻结 dataclass，由 ProcessSupervisor 在 wait/run/stop 返回前构造。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from autogame_orchestrator.models import JsonValue, is_json_serializable
from autogame_orchestrator.process.errors import ProcessExecutionErrorCode, TerminationReason


@dataclass(frozen=True)
class ProcessResult:
    """不可变的进程执行结果。

    由 ProcessSupervisor 在进程终态时生成。
    对外使用带时区 datetime，内部 duration 基于 monotonic 时间计算。
    """

    name: str
    """进程名称（来自 ProcessSpec.name）。"""

    pid: int | None
    """操作系统 PID。启动失败时为 None。"""

    termination_reason: TerminationReason
    """终止原因。"""

    exit_code: int | None
    """操作系统退出码。强制终止时为 None。"""

    error_code: ProcessExecutionErrorCode
    """稳定错误码。NORMAL_EXIT 使用 OK。"""

    started_at: datetime | None
    """启动时间（带时区）。启动失败时为 None。"""

    finished_at: datetime
    """结束时间（带时区）。"""

    duration_ms: int
    """执行耗时（毫秒），基于 monotonic 时钟。"""

    stdout_path: Path | None = None
    """stdout 输出文件路径。"""

    stderr_path: Path | None = None
    """stderr 输出文件路径。"""

    forced_termination: bool = False
    """是否被强制终止（timeout/cancel/stop）。"""

    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)
    """附加诊断信息（不含环境变量或凭据）。"""

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            msg = f"duration_ms 不能为负，收到 {self.duration_ms}"
            raise ValueError(msg)

        # NORMAL_EXIT 必须使用 OK
        if self.termination_reason == TerminationReason.NORMAL_EXIT and self.error_code != ProcessExecutionErrorCode.OK:
            msg = f"NORMAL_EXIT 必须使用 OK，收到 {self.error_code.value}"
            raise ValueError(msg)

        # 非正常结果不得使用 OK
        _non_ok_reasons = {
            TerminationReason.NONZERO_EXIT,
            TerminationReason.TIMEOUT,
            TerminationReason.CANCELLED,
            TerminationReason.STOPPED,
            TerminationReason.START_FAILED,
            TerminationReason.WAIT_FAILED,
            TerminationReason.TERMINATION_FAILED,
        }
        if self.termination_reason in _non_ok_reasons and self.error_code == ProcessExecutionErrorCode.OK:
            msg = f"{self.termination_reason.value} 不得使用 OK"
            raise ValueError(msg)

        # diagnostics 必须可 JSON 序列化
        if not is_json_serializable(dict(self.diagnostics)):
            msg = "diagnostics 包含不可 JSON 序列化的值"
            raise ValueError(msg)

    @classmethod
    def start_failed(
        cls,
        name: str,
        error_code: ProcessExecutionErrorCode,
        diagnostics: Mapping[str, JsonValue] | None = None,
    ) -> ProcessResult:
        """构造启动失败结果。"""
        now = datetime.now(UTC)
        return cls(
            name=name,
            pid=None,
            termination_reason=TerminationReason.START_FAILED,
            exit_code=None,
            error_code=error_code,
            started_at=None,
            finished_at=now,
            duration_ms=0,
            diagnostics=diagnostics or {},
        )

    @classmethod
    def from_exit(
        cls,
        name: str,
        pid: int,
        exit_code: int,
        started_at_monotonic: float,
        stdout_path: Path | None,
        stderr_path: Path | None,
        forced_termination: bool = False,
        diagnostics: Mapping[str, JsonValue] | None = None,
    ) -> ProcessResult:
        """根据退出码构造结果。"""
        now = datetime.now(UTC)
        import time

        duration = time.monotonic() - started_at_monotonic
        duration_ms = max(0, int(duration * 1000))

        if exit_code == 0:
            reason = TerminationReason.NORMAL_EXIT
            code = ProcessExecutionErrorCode.OK
        else:
            reason = TerminationReason.NONZERO_EXIT
            code = ProcessExecutionErrorCode.EXIT_NONZERO

        return cls(
            name=name,
            pid=pid,
            termination_reason=reason,
            exit_code=exit_code,
            error_code=code,
            started_at=None,  # 后续可由 Adapter 填充
            finished_at=now,
            duration_ms=duration_ms,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            forced_termination=forced_termination,
            diagnostics=diagnostics or {},
        )

    @classmethod
    def terminated(
        cls,
        name: str,
        pid: int,
        reason: TerminationReason,
        error_code: ProcessExecutionErrorCode,
        started_at_monotonic: float,
        stdout_path: Path | None,
        stderr_path: Path | None,
        exit_code: int | None = None,
        diagnostics: Mapping[str, JsonValue] | None = None,
    ) -> ProcessResult:
        """构造强制终止结果。"""
        now = datetime.now(UTC)
        import time

        duration = time.monotonic() - started_at_monotonic
        duration_ms = max(0, int(duration * 1000))

        return cls(
            name=name,
            pid=pid,
            termination_reason=reason,
            exit_code=exit_code,
            error_code=error_code,
            started_at=None,
            finished_at=now,
            duration_ms=duration_ms,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            forced_termination=True,
            diagnostics=diagnostics or {},
        )
