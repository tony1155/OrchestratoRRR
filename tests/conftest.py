"""Shared pytest fixtures for the orchestrator test suite."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def tmp_workdir() -> Generator[Path, None, None]:
    """Temporary directory that acts as a clean working area."""
    with tempfile.TemporaryDirectory(prefix="orch-test-") as td:
        yield Path(td)


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the ``tests/fixtures/`` directory."""
    return Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def valid_config() -> Path:
    """Path to a valid reference config."""
    return Path(__file__).resolve().parent / "fixtures" / "valid-config.toml"


@pytest.fixture
def invalid_toml() -> Path:
    """Path to a syntactically invalid TOML file."""
    return Path(__file__).resolve().parent / "fixtures" / "invalid-toml.toml"


@pytest.fixture
def missing_fields_config() -> Path:
    """Path to a config with missing required sections."""
    return Path(__file__).resolve().parent / "fixtures" / "missing-fields-config.toml"


@pytest.fixture
def invalid_values_config() -> Path:
    """Path to a config with invalid field values."""
    return Path(__file__).resolve().parent / "fixtures" / "invalid-values-config.toml"


@pytest.fixture
def schema_path() -> Path:
    """Path to the RunReport v1 JSON schema."""
    return Path(__file__).resolve().parent.parent / "schemas" / "run-report-v1.schema.json"


@pytest.fixture
def golden_path() -> Path:
    """Path to the RunReport v1 golden sample."""
    return Path(__file__).resolve().parent.parent / "schemas" / "golden" / "run-report-v1.golden.json"
