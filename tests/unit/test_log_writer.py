"""Unit tests for JSONL log writer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autogame_orchestrator.log_writer import JsonlLogWriter, LogWriteError


def test_single_record_is_valid_json(tmp_workdir: Path) -> None:
    log_path = tmp_workdir / "test.jsonl"
    with JsonlLogWriter(log_path, "run-1") as writer:
        writer.info("test.event", "Hello world")

    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["level"] == "INFO"
    assert record["event"] == "test.event"
    assert record["run_id"] == "run-1"
    assert record["message"] == "Hello world"
    assert "timestamp" in record
    assert "details" in record


def test_multiple_records_are_separate_lines(tmp_workdir: Path) -> None:
    log_path = tmp_workdir / "test.jsonl"
    with JsonlLogWriter(log_path, "run-2") as writer:
        writer.info("a", "one")
        writer.warning("b", "two")
        writer.error("c", "three")

    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3
    assert all(json.loads(line) for line in lines)


def test_timestamp_has_timezone(tmp_workdir: Path) -> None:
    log_path = tmp_workdir / "test.jsonl"
    with JsonlLogWriter(log_path, "run-3") as writer:
        writer.info("x", "y")

    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    record = json.loads(lines[0])
    ts = record["timestamp"]
    assert "+" in ts or "Z" in ts


def test_file_is_complete_after_close(tmp_workdir: Path) -> None:
    log_path = tmp_workdir / "test.jsonl"
    writer = JsonlLogWriter(log_path, "run-4")
    writer.__enter__()
    writer.info("pre", "before close")
    writer.__exit__(None, None, None)

    content = log_path.read_text(encoding="utf-8")
    assert content.endswith("\n")
    lines = content.strip().split("\n")
    assert len(lines) == 1


def test_non_serializable_details_rejected(tmp_workdir: Path) -> None:
    log_path = tmp_workdir / "test.jsonl"

    class _Bad:
        pass

    with pytest.raises(LogWriteError, match="JSON-serializable"):
        with JsonlLogWriter(log_path, "run-5") as writer:
            writer.info("ev", "msg", {"bad": _Bad()})  # type: ignore[dict-item]


def test_write_failure_maps_to_log_write_error(tmp_workdir: Path) -> None:
    log_path = tmp_workdir / "subdir" / "test.jsonl"
    # Create a FILE at 'subdir' to prevent mkdir from creating it as a directory
    (tmp_workdir / "subdir").write_text("not-a-dir", encoding="utf-8")

    with pytest.raises(LogWriteError, match="Failed to open"):
        with JsonlLogWriter(log_path, "run-6"):
            pass


def test_close_cleans_up_handle(tmp_workdir: Path) -> None:
    log_path = tmp_workdir / "test.jsonl"
    writer = JsonlLogWriter(log_path, "run-7")
    writer.__enter__()
    assert writer._fh is not None
    writer.__exit__(None, None, None)
    assert writer._fh is None


def test_details_preserves_order(tmp_workdir: Path) -> None:
    log_path = tmp_workdir / "test.jsonl"
    with JsonlLogWriter(log_path, "run-8") as writer:
        writer.info("e1", "first", {"a": 1})
        writer.info("e2", "second", {"b": 2})

    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    r1 = json.loads(lines[0])
    r2 = json.loads(lines[1])
    assert r1["details"]["a"] == 1
    assert r2["details"]["b"] == 2
