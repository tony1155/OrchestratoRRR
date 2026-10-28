"""BetterGI execution evidence, independent of its GUI process exit code."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class BetterGIRunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class BetterGIErrorCode(StrEnum):
    OK = "OK"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INSTANCE_CONFLICT = "INSTANCE_CONFLICT"
    INSTANCE_CHECK_FAILED = "INSTANCE_CHECK_FAILED"
    PROCESS_START_FAILED = "PROCESS_START_FAILED"
    PROCESS_EXIT_NONZERO = "PROCESS_EXIT_NONZERO"
    COMPLETION_UNCONFIRMED = "COMPLETION_UNCONFIRMED"
    TASK_FAILED = "TASK_FAILED"
    TASK_TIMEOUT = "TASK_TIMEOUT"
    CANCELLED = "CANCELLED"
    LOG_CONTRACT_FAILED = "LOG_CONTRACT_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CLEANUP_FAILED = "CLEANUP_FAILED"


@dataclass(frozen=True)
class BetterGIRunResult:
    status: BetterGIRunStatus
    error_code: BetterGIErrorCode
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    exit_code: int | None = None
    owned_process_cleaned: bool = True
    configuration_confirmed: bool = False
    completion_confirmed: bool = False

    def __post_init__(self) -> None:
        if self.status == BetterGIRunStatus.COMPLETED and not (
            self.error_code == BetterGIErrorCode.OK
            and self.exit_code == 0
            and self.owned_process_cleaned
            and self.configuration_confirmed
            and self.completion_confirmed
        ):
            raise ValueError("BetterGI success requires execution evidence and cleanup")
        if self.status != BetterGIRunStatus.COMPLETED and self.error_code == BetterGIErrorCode.OK:
            raise ValueError("Non-success cannot use OK")
