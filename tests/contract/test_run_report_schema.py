"""Contract tests for RunReport v1 JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

from autogame_orchestrator.reporter import validate_run_report_json

_GOLDEN = Path(__file__).resolve().parent.parent.parent / "schemas" / "golden" / "run-report-v1.golden.json"


def test_golden_sample_validates(golden_path: Path) -> None:
    data = json.loads(golden_path.read_text(encoding="utf-8"))
    valid, msg = validate_run_report_json(data)
    assert valid, f"golden sample must pass: {msg}"


def test_missing_run_id_fails() -> None:
    data = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    del data["run_id"]
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_wrong_schema_version_fails() -> None:
    data = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    data["schema_version"] = 2
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_bad_stage_fails() -> None:
    data = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    data["stages"].append({"stage": "garbage", "outcome": "success", "error_code": "OK"})
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_additional_properties_fails() -> None:
    data = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    data["extra_field"] = "should not be here"
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_valid_iso8601_datetime_accepted() -> None:
    data = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    valid, msg = validate_run_report_json(data)
    assert valid, f"golden datetime must pass: {msg}"


def test_not_a_date_datetime_rejected() -> None:
    data = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    data["started_at"] = "not-a-date"
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_no_t_separator_datetime_rejected() -> None:
    data = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    data["started_at"] = "2026-07-21 08:30:00"
    valid, _ = validate_run_report_json(data)
    assert not valid


def test_invalid_calendar_date_rejected() -> None:
    data = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    data["started_at"] = "2026-13-40T25:61:61+00:00"
    valid, _ = validate_run_report_json(data)
    assert not valid
