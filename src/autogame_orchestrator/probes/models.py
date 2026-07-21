"""探测结果模型。

定义 ProbeResult、AdbDevice、AdbDevicesResult 及其枚举类型。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from autogame_orchestrator.models import JsonValue, is_json_serializable


class ProbeStatus(StrEnum):
    """探测状态。"""

    READY = "ready"
    NOT_READY = "not_ready"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    FAILED = "failed"


class ProbeErrorCode(StrEnum):
    """探测错误码。READY 只能搭配 OK。"""

    OK = "OK"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    NON_LOCAL_ADDRESS_REJECTED = "NON_LOCAL_ADDRESS_REJECTED"
    PORT_CLOSED = "PORT_CLOSED"
    TCP_TIMEOUT = "TCP_TIMEOUT"
    ADB_NOT_FOUND = "ADB_NOT_FOUND"
    ADB_START_FAILED = "ADB_START_FAILED"
    ADB_TIMEOUT = "ADB_TIMEOUT"
    ADB_EXIT_NONZERO = "ADB_EXIT_NONZERO"
    ADB_CANCELLED = "ADB_CANCELLED"
    ADB_OUTPUT_INVALID = "ADB_OUTPUT_INVALID"
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    DEVICE_UNAUTHORIZED = "DEVICE_UNAUTHORIZED"
    MULTIPLE_DEVICES = "MULTIPLE_DEVICES"
    ANDROID_NOT_BOOTED = "ANDROID_NOT_BOOTED"


class AdbDeviceState(StrEnum):
    """ADB 设备状态。"""

    DEVICE = "device"
    OFFLINE = "offline"
    UNAUTHORIZED = "unauthorized"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProbeResult:
    """不可变的探测结果。"""

    probe_name: str
    status: ProbeStatus
    error_code: ProbeErrorCode
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status == ProbeStatus.READY and self.error_code != ProbeErrorCode.OK:
            msg = f"READY 状态必须使用 OK，收到 {self.error_code.value}"
            raise ValueError(msg)
        if self.status != ProbeStatus.READY and self.error_code == ProbeErrorCode.OK:
            msg = f"非 READY 状态不得使用 OK，当前状态: {self.status.value}"
            raise ValueError(msg)
        if self.duration_ms < 0:
            msg = f"duration_ms 不能为负，收到 {self.duration_ms}"
            raise ValueError(msg)
        if not is_json_serializable(dict(self.diagnostics)):
            msg = "diagnostics 包含不可 JSON 序列化的值"
            raise ValueError(msg)

    @classmethod
    def ready(cls, probe_name: str, diagnostics: Mapping[str, JsonValue] | None = None) -> ProbeResult:
        """构造 READY 结果。"""
        now = datetime.now(UTC)
        return cls(
            probe_name=probe_name,
            status=ProbeStatus.READY,
            error_code=ProbeErrorCode.OK,
            started_at=now,
            finished_at=now,
            duration_ms=0,
            diagnostics=diagnostics or {},
        )

    @classmethod
    def from_monotonic(
        cls,
        probe_name: str,
        status: ProbeStatus,
        error_code: ProbeErrorCode,
        started_at_mono: float,
        diagnostics: Mapping[str, JsonValue] | None = None,
    ) -> ProbeResult:
        """使用 monotonic 起始时间构造结果。"""
        now = datetime.now(UTC)
        elapsed = time.monotonic() - started_at_mono
        duration_ms = max(0, int(elapsed * 1000))
        return cls(
            probe_name=probe_name,
            status=status,
            error_code=error_code,
            started_at=now,
            finished_at=now,
            duration_ms=duration_ms,
            diagnostics=diagnostics or {},
        )


@dataclass(frozen=True)
class AdbDevice:
    """ADB 设备信息。"""

    serial: str
    state: AdbDeviceState
    attributes: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AdbDevicesResult:
    """ADB devices 命令的完整结果。"""

    probe: ProbeResult
    devices: tuple[AdbDevice, ...]
