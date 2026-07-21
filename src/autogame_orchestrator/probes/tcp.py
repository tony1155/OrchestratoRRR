"""本地 TCP 端口探测。

只允许 127.0.0.0/8、::1 和 localhost。拒绝外部地址。
"""

from __future__ import annotations

import ipaddress
import socket
import time

from autogame_orchestrator.probes.models import ProbeErrorCode, ProbeResult, ProbeStatus
from autogame_orchestrator.process.deadline import Deadline


def _is_local_host(host: str) -> bool:
    """检查 host 是否为精确的 localhost 字符串。"""
    return host == "localhost"


def _is_loopback_ip(host: str) -> bool:
    """检查 host 是否为回环 IP 地址。"""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def probe_tcp_endpoint(
    host: str,
    port: int,
    deadline: Deadline,
) -> ProbeResult:
    """探测本地 TCP 端口是否可连接。

    只允许 127.0.0.0/8、::1 和 localhost。
    """
    started_at = time.monotonic()

    # 校验地址
    if not _is_local_host(host) and not _is_loopback_ip(host):
        return ProbeResult.from_monotonic(
            "tcp_probe",
            ProbeStatus.FAILED,
            ProbeErrorCode.NON_LOCAL_ADDRESS_REJECTED,
            started_at,
            {"host": host, "reason": "仅允许本地回环地址"},
        )

    # 校验端口
    if port < 1 or port > 65535:
        return ProbeResult.from_monotonic(
            "tcp_probe",
            ProbeStatus.FAILED,
            ProbeErrorCode.INVALID_CONFIGURATION,
            started_at,
            {"port": port, "reason": f"端口号必须在 1-65535 之间，收到 {port}"},
        )

    # Deadline 已过期
    if deadline.expired:
        return ProbeResult.from_monotonic(
            "tcp_probe",
            ProbeStatus.TIMEOUT,
            ProbeErrorCode.TCP_TIMEOUT,
            started_at,
        )

    sock: socket.socket | None = None
    try:
        timeout = deadline.remaining_seconds
        sock = socket.create_connection((host, port), timeout=timeout)
        return ProbeResult.from_monotonic(
            "tcp_probe",
            ProbeStatus.READY,
            ProbeErrorCode.OK,
            started_at,
            {"host": host, "port": port},
        )
    except ConnectionRefusedError:
        return ProbeResult.from_monotonic(
            "tcp_probe",
            ProbeStatus.UNAVAILABLE,
            ProbeErrorCode.PORT_CLOSED,
            started_at,
            {"host": host, "port": port},
        )
    except TimeoutError:
        return ProbeResult.from_monotonic(
            "tcp_probe",
            ProbeStatus.TIMEOUT,
            ProbeErrorCode.TCP_TIMEOUT,
            started_at,
            {"host": host, "port": port},
        )
    except OSError as exc:
        return ProbeResult.from_monotonic(
            "tcp_probe",
            ProbeStatus.FAILED,
            ProbeErrorCode.PORT_CLOSED,
            started_at,
            {"host": host, "port": port, "error": str(exc)},
        )
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
