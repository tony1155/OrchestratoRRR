"""Regression tests for bounded MuMu lifecycle operation deadlines."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from autogame_orchestrator.models import StageName
from autogame_orchestrator.probes.adb_client import AdbClient, AdbClientConfig
from autogame_orchestrator.probes.models import ProbeErrorCode, ProbeResult, ProbeStatus
from autogame_orchestrator.probes.mumu_readiness import MumuReadinessProbe
from autogame_orchestrator.process import CancellationToken, Deadline
from autogame_orchestrator.runtime.models import (
    MumuAction,
    MumuRuntimeErrorCode,
    MumuRuntimeResult,
    MumuRuntimeStatus,
)
from autogame_orchestrator.runtime.mumu import MumuAdapter
from autogame_orchestrator.workflow.production.projection import project_mumu

_FAKE_ADB = str(Path(__file__).resolve().parent.parent / "fakes" / "fake_adb.py")


def _status(status: MumuRuntimeStatus, error: MumuRuntimeErrorCode) -> MumuRuntimeResult:
    return MumuRuntimeResult.from_monotonic(
        MumuAction.STATUS,
        status,
        error,
        time.monotonic(),
        changed=False,
    )


def _manager_success() -> dict[str, object]:
    return {
        "ok": True,
        "status": MumuRuntimeStatus.STARTED,
        "error_code": MumuRuntimeErrorCode.OK,
        "diag": {},
    }


def _adapter(
    tmp_path: Path,
    *,
    start_timeout: float = 0.08,
    stop_timeout: float = 0.08,
) -> MumuAdapter:
    manager = tmp_path / "manager.exe"
    manager.write_text("fake", encoding="utf-8")
    return MumuAdapter(
        executable=manager,
        start_arguments=("control", "-v", "0", "launch"),
        stop_arguments=("control", "-v", "0", "shutdown"),
        adb_executable=Path(sys.executable),
        adb_serial="127.0.0.1:16384",
        start_timeout_seconds=start_timeout,
        stop_timeout_seconds=stop_timeout,
    )


class _NeverReadyProbe:
    def __init__(self) -> None:
        self.ensure_calls = 0
        self.probe_calls = 0
        self.deadlines: list[Deadline] = []
        self.remaining_seen: list[float] = []

    def _not_ready(self, deadline: Deadline) -> ProbeResult:
        self.deadlines.append(deadline)
        self.remaining_seen.append(deadline.remaining_seconds)
        return ProbeResult.from_monotonic(
            "mumu_readiness",
            ProbeStatus.NOT_READY,
            ProbeErrorCode.ANDROID_NOT_BOOTED,
            time.monotonic(),
            {
                "step": "adb_boot_completed",
                "serial": "private-serial",
                "stdout_trimmed": "private-output",
            },
        )

    def ensure_ready(
        self,
        host: str,
        port: int,
        serial: str | None,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        self.ensure_calls += 1
        return self._not_ready(deadline)

    def probe(
        self,
        host: str,
        port: int,
        serial: str | None,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        self.probe_calls += 1
        return self._not_ready(deadline)


class _ReadyProbe(_NeverReadyProbe):
    def ensure_ready(
        self,
        host: str,
        port: int,
        serial: str | None,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        self.ensure_calls += 1
        self.deadlines.append(deadline)
        return ProbeResult.ready("mumu_readiness")


class _StoppedProbe:
    def probe(
        self,
        host: str,
        port: int,
        serial: str | None,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        return ProbeResult.from_monotonic(
            "mumu_readiness",
            ProbeStatus.UNAVAILABLE,
            ProbeErrorCode.PORT_CLOSED,
            time.monotonic(),
            {"step": "tcp_probe"},
        )


class _ConnectOnceThenMissingProbe:
    def __init__(self) -> None:
        self.ensure_calls = 0
        self.probe_calls = 0

    def ensure_ready(
        self,
        host: str,
        port: int,
        serial: str | None,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        self.ensure_calls += 1
        return ProbeResult.from_monotonic(
            "mumu_readiness",
            ProbeStatus.FAILED,
            ProbeErrorCode.ADB_CONNECT_FAILED,
            time.monotonic(),
            {
                "step": "adb_connect",
                "adb_connect_attempted": True,
                "adb_connect_status": "failed",
                "adb_connect_error": "ADB_CONNECT_FAILED",
                "readiness_rechecked_after_connect": False,
                "serial": "private-serial",
                "stdout_trimmed": "private-output",
            },
        )

    def probe(
        self,
        host: str,
        port: int,
        serial: str | None,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        self.probe_calls += 1
        return ProbeResult.from_monotonic(
            "mumu_readiness",
            ProbeStatus.UNAVAILABLE,
            ProbeErrorCode.DEVICE_NOT_FOUND,
            time.monotonic(),
            {
                "step": "select_device",
                "serial": "private-serial",
                "stderr_trimmed": "private-output",
            },
        )


class _ScriptedReadinessProbe:
    def __init__(self, ensure_results: tuple[ProbeResult, ...], readonly_result: ProbeResult) -> None:
        self.ensure_results = ensure_results
        self.readonly_result = readonly_result
        self.ensure_calls = 0
        self.probe_calls = 0
        self.connect_attempts = 0
        self.ensure_probe_counts: list[int] = []

    def ensure_ready(
        self,
        host: str,
        port: int,
        serial: str | None,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        self.ensure_calls += 1
        self.ensure_probe_counts.append(self.probe_calls)
        result = self.ensure_results[min(self.ensure_calls - 1, len(self.ensure_results) - 1)]
        if result.diagnostics.get("adb_connect_attempted") is True:
            self.connect_attempts += 1
        return result

    def probe(
        self,
        host: str,
        port: int,
        serial: str | None,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        self.probe_calls += 1
        return self.readonly_result


def _connect_attempt(
    status: ProbeStatus,
    error: ProbeErrorCode,
    *,
    step: str,
    connect_status: str,
    rechecked: bool,
) -> ProbeResult:
    return ProbeResult.from_monotonic(
        "mumu_readiness",
        status,
        error,
        time.monotonic(),
        {
            "step": step,
            "adb_connect_attempted": True,
            "adb_connect_status": connect_status,
            "adb_connect_error": "OK" if connect_status == "connected" else error.value,
            "readiness_rechecked_after_connect": rechecked,
        },
    )


def _missing_device() -> ProbeResult:
    return ProbeResult.from_monotonic(
        "mumu_readiness",
        ProbeStatus.UNAVAILABLE,
        ProbeErrorCode.DEVICE_NOT_FOUND,
        time.monotonic(),
        {"step": "select_device"},
    )


def _run_start(
    adapter: MumuAdapter,
    probe: object,
    parent_seconds: float = 7200.0,
    cancel: CancellationToken | None = None,
) -> MumuRuntimeResult:
    with (
        patch.object(
            adapter,
            "status",
            return_value=_status(MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK),
        ),
        patch.object(adapter, "_run_manager_command", return_value=_manager_success()),
        patch.object(adapter, "_create_probe", return_value=probe),
    ):
        return adapter.start(Deadline.after(parent_seconds), cancel)


def test_start_timeout_does_not_inherit_long_workflow_deadline(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, start_timeout=0.08)
    probe = _NeverReadyProbe()

    started = time.monotonic()
    result = _run_start(adapter, probe)
    elapsed = time.monotonic() - started

    assert result.status == MumuRuntimeStatus.TIMEOUT
    assert result.error_code == MumuRuntimeErrorCode.START_TIMEOUT
    assert elapsed < 0.8


def test_blocked_adb_command_is_bounded_by_start_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "autogame_orchestrator.probes.mumu_readiness.probe_tcp_endpoint",
        lambda *_args: ProbeResult.ready("tcp_probe"),
    )
    adapter = _adapter(tmp_path, start_timeout=0.2)
    probe = MumuReadinessProbe(
        AdbClient(
            AdbClientConfig(
                executable=Path(sys.executable),
                base_arguments=(_FAKE_ADB, "--mode", "sleep_forever"),
                command_timeout_seconds=0.04,
            )
        )
    )

    started = time.monotonic()
    with (
        patch.object(
            adapter,
            "status",
            return_value=_status(MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK),
        ),
        patch.object(adapter, "_run_manager_command", return_value=_manager_success()),
        patch.object(adapter, "_create_probe", return_value=probe),
    ):
        result = adapter.start(Deadline.after(7200.0))
    elapsed = time.monotonic() - started

    assert result.status == MumuRuntimeStatus.TIMEOUT
    assert result.error_code == MumuRuntimeErrorCode.START_TIMEOUT
    assert result.diagnostics["probe_step"] == "adb_devices"
    assert result.diagnostics["probe_error"] == "ADB_TIMEOUT"
    assert elapsed < 2.0


def test_start_recovers_after_one_adb_devices_command_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timed-out adb process yields to the next poll inside one start budget."""
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._POLL_INTERVAL", 0.005)
    monkeypatch.setattr(
        "autogame_orchestrator.probes.mumu_readiness.probe_tcp_endpoint",
        lambda *_args: ProbeResult.ready("tcp_probe"),
    )
    state_file = tmp_path / "adb-state"
    adapter = _adapter(tmp_path, start_timeout=2.0)
    probe = MumuReadinessProbe(
        AdbClient(
            AdbClientConfig(
                executable=Path(sys.executable),
                base_arguments=(
                    _FAKE_ADB,
                    "--mode",
                    "hang_devices_once",
                    "--state-file",
                    str(state_file),
                ),
                command_timeout_seconds=0.3,
            )
        )
    )

    with (
        patch.object(
            adapter,
            "status",
            return_value=_status(MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK),
        ),
        patch.object(adapter, "_run_manager_command", return_value=_manager_success()) as manager,
        patch.object(adapter, "_create_probe", return_value=probe),
    ):
        result = adapter.start(Deadline.after(7200.0))

    assert state_file.read_text(encoding="utf-8") == "hung"
    assert result.status == MumuRuntimeStatus.STARTED
    assert result.error_code == MumuRuntimeErrorCode.OK
    assert result.changed is True
    manager.assert_called_once()


def test_start_budget_is_created_once_and_never_refreshed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._POLL_INTERVAL", 0.005)
    adapter = _adapter(tmp_path, start_timeout=0.06)
    probe = _NeverReadyProbe()

    result = _run_start(adapter, probe)

    assert result.status == MumuRuntimeStatus.TIMEOUT
    assert probe.ensure_calls >= 3
    assert len({id(item) for item in probe.deadlines}) == 1
    assert probe.remaining_seen[0] > probe.remaining_seen[-1]


def test_stop_timeout_is_bounded_independently_of_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._POLL_INTERVAL", 0.005)
    adapter = _adapter(tmp_path, stop_timeout=0.06)
    probe = _NeverReadyProbe()

    started = time.monotonic()
    with (
        patch.object(
            adapter,
            "status",
            return_value=_status(MumuRuntimeStatus.READY, MumuRuntimeErrorCode.OK),
        ),
        patch.object(adapter, "_run_manager_command", return_value=_manager_success()),
        patch.object(adapter, "_create_probe", return_value=probe),
    ):
        result = adapter.stop(Deadline.after(7200.0))
    elapsed = time.monotonic() - started

    assert result.status == MumuRuntimeStatus.TIMEOUT
    assert result.error_code == MumuRuntimeErrorCode.STOP_TIMEOUT
    assert elapsed < 0.8


def test_timeout_preserves_last_safe_probe_and_connect_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._POLL_INTERVAL", 0.005)
    adapter = _adapter(tmp_path, start_timeout=0.06)
    probe = _ConnectOnceThenMissingProbe()

    result = _run_start(adapter, probe)
    report = project_mumu(StageName.ENSURE_MUMU_RUNNING, result, ensure_running=True)
    serialized = json.dumps(dict(report.diagnostics))

    assert result.status == MumuRuntimeStatus.TIMEOUT
    assert result.diagnostics["probe_status"] == "unavailable"
    assert result.diagnostics["probe_error"] == "DEVICE_NOT_FOUND"
    assert result.diagnostics["probe_step"] == "select_device"
    assert result.diagnostics["adb_connect_attempted"] is True
    assert result.diagnostics["adb_connect_status"] == "failed"
    assert result.diagnostics["readiness_rechecked_after_connect"] is False
    assert probe.ensure_calls == 1
    assert probe.probe_calls >= 1
    for forbidden in ("serial", "stdout", "stderr", "private-serial", "private-output"):
        assert forbidden not in serialized


def test_ready_start_remains_idempotent_and_skips_manager(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    with (
        patch.object(
            adapter,
            "status",
            return_value=_status(MumuRuntimeStatus.READY, MumuRuntimeErrorCode.OK),
        ),
        patch.object(adapter, "_run_manager_command") as manager,
    ):
        result = adapter.start(Deadline.after(7200.0))

    assert result.status == MumuRuntimeStatus.STARTED
    assert result.error_code == MumuRuntimeErrorCode.OK
    assert result.changed is False
    manager.assert_not_called()


def test_cold_start_launches_manager_once_and_becomes_ready(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    probe = _ReadyProbe()
    with (
        patch.object(
            adapter,
            "status",
            return_value=_status(MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK),
        ),
        patch.object(adapter, "_run_manager_command", return_value=_manager_success()) as manager,
        patch.object(adapter, "_create_probe", return_value=probe),
    ):
        result = adapter.start(Deadline.after(7200.0))

    assert result.status == MumuRuntimeStatus.STARTED
    assert result.error_code == MumuRuntimeErrorCode.OK
    assert result.changed is True
    manager.assert_called_once()
    assert probe.ensure_calls == 1


def test_initial_not_ready_waits_without_relaunching_manager(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    probe = _ReadyProbe()
    with (
        patch.object(
            adapter,
            "status",
            return_value=_status(MumuRuntimeStatus.NOT_READY, MumuRuntimeErrorCode.READINESS_FAILED),
        ),
        patch.object(adapter, "_run_manager_command") as manager,
        patch.object(adapter, "_create_probe", return_value=probe),
    ):
        result = adapter.start(Deadline.after(7200.0))

    assert result.status == MumuRuntimeStatus.STARTED
    assert result.error_code == MumuRuntimeErrorCode.OK
    assert result.changed is False
    manager.assert_not_called()
    assert probe.ensure_calls == 1


def test_initial_adb_command_timeout_waits_without_relaunching_manager(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    probe = _ReadyProbe()
    with (
        patch.object(
            adapter,
            "status",
            return_value=_status(MumuRuntimeStatus.TIMEOUT, MumuRuntimeErrorCode.READINESS_FAILED),
        ),
        patch.object(adapter, "_run_manager_command") as manager,
        patch.object(adapter, "_create_probe", return_value=probe),
    ):
        result = adapter.start(Deadline.after(7200.0))

    assert result.status == MumuRuntimeStatus.STARTED
    assert result.error_code == MumuRuntimeErrorCode.OK
    assert result.changed is False
    manager.assert_not_called()
    assert probe.ensure_calls == 1


def test_initial_adb_command_timeout_does_not_skip_shutdown(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    probe = _StoppedProbe()
    with (
        patch.object(
            adapter,
            "status",
            return_value=_status(MumuRuntimeStatus.TIMEOUT, MumuRuntimeErrorCode.READINESS_FAILED),
        ),
        patch.object(adapter, "_run_manager_command", return_value=_manager_success()) as manager,
        patch.object(adapter, "_create_probe", return_value=probe),
    ):
        result = adapter.stop(Deadline.after(7200.0))

    assert result.status == MumuRuntimeStatus.STOPPED
    assert result.error_code == MumuRuntimeErrorCode.OK
    assert result.changed is True
    manager.assert_called_once()


def test_readiness_wait_honors_cancellation(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, start_timeout=5.0)
    probe = _NeverReadyProbe()
    cancel = CancellationToken()

    def cancel_soon() -> None:
        time.sleep(0.05)
        cancel.cancel()

    worker = threading.Thread(target=cancel_soon, daemon=True)
    worker.start()
    started = time.monotonic()
    with (
        patch.object(
            adapter,
            "status",
            return_value=_status(MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK),
        ),
        patch.object(adapter, "_run_manager_command", return_value=_manager_success()),
        patch.object(adapter, "_create_probe", return_value=probe),
    ):
        result = adapter.start(Deadline.after(7200.0), cancel)
    worker.join(timeout=1.0)
    elapsed = time.monotonic() - started

    assert result.status == MumuRuntimeStatus.CANCELLED
    assert result.error_code == MumuRuntimeErrorCode.CANCELLED
    assert elapsed < 1.0


@pytest.mark.parametrize(
    ("initial_status", "initial_error", "expected_status", "expected_error"),
    [
        (
            MumuRuntimeStatus.CANCELLED,
            MumuRuntimeErrorCode.CANCELLED,
            MumuRuntimeStatus.CANCELLED,
            MumuRuntimeErrorCode.CANCELLED,
        ),
        (
            MumuRuntimeStatus.FAILED,
            MumuRuntimeErrorCode.READINESS_FAILED,
            MumuRuntimeStatus.FAILED,
            MumuRuntimeErrorCode.READINESS_FAILED,
        ),
    ],
)
def test_start_does_not_launch_when_initial_status_is_terminal(
    tmp_path: Path,
    initial_status: MumuRuntimeStatus,
    initial_error: MumuRuntimeErrorCode,
    expected_status: MumuRuntimeStatus,
    expected_error: MumuRuntimeErrorCode,
) -> None:
    adapter = _adapter(tmp_path)
    with (
        patch.object(adapter, "status", return_value=_status(initial_status, initial_error)),
        patch.object(adapter, "_run_manager_command") as manager,
    ):
        result = adapter.start(Deadline.after(7200.0))

    assert (result.status, result.error_code) == (expected_status, expected_error)
    manager.assert_not_called()


def test_shorter_parent_deadline_takes_priority(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, start_timeout=120.0)
    probe = _NeverReadyProbe()

    started = time.monotonic()
    result = _run_start(adapter, probe, parent_seconds=0.05)
    elapsed = time.monotonic() - started

    assert result.status == MumuRuntimeStatus.TIMEOUT
    assert elapsed < 0.8
    assert probe.remaining_seen
    assert max(probe.remaining_seen) <= 0.06


def test_controlled_connect_retries_after_early_connected_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._POLL_INTERVAL", 0.002)
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._CONTROLLED_CONNECT_RETRY_INTERVAL", 0.01)
    adapter = _adapter(tmp_path, start_timeout=0.08)
    probe = _ScriptedReadinessProbe(
        (
            _connect_attempt(
                ProbeStatus.UNAVAILABLE,
                ProbeErrorCode.DEVICE_NOT_FOUND,
                step="select_device",
                connect_status="connected",
                rechecked=True,
            ),
            _connect_attempt(
                ProbeStatus.READY,
                ProbeErrorCode.OK,
                step="adb_boot_completed",
                connect_status="connected",
                rechecked=True,
            ),
        ),
        _missing_device(),
    )

    result = _run_start(adapter, probe)

    assert result.status == MumuRuntimeStatus.STARTED
    assert result.error_code == MumuRuntimeErrorCode.OK
    assert probe.connect_attempts == 2
    assert probe.ensure_calls == 2
    assert probe.ensure_probe_counts[0] == 0
    assert probe.ensure_probe_counts[1] > 0


def test_controlled_connect_failures_use_cooldown_instead_of_spam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._POLL_INTERVAL", 0.002)
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._CONTROLLED_CONNECT_RETRY_INTERVAL", 0.015)
    adapter = _adapter(tmp_path, start_timeout=0.08)
    failed = _connect_attempt(
        ProbeStatus.FAILED,
        ProbeErrorCode.ADB_CONNECT_FAILED,
        step="adb_connect",
        connect_status="failed",
        rechecked=False,
    )
    probe = _ScriptedReadinessProbe((failed,), _missing_device())

    result = _run_start(adapter, probe)

    assert result.status == MumuRuntimeStatus.TIMEOUT
    assert result.error_code == MumuRuntimeErrorCode.START_TIMEOUT
    assert probe.connect_attempts >= 2
    assert probe.connect_attempts <= 7
    assert probe.probe_calls >= probe.ensure_calls * 2


def test_established_readiness_stops_further_connect_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._POLL_INTERVAL", 0.002)
    adapter = _adapter(tmp_path, start_timeout=0.08)
    probe = _ScriptedReadinessProbe(
        (
            _connect_attempt(
                ProbeStatus.NOT_READY,
                ProbeErrorCode.ANDROID_NOT_BOOTED,
                step="adb_boot_completed",
                connect_status="connected",
                rechecked=True,
            ),
        ),
        ProbeResult.ready("mumu_readiness"),
    )

    result = _run_start(adapter, probe)

    assert result.status == MumuRuntimeStatus.STARTED
    assert probe.connect_attempts == 1
    assert probe.ensure_calls == 1
    assert probe.probe_calls == 1


@pytest.mark.parametrize(
    ("status", "error", "step"),
    [
        (ProbeStatus.NOT_READY, ProbeErrorCode.DEVICE_OFFLINE, "adb_get_state"),
        (ProbeStatus.NOT_READY, ProbeErrorCode.ANDROID_NOT_BOOTED, "adb_boot_completed"),
        (ProbeStatus.TIMEOUT, ProbeErrorCode.ADB_TIMEOUT, "adb_devices"),
        (ProbeStatus.UNAVAILABLE, ProbeErrorCode.PORT_CLOSED, "tcp_probe"),
    ],
)
def test_noneligible_states_do_not_schedule_controlled_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: ProbeStatus,
    error: ProbeErrorCode,
    step: str,
) -> None:
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._POLL_INTERVAL", 0.002)
    adapter = _adapter(tmp_path, start_timeout=0.02)
    noneligible = ProbeResult.from_monotonic(
        "mumu_readiness",
        status,
        error,
        time.monotonic(),
        {
            "step": step,
            "adb_connect_attempted": False,
            "adb_connect_status": "not_attempted",
            "adb_connect_error": "none",
            "readiness_rechecked_after_connect": False,
        },
    )
    probe = _ScriptedReadinessProbe((noneligible,), noneligible)

    result = _run_start(adapter, probe)

    assert result.status == MumuRuntimeStatus.TIMEOUT
    assert probe.connect_attempts == 0


def test_connect_retry_stays_within_start_operation_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._POLL_INTERVAL", 0.002)
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._CONTROLLED_CONNECT_RETRY_INTERVAL", 0.005)
    adapter = _adapter(tmp_path, start_timeout=0.06)
    failed = _connect_attempt(
        ProbeStatus.FAILED,
        ProbeErrorCode.ADB_CONNECT_FAILED,
        step="adb_connect",
        connect_status="failed",
        rechecked=False,
    )
    probe = _ScriptedReadinessProbe((failed,), _missing_device())

    started = time.monotonic()
    result = _run_start(adapter, probe, parent_seconds=7200.0)
    elapsed = time.monotonic() - started

    assert result.status == MumuRuntimeStatus.TIMEOUT
    assert result.error_code == MumuRuntimeErrorCode.START_TIMEOUT
    assert elapsed < 0.8


def test_connect_retry_honors_cancellation_during_cooldown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._POLL_INTERVAL", 0.002)
    monkeypatch.setattr("autogame_orchestrator.runtime.mumu._CONTROLLED_CONNECT_RETRY_INTERVAL", 1.0)
    adapter = _adapter(tmp_path, start_timeout=5.0)
    failed = _connect_attempt(
        ProbeStatus.FAILED,
        ProbeErrorCode.ADB_CONNECT_FAILED,
        step="adb_connect",
        connect_status="failed",
        rechecked=False,
    )
    probe = _ScriptedReadinessProbe((failed,), _missing_device())
    cancel = CancellationToken()

    def cancel_soon() -> None:
        time.sleep(0.03)
        cancel.cancel()

    worker = threading.Thread(target=cancel_soon, daemon=True)
    worker.start()
    started = time.monotonic()
    result = _run_start(adapter, probe, cancel=cancel)
    worker.join(timeout=1.0)
    elapsed = time.monotonic() - started

    assert result.status == MumuRuntimeStatus.CANCELLED
    assert result.error_code == MumuRuntimeErrorCode.CANCELLED
    assert elapsed < 0.8
