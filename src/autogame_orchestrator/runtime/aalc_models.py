"""AALC 有界重试运行结果模型。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from autogame_orchestrator.models import JsonValue, is_json_serializable


class AALCRunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class AALCAttemptStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class AALCCompletionMode(StrEnum):
    NORMAL_EXIT = "normal_exit"
    RETRIES_EXHAUSTED = "retries_exhausted"
    PARENT_DEADLINE = "parent_deadline"
    CANCELLATION = "cancellation"
    START_FAILURE = "start_failure"
    CLEANUP_FAILURE = "cleanup_failure"
    INTERNAL_ERROR = "internal_error"


class AALCErrorCode(StrEnum):
    OK = "OK"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    EXECUTABLE_NOT_FOUND = "EXECUTABLE_NOT_FOUND"
    WORKING_DIRECTORY_NOT_FOUND = "WORKING_DIRECTORY_NOT_FOUND"
    PROCESS_START_FAILED = "PROCESS_START_FAILED"
    PROCESS_EXIT_NONZERO = "PROCESS_EXIT_NONZERO"
    ATTEMPT_TIMEOUT = "ATTEMPT_TIMEOUT"
    PARENT_DEADLINE = "PARENT_DEADLINE"
    RETRIES_EXHAUSTED = "RETRIES_EXHAUSTED"
    CANCELLED = "CANCELLED"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def _check_common(
    started_at: datetime,
    finished_at: datetime,
    duration_seconds: float,
    stdout_excerpt: str = "",
    stderr_excerpt: str = "",
    diagnostics: Mapping[str, JsonValue] | None = None,
) -> None:
    if started_at.tzinfo is None or finished_at.tzinfo is None:
        raise ValueError("时间必须带时区")
    if finished_at < started_at or duration_seconds < 0:
        raise ValueError("结束时间和耗时无效")
    if not isinstance(stdout_excerpt, str) or not isinstance(stderr_excerpt, str):
        raise ValueError("输出摘要必须是字符串")
    if diagnostics is not None and not is_json_serializable(dict(diagnostics)):
        raise ValueError("诊断信息必须可 JSON 序列化")


@dataclass(frozen=True)
class AALCAttemptResult:
    attempt_number: int
    status: AALCAttemptStatus
    error_code: AALCErrorCode
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    pid: int | None
    exit_code: int | None
    owned_process_cleaned: bool
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _check_common(
            self.started_at,
            self.finished_at,
            self.duration_seconds,
            self.stdout_excerpt,
            self.stderr_excerpt,
            self.diagnostics,
        )
        if not isinstance(self.attempt_number, int) or isinstance(self.attempt_number, bool) or self.attempt_number < 1:
            raise ValueError("attempt_number 必须从 1 开始")
        if self.status == AALCAttemptStatus.COMPLETED:
            if self.error_code != AALCErrorCode.OK or self.exit_code != 0 or not self.owned_process_cleaned:
                raise ValueError("成功尝试不变量无效")
        elif self.error_code == AALCErrorCode.OK:
            raise ValueError("失败尝试不得使用 OK")
        if self.error_code == AALCErrorCode.CLEANUP_FAILED and self.owned_process_cleaned:
            raise ValueError("清理失败必须 owned_process_cleaned=False")
        if self.status == AALCAttemptStatus.CANCELLED and self.error_code not in {
            AALCErrorCode.CANCELLED,
            AALCErrorCode.CLEANUP_FAILED,
        }:
            raise ValueError("取消尝试错误码无效")
        if self.status == AALCAttemptStatus.TIMEOUT and self.error_code not in {
            AALCErrorCode.ATTEMPT_TIMEOUT,
            AALCErrorCode.PARENT_DEADLINE,
            AALCErrorCode.CLEANUP_FAILED,
        }:
            raise ValueError("超时尝试错误码无效")

    def to_dict(self) -> dict[str, object]:
        return {
            "attempt_number": self.attempt_number,
            "status": self.status.value,
            "error_code": self.error_code.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "pid": self.pid,
            "exit_code": self.exit_code,
            "owned_process_cleaned": self.owned_process_cleaned,
            "stdout_excerpt": self.stdout_excerpt,
            "stderr_excerpt": self.stderr_excerpt,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True)
class AALCRunResult:
    status: AALCRunStatus
    error_code: AALCErrorCode
    completion_mode: AALCCompletionMode
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    configured_attempts: int
    attempts_started: int
    successful_attempt_number: int | None
    attempt_results: tuple[AALCAttemptResult, ...] = ()
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _check_common(self.started_at, self.finished_at, self.duration_seconds, diagnostics=self.diagnostics)
        if not isinstance(self.configured_attempts, int) or not 1 <= self.configured_attempts <= 3:
            raise ValueError("configured_attempts 无效")
        if self.attempts_started != len(self.attempt_results) or self.attempts_started > self.configured_attempts:
            raise ValueError("attempts_started 与尝试结果不一致")
        if tuple(item.attempt_number for item in self.attempt_results) != tuple(range(1, self.attempts_started + 1)):
            raise ValueError("尝试编号必须严格连续")
        if self.status == AALCRunStatus.COMPLETED:
            if self.error_code != AALCErrorCode.OK or self.completion_mode != AALCCompletionMode.NORMAL_EXIT:
                raise ValueError("完成结果必须为 OK/NORMAL_EXIT")
            if self.successful_attempt_number != self.attempts_started or not self.attempt_results:
                raise ValueError("成功尝试必须是最后一次")
            if self.attempt_results[-1].status != AALCAttemptStatus.COMPLETED:
                raise ValueError("最后一次尝试必须成功")
        elif self.error_code == AALCErrorCode.OK:
            raise ValueError("非完成结果不得使用 OK")
        if self.completion_mode == AALCCompletionMode.RETRIES_EXHAUSTED:
            if self.attempts_started != self.configured_attempts:
                raise ValueError("重试耗尽必须启动全部尝试")
            retryable = {AALCErrorCode.PROCESS_EXIT_NONZERO, AALCErrorCode.ATTEMPT_TIMEOUT}
            if any(item.error_code not in retryable for item in self.attempt_results):
                raise ValueError("重试耗尽包含不可重试失败")
        if self.successful_attempt_number is not None and self.status != AALCRunStatus.COMPLETED:
            raise ValueError("非完成结果不得有成功尝试")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "error_code": self.error_code.value,
            "completion_mode": self.completion_mode.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "configured_attempts": self.configured_attempts,
            "attempts_started": self.attempts_started,
            "successful_attempt_number": self.successful_attempt_number,
            "attempt_results": [item.to_dict() for item in self.attempt_results],
            "diagnostics": dict(self.diagnostics),
        }
