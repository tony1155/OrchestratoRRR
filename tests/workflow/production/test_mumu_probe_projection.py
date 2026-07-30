"""MuMu probe 分类的生产白名单投影和隐私测试。"""

from __future__ import annotations

import json
import time

import pytest

from autogame_orchestrator.models import StageName
from autogame_orchestrator.runtime.models import (
    MumuAction,
    MumuRuntimeErrorCode,
    MumuRuntimeResult,
    MumuRuntimeStatus,
)
from autogame_orchestrator.workflow.production.projection import project_mumu


def _result(diagnostics: dict[str, object]) -> MumuRuntimeResult:
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
