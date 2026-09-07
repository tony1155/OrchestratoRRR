"""Read-only launch metadata for the repository-local PowerShell entry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from autogame_orchestrator.config_loader import load_config
from autogame_orchestrator.resource_paths import resolve_run_report_schema_path
from autogame_orchestrator.run_application import (
    RUN_CONFIRMATION,
    validate_external_plan,
    validate_run_v1_config,
)
from autogame_orchestrator.workflow.plan import build_execution_plan


class LocalPreflightError(ValueError):
    """A local entry requirement was not met; no workflow has been started."""


def inspect_local_launch(config_path: Path, source_root: Path, data_directory: Path) -> dict[str, object]:
    if not all(path.is_absolute() for path in (config_path, source_root, data_directory)):
        raise LocalPreflightError("LOCAL_ABSOLUTE_PATHS_REQUIRED")
    source_root = source_root.resolve(strict=True)
    if bool(getattr(sys, "frozen", False)) or Path(__file__).resolve().parents[2] != source_root:
        raise LocalPreflightError("LOCAL_SOURCE_MISMATCH")
    python = source_root / ".venv" / "Scripts" / "python.exe"
    if Path(sys.executable).resolve() != python.resolve():
        raise LocalPreflightError("LOCAL_VENV_REQUIRED")
    resolve_run_report_schema_path()
    config_path = config_path.resolve(strict=True)
    data_directory = data_directory.resolve()
    log_directory = data_directory / "logs"
    report_directory = data_directory / "run-results"
    runtime_directory = data_directory / "runtime"
    config, errors = load_config(config_path, check_paths=True)
    if config is None or errors:
        code = errors[0].value if errors else "CONFIG_SCHEMA_ERROR"
        raise LocalPreflightError(f"LOCAL_CONFIG_INVALID: {code}")
    issues = config.check_default_entry_paths(
        canonical_log_directory=log_directory,
        canonical_report_directory=report_directory,
    )
    if issues:
        raise LocalPreflightError(f"LOCAL_PATH_POLICY_INVALID: {issues[0].field}")
    gate_error = validate_run_v1_config(config)
    if gate_error is not None:
        raise LocalPreflightError(f"LOCAL_RUN_REJECTED: {gate_error}")
    plan = build_execution_plan(config)
    if validate_external_plan(plan) is not None:
        raise LocalPreflightError("LOCAL_PLAN_INVALID")
    for directory in (data_directory, log_directory, report_directory, runtime_directory):
        if directory.exists() and not directory.is_dir():
            raise LocalPreflightError("LOCAL_DATA_DIRECTORY_INVALID")
    return {
        "source_root": str(source_root),
        "python": str(python),
        "config_path": str(config_path),
        "log_directory": str(log_directory),
        "report_directory": str(report_directory),
        "runtime_directory": str(runtime_directory),
        "stages": [stage.value for stage in plan.stages],
        "requires_administrator": plan.requires_administrator,
        "confirmation": RUN_CONFIRMATION,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--data-directory", required=True, type=Path)
    args = parser.parse_args()
    try:
        metadata = inspect_local_launch(args.config, args.source_root, args.data_directory)
    except (OSError, ValueError, RuntimeError) as exc:
        message = str(exc) if isinstance(exc, LocalPreflightError) else "LOCAL_PREFLIGHT_FAILED"
        print(message, file=sys.stderr)
        return 2
    print(json.dumps(metadata, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
