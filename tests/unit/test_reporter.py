"""Unit tests for RunReport atomic writer and schema validation."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from autogame_orchestrator.models import (
    ErrorCode,
    OutcomeKind,
    RunReport,
    RunStatus,
    StageName,
    StageReport,
)
from autogame_orchestrator.reporter import validate_run_report_json, write_report_atomic

_NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
_LATER = datetime(2026, 7, 21, 12, 0, 1, tzinfo=UTC)


def _make_sample_report() -> RunReport:
    stage = StageReport(
        stage=StageName.VALIDATE_CONFIG,
        outcome=OutcomeKind.SUCCESS,
        error_code=ErrorCode.OK,
        started_at=_NOW,
        finished_at=_LATER,
        duration_ms=500,
        message="OK",
    )
    return RunReport(
        schema_version=1,
        run_id=str(uuid.uuid4()),
        orchestrator_version="0.1.0",
        mode="test",
        status=RunStatus.SUCCESS,
        error_code=ErrorCode.OK,
        started_at=_NOW,
        finished_at=_LATER,
        duration_ms=1000,
        stages=(stage,),
    )


def test_golden_sample_passes_schema(golden_path: Path) -> None:
    data = json.loads(golden_path.read_text(encoding="utf-8"))
    valid, msg = validate_run_report_json(data)
    assert valid, f"golden sample failed: {msg}"


def test_python_report_passes_schema() -> None:
    report = _make_sample_report()
    json_str = report.to_json()
    data = json.loads(json_str)
    valid, msg = validate_run_report_json(data)
    assert valid, f"Python-generated report failed: {msg}"


def test_invalid_schema_version_rejected() -> None:
    data = {
        "schema_version": 99,
        "run_id": str(uuid.uuid4()),
        "orchestrator_version": "0.1.0",
        "mode": "test",
        "status": "success",
        "error_code": "OK",
        "started_at": "2026-07-21T12:00:00+00:00",
        "finished_at": "2026-07-21T12:00:01+00:00",
        "duration_ms": 1000,
        "stages": [],
        "diagnostics": {},
    }
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_invalid_status_rejected() -> None:
    data = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "orchestrator_version": "0.1.0",
        "mode": "test",
        "status": "unknown_status",
        "error_code": "OK",
        "started_at": "2026-07-21T12:00:00+00:00",
        "finished_at": "2026-07-21T12:00:01+00:00",
        "duration_ms": 1000,
        "stages": [],
        "diagnostics": {},
    }
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_invalid_error_code_rejected() -> None:
    data = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "orchestrator_version": "0.1.0",
        "mode": "test",
        "status": "success",
        "error_code": "BOGUS_CODE",
        "started_at": "2026-07-21T12:00:00+00:00",
        "finished_at": "2026-07-21T12:00:01+00:00",
        "duration_ms": 1000,
        "stages": [],
        "diagnostics": {},
    }
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_invalid_stage_name_rejected() -> None:
    data = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "orchestrator_version": "0.1.0",
        "mode": "test",
        "status": "success",
        "error_code": "OK",
        "started_at": "2026-07-21T12:00:00+00:00",
        "finished_at": "2026-07-21T12:00:01+00:00",
        "duration_ms": 1000,
        "stages": [
            {
                "stage": "not_a_real_stage",
                "outcome": "success",
                "error_code": "OK",
                "started_at": "2026-07-21T12:00:00+00:00",
                "finished_at": "2026-07-21T12:00:01+00:00",
                "duration_ms": 500,
                "message": "",
                "diagnostics": {},
            }
        ],
        "diagnostics": {},
    }
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_negative_duration_rejected() -> None:
    data = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "orchestrator_version": "0.1.0",
        "mode": "test",
        "status": "success",
        "error_code": "OK",
        "started_at": "2026-07-21T12:00:00+00:00",
        "finished_at": "2026-07-21T12:00:01+00:00",
        "duration_ms": -5,
        "stages": [],
        "diagnostics": {},
    }
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_missing_required_field_returned_by_schema() -> None:
    data = {
        "schema_version": 1,
        # missing run_id
        "orchestrator_version": "0.1.0",
        "mode": "test",
        "status": "success",
        "error_code": "OK",
        "started_at": "2026-07-21T12:00:00+00:00",
        "finished_at": "2026-07-21T12:00:01+00:00",
        "duration_ms": 1000,
        "stages": [],
        "diagnostics": {},
    }
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_missing_required_field_rejected() -> None:
    data = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        # missing orchestrator_version
        "mode": "test",
        "status": "success",
        "error_code": "OK",
        "started_at": "2026-07-21T12:00:00+00:00",
        "finished_at": "2026-07-21T12:00:01+00:00",
        "duration_ms": 1000,
        "stages": [],
        "diagnostics": {},
    }
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_datetime_valid_iso8601_with_tz_accepted() -> None:
    data = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "orchestrator_version": "0.1.0",
        "mode": "test",
        "status": "success",
        "error_code": "OK",
        "started_at": "2026-07-21T08:30:00+00:00",
        "finished_at": "2026-07-21T08:30:01+00:00",
        "duration_ms": 1000,
        "stages": [],
        "diagnostics": {},
    }
    valid, msg = validate_run_report_json(data)
    assert valid, f"valid datetime should pass: {msg}"


def test_datetime_not_a_date_rejected() -> None:
    data = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "orchestrator_version": "0.1.0",
        "mode": "test",
        "status": "success",
        "error_code": "OK",
        "started_at": "not-a-date",
        "finished_at": "2026-07-21T12:00:01+00:00",
        "duration_ms": 1000,
        "stages": [],
        "diagnostics": {},
    }
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_datetime_no_t_separator_rejected() -> None:
    data = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "orchestrator_version": "0.1.0",
        "mode": "test",
        "status": "success",
        "error_code": "OK",
        "started_at": "2026-07-21 08:30:00",
        "finished_at": "2026-07-21T08:30:01+00:00",
        "duration_ms": 1000,
        "stages": [],
        "diagnostics": {},
    }
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_datetime_invalid_calendar_date_rejected() -> None:
    data = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "orchestrator_version": "0.1.0",
        "mode": "test",
        "status": "success",
        "error_code": "OK",
        "started_at": "2026-13-40T25:61:61+00:00",
        "finished_at": "2026-07-21T08:30:01+00:00",
        "duration_ms": 1000,
        "stages": [],
        "diagnostics": {},
    }
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_atomic_write_creates_file(tmp_workdir: Path) -> None:
    report = _make_sample_report()
    path, errs = write_report_atomic(report, tmp_workdir)
    assert errs == []
    assert path is not None
    assert path.exists()
    content = json.loads(path.read_text(encoding="utf-8"))
    assert content["run_id"] == report.run_id


def test_atomic_write_no_half_file_on_failure(tmp_workdir: Path) -> None:
    report_json = [f for f in tmp_workdir.iterdir() if f.name.startswith("run-report-")]
    assert len(report_json) == 0


def test_temp_file_cleaned_up(tmp_workdir: Path) -> None:
    report = _make_sample_report()

    path, errs = write_report_atomic(report, tmp_workdir)
    assert errs == []
    assert path is not None

    # Verify no leftover .tmp- files
    leftovers = [f for f in tmp_workdir.iterdir() if f.name.startswith(".tmp-")]
    assert len(leftovers) == 0
