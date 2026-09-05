"""ADB devices 空白分隔兼容和纯 Fake readiness 回归测试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from autogame_orchestrator.probes.adb_parser import AdbParseError, parse_adb_devices
from autogame_orchestrator.probes.models import (
    AdbDevicesResult,
    AdbDeviceState,
    ProbeErrorCode,
    ProbeResult,
    ProbeStatus,
)
from autogame_orchestrator.probes.mumu_readiness import MumuReadinessProbe
from autogame_orchestrator.process import Deadline

HEADER = "List of devices attached\n"
SERIAL = "emulator-example"


@pytest.mark.parametrize("separator", [" ", "  ", "    ", "\t", "\t ", " \t ", "\t\t"])
def test_device_record_accepts_contiguous_whitespace(separator: str) -> None:
    devices = parse_adb_devices(f"{HEADER}{SERIAL}{separator}device\n")
    assert len(devices) == 1
    assert devices[0].serial == SERIAL
    assert devices[0].state == AdbDeviceState.DEVICE


@pytest.mark.parametrize(
    "line",
    [
        f"{SERIAL} device product:example model:Example device:example transport_id:1",
        f"{SERIAL}    device    product:example    model:Example",
        f"{SERIAL}\tdevice model:Example device:example",
        f"{SERIAL}\tdevice\tmodel:Example\tdevice:example",
    ],
)
def test_attributes_survive_all_supported_separators(line: str) -> None:
    device = parse_adb_devices(f"{HEADER}{line}\n")[0]
    assert device.attributes["model"] == "Example"
    assert "serial" not in device.attributes
    assert "state" not in device.attributes


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("offline", AdbDeviceState.OFFLINE),
        ("unauthorized", AdbDeviceState.UNAUTHORIZED),
        ("future-state", AdbDeviceState.UNKNOWN),
    ],
)
def test_state_semantics_are_preserved_with_spaces(state: str, expected: AdbDeviceState) -> None:
    device = parse_adb_devices(f"{HEADER}{SERIAL}  {state}\n")[0]
    assert device.state == expected


def test_multiple_space_separated_devices_are_preserved() -> None:
    output = f"{HEADER}{SERIAL} device\nemulator-secondary   offline\n"
    devices = parse_adb_devices(output)
    assert [device.serial for device in devices] == [SERIAL, "emulator-secondary"]


def test_duplicate_serial_with_spaces_is_rejected() -> None:
    output = f"{HEADER}{SERIAL} device\n{SERIAL}   offline\n"
    with pytest.raises(AdbParseError) as caught:
        parse_adb_devices(output)
    assert caught.value.error_code == ProbeErrorCode.ADB_OUTPUT_INVALID


def test_serial_without_state_remains_invalid() -> None:
    with pytest.raises(AdbParseError) as caught:
        parse_adb_devices(f"{HEADER}{SERIAL}\n")
    assert caught.value.error_code == ProbeErrorCode.ADB_OUTPUT_INVALID


def test_whitespace_only_lines_are_ignored() -> None:
    assert parse_adb_devices(f"{HEADER} \t  \n{SERIAL} device\n")[0].serial == SERIAL


def test_attribute_value_uses_first_colon_only() -> None:
    device = parse_adb_devices(f"{HEADER}{SERIAL} device model:Example:Variant\n")[0]
    assert device.attributes["model"] == "Example:Variant"


def test_crlf_space_separated_record_is_supported() -> None:
    devices = parse_adb_devices(f"List of devices attached\r\n{SERIAL}  device\r\n")
    assert devices[0].state == AdbDeviceState.DEVICE


def test_leading_garbage_before_header_remains_invalid() -> None:
    with pytest.raises(AdbParseError):
        parse_adb_devices(f"garbage\n{HEADER}{SERIAL} device\n")


class _WhitespaceAdb:
    def __init__(self, output: str) -> None:
        self.output = output
        self.get_state_calls = 0
        self.boot_calls = 0
        self.ensure_server_calls = 0

    def ensure_server(self, _deadline: Deadline, _cancel=None) -> ProbeResult:
        self.ensure_server_calls += 1
        return ProbeResult.ready("adb_start_server")

    def list_devices(self, _deadline: Deadline, _cancel=None) -> AdbDevicesResult:
        try:
            devices = parse_adb_devices(self.output)
        except AdbParseError as exc:
            return AdbDevicesResult(
                ProbeResult.from_monotonic(
                    "adb_devices",
                    ProbeStatus.FAILED,
                    exc.error_code,
                    0.0,
                ),
                (),
            )
        return AdbDevicesResult(ProbeResult.ready("adb_devices"), devices)

    def get_state(self, _serial: str, _deadline: Deadline, _cancel=None) -> ProbeResult:
        self.get_state_calls += 1
        return ProbeResult.ready("adb_get_state", {"stdout_trimmed": "device"})

    def get_boot_completed(self, _serial: str, _deadline: Deadline, _cancel=None) -> ProbeResult:
        self.boot_calls += 1
        return ProbeResult.ready("adb_boot_completed", {"stdout_trimmed": "1"})


def _ready_tcp(*_args: object, **_kwargs: object) -> ProbeResult:
    return ProbeResult.ready("tcp_probe")


def test_space_separated_output_reaches_state_and_boot() -> None:
    adb = _WhitespaceAdb(f"{HEADER}{SERIAL}    device model:Example\n")
    with patch("autogame_orchestrator.probes.mumu_readiness.probe_tcp_endpoint", _ready_tcp):
        result = MumuReadinessProbe(adb).probe("host-placeholder", 1, SERIAL, Deadline.after(5))
    assert result.status == ProbeStatus.READY
    assert result.error_code == ProbeErrorCode.OK
    assert (adb.get_state_calls, adb.boot_calls) == (1, 1)


@pytest.mark.parametrize(
    ("state", "error"),
    [
        ("offline", ProbeErrorCode.DEVICE_OFFLINE),
        ("unauthorized", ProbeErrorCode.DEVICE_UNAUTHORIZED),
    ],
)
def test_space_separated_unready_state_mapping_is_unchanged(
    state: str,
    error: ProbeErrorCode,
) -> None:
    adb = _WhitespaceAdb(f"{HEADER}{SERIAL} {state}\n")
    with patch("autogame_orchestrator.probes.mumu_readiness.probe_tcp_endpoint", _ready_tcp):
        result = MumuReadinessProbe(adb).probe("host-placeholder", 1, SERIAL, Deadline.after(5))
    assert result.status == ProbeStatus.NOT_READY
    assert result.error_code == error
    assert (adb.get_state_calls, adb.boot_calls) == (0, 0)


def test_malformed_devices_output_mapping_is_unchanged() -> None:
    adb = _WhitespaceAdb(f"{HEADER}{SERIAL}\n")
    with patch("autogame_orchestrator.probes.mumu_readiness.probe_tcp_endpoint", _ready_tcp):
        result = MumuReadinessProbe(adb).probe("host-placeholder", 1, SERIAL, Deadline.after(5))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_OUTPUT_INVALID
    assert result.diagnostics["step"] == "adb_devices"
