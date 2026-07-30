"""MAA 配置同步的不可变安全结果。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class MAASyncStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class MAASyncErrorCode(StrEnum):
    OK = "OK"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
    SOURCE_READ_FAILED = "SOURCE_READ_FAILED"
    SOURCE_PARSE_FAILED = "SOURCE_PARSE_FAILED"
    TRANSFORM_FAILED = "TRANSFORM_FAILED"
    TARGET_PREPARE_FAILED = "TARGET_PREPARE_FAILED"
    TARGET_WRITE_FAILED = "TARGET_WRITE_FAILED"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    CANCELLED = "CANCELLED"
    PARENT_DEADLINE = "PARENT_DEADLINE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class MAASyncResult:
    status: MAASyncStatus
    error_code: MAASyncErrorCode
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    enabled: bool
    changed: bool
    profile_written: bool
    tasks_written: bool
    profile_backup_written: bool
    tasks_backup_written: bool
    rollback_attempted: bool
    rollback_succeeded: bool

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("同步时间必须带时区")
        if self.finished_at < self.started_at or self.duration_ms < 0:
            raise ValueError("同步时间范围无效")
        if self.status == MAASyncStatus.COMPLETED and self.error_code != MAASyncErrorCode.OK:
            raise ValueError("完成结果必须使用 OK")
        if self.status != MAASyncStatus.COMPLETED and self.error_code == MAASyncErrorCode.OK:
            raise ValueError("失败结果不得使用 OK")
        if self.status == MAASyncStatus.CANCELLED and self.error_code != MAASyncErrorCode.CANCELLED:
            raise ValueError("取消状态与错误码不匹配")
        if self.status == MAASyncStatus.TIMEOUT and self.error_code != MAASyncErrorCode.PARENT_DEADLINE:
            raise ValueError("超时状态与错误码不匹配")
        if self.rollback_succeeded and not self.rollback_attempted:
            raise ValueError("未尝试回滚时不得标记成功")

    @classmethod
    def from_monotonic(
        cls,
        *,
        status: MAASyncStatus,
        error_code: MAASyncErrorCode,
        started_at: datetime,
        started_monotonic: float,
        enabled: bool,
        changed: bool = False,
        profile_written: bool = False,
        tasks_written: bool = False,
        profile_backup_written: bool = False,
        tasks_backup_written: bool = False,
        rollback_attempted: bool = False,
        rollback_succeeded: bool = False,
    ) -> MAASyncResult:
        return cls(
            status,
            error_code,
            started_at,
            datetime.now(UTC),
            max(0, int((time.monotonic() - started_monotonic) * 1000)),
            enabled,
            changed,
            profile_written,
            tasks_written,
            profile_backup_written,
            tasks_backup_written,
            rollback_attempted,
            rollback_succeeded,
        )
