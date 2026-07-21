"""MuMu readiness 探测测试。使用 Fake ADB 和精确状态映射断言。"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

from autogame_orchestrator.probes.adb_client import AdbClient, AdbClientConfig
from autogame_orchestrator.probes.models import ProbeErrorCode, ProbeStatus
from autogame_orchestrator.probes.mumu_readiness import MumuReadinessProbe
from autogame_orchestrator.process import CancellationToken, Deadline

_FAKE_ADB = str(Path(__file__).resolve().parent.parent / "fakes" / "fake_adb.py")


def _make_probe(mode: str = "normal") -> MumuReadinessProbe:
    client = AdbClient(
        AdbClientConfig(
            executable=Path(sys.executable),
            base_arguments=(_FAKE_ADB, "--mode", mode),
        )
    )
    return MumuReadinessProbe(client)


def _open_port() -> tuple[socket.socket, int]:
    """打开一个临时 TCP 端口并返回 (socket, port)。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock, sock.getsockname()[1]


# ─── TCP 失败 ────────────────────────────────────────────────────


def test_tcp_refused() -> None:
    """TCP 端口拒绝：UNAVAILABLE + PORT_CLOSED。"""
    from unittest.mock import patch

    with patch("socket.create_connection", side_effect=ConnectionRefusedError):
        probe = _make_probe("normal")
        result = probe.probe("127.0.0.1", 12345, None, Deadline.after(1.0))
        assert result.status == ProbeStatus.UNAVAILABLE
        assert result.error_code == ProbeErrorCode.PORT_CLOSED


# ─── ADB timeout（TCP 必须成功） ─────────────────────────────────


def test_adb_timeout_precise() -> None:
    """TCP 成功 + Fake ADB sleep_forever → TIMEOUT + ADB_TIMEOUT。"""
    sock, port = _open_port()
    try:
        probe = _make_probe("sleep_forever")
        result = probe.probe("127.0.0.1", port, None, Deadline.after(0.3))
        assert result.status == ProbeStatus.TIMEOUT
        assert result.error_code == ProbeErrorCode.ADB_TIMEOUT
    finally:
        sock.close()


# ─── Cancellation（TCP 必须成功） ────────────────────────────────


def test_cancellation_precise() -> None:
    """TCP 成功 + Fake ADB 永久等待 + 另一线程 cancel → FAILED + ADB_CANCELLED。"""
    sock, port = _open_port()
    try:
        probe = _make_probe("sleep_forever")
        cancel = CancellationToken()
        t0 = time.monotonic()

        def _cancel() -> None:
            time.sleep(0.2)
            cancel.cancel()

        t = threading.Thread(target=_cancel, daemon=True)
        t.start()

        result = probe.probe("127.0.0.1", port, None, Deadline.after(5.0), cancel=cancel)
        t.join()

        assert result.status == ProbeStatus.FAILED
        assert result.error_code == ProbeErrorCode.ADB_CANCELLED
        assert time.monotonic() - t0 < 3.0
    finally:
        sock.close()


# ─── 设备状态映射 ────────────────────────────────────────────────


def _test_with_port(mode: str, expected_status: ProbeStatus, expected_code: ProbeErrorCode) -> None:
    sock, port = _open_port()
    try:
        probe = _make_probe(mode)
        result = probe.probe("127.0.0.1", port, None, Deadline.after(5.0))
        assert result.status == expected_status, f"mode={mode} 期望 {expected_status.value}，实际 {result.status.value}"
        assert result.error_code == expected_code, (
            f"mode={mode} 期望 {expected_code.value}，实际 {result.error_code.value}"
        )
    finally:
        sock.close()


def test_no_devices() -> None:
    """无设备：UNAVAILABLE + DEVICE_NOT_FOUND。"""
    _test_with_port("no_devices", ProbeStatus.UNAVAILABLE, ProbeErrorCode.DEVICE_NOT_FOUND)


def test_offline() -> None:
    """offline：NOT_READY + DEVICE_OFFLINE。"""
    _test_with_port("offline", ProbeStatus.NOT_READY, ProbeErrorCode.DEVICE_OFFLINE)


def test_unauthorized() -> None:
    """unauthorized：NOT_READY + DEVICE_UNAUTHORIZED。"""
    _test_with_port("unauthorized", ProbeStatus.NOT_READY, ProbeErrorCode.DEVICE_UNAUTHORIZED)


def test_multi_devices() -> None:
    """多设备：FAILED + MULTIPLE_DEVICES。"""
    _test_with_port("multi_devices", ProbeStatus.FAILED, ProbeErrorCode.MULTIPLE_DEVICES)


def test_boot_completed_zero() -> None:
    """boot_completed=0：NOT_READY + ANDROID_NOT_BOOTED。"""
    _test_with_port("boot_0", ProbeStatus.NOT_READY, ProbeErrorCode.ANDROID_NOT_BOOTED)
