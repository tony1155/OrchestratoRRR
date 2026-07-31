"""Stable locations for resources required by the running application."""

from __future__ import annotations

import sys
from pathlib import Path

_RUN_REPORT_SCHEMA_NAME = "run-report-v1.schema.json"


class RunReportSchemaResourceError(RuntimeError):
    """Raised when the canonical RunReport schema cannot be resolved."""


def resolve_run_report_schema_path() -> Path:
    """Return the canonical RunReport schema path for the current runtime.

    Source mode uses the repository's ``schemas`` directory.  Frozen mode
    uses the schema copied beside the bundled package by the PyInstaller spec.
    The function deliberately checks one deterministic location only.
    """
    if bool(getattr(sys, "frozen", False)):
        candidate = Path(__file__).resolve().parent / "_resources" / _RUN_REPORT_SCHEMA_NAME
    else:
        candidate = Path(__file__).resolve().parents[2] / "schemas" / _RUN_REPORT_SCHEMA_NAME

    if not candidate.is_file():
        raise RunReportSchemaResourceError("RunReport schema resource is unavailable.")
    return candidate
