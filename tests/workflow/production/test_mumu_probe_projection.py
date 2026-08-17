"""MuMu probe 分类的生产白名单投影和隐私测试。"""

from __future__ import annotations

import json
import time

import pytest

from autogame_orchestrator.models import JsonValue, StageName
from autogame_orchestrator.runtime.models import (
    MumuAction,
    MumuRuntimeErrorCode,
    MumuRuntimeResult,
    MumuRuntimeStatus,
)
from autogame_orchestrator.workflow.production.projection import project_mumu


def _result(diagnostics: dict[str, JsonValue]) -> MumuRuntimeResult:
    return MumuRuntimeResult.from_monotonic(
        MumuAction.STATUS,
        MumuRuntimeStatus.NOT_READY,
        MumuRuntimeErrorCode.READINESS_FAILED,
        time.monotonic(),
        changed=False,
        diagnostics=diagnostics,
    )


def test_probe_classification_is_safely_projected() -> None:
    report = project_mumu(
        StageName.ENSURE_MUMU_RUNNING,
        _result(
            {
                "probe_status": "failed",
                "probe_error": "ADB_OUTPUT_INVALID",
                "probe_step": "adb_devices",
            }
        ),
    )
    assert report.diagnostics["probe_status"] == "failed"
    assert report.diagnostics["probe_error"] == "ADB_OUTPUT_INVALID"
    assert report.diagnostics["probe_step"] == "adb_devices"
    json.dumps(dict(report.diagnostics))


@pytest.mark.parametrize(
    "forbidden",
    [
        "serial",
        "host",
        "port",
        "detail",
        "stdout",
        "stderr",
        "output",
        "command",
        "executable",
        "exception",
    ],
)
def test_sensitive_runtime_diagnostic_is_not_projected(forbidden: str) -> None:
    report = project_mumu(
        StageName.ENSURE_MUMU_RUNNING,
        _result(
            {
                "probe_status": "failed",
                "probe_error": "ADB_OUTPUT_INVALID",
                "probe_step": "adb_devices",
                forbidden: "private-value",
            }
        ),
    )
    assert forbidden not in report.diagnostics
    assert "private-value" not in json.dumps(dict(report.diagnostics))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("probe_status", "private-status"),
        ("probe_error", "private-error"),
        ("probe_step", "private-step"),
    ],
)
def test_non_allowlisted_probe_value_is_not_projected(key: str, value: str) -> None:
    report = project_mumu(StageName.ENSURE_MUMU_RUNNING, _result({key: value}))
    assert key not in report.diagnostics


def test_connect_projection_keeps_only_fixed_fields() -> None:
    report = project_mumu(
        StageName.ENSURE_MUMU_RUNNING,
        _result(
            {
                "probe_status": "failed",
                "probe_error": "ADB_CONNECT_FAILED",
                "probe_step": "adb_connect",
                "adb_connect_attempted": True,
                "adb_connect_status": "failed",
                "adb_connect_error": "ADB_CONNECT_FAILED",
                "readiness_rechecked_after_connect": False,
                "serial": "private-serial",
                "host": "private-host",
                "port": 16384,
                "stdout": "private-stdout",
                "stderr": "private-stderr",
            }
        ),
    )
    assert report.diagnostics == {
        "source_error_code": "READINESS_FAILED",
        "action": "status",
        "changed": False,
        "lifecycle_mode": "managed",
        "probe_status": "failed",
        "probe_error": "ADB_CONNECT_FAILED",
        "probe_step": "adb_connect",
        "adb_connect_attempted": True,
        "adb_connect_status": "failed",
        "adb_connect_error": "ADB_CONNECT_FAILED",
        "readiness_rechecked_after_connect": False,
    }


def test_offline_recovery_projection_keeps_only_bounded_safe_fields() -> None:
    report = project_mumu(
        StageName.ENSURE_MUMU_RUNNING,
        _result(
            {
                "probe_status": "not_ready",
                "probe_error": "DEVICE_OFFLINE",
                "probe_step": "select_device",
                "offline_recovery_attempted": True,
                "offline_recovery_count": 1,
                "offline_recovery_status": "completed",
                "offline_endpoint_recovery_attempted": True,
                "offline_endpoint_recovery_count": 2,
                "offline_endpoint_recovery_status": "connected",
                "offline_endpoint_disconnect_status": "disconnected",
                "offline_endpoint_connect_status": "connected",
                "serial": "private-serial",
                "stdout": "private-stdout",
                "stderr": "private-stderr",
            }
        ),
    )

    assert report.diagnostics == {
        "source_error_code": "READINESS_FAILED",
        "action": "status",
        "changed": False,
        "lifecycle_mode": "managed",
        "probe_status": "not_ready",
        "probe_error": "DEVICE_OFFLINE",
        "probe_step": "select_device",
        "offline_recovery_attempted": True,
        "offline_recovery_count": 1,
        "offline_recovery_status": "completed",
        "offline_endpoint_recovery_attempted": True,
        "offline_endpoint_recovery_count": 2,
        "offline_endpoint_recovery_status": "connected",
        "offline_endpoint_disconnect_status": "disconnected",
        "offline_endpoint_connect_status": "connected",
    }
