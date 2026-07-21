"""TCP 本地端口探测测试。"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from autogame_orchestrator.probes.models import ProbeErrorCode, ProbeStatus
from autogame_orchestrator.probes.tcp import probe_tcp_endpoint
from autogame_orchestrator.process.deadline import Deadline


def _start_temp_server() -> tuple[socket.socket, str, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    host, port = sock.getsockname()[:2]
    return sock, host, port


def test_ipv4_loopback_ready() -> None:
    """IPv4 loopback 端口可连接。"""
    sock, host, port = _start_temp_server()
    try:
        result = probe_tcp_endpoint(host, port, Deadline.after(1.0))
        assert result.status == ProbeStatus.READY
        assert result.error_code == ProbeErrorCode.OK
    finally:
        sock.close()


def test_localhost_ready() -> None:
    """localhost 端口可连接。"""
    sock, _, port = _start_temp_server()
    try:
        result = probe_tcp_endpoint("localhost", port, Deadline.after(1.0))
        assert result.status == ProbeStatus.READY
    finally:
        sock.close()


def test_port_refused() -> None:
    """ConnectionRefusedError 返回 UNAVAILABLE + PORT_CLOSED。"""
    with patch("socket.create_connection", side_effect=ConnectionRefusedError):
        result = probe_tcp_endpoint("127.0.0.1", 12345, Deadline.after(1.0))
        assert result.status == ProbeStatus.UNAVAILABLE
        assert result.error_code == ProbeErrorCode.PORT_CLOSED


def test_timeout_precise() -> None:
    """socket.timeout 返回 TIMEOUT + TCP_TIMEOUT。"""
    with patch("socket.create_connection", side_effect=socket.timeout):
        result = probe_tcp_endpoint("127.0.0.1", 12345, Deadline.after(1.0))
        assert result.status == ProbeStatus.TIMEOUT
        assert result.error_code == ProbeErrorCode.TCP_TIMEOUT


def test_ipv6_loopback_ready_or_skip() -> None:
    """IPv6 loopback 能连接则 READY，否则 SKIP。"""
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.bind(("::1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
    except OSError:
        pytest.skip("IPv6 在当前机器不可用")
        return
    try:
        result = probe_tcp_endpoint("::1", port, Deadline.after(1.0))
        assert result.status == ProbeStatus.READY
    finally:
        sock.close()


def test_invalid_port_zero() -> None:
    """端口 0 被拒绝。"""
    result = probe_tcp_endpoint("127.0.0.1", 0, Deadline.after(1.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.INVALID_CONFIGURATION


def test_invalid_port_too_high() -> None:
    """端口 65536 被拒绝。"""
    result = probe_tcp_endpoint("127.0.0.1", 65536, Deadline.after(1.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.INVALID_CONFIGURATION


def test_external_ip_rejected() -> None:
    """外部 IP 被拒绝。"""
    result = probe_tcp_endpoint("8.8.8.8", 53, Deadline.after(1.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.NON_LOCAL_ADDRESS_REJECTED


def test_external_domain_rejected() -> None:
    """外部域名被拒绝（不做 DNS 查询）。"""
    result = probe_tcp_endpoint("example.com", 80, Deadline.after(1.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.NON_LOCAL_ADDRESS_REJECTED


def test_socket_closed_after_probe() -> None:
    """探测后 socket 已关闭。"""
    sock, host, port = _start_temp_server()
    try:
        probe_tcp_endpoint(host, port, Deadline.after(1.0))
    finally:
        sock.close()
