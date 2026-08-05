"""Tests for deterministic source and frozen resource locations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import autogame_orchestrator.resource_paths as resource_paths
from autogame_orchestrator.resource_paths import RunReportSchemaResourceError


def test_source_schema_resolves_to_canonical_repository_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    resolved = resource_paths.resolve_run_report_schema_path()

    expected = Path(__file__).resolve().parent.parent / "schemas" / "run-report-v1.schema.json"
    assert resolved == expected
    schema = json.loads(resolved.read_text(encoding="utf-8"))
    assert schema["$id"] == "https://autogame.local/schemas/run-report-v1.json"
    assert schema["$defs"]["run_status"]["enum"] == ["running", "success", "failure", "cancelled"]


def test_frozen_schema_resolves_to_adjacent_bundle_resource(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package_dir = tmp_path / "bundle" / "autogame_orchestrator"
    resources_dir = package_dir / "_resources"
    resources_dir.mkdir(parents=True)
    canonical = Path(__file__).resolve().parent.parent / "schemas" / "run-report-v1.schema.json"
    bundled = resources_dir / canonical.name
    bundled.write_bytes(canonical.read_bytes())
    monkeypatch.setattr(resource_paths, "__file__", str(package_dir / "resource_paths.py"))
    monkeypatch.setattr(resource_paths.sys, "frozen", True, raising=False)
    monkeypatch.chdir(tmp_path)

    assert resource_paths.resolve_run_report_schema_path() == bundled


def test_missing_frozen_schema_fails_closed_without_cwd_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_dir = tmp_path / "bundle" / "autogame_orchestrator"
    package_dir.mkdir(parents=True)
    (tmp_path / "run-report-v1.schema.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(resource_paths, "__file__", str(package_dir / "resource_paths.py"))
    monkeypatch.setattr(resource_paths.sys, "frozen", True, raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RunReportSchemaResourceError, match="unavailable"):
        resource_paths.resolve_run_report_schema_path()


def test_resource_locator_does_not_use_meipass_or_parent_search() -> None:
    source = Path(resource_paths.__file__).read_text(encoding="utf-8")

    assert "_MEIPASS" not in source
    assert ".glob(" not in source
    assert ".rglob(" not in source
