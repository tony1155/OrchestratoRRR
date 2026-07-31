"""MuMu status 的固定 probe 分类与状态映射测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from autogame_orchestrator.probes.models import ProbeErrorCode, ProbeResult, ProbeStatus
from autogame_orchestrator.process import Deadline
from autogame_orchestrator.runtime.models import MumuRuntimeErrorCode, MumuRuntimeStatus
from autogame_orchestrator.runtime.mumu import MumuAdapter


class _FixedProbe:
    def __init__(self, result: ProbeResult) -> None:
        self.result = result

    def probe(self, *_args: object, **_kwargs: object) -> ProbeResult:
        return self.result


class _FixedEnsureProbe:
    def __init__(self, result: ProbeResult) -> None:
        self.result = result

    def ensure_ready(self, *_args: object, **_kwargs: object) -> ProbeResult:
        return self.result


def _adapter() -> MumuAdapter:
    return MumuAdapter(
        Path("manager-placeholder"),
        (),
        (),
        Path("adb-placeholder"),
        "serial-placeholder",
        adb_port=1,
    )


@pytest.mark.parametrize(
    ("probe_status", "probe_error", "step", "runtime_status", "runtime_error"),
    [
        (ProbeStatus.READY, ProbeErrorCode.OK, None, MumuRuntimeStatus.READY, MumuRuntimeErrorCode.OK),
        (
            ProbeStatus.UNAVAILABLE,
            ProbeErrorCode.PORT_CLOSED,
            "tcp_probe",
            MumuRuntimeStatus.STOPPED,
            MumuRuntimeErrorCode.OK,
        ),
        (
            ProbeStatus.TIMEOUT,
            ProbeErrorCode.ADB_TIMEOUT,
            "adb_devices",
            MumuRuntimeStatus.TIMEOUT,
            MumuRuntimeErrorCode.READINESS_FAILED,
        ),
        (
            ProbeStatus.FAILED,
            ProbeErrorCode.ADB_CANCELLED,
            None,
            MumuRuntimeStatus.CANCELLED,
            MumuRuntimeErrorCode.CANCELLED,
        ),
        (
            ProbeStatus.FAILED,
            ProbeErrorCode.ADB_OUTPUT_INVALID,
            "adb_devices",
            MumuRuntimeStatus.NOT_READY,
            MumuRuntimeErrorCode.READINESS_FAILED,
        ),
    ],
)
def test_status_preserves_mapping_and_safe_probe_classification(
    probe_status: ProbeStatus,
    probe_error: ProbeErrorCode,
    step: str | None,
    runtime_status: MumuRuntimeStatus,
    runtime_error: MumuRuntimeErrorCode,
) -> None:
    diagnostics = {} if step is None else {"step": step, "detail": "private-value"}
    result = ProbeResult.from_monotonic(
        "mumu_readiness",
        probe_status,
        probe_error,
        0.0,
        diagnostics,
    )
    adapter = _adapter()
    with patch.object(adapter, "_create_probe", return_value=_FixedProbe(result)):
        runtime = adapter.status(Deadline.after(5))
    assert (runtime.status, runtime.error_code) == (runtime_status, runtime_error)
    assert runtime.diagnostics == {
        "probe_status": probe_status.value,
        "probe_error": probe_error.value,
        "probe_step": step or "none",
    }


def test_unknown_probe_step_is_replaced_with_none() -> None:
    result = ProbeResult.from_monotonic(
        "mumu_readiness",
        ProbeStatus.FAILED,
        ProbeErrorCode.ADB_OUTPUT_INVALID,
        0.0,
        {"step": "private-step", "serial": "private-value"},
    )
    adapter = _adapter()
    with patch.object(adapter, "_create_probe", return_value=_FixedProbe(result)):
        runtime = adapter.status(Deadline.after(5))
    assert runtime.diagnostics["probe_step"] == "none"
    assert "serial" not in runtime.diagnostics


def test_external_ensure_projects_only_fixed_connect_fields() -> None:
    result = ProbeResult.from_monotonic(
        "mumu_readiness",
        ProbeStatus.NOT_READY,
        ProbeErrorCode.ADB_CONNECT_FAILED,
        0.0,
        {
            "step": "adb_connect",
            "serial": "private-value",
            "host": "private-host",
            "port": 16384,
            "stdout_trimmed": "private-output",
            "adb_connect_attempted": True,
            "adb_connect_status": "failed",
            "adb_connect_error": "ADB_CONNECT_FAILED",
            "readiness_rechecked_after_connect": False,
        },
    )
    adapter = _adapter()
    with patch.object(adapter, "_create_probe", return_value=_FixedEnsureProbe(result)):
        runtime = adapter.ensure_external_ready(Deadline.after(5))
    assert runtime.status == MumuRuntimeStatus.NOT_READY
    assert runtime.error_code == MumuRuntimeErrorCode.READINESS_FAILED
    assert runtime.diagnostics == {
        "probe_status": "not_ready",
        "probe_error": "ADB_CONNECT_FAILED",
        "probe_step": "adb_connect",
        "adb_connect_attempted": True,
        "adb_connect_status": "failed",
        "adb_connect_error": "ADB_CONNECT_FAILED",
        "readiness_rechecked_after_connect": False,
    }
