"""Stable invocation results; process exit is not MaaFgo task completion evidence."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from autogame_orchestrator.models import JsonValue
from autogame_orchestrator.process.errors import TerminationReason


class MaaFgoRunStatus(StrEnum):
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class MaaFgoErrorCode(StrEnum):
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"
    EXECUTABLE_NOT_FOUND = "EXECUTABLE_NOT_FOUND"
    WORKING_DIRECTORY_NOT_FOUND = "WORKING_DIRECTORY_NOT_FOUND"
    PROJECT_INTERFACE_NOT_FOUND = "PROJECT_INTERFACE_NOT_FOUND"
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    ADB_CONFIGURATION_MISMATCH = "ADB_CONFIGURATION_MISMATCH"
    ADB_AUTODETECT_UNSUPPORTED = "ADB_AUTODETECT_UNSUPPORTED"
    PROCESS_START_FAILED = "PROCESS_START_FAILED"
    PROCESS_EXIT_NONZERO = "PROCESS_EXIT_NONZERO"
    TASK_TIMEOUT = "TASK_TIMEOUT"
    CANCELLED = "CANCELLED"
    WAIT_FAILED = "WAIT_FAILED"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    COMPLETION_UNCONFIRMED = "COMPLETION_UNCONFIRMED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class MaaFgoRunResult:
    """Phase one deliberately has no business-success state or raw output fields."""

    status: MaaFgoRunStatus
    error_code: MaaFgoErrorCode
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    exit_code: int | None = None
    termination_reason: TerminationReason | None = None
    owned_process_cleaned: bool = True
    configuration_confirmed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.status, MaaFgoRunStatus) or not isinstance(self.error_code, MaaFgoErrorCode):
            raise ValueError("Invalid result enum")
        if any(t.tzinfo is None or t.utcoffset() is None for t in (self.started_at, self.finished_at)):
            raise ValueError("Timestamps must be timezone aware")
        if self.finished_at < self.started_at or type(self.duration_ms) is not int or self.duration_ms < 0:
            raise ValueError("Invalid result duration")
        if type(self.owned_process_cleaned) is not bool or type(self.configuration_confirmed) is not bool:
            raise ValueError("Invalid result flags")
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise ValueError("Invalid exit code")
        if self.error_code == MaaFgoErrorCode.CLEANUP_FAILED and self.owned_process_cleaned:
            raise ValueError("Cleanup failure cannot claim cleanup")
        if self.error_code == MaaFgoErrorCode.COMPLETION_UNCONFIRMED and not (
            self.status == MaaFgoRunStatus.FAILED
            and self.exit_code == 0
            and self.termination_reason == TerminationReason.NORMAL_EXIT
            and self.owned_process_cleaned
            and self.configuration_confirmed
        ):
            raise ValueError("Unconfirmed completion requires a clean normal process exit")
        for status, code, reason in (
            (MaaFgoRunStatus.TIMEOUT, MaaFgoErrorCode.TASK_TIMEOUT, TerminationReason.TIMEOUT),
            (MaaFgoRunStatus.CANCELLED, MaaFgoErrorCode.CANCELLED, TerminationReason.CANCELLED),
        ):
            if self.status == status and (
                self.error_code not in (code, MaaFgoErrorCode.CLEANUP_FAILED)
                or self.termination_reason not in (reason, TerminationReason.TERMINATION_FAILED)
            ):
                raise ValueError("Control result mismatch")

    @property
    def completion_confirmed(self) -> bool:
        return False

    @property
    def diagnostics(self) -> dict[str, JsonValue]:
        """Allowlisted projection, not a copy of ProcessResult.diagnostics."""
        return {
            "source_error_code": self.error_code.value,
            "exit_code": self.exit_code,
            "termination_reason": self.termination_reason.value if self.termination_reason else None,
            "owned_process_cleaned": self.owned_process_cleaned,
            "configuration_confirmed": self.configuration_confirmed,
            "completion_confirmed": False,
            "output_capture": "discarded",
        }
