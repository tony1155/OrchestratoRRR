from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from autogame_orchestrator.entry_runtime import EntryRuntime, EntryRuntimeKind, detect_entry_runtime


def test_missing_frozen_marker_detects_source(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.chdir(tmp_path)

    runtime = detect_entry_runtime()

    assert runtime.kind is EntryRuntimeKind.SOURCE
    assert runtime.executable == tmp_path / "python.exe"
    assert runtime.working_directory == tmp_path


def test_false_frozen_marker_detects_source(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))

    assert detect_entry_runtime().kind is EntryRuntimeKind.SOURCE


def test_true_frozen_marker_detects_frozen(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "OrchestratoRRR.exe"))
    monkeypatch.chdir(tmp_path)

    runtime = detect_entry_runtime()

    assert runtime.kind is EntryRuntimeKind.FROZEN
    assert runtime.executable == tmp_path / "OrchestratoRRR.exe"
    assert runtime.working_directory == tmp_path


@pytest.mark.parametrize(
    ("marker", "expected"),
    [(0, EntryRuntimeKind.SOURCE), (1, EntryRuntimeKind.FROZEN), ("yes", EntryRuntimeKind.FROZEN)],
)
def test_non_boolean_frozen_marker_uses_bool_contract(
    monkeypatch, tmp_path: Path, marker: object, expected: EntryRuntimeKind
) -> None:
    monkeypatch.setattr(sys, "frozen", marker, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "entry.exe"))

    assert detect_entry_runtime().kind is expected


def test_detection_ignores_packager_private_marker(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    private_marker = "_" + "MEIPASS"
    monkeypatch.setattr(sys, private_marker, str(tmp_path / "private"), raising=False)

    assert detect_entry_runtime().kind is EntryRuntimeKind.SOURCE


def test_detection_reads_process_values_each_time(monkeypatch, tmp_path: Path) -> None:
    first_directory = tmp_path / "first"
    second_directory = tmp_path / "second"
    first_directory.mkdir()
    second_directory.mkdir()
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "executable", str(first_directory / "python.exe"))
    monkeypatch.chdir(first_directory)
    first = detect_entry_runtime()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(second_directory / "OrchestratoRRR.exe"))
    monkeypatch.chdir(second_directory)
    second = detect_entry_runtime()

    assert first.kind is EntryRuntimeKind.SOURCE
    assert second.kind is EntryRuntimeKind.FROZEN
    assert second.executable == second_directory / "OrchestratoRRR.exe"
    assert second.working_directory == second_directory


def test_entry_runtime_is_immutable(tmp_path: Path) -> None:
    runtime = EntryRuntime(EntryRuntimeKind.SOURCE, tmp_path / "python.exe", tmp_path)

    with pytest.raises(FrozenInstanceError):
        runtime.kind = EntryRuntimeKind.FROZEN  # type: ignore[misc]
