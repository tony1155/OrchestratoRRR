"""Unit tests for core data models."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from autogame_orchestrator.models import (
    ErrorCode,
    OutcomeKind,
    RunReport,
    RunStatus,
    StageName,
    StageReport,
    is_json_serializable,
)

_NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
_LATER = _NOW + timedelta(seconds=1)


# ── ErrorCode ──────────────────────────────────────────────────


def test_error_code_ok_is_ok() -> None:
    assert ErrorCode.OK.value == "OK"


def test_error_code_serializable() -> None:
    assert json.dumps(ErrorCode.CONFIG_FILE_NOT_FOUND.value) == '"CONFIG_FILE_NOT_FOUND"'


# ── StageReport ────────────────────────────────────────────────


def test_stage_report_success_requires_ok() -> None:
    with pytest.raises(ValueError, match="SUCCESS"):
        StageReport(
            stage=StageName.VALIDATE_CONFIG,
            outcome=OutcomeKind.SUCCESS,
            error_code=ErrorCode.CONFIG_FILE_NOT_FOUND,
            started_at=_NOW,
            finished_at=_LATER,
            duration_ms=1000,
        )


def test_stage_report_failure_must_not_use_ok() -> None:
    with pytest.raises(ValueError, match="non-SUCCESS"):
        StageReport(
            stage=StageName.VALIDATE_CONFIG,
            outcome=OutcomeKind.FAILURE,
            error_code=ErrorCode.OK,
            started_at=_NOW,
            finished_at=_LATER,
            duration_ms=1000,
        )


def test_stage_report_skipped_with_ok_rejected() -> None:
    with pytest.raises(ValueError, match="non-SUCCESS"):
        StageReport(
            stage=StageName.RUN_MAA,
            outcome=OutcomeKind.SKIPPED,
            error_code=ErrorCode.OK,
            started_at=_NOW,
            finished_at=_LATER,
            duration_ms=0,
            message="Skipped.",
        )


def test_stage_report_skipped_with_skipped_accepted() -> None:
    report = StageReport(
        stage=StageName.RUN_MAA,
        outcome=OutcomeKind.SKIPPED,
        error_code=ErrorCode.SKIPPED,
        started_at=_NOW,
        finished_at=_LATER,
        duration_ms=0,
        message="Skipped.",
    )
    assert report.error_code == ErrorCode.SKIPPED


def test_stage_report_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        StageReport(
            stage=StageName.VALIDATE_CONFIG,
            outcome=OutcomeKind.SUCCESS,
            error_code=ErrorCode.OK,
            started_at=datetime(2026, 7, 21, 12, 0, 0),
            finished_at=_LATER,
            duration_ms=0,
        )


def test_stage_report_rejects_finished_before_started() -> None:
    with pytest.raises(ValueError, match="finished_at.*>=.*started_at"):
        StageReport(
            stage=StageName.VALIDATE_CONFIG,
            outcome=OutcomeKind.SUCCESS,
            error_code=ErrorCode.OK,
            started_at=_LATER,
            finished_at=_NOW,
            duration_ms=0,
        )


def test_stage_report_rejects_negative_duration() -> None:
    with pytest.raises(ValueError, match="duration_ms must be >= 0"):
        StageReport(
            stage=StageName.VALIDATE_CONFIG,
            outcome=OutcomeKind.SUCCESS,
            error_code=ErrorCode.OK,
            started_at=_NOW,
            finished_at=_LATER,
            duration_ms=-1,
        )


def test_stage_report_rejects_non_json_diagnostics() -> None:
    with pytest.raises(ValueError, match="JSON-serializable"):

        class _Unserializable:
            pass

        StageReport(
            stage=StageName.VALIDATE_CONFIG,
            outcome=OutcomeKind.SUCCESS,
            error_code=ErrorCode.OK,
            started_at=_NOW,
            finished_at=_LATER,
            duration_ms=0,
            diagnostics={"bad": _Unserializable()},  # type: ignore[dict-item]
        )


def test_stage_report_to_json_encodable() -> None:
    report = StageReport(
        stage=StageName.VALIDATE_CONFIG,
        outcome=OutcomeKind.SUCCESS,
        error_code=ErrorCode.OK,
        started_at=_NOW,
        finished_at=_LATER,
        duration_ms=1000,
        message="OK",
    )
    d = report.to_json_encodable()
    assert d["stage"] == "validate_config"
    assert d["outcome"] == "success"
    assert d["duration_ms"] == 1000


# ── RunReport ──────────────────────────────────────────────────


def _valid_stage() -> StageReport:
    return StageReport(
        stage=StageName.VALIDATE_CONFIG,
        outcome=OutcomeKind.SUCCESS,
        error_code=ErrorCode.OK,
        started_at=_NOW,
        finished_at=_LATER,
        duration_ms=500,
    )


def test_run_report_success_requires_ok() -> None:
    with pytest.raises(ValueError, match="SUCCESS status requires"):
        RunReport(
            schema_version=1,
            run_id=str(uuid.uuid4()),
            orchestrator_version="0.1.0",
            mode="test",
            status=RunStatus.SUCCESS,
            error_code=ErrorCode.CONFIG_FILE_NOT_FOUND,
            started_at=_NOW,
            finished_at=_LATER,
            duration_ms=0,
        )


def test_run_report_failure_must_not_use_ok() -> None:
    with pytest.raises(ValueError, match="non-SUCCESS status"):
        RunReport(
            schema_version=1,
            run_id=str(uuid.uuid4()),
            orchestrator_version="0.1.0",
            mode="test",
            status=RunStatus.FAILURE,
            error_code=ErrorCode.OK,
            started_at=_NOW,
            finished_at=_LATER,
            duration_ms=0,
        )


def test_run_report_rejects_invalid_uuid() -> None:
    with pytest.raises(ValueError, match="valid UUID"):
        RunReport(
            schema_version=1,
            run_id="not-a-uuid",
            orchestrator_version="0.1.0",
            mode="test",
            status=RunStatus.SUCCESS,
            error_code=ErrorCode.OK,
            started_at=_NOW,
            finished_at=_LATER,
            duration_ms=0,
        )


def test_run_report_rejects_wrong_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version must be 1"):
        RunReport(
            schema_version=2,
            run_id=str(uuid.uuid4()),
            orchestrator_version="0.1.0",
            mode="test",
            status=RunStatus.SUCCESS,
            error_code=ErrorCode.OK,
            started_at=_NOW,
            finished_at=_LATER,
            duration_ms=0,
        )


def test_run_report_rejects_duplicate_stages() -> None:
    s1 = StageReport(
        stage=StageName.VALIDATE_CONFIG,
        outcome=OutcomeKind.SUCCESS,
        error_code=ErrorCode.OK,
        started_at=_NOW,
        finished_at=_LATER,
        duration_ms=50,
    )
    s2 = StageReport(
        stage=StageName.VALIDATE_CONFIG,
        outcome=OutcomeKind.SUCCESS,
        error_code=ErrorCode.OK,
        started_at=_NOW,
        finished_at=_LATER,
        duration_ms=60,
    )
    with pytest.raises(ValueError, match="duplicate stage"):
        RunReport(
            schema_version=1,
            run_id=str(uuid.uuid4()),
            orchestrator_version="0.1.0",
            mode="test",
            status=RunStatus.SUCCESS,
            error_code=ErrorCode.OK,
            started_at=_NOW,
            finished_at=_LATER,
            duration_ms=0,
            stages=(s1, s2),
        )


def test_run_report_serialization_roundtrip() -> None:
    rid = str(uuid.uuid4())
    report = RunReport(
        schema_version=1,
        run_id=rid,
        orchestrator_version="0.1.0",
        mode="validate",
        status=RunStatus.SUCCESS,
        error_code=ErrorCode.OK,
        started_at=_NOW,
        finished_at=_LATER,
        duration_ms=1000,
        stages=(_valid_stage(),),
    )
    json_str = report.to_json()
    parsed = json.loads(json_str)
    assert parsed["schema_version"] == 1
    assert parsed["run_id"] == rid
    assert parsed["status"] == "success"
    assert len(parsed["stages"]) == 1


# ── is_json_serializable ──────────────────────────────────────


def test_is_json_serializable_primitives() -> None:
    assert is_json_serializable("hello")
    assert is_json_serializable(42)
    assert is_json_serializable(3.14)
    assert is_json_serializable(True)
    assert is_json_serializable(None)


def test_is_json_serializable_list() -> None:
    assert is_json_serializable([1, "a", None])


def test_is_json_serializable_nested() -> None:
    assert is_json_serializable({"key": [1, {"nested": True}]})


def test_is_json_serializable_rejects_bytes() -> None:
    assert not is_json_serializable(b"bytes")


def test_is_json_serializable_rejects_object() -> None:
    class Foo:
        pass

    assert not is_json_serializable(Foo())


def test_is_json_serializable_dict_with_int_key() -> None:
    assert not is_json_serializable({1: "value"})
