"""MuMu ADB 就绪探测。

组合 TCP 探测 + ADB devices + get-state + boot_completed。
共享同一个 Deadline，任一步失败立即返回。不启动或重启 MuMu。
"""

from __future__ import annotations

import time
from dataclasses import replace

from autogame_orchestrator.probes.adb_client import AdbClient
from autogame_orchestrator.probes.adb_parser import AdbParseError, select_adb_device
from autogame_orchestrator.probes.models import ProbeErrorCode, ProbeResult, ProbeStatus
from autogame_orchestrator.probes.tcp import probe_tcp_endpoint
from autogame_orchestrator.process import CancellationToken, Deadline


class MumuReadinessProbe:
    """MuMu 模拟器 ADB 就绪探测。

    只读探测：不启动、停止或连接设备。
    """

    def __init__(self, adb_client: AdbClient) -> None:
        self._adb = adb_client

    def probe(
        self,
        host: str,
        port: int,
        expected_serial: str | None,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        """执行完整 MuMu 就绪探测。

        流程：检查取消 → TCP → 检查取消 → devices → 选择 → 检查取消 → state → 检查取消 → boot。
        """
        started_at = time.monotonic()

        # 1. 检查取消
        if cancel is not None and cancel.is_cancelled:
            return ProbeResult.from_monotonic(
                "mumu_readiness", ProbeStatus.FAILED, ProbeErrorCode.ADB_CANCELLED, started_at
            )
        if deadline.expired:
            return _deadline_result(started_at, "tcp_probe", ProbeErrorCode.TCP_TIMEOUT)

        # 2. TCP 端口探测
        tcp_result = probe_tcp_endpoint(host, port, deadline)
        if tcp_result.status != ProbeStatus.READY:
            return ProbeResult.from_monotonic(
                "mumu_readiness",
                tcp_result.status,
                tcp_result.error_code,
                started_at,
                {"step": "tcp_probe", "detail": f"{host}:{port}"},
            )

        # 3. 检查取消
        if cancel is not None and cancel.is_cancelled:
            return ProbeResult.from_monotonic(
                "mumu_readiness", ProbeStatus.FAILED, ProbeErrorCode.ADB_CANCELLED, started_at
            )
        if deadline.expired:
            return _deadline_result(started_at, "adb_devices")

        # 4. adb devices -l
        devices_result = self._adb.list_devices(deadline, cancel)
        if devices_result.probe.status != ProbeStatus.READY:
            return ProbeResult.from_monotonic(
                "mumu_readiness",
                devices_result.probe.status,
                devices_result.probe.error_code,
                started_at,
                {"step": "adb_devices"},
            )
        if cancel is not None and cancel.is_cancelled:
            return ProbeResult.from_monotonic(
                "mumu_readiness", ProbeStatus.FAILED, ProbeErrorCode.ADB_CANCELLED, started_at
            )
        if deadline.expired:
            return _deadline_result(started_at, "adb_devices")

        # 5. 选择设备
        try:
            device = select_adb_device(devices_result.devices, expected_serial)
        except AdbParseError as exc:
            return ProbeResult.from_monotonic(
                "mumu_readiness",
                _status_for_code(exc.error_code),
                exc.error_code,
                started_at,
                {"step": "select_device", "detail": str(exc)},
            )

        # 6. 检查取消
        if cancel is not None and cancel.is_cancelled:
            return ProbeResult.from_monotonic(
                "mumu_readiness", ProbeStatus.FAILED, ProbeErrorCode.ADB_CANCELLED, started_at
            )
        if deadline.expired:
            return _deadline_result(started_at, "adb_get_state")

        # 7. adb get-state
        state_result = self._adb.get_state(device.serial, deadline, cancel)
        if state_result.status != ProbeStatus.READY:
            return ProbeResult.from_monotonic(
                "mumu_readiness",
                state_result.status,
                state_result.error_code,
                started_at,
                {"step": "adb_get_state", "serial": device.serial},
            )

        # 验证 get-state 输出为 "device"
        state_output = state_result.diagnostics.get("stdout_trimmed", "")
        if isinstance(state_output, str) and state_output.strip() != "device":
            return ProbeResult.from_monotonic(
                "mumu_readiness",
                ProbeStatus.NOT_READY,
                ProbeErrorCode.DEVICE_NOT_FOUND,
                started_at,
                {"step": "adb_get_state", "serial": device.serial, "output": state_output.strip()},
            )

        # 8. 检查取消
        if cancel is not None and cancel.is_cancelled:
            return ProbeResult.from_monotonic(
                "mumu_readiness", ProbeStatus.FAILED, ProbeErrorCode.ADB_CANCELLED, started_at
            )
        if deadline.expired:
            return _deadline_result(started_at, "adb_boot_completed")

        # 9. adb shell getprop sys.boot_completed
        boot_result = self._adb.get_boot_completed(device.serial, deadline, cancel)
        if boot_result.status != ProbeStatus.READY:
            return ProbeResult.from_monotonic(
                "mumu_readiness",
                boot_result.status,
                boot_result.error_code,
                started_at,
                {"step": "adb_boot_completed", "serial": device.serial},
            )

        # 验证 boot_completed 严格为 "1"
        boot_output = boot_result.diagnostics.get("stdout_trimmed", "")
        if isinstance(boot_output, str) and boot_output.strip() != "1":
            return ProbeResult.from_monotonic(
                "mumu_readiness",
                ProbeStatus.NOT_READY,
                ProbeErrorCode.ANDROID_NOT_BOOTED,
                started_at,
                {"step": "adb_boot_completed", "serial": device.serial, "output": boot_output.strip()},
            )

        # 10. READY
        return ProbeResult.from_monotonic(
            "mumu_readiness",
            ProbeStatus.READY,
            ProbeErrorCode.OK,
            started_at,
            {"serial": device.serial},
        )

    def ensure_ready(
        self,
        host: str,
        port: int,
        expected_serial: str | None,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        """Explicitly recover one eligible local TCP ADB endpoint.

        The ordinary probe remains readonly. This method allows at most one
        connect between an initial readonly probe and one readonly recheck.
        """
        initial = self.probe(host, port, expected_serial, deadline, cancel)
        initial = _with_connect_metadata(
            initial,
            attempted=False,
            status="not_attempted",
            error="none",
            rechecked=False,
        )
        if initial.status == ProbeStatus.READY:
            return initial
        if not _connect_is_allowed(initial, host, port, expected_serial, deadline, cancel):
            return initial

        connect_result = self._adb.connect(host, port, deadline, cancel)
        connect_status = connect_result.diagnostics.get("connect_status")
        if connect_status not in ("connected", "already_connected"):
            connect_status = "failed"
        if connect_result.status != ProbeStatus.READY:
            return _with_connect_metadata(
                replace(connect_result, probe_name="mumu_readiness"),
                attempted=True,
                status=connect_status,
                error=connect_result.error_code.value,
                rechecked=False,
                step="adb_connect",
            )

        if cancel is not None and cancel.is_cancelled:
            return _control_result(
                ProbeStatus.FAILED,
                ProbeErrorCode.ADB_CANCELLED,
                connect_status,
                connect_result.error_code.value,
            )
        if deadline.expired:
            return _control_result(
                ProbeStatus.TIMEOUT,
                ProbeErrorCode.ADB_TIMEOUT,
                connect_status,
                connect_result.error_code.value,
            )

        rechecked = self.probe(host, port, expected_serial, deadline, cancel)
        return _with_connect_metadata(
            rechecked,
            attempted=True,
            status=connect_status,
            error=connect_result.error_code.value,
            rechecked=True,
        )


def _status_for_code(code: ProbeErrorCode) -> ProbeStatus:
    """将 ProbeErrorCode 映射到默认 ProbeStatus。"""
    if code in (ProbeErrorCode.DEVICE_NOT_FOUND, ProbeErrorCode.PORT_CLOSED):
        return ProbeStatus.UNAVAILABLE
    if code in (ProbeErrorCode.DEVICE_OFFLINE, ProbeErrorCode.DEVICE_UNAUTHORIZED, ProbeErrorCode.ANDROID_NOT_BOOTED):
        return ProbeStatus.NOT_READY
    if code in (ProbeErrorCode.TCP_TIMEOUT, ProbeErrorCode.ADB_TIMEOUT):
        return ProbeStatus.TIMEOUT
    return ProbeStatus.FAILED


def _deadline_result(
    started_at: float,
    step: str,
    error_code: ProbeErrorCode = ProbeErrorCode.ADB_TIMEOUT,
) -> ProbeResult:
    return ProbeResult.from_monotonic(
        "mumu_readiness",
        ProbeStatus.TIMEOUT,
        error_code,
        started_at,
        {"step": step},
    )


def _connect_is_allowed(
    initial: ProbeResult,
    host: str,
    port: int,
    expected_serial: str | None,
    deadline: Deadline,
    cancel: CancellationToken | None,
) -> bool:
    return (
        initial.error_code == ProbeErrorCode.DEVICE_NOT_FOUND
        and initial.diagnostics.get("step") == "select_device"
        and host == "127.0.0.1"
        and isinstance(port, int)
        and not isinstance(port, bool)
        and 1 <= port <= 65_535
        and expected_serial == f"{host}:{port}"
        and not deadline.expired
        and not (cancel is not None and cancel.is_cancelled)
    )


def _with_connect_metadata(
    result: ProbeResult,
    *,
    attempted: bool,
    status: str,
    error: str,
    rechecked: bool,
    step: str | None = None,
) -> ProbeResult:
    diagnostics = dict(result.diagnostics)
    if step is not None:
        diagnostics["step"] = step
    diagnostics.update(
        {
            "adb_connect_attempted": attempted,
            "adb_connect_status": status,
            "adb_connect_error": error,
            "readiness_rechecked_after_connect": rechecked,
        }
    )
    return replace(result, diagnostics=diagnostics)


def _control_result(
    status: ProbeStatus,
    error_code: ProbeErrorCode,
    connect_status: str,
    connect_error: str,
) -> ProbeResult:
    return ProbeResult.from_monotonic(
        "mumu_readiness",
        status,
        error_code,
        time.monotonic(),
        {
            "step": "adb_connect",
            "adb_connect_attempted": True,
            "adb_connect_status": connect_status,
            "adb_connect_error": connect_error,
            "readiness_rechecked_after_connect": False,
        },
    )
