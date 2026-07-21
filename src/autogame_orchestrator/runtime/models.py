"""MuMu 运行时结果模型。

定义 MumuAction、MumuRuntimeStatus、MumuRuntimeErrorCode、MumuRuntimeResult。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from autogame_orchestrator.models import JsonValue, is_json_serializable


class MumuAction(StrEnum):
    """MuMu 操作类型。"""

    STATUS = "status"
    START = "start"
    STOP = "stop"
    RESTART = "restart"


class MumuRuntimeStatus(StrEnum):
    """MuMu 运行时状态。"""

    READY = "ready"
    STOPPED = "stopped"
    STARTED = "started"
    RESTARTED = "restarted"
    NOT_READY = "not_ready"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    FAILED = "failed"


class MumuRuntimeErrorCode(StrEnum):
    """MuMu 运行时错误码。"""

    OK = "OK"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    MANAGER_NOT_FOUND = "MANAGER_NOT_FOUND"
    COMMAND_START_FAILED = "COMMAND_START_FAILED"
    COMMAND_EXIT_NONZERO = "COMMAND_EXIT_NONZERO"
    START_TIMEOUT = "START_TIMEOUT"
    STOP_TIMEOUT = "STOP_TIMEOUT"
    CANCELLED = "CANCELLED"
    READINESS_FAILED = "READINESS_FAILED"


@dataclass(frozen=True)
class MumuRuntimeResult:
    """不可变的 MuMu 运行时操作结果。"""

    action: MumuAction
    status: MumuRuntimeStatus
    error_code: MumuRuntimeErrorCode
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    changed: bool
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            msg = f"duration_ms 不能为负，收到 {self.duration_ms}"
            raise ValueError(msg)

        _success_codes = {
            MumuRuntimeStatus.READY,
            MumuRuntimeStatus.STOPPED,
            MumuRuntimeStatus.STARTED,
            MumuRuntimeStatus.RESTARTED,
        }
        if self.status in _success_codes and self.error_code != MumuRuntimeErrorCode.OK:
            msg = f"{self.status.value} 必须使用 OK，收到 {self.error_code.value}"
            raise ValueError(msg)
        if self.status not in _success_codes and self.error_code == MumuRuntimeErrorCode.OK:
            msg = f"非成功状态 ({self.status.value}) 不得使用 OK"
            raise ValueError(msg)
        if not is_json_serializable(dict(self.diagnostics)):
            msg = "diagnostics 包含不可 JSON 序列化的值"
            raise ValueError(msg)

    @classmethod
    def from_monotonic(
        cls,
        action: MumuAction,
        status: MumuRuntimeStatus,
        error_code: MumuRuntimeErrorCode,
        started_at_mono: float,
        changed: bool,
        diagnostics: Mapping[str, JsonValue] | None = None,
    ) -> MumuRuntimeResult:
        now = datetime.now(UTC)
        elapsed = time.monotonic() - started_at_mono
        duration_ms = max(0, int(elapsed * 1000))
        return cls(
            action=action,
            status=status,
            error_code=error_code,
            started_at=now,
            finished_at=now,
            duration_ms=duration_ms,
            changed=changed,
            diagnostics=diagnostics or {},
        )
