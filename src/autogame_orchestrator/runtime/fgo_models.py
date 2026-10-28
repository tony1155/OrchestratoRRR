"""STOP_FGO 的稳定结果模型：精确 ADB 设备上的 Android 应用退出。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from autogame_orchestrator.models import JsonValue


class FgoAppStopStatus(StrEnum):
    STOPPED = "stopped"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class FgoAppStopErrorCode(StrEnum):
    OK = "OK"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    ADB_START_FAILED = "ADB_START_FAILED"
    ADB_COMMAND_FAILED = "ADB_COMMAND_FAILED"
    VERIFY_FAILED = "VERIFY_FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class FgoStopVerification(StrEnum):
    """force-stop 后的可选验证结果；不确定不等于失败。"""

    VERIFIED = "verified"
    INCONCLUSIVE = "inconclusive"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class FgoAppStopResult:
    """不携带 serial、package、路径或 PID；只输出白名单枚举。"""

    status: FgoAppStopStatus
    error_code: FgoAppStopErrorCode
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    verification: FgoStopVerification = FgoStopVerification.SKIPPED

    def __post_init__(self) -> None:
        if not isinstance(self.status, FgoAppStopStatus) or not isinstance(self.error_code, FgoAppStopErrorCode):
            raise ValueError("Invalid stop result enum")
        if not isinstance(self.verification, FgoStopVerification):
            raise ValueError("Invalid verification enum")
        if any(t.tzinfo is None or t.utcoffset() is None for t in (self.started_at, self.finished_at)):
            raise ValueError("Timestamps must be timezone aware")
        if self.finished_at < self.started_at or type(self.duration_ms) is not int or self.duration_ms < 0:
            raise ValueError("Invalid stop result duration")
        if self.status is FgoAppStopStatus.STOPPED and self.error_code is not FgoAppStopErrorCode.OK:
            raise ValueError("Stopped requires OK")
        if self.status is not FgoAppStopStatus.STOPPED and self.error_code is FgoAppStopErrorCode.OK:
            raise ValueError("Non-stopped cannot use OK")
        if self.verification is FgoStopVerification.VERIFIED and self.status is not FgoAppStopStatus.STOPPED:
            raise ValueError("Verified requires stopped")

    @property
    def diagnostics(self) -> dict[str, JsonValue]:
        return {
            "source_error_code": self.error_code.value,
            "verification": self.verification.value,
        }
