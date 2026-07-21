"""StarRailCopilot 运行结果模型。

定义 StarRailRunResult、StarRailCompletionMode、StarRailRunStatus、StarRailErrorCode。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from autogame_orchestrator.models import JsonValue, is_json_serializable

MAX_OUTPUT_EXCERPT_CHARS = 8 * 1024


class StarRailRunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class StarRailCompletionMode(StrEnum):
    LOG_SUCCESS = "log_success"
    LOG_FAILURE = "log_failure"
    PROCESS_EXIT = "process_exit"
    TASK_TIMEOUT = "task_timeout"
    CANCELLATION = "cancellation"
    START_FAILURE = "start_failure"
    LOG_ERROR = "log_error"


class StarRailErrorCode(StrEnum):
    OK = "OK"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    EXECUTABLE_NOT_FOUND = "EXECUTABLE_NOT_FOUND"
    WORKING_DIRECTORY_NOT_FOUND = "WORKING_DIRECTORY_NOT_FOUND"
    LOG_PARENT_NOT_FOUND = "LOG_PARENT_NOT_FOUND"
    PROCESS_START_FAILED = "PROCESS_START_FAILED"
    PROCESS_EXIT_NONZERO = "PROCESS_EXIT_NONZERO"
    PROCESS_EXIT_BEFORE_SUCCESS = "PROCESS_EXIT_BEFORE_SUCCESS"
    FAILURE_KEYWORD = "FAILURE_KEYWORD"
    LOG_READ_FAILED = "LOG_READ_FAILED"
    LOG_OUTPUT_LIMIT = "LOG_OUTPUT_LIMIT"
    TASK_TIMEOUT = "TASK_TIMEOUT"
    CANCELLED = "CANCELLED"
    CLEANUP_FAILED = "CLEANUP_FAILED"


@dataclass(frozen=True)
class StarRailRunResult:
    status: StarRailRunStatus
    error_code: StarRailErrorCode
    completion_mode: StarRailCompletionMode
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    pid: int | None
    exit_code: int | None
    matched_keyword: str
    log_path: str
    owned_process_cleaned: bool
    stdout_excerpt: str
    stderr_excerpt: str
    stdout_truncated: bool
    stderr_truncated: bool
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            msg = f"duration_ms 不能为负，收到 {self.duration_ms}"
            raise ValueError(msg)
        if self.status == StarRailRunStatus.COMPLETED:
            if self.error_code != StarRailErrorCode.OK:
                msg = f"COMPLETED 必须使用 OK，收到 {self.error_code.value}"
                raise ValueError(msg)
            if self.completion_mode != StarRailCompletionMode.LOG_SUCCESS:
                msg = f"COMPLETED 必须使用 LOG_SUCCESS，收到 {self.completion_mode.value}"
                raise ValueError(msg)
            if not self.matched_keyword:
                msg = "COMPLETED 必须有 matched_keyword"
                raise ValueError(msg)
            if not self.owned_process_cleaned:
                msg = "COMPLETED 必须 owned_process_cleaned=True"
                raise ValueError(msg)
            if not self.matched_keyword:
                msg = "COMPLETED 必须有非空 matched_keyword"
                raise ValueError(msg)
        else:
            if self.error_code == StarRailErrorCode.OK:
                msg = f"非 COMPLETED 状态 ({self.status.value}) 不得使用 OK"
                raise ValueError(msg)
        if self.error_code == StarRailErrorCode.FAILURE_KEYWORD and not self.matched_keyword:
            msg = "FAILURE_KEYWORD 必须有 matched_keyword"
            raise ValueError(msg)
        if not is_json_serializable(dict(self.diagnostics)):
            msg = "diagnostics 包含不可 JSON 序列化的值"
            raise ValueError(msg)

    @classmethod
    def from_monotonic(
        cls,
        *,
        status: StarRailRunStatus,
        error_code: StarRailErrorCode,
        completion_mode: StarRailCompletionMode,
        started_at: datetime,
        started_at_monotonic: float,
        pid: int | None,
        exit_code: int | None = None,
        matched_keyword: str = "",
        log_path: str = "",
        owned_process_cleaned: bool,
        stdout_excerpt: str = "",
        stderr_excerpt: str = "",
        stdout_truncated: bool = False,
        stderr_truncated: bool = False,
        diagnostics: Mapping[str, JsonValue] | None = None,
    ) -> StarRailRunResult:
        now = datetime.now(UTC)
        elapsed = time.monotonic() - started_at_monotonic
        duration_ms = max(0, int(elapsed * 1000))
        return cls(
            status=status,
            error_code=error_code,
            completion_mode=completion_mode,
            started_at=started_at,
            finished_at=now,
            duration_ms=duration_ms,
            pid=pid,
            exit_code=exit_code,
            matched_keyword=matched_keyword,
            log_path=log_path,
            owned_process_cleaned=owned_process_cleaned,
            stdout_excerpt=stdout_excerpt,
            stderr_excerpt=stderr_excerpt,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            diagnostics=diagnostics or {},
        )
