"""MAA CLI 运行结果模型。"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from autogame_orchestrator.models import JsonValue, is_json_serializable
from autogame_orchestrator.process.errors import TerminationReason


class MAARunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class MAAErrorCode(StrEnum):
    OK = "OK"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    EXECUTABLE_NOT_FOUND = "EXECUTABLE_NOT_FOUND"
    WORKING_DIRECTORY_NOT_FOUND = "WORKING_DIRECTORY_NOT_FOUND"
    PROCESS_START_FAILED = "PROCESS_START_FAILED"
    PROCESS_EXIT_NONZERO = "PROCESS_EXIT_NONZERO"
    PROCESS_TIMEOUT = "PROCESS_TIMEOUT"
    CANCELLED = "CANCELLED"
    WAIT_FAILED = "WAIT_FAILED"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class MAARunResult:
    """单次 MAA CLI 调用的不可变结果。"""

    status: MAARunStatus
    error_code: MAAErrorCode
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    pid: int | None
    exit_code: int | None
    termination_reason: TerminationReason | None
    owned_process_cleaned: bool
    stdout_excerpt: str
    stderr_excerpt: str
    stdout_truncated: bool
    stderr_truncated: bool
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None or self.duration_ms < 0:
            raise ValueError("时间必须带时区且耗时非负")
        if self.status == MAARunStatus.COMPLETED:
            valid = self.error_code == MAAErrorCode.OK and self.termination_reason == TerminationReason.NORMAL_EXIT
            if not valid or self.exit_code != 0 or not self.owned_process_cleaned:
                raise ValueError("完成结果不满足成功不变量")
        elif self.error_code == MAAErrorCode.OK:
            raise ValueError("非完成结果不得使用 OK")
        if self.error_code == MAAErrorCode.CLEANUP_FAILED and self.owned_process_cleaned:
            raise ValueError("清理失败必须标记为未清理")
        if self.status == MAARunStatus.TIMEOUT:
            if self.error_code not in {MAAErrorCode.PROCESS_TIMEOUT, MAAErrorCode.CLEANUP_FAILED}:
                raise ValueError("超时错误码不匹配")
            if self.termination_reason not in {TerminationReason.TIMEOUT, TerminationReason.TERMINATION_FAILED}:
                raise ValueError("超时终止原因不匹配")
        if self.status == MAARunStatus.CANCELLED:
            if self.error_code not in {MAAErrorCode.CANCELLED, MAAErrorCode.CLEANUP_FAILED}:
                raise ValueError("取消错误码不匹配")
            if self.termination_reason not in {TerminationReason.CANCELLED, TerminationReason.TERMINATION_FAILED}:
                raise ValueError("取消终止原因不匹配")
        if not is_json_serializable(dict(self.diagnostics)):
            raise ValueError("诊断信息必须可 JSON 序列化")

    @classmethod
    def from_monotonic(
        cls,
        *,
        status: MAARunStatus,
        error_code: MAAErrorCode,
        started_at: datetime,
        started_at_monotonic: float,
        pid: int | None,
        exit_code: int | None = None,
        termination_reason: TerminationReason | None = None,
        owned_process_cleaned: bool = True,
        stdout_excerpt: str = "",
        stderr_excerpt: str = "",
        stdout_truncated: bool = False,
        stderr_truncated: bool = False,
        diagnostics: Mapping[str, JsonValue] | None = None,
    ) -> MAARunResult:
        return cls(
            status=status,
            error_code=error_code,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            duration_ms=max(0, int((time.monotonic() - started_at_monotonic) * 1000)),
            pid=pid,
            exit_code=exit_code,
            termination_reason=termination_reason,
            owned_process_cleaned=owned_process_cleaned,
            stdout_excerpt=stdout_excerpt,
            stderr_excerpt=stderr_excerpt,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            diagnostics=diagnostics or {},
        )
