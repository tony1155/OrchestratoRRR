"""ADB devices 解析和选择测试。"""

from __future__ import annotations

import pytest

from autogame_orchestrator.probes.adb_parser import AdbParseError, parse_adb_devices, select_adb_device
from autogame_orchestrator.probes.models import AdbDeviceState, ProbeErrorCode


def _normal_output() -> str:
    return "List of devices attached\r\n127.0.0.1:16384\tdevice\n"


def _multi_output() -> str:
    return "List of devices attached\n127.0.0.1:16384\tdevice\nemulator-5554\tdevice\n"


def _offline_output() -> str:
    return "List of devices attached\n127.0.0.1:16384\toffline\n"


def _unauthorized_output() -> str:
    return "List of devices attached\n127.0.0.1:16384\tunauthorized\n"


def _with_attrs_output() -> str:
    return "List of devices attached\n127.0.0.1:16384\tdevice model:MuMu12 device:starrail\n"


def test_empty_list() -> None:
    """空设备列表返回空元组。"""
    devices = parse_adb_devices("List of devices attached\n")
    assert devices == ()


def test_single_device() -> None:
    """单设备解析。"""
    devices = parse_adb_devices(_normal_output())
    assert len(devices) == 1
    assert devices[0].serial == "127.0.0.1:16384"
    assert devices[0].state == AdbDeviceState.DEVICE


def test_multi_device() -> None:
    """多设备解析。"""
    devices = parse_adb_devices(_multi_output())
    assert len(devices) == 2
    assert devices[0].serial == "127.0.0.1:16384"
    assert devices[1].serial == "emulator-5554"


def test_offline() -> None:
    """offline 状态。"""
    devices = parse_adb_devices(_offline_output())
    assert devices[0].state == AdbDeviceState.OFFLINE


def test_unauthorized() -> None:
    """unauthorized 状态。"""
    devices = parse_adb_devices(_unauthorized_output())
    assert devices[0].state == AdbDeviceState.UNAUTHORIZED


def test_attributes() -> None:
    """devices -l 属性解析。"""
    devices = parse_adb_devices(_with_attrs_output())
    assert devices[0].attributes.get("model") == "MuMu12"
    assert devices[0].attributes.get("device") == "starrail"


def test_crlf_support() -> None:
    """CRLF 行结尾。"""
    output = "List of devices attached\r\n127.0.0.1:16384\tdevice\r\n"
    devices = parse_adb_devices(output)
    assert len(devices) == 1


def test_malformed_line() -> None:
    """格式错误行抛出 AdbParseError。"""
    output = "List of devices attached\nbad_line_without_tab\n"
    with pytest.raises(AdbParseError) as exc_info:
        parse_adb_devices(output)
    assert exc_info.value.error_code == ProbeErrorCode.ADB_OUTPUT_INVALID


def test_duplicate_serial() -> None:
    """重复 serial 抛出 AdbParseError。"""
    output = "List of devices attached\n127.0.0.1:16384\tdevice\n127.0.0.1:16384\tdevice\n"
    with pytest.raises(AdbParseError):
        parse_adb_devices(output)


def test_missing_header() -> None:
    """缺少标题行抛出 AdbParseError。"""
    with pytest.raises(AdbParseError):
        parse_adb_devices("127.0.0.1:16384\tdevice\n")


# ── select_adb_device 测试 ────────────────────────────────────────


def test_select_exact_serial() -> None:
    """精确 serial 匹配。"""
    devices = parse_adb_devices(_normal_output())
    d = select_adb_device(devices, "127.0.0.1:16384")
    assert d.serial == "127.0.0.1:16384"


def test_select_serial_not_found() -> None:
    """serial 不存在。"""
    devices = parse_adb_devices(_normal_output())
    with pytest.raises(AdbParseError) as exc_info:
        select_adb_device(devices, "192.168.1.1:5555")
    assert exc_info.value.error_code == ProbeErrorCode.DEVICE_NOT_FOUND


def test_select_single_device_auto() -> None:
    """唯一设备自动选择。"""
    devices = parse_adb_devices(_normal_output())
    d = select_adb_device(devices, None)
    assert d.serial == "127.0.0.1:16384"


def test_select_multi_devices_rejected() -> None:
    """多设备拒绝自动选择。"""
    devices = parse_adb_devices(_multi_output())
    with pytest.raises(AdbParseError) as exc_info:
        select_adb_device(devices, None)
    assert exc_info.value.error_code == ProbeErrorCode.MULTIPLE_DEVICES


def test_select_no_devices() -> None:
    """无设备返回 DEVICE_NOT_FOUND。"""
    devices = parse_adb_devices("List of devices attached\n")
    with pytest.raises(AdbParseError) as exc_info:
        select_adb_device(devices, None)
    assert exc_info.value.error_code == ProbeErrorCode.DEVICE_NOT_FOUND


def test_select_offline_rejected() -> None:
    """offline 设备被拒绝。"""
    devices = parse_adb_devices(_offline_output())
    with pytest.raises(AdbParseError) as exc_info:
        select_adb_device(devices, "127.0.0.1:16384")
    assert exc_info.value.error_code == ProbeErrorCode.DEVICE_OFFLINE


def test_select_unauthorized_rejected() -> None:
    """unauthorized 设备被拒绝。"""
    devices = parse_adb_devices(_unauthorized_output())
    with pytest.raises(AdbParseError) as exc_info:
        select_adb_device(devices, "127.0.0.1:16384")
    assert exc_info.value.error_code == ProbeErrorCode.DEVICE_UNAUTHORIZED
