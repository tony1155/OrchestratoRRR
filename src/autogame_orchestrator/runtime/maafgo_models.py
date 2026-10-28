"""Stable invocation results; process exit is not MaaFgo task completion evidence."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from autogame_orchestrator.models import JsonValue
from autogame_orchestrator.process.errors import TerminationReason


class MaaFgoRunStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class MaaFgoErrorCode(StrEnum):
    OK = "OK"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"
    EXECUTABLE_NOT_FOUND = "EXECUTABLE_NOT_FOUND"
    WORKING_DIRECTORY_NOT_FOUND = "WORKING_DIRECTORY_NOT_FOUND"
    PROJECT_INTERFACE_NOT_FOUND = "PROJECT_INTERFACE_NOT_FOUND"
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    ADB_CONFIGURATION_MISMATCH = "ADB_CONFIGURATION_MISMATCH"
    ADB_AUTODETECT_UNSUPPORTED = "ADB_AUTODETECT_UNSUPPORTED"
    PROFILE_POLICY_REJECTED = "MAAFGO_PROFILE_POLICY_REJECTED"
    DISTRIBUTION_UNVERIFIED = "MAAFGO_DISTRIBUTION_UNVERIFIED"
    PROCESS_START_FAILED = "PROCESS_START_FAILED"
    PROCESS_EXIT_NONZERO = "PROCESS_EXIT_NONZERO"
    RESULT_MISSING = "MAAFGO_RESULT_MISSING"
    RESULT_INVALID = "MAAFGO_RESULT_INVALID"
    RESULT_ID_MISMATCH = "MAAFGO_RESULT_ID_MISMATCH"
    TASK_FAILED = "MAAFGO_TASK_FAILED"
    TASK_TIMEOUT = "TASK_TIMEOUT"
    CANCELLED = "CANCELLED"
    WAIT_FAILED = "WAIT_FAILED"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    COMPLETION_UNCONFIRMED = "COMPLETION_UNCONFIRMED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class MaaFgoRunResult:
    """Run result with explicit completion evidence fields.

    ``exit_code == 0`` alone is never success: SUCCESS additionally requires a
    strictly verified run-scoped completion artifact (see
    ``autogame_orchestrator.maafgo_evidence``) and a clean owned-process exit.
    """

    status: MaaFgoRunStatus
    error_code: MaaFgoErrorCode
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    exit_code: int | None = None
    termination_reason: TerminationReason | None = None
    owned_process_cleaned: bool = True
    configuration_confirmed: bool = False
    completion_confirmed: bool = False
    expected_task_count: int = 0
    confirmed_task_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.status, MaaFgoRunStatus) or not isinstance(self.error_code, MaaFgoErrorCode):
            raise ValueError("Invalid result enum")
        if any(t.tzinfo is None or t.utcoffset() is None for t in (self.started_at, self.finished_at)):
            raise ValueError("Timestamps must be timezone aware")
        if self.finished_at < self.started_at or type(self.duration_ms) is not int or self.duration_ms < 0:
            raise ValueError("Invalid result duration")
        if type(self.owned_process_cleaned) is not bool or type(self.configuration_confirmed) is not bool:
            raise ValueError("Invalid result flags")
        if type(self.completion_confirmed) is not bool:
            raise ValueError("Invalid completion flag")
        if any(
            type(v) is not int or v < 0 for v in (self.expected_task_count, self.confirmed_task_count)
        ) or self.confirmed_task_count > self.expected_task_count:
            raise ValueError("Invalid completion counts")
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
            and not self.completion_confirmed
        ):
            raise ValueError("Unconfirmed completion requires a clean normal process exit")
        if self.status == MaaFgoRunStatus.SUCCESS and not (
            self.error_code == MaaFgoErrorCode.OK
            and self.exit_code == 0
            and self.termination_reason == TerminationReason.NORMAL_EXIT
            and self.owned_process_cleaned
            and self.configuration_confirmed
            and self.completion_confirmed
            and self.expected_task_count > 0
            and self.confirmed_task_count == self.expected_task_count
        ):
            raise ValueError("Success requires verified completion evidence and a clean owned exit")
        if self.completion_confirmed and self.status != MaaFgoRunStatus.SUCCESS:
            raise ValueError("Completion confirmation is only valid for success")
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
    def diagnostics(self) -> dict[str, JsonValue]:
        """Allowlisted projection, not a copy of ProcessResult.diagnostics."""
        return {
            "source_error_code": self.error_code.value,
            "exit_code": self.exit_code,
            "termination_reason": self.termination_reason.value if self.termination_reason else None,
            "owned_process_cleaned": self.owned_process_cleaned,
            "configuration_confirmed": self.configuration_confirmed,
            "completion_confirmed": self.completion_confirmed,
            "expected_task_count": self.expected_task_count,
            "confirmed_task_count": self.confirmed_task_count,
            "output_capture": "discarded",
        }
