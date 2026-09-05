"""MaaResource 覆盖合并的不可变安全结果。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class MAAResourceMergeStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class MAAResourceMergeErrorCode(StrEnum):
    OK = "OK"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    DESTINATION_NOT_FOUND = "DESTINATION_NOT_FOUND"
    SOURCE_SCAN_FAILED = "SOURCE_SCAN_FAILED"
    SOURCE_TOO_MANY_FILES = "SOURCE_TOO_MANY_FILES"
    SOURCE_FILE_TOO_LARGE = "SOURCE_FILE_TOO_LARGE"
    SOURCE_READ_FAILED = "SOURCE_READ_FAILED"
    TARGET_WRITE_FAILED = "TARGET_WRITE_FAILED"
    CANCELLED = "CANCELLED"
    PARENT_DEADLINE = "PARENT_DEADLINE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class MAAResourceMergeResult:
    """单次合并的结果；只包含计数与稳定错误码，不含任何路径。"""

    status: MAAResourceMergeStatus
    error_code: MAAResourceMergeErrorCode
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    enabled: bool
    files_scanned: int
    files_copied: int
    files_identical: int
    bytes_copied: int
    directories_created: int

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("合并时间必须带时区")
        if self.finished_at < self.started_at or self.duration_ms < 0:
            raise ValueError("合并时间范围无效")
        if self.status == MAAResourceMergeStatus.COMPLETED and self.error_code != MAAResourceMergeErrorCode.OK:
            raise ValueError("完成结果必须使用 OK")
        if self.status != MAAResourceMergeStatus.COMPLETED and self.error_code == MAAResourceMergeErrorCode.OK:
            raise ValueError("失败结果不得使用 OK")
        if self.status == MAAResourceMergeStatus.CANCELLED and self.error_code != MAAResourceMergeErrorCode.CANCELLED:
            raise ValueError("取消状态与错误码不匹配")
        if (
            self.status == MAAResourceMergeStatus.TIMEOUT
            and self.error_code != MAAResourceMergeErrorCode.PARENT_DEADLINE
        ):
            raise ValueError("超时状态与错误码不匹配")
        for value in (
            self.files_scanned,
            self.files_copied,
            self.files_identical,
            self.bytes_copied,
            self.directories_created,
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("合并计数必须是非负整数")
        if self.files_copied + self.files_identical > self.files_scanned:
            raise ValueError("已处理文件数不得超过扫描文件数")

    @property
    def changed(self) -> bool:
        """是否真正写入过目标文件。"""
        return self.files_copied > 0

    @classmethod
    def from_monotonic(
        cls,
        *,
        status: MAAResourceMergeStatus,
        error_code: MAAResourceMergeErrorCode,
        started_at: datetime,
        started_monotonic: float,
        enabled: bool,
        files_scanned: int = 0,
        files_copied: int = 0,
        files_identical: int = 0,
        bytes_copied: int = 0,
        directories_created: int = 0,
    ) -> MAAResourceMergeResult:
        return cls(
            status,
            error_code,
            started_at,
            datetime.now(UTC),
            max(0, int((time.monotonic() - started_monotonic) * 1000)),
            enabled,
            files_scanned,
            files_copied,
            files_identical,
            bytes_copied,
            directories_created,
        )
