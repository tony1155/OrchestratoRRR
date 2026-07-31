from __future__ import annotations

import time
from collections.abc import Sequence

import pytest

import autogame_orchestrator.probes.mumu_readiness as readiness_module
from autogame_orchestrator.models import JsonValue
from autogame_orchestrator.probes.adb_client import AdbClient
from autogame_orchestrator.probes.models import (
    AdbDevice,
    AdbDevicesResult,
    AdbDeviceState,
    ProbeErrorCode,
    ProbeResult,
    ProbeStatus,
)
from autogame_orchestrator.probes.mumu_readiness import MumuReadinessProbe
from autogame_orchestrator.process import CancellationToken, Deadline

_HOST = "127.0.0.1"
_PORT = 16384
_EXPECTED = f"{_HOST}:{_PORT}"


def _ready(name: str, diagnostics: dict[str, JsonValue] | None = None) -> ProbeResult:
    return ProbeResult.from_monotonic(
        name,
        ProbeStatus.READY,
        ProbeErrorCode.OK,
        time.monotonic(),
        diagnostics or {},
    )


def _failed(name: str, status: ProbeStatus, error: ProbeErrorCode) -> ProbeResult:
    return ProbeResult.from_monotonic(name, status, error, time.monotonic())


def _device(serial: str, state: AdbDeviceState) -> AdbDevice:
    return AdbDevice(serial=serial, state=state)


class FakeAdb(AdbClient):
    def __init__(
        self,
        device_sequences: Sequence[tuple[AdbDevice, ...]],
        *,
        connect_result: ProbeResult | None = None,
        cancel_after_first_list: CancellationToken | None = None,
        cancel_after_connect: CancellationToken | None = None,
    ) -> None:
        self.device_sequences = tuple(device_sequences)
        self.connect_result = connect_result or _ready("adb_connect", {"connect_status": "connected"})
        self.cancel_after_first_list = cancel_after_first_list
        self.cancel_after_connect = cancel_after_connect
        self.list_calls = 0
        self.connect_calls = 0
        self.state_calls = 0
        self.boot_calls = 0
        self.deadlines: list[Deadline] = []

    def list_devices(self, deadline: Deadline, cancel: CancellationToken | None = None) -> AdbDevicesResult:
        self.list_calls += 1
        self.deadlines.append(deadline)
        index = min(self.list_calls - 1, len(self.device_sequences) - 1)
        devices = self.device_sequences[index]
        if self.list_calls == 1 and self.cancel_after_first_list is not None:
            self.cancel_after_first_list.cancel()
        return AdbDevicesResult(_ready("adb_devices"), devices)

    def connect(
        self,
        host: str,
        port: int,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        assert host == _HOST
        assert port == _PORT
        self.connect_calls += 1
        self.deadlines.append(deadline)
        if self.cancel_after_connect is not None:
            self.cancel_after_connect.cancel()
        return self.connect_result

    def get_state(self, serial: str, deadline: Deadline, cancel: CancellationToken | None = None) -> ProbeResult:
        assert serial == _EXPECTED
        self.state_calls += 1
        self.deadlines.append(deadline)
        return _ready("adb_get_state", {"stdout_trimmed": "device"})

    def get_boot_completed(
        self, serial: str, deadline: Deadline, cancel: CancellationToken | None = None
    ) -> ProbeResult:
        assert serial == _EXPECTED
        self.boot_calls += 1
        self.deadlines.append(deadline)
        return _ready("adb_boot_completed", {"stdout_trimmed": "1"})


def _patch_tcp(monkeypatch: pytest.MonkeyPatch, result: ProbeResult, seen: list[Deadline]) -> None:
    def _probe_tcp(host: str, port: int, deadline: Deadline) -> ProbeResult:
        assert host == _HOST
        assert port == _PORT
        seen.append(deadline)
        return result

    monkeypatch.setattr(readiness_module, "probe_tcp_endpoint", _probe_tcp)


def _ensure(
    adb: FakeAdb,
    *,
    expected_serial: str | None = _EXPECTED,
    deadline: Deadline | None = None,
    cancel: CancellationToken | None = None,
) -> ProbeResult:
    probe = MumuReadinessProbe(adb)
    return probe.ensure_ready(_HOST, _PORT, expected_serial, deadline or Deadline.after(5.0), cancel)


def test_already_ready_does_not_connect_or_recheck(monkeypatch: pytest.MonkeyPatch) -> None:
    tcp_deadlines: list[Deadline] = []
    _patch_tcp(monkeypatch, _ready("tcp_probe"), tcp_deadlines)
    adb = FakeAdb([(_device(_EXPECTED, AdbDeviceState.DEVICE),)])

    result = _ensure(adb)

    assert result.status == ProbeStatus.READY
    assert adb.connect_calls == 0
    assert adb.list_calls == 1
    assert result.diagnostics["adb_connect_attempted"] is False
    assert result.diagnostics["readiness_rechecked_after_connect"] is False


def test_missing_target_connects_once_and_rechecks_once(monkeypatch: pytest.MonkeyPatch) -> None:
    tcp_deadlines: list[Deadline] = []
    _patch_tcp(monkeypatch, _ready("tcp_probe"), tcp_deadlines)
    adb = FakeAdb(
        [
            (),
            (_device(_EXPECTED, AdbDeviceState.DEVICE),),
        ]
    )
    deadline = Deadline.after(5.0)

    result = _ensure(adb, deadline=deadline)

    assert result.status == ProbeStatus.READY
    assert result.error_code == ProbeErrorCode.OK
    assert adb.connect_calls == 1
    assert adb.list_calls == 2
    assert adb.state_calls == 1
    assert adb.boot_calls == 1
    assert result.diagnostics["adb_connect_status"] == "connected"
    assert result.diagnostics["adb_connect_error"] == "OK"
    assert result.diagnostics["readiness_rechecked_after_connect"] is True
    assert all(item is deadline for item in [*tcp_deadlines, *adb.deadlines])


def test_connect_failure_does_not_recheck(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tcp(monkeypatch, _ready("tcp_probe"), [])
    adb = FakeAdb(
        [()],
        connect_result=_failed("adb_connect", ProbeStatus.FAILED, ProbeErrorCode.ADB_CONNECT_FAILED),
    )

    result = _ensure(adb)

    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_CONNECT_FAILED
    assert adb.connect_calls == 1
    assert adb.list_calls == 1
    assert result.diagnostics["readiness_rechecked_after_connect"] is False


def test_connect_timeout_does_not_recheck(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tcp(monkeypatch, _ready("tcp_probe"), [])
    adb = FakeAdb(
        [()],
        connect_result=_failed("adb_connect", ProbeStatus.TIMEOUT, ProbeErrorCode.ADB_TIMEOUT),
    )

    result = _ensure(adb)

    assert result.status == ProbeStatus.TIMEOUT
    assert result.error_code == ProbeErrorCode.ADB_TIMEOUT
    assert adb.connect_calls == 1
    assert adb.list_calls == 1
    assert result.diagnostics["readiness_rechecked_after_connect"] is False


def test_successful_connect_returns_second_readiness_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tcp(monkeypatch, _ready("tcp_probe"), [])
    adb = FakeAdb(
        [
            (),
            (_device(_EXPECTED, AdbDeviceState.OFFLINE),),
        ]
    )

    result = _ensure(adb)

    assert result.status == ProbeStatus.NOT_READY
    assert result.error_code == ProbeErrorCode.DEVICE_OFFLINE
    assert adb.connect_calls == 1
    assert adb.list_calls == 2
    assert result.diagnostics["readiness_rechecked_after_connect"] is True


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (ProbeStatus.UNAVAILABLE, ProbeErrorCode.PORT_CLOSED),
        (ProbeStatus.TIMEOUT, ProbeErrorCode.TCP_TIMEOUT),
    ],
)
def test_tcp_failure_does_not_connect(
    monkeypatch: pytest.MonkeyPatch, status: ProbeStatus, error: ProbeErrorCode
) -> None:
    _patch_tcp(monkeypatch, _failed("tcp_probe", status, error), [])
    adb = FakeAdb([()])

    result = _ensure(adb)

    assert result.error_code == error
    assert adb.connect_calls == 0
    assert adb.list_calls == 0


def test_expected_serial_mismatch_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tcp(monkeypatch, _ready("tcp_probe"), [])
    adb = FakeAdb([()])

    result = _ensure(adb, expected_serial="127.0.0.1:16385")

    assert result.error_code == ProbeErrorCode.DEVICE_NOT_FOUND
    assert adb.connect_calls == 0
    assert adb.list_calls == 1


def test_expected_serial_whitespace_mismatch_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tcp(monkeypatch, _ready("tcp_probe"), [])
    adb = FakeAdb([()])

    result = _ensure(adb, expected_serial=f" {_EXPECTED}")

    assert result.error_code == ProbeErrorCode.DEVICE_NOT_FOUND
    assert adb.connect_calls == 0


@pytest.mark.parametrize("state", [AdbDeviceState.OFFLINE, AdbDeviceState.UNAUTHORIZED])
def test_exact_non_ready_target_does_not_connect(monkeypatch: pytest.MonkeyPatch, state: AdbDeviceState) -> None:
    _patch_tcp(monkeypatch, _ready("tcp_probe"), [])
    adb = FakeAdb([(_device(_EXPECTED, state),)])

    result = _ensure(adb)

    assert result.status == ProbeStatus.NOT_READY
    assert adb.connect_calls == 0
    assert adb.list_calls == 1


def test_exact_ready_target_wins_over_emulator_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tcp(monkeypatch, _ready("tcp_probe"), [])
    adb = FakeAdb(
        [
            (
                _device(_EXPECTED, AdbDeviceState.DEVICE),
                _device("emulator-5554", AdbDeviceState.DEVICE),
            )
        ]
    )

    result = _ensure(adb)

    assert result.status == ProbeStatus.READY
    assert adb.connect_calls == 0
    assert adb.list_calls == 1


def test_missing_target_does_not_select_emulator(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tcp(monkeypatch, _ready("tcp_probe"), [])
    adb = FakeAdb(
        [
            (_device("emulator-5554", AdbDeviceState.OFFLINE),),
            (
                _device(_EXPECTED, AdbDeviceState.DEVICE),
                _device("emulator-5554", AdbDeviceState.OFFLINE),
            ),
        ]
    )

    result = _ensure(adb)

    assert result.status == ProbeStatus.READY
    assert adb.connect_calls == 1
    assert adb.state_calls == 1


def test_cancellation_after_initial_probe_prevents_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tcp(monkeypatch, _ready("tcp_probe"), [])
    cancel = CancellationToken()
    adb = FakeAdb([()], cancel_after_first_list=cancel)

    result = _ensure(adb, cancel=cancel)

    assert result.error_code == ProbeErrorCode.ADB_CANCELLED
    assert adb.connect_calls == 0
    assert result.diagnostics["adb_connect_attempted"] is False


def test_expired_deadline_prevents_initial_probe_children(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tcp(monkeypatch, _ready("tcp_probe"), [])
    adb = FakeAdb([()])
    deadline = Deadline.at(time.monotonic() - 1.0)

    result = _ensure(adb, deadline=deadline)

    assert result.status == ProbeStatus.TIMEOUT
    assert result.error_code == ProbeErrorCode.TCP_TIMEOUT
    assert adb.connect_calls == 0
    assert adb.list_calls == 0


def test_cancellation_after_connect_prevents_recheck(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tcp(monkeypatch, _ready("tcp_probe"), [])
    cancel = CancellationToken()
    adb = FakeAdb([()], cancel_after_connect=cancel)

    result = _ensure(adb, cancel=cancel)

    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_CANCELLED
    assert adb.connect_calls == 1
    assert adb.list_calls == 1
    assert result.diagnostics["readiness_rechecked_after_connect"] is False


def test_missing_target_with_multiple_transports_still_allows_only_one_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_tcp(monkeypatch, _ready("tcp_probe"), [])
    adb = FakeAdb(
        [
            (_device("emulator-5554", AdbDeviceState.OFFLINE),),
            (_device("emulator-5554", AdbDeviceState.OFFLINE),),
        ]
    )

    result = _ensure(adb)

    assert result.error_code == ProbeErrorCode.DEVICE_NOT_FOUND
    assert adb.connect_calls == 1
    assert adb.list_calls == 2
