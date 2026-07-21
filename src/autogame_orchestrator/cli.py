"""CLI entry-point for Autogame Orchestrator.

Commands:
    version    Print version and exit.
    validate   Load and validate a TOML config file.
    plan       Print a static execution plan.
"""

from __future__ import annotations

import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from autogame_orchestrator import __version__
from autogame_orchestrator.config_loader import load_config
from autogame_orchestrator.log_writer import JsonlLogWriter
from autogame_orchestrator.models import (
    ErrorCode,
    OutcomeKind,
    RunReport,
    RunStatus,
    StageName,
    StageReport,
)
from autogame_orchestrator.planning import PLAN_HEADER, build_plan
from autogame_orchestrator.reporter import write_report_atomic

if TYPE_CHECKING:
    pass

app = typer.Typer(
    name="autogame-orch",
    help="Autogame Orchestrator — phase 0 (project skeleton and contracts).",
    add_completion=False,
)

_DEBUG_ENV = "AUTOGAME_ORCH_DEBUG"


def _is_debug() -> bool:
    import os

    return os.environ.get(_DEBUG_ENV, "0") == "1"


def _make_stage_report(
    stage: StageName,
    outcome: OutcomeKind,
    error_code: ErrorCode,
    started_at: datetime,
    message: str,
) -> StageReport:
    finished_at = datetime.now(UTC)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    return StageReport(
        stage=stage,
        outcome=outcome,
        error_code=error_code,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        message=message,
    )


@app.command()
def version() -> None:
    """Print the orchestrator version and exit."""
    typer.echo(f"autogame-orchestrator {__version__}")


@app.command()
def validate(
    config: str = typer.Option(  # noqa: B008
        ..., "--config", "-c", help="Path to TOML configuration file."
    ),
    check_paths: bool = typer.Option(  # noqa: B008
        False, "--check-paths", help="Also verify that executable paths exist on disk."
    ),
) -> None:
    """Load and validate a TOML configuration file."""
    run_id = str(uuid.uuid4())
    config_path = Path(config).resolve()
    started_at = datetime.now(UTC)
    app_config = None
    error_code = ErrorCode.OK
    outcome_kind = OutcomeKind.SUCCESS
    stage_message = "Configuration validated successfully."

    log_dir = Path("logs")
    report_dir = Path("run-results")
    log_writer: JsonlLogWriter | None = None

    try:
        cfg, errs = load_config(config_path, check_paths=check_paths)
        if errs:
            error_code = errs[0]
            outcome_kind = OutcomeKind.FAILURE
            stage_message = f"Configuration validation failed: {error_code.value}"

        app_config = cfg
        if app_config is not None:
            log_dir = Path(app_config.orchestrator.log_dir)
            report_dir = Path(app_config.orchestrator.report_dir)

    except Exception:
        error_code = ErrorCode.INTERNAL_ERROR
        outcome_kind = OutcomeKind.FAILURE
        stage_message = "Unexpected error during validation."
        if _is_debug():
            traceback.print_exc()

    log_writer = _open_log(log_dir, run_id, log_writer)
    _log_validation(log_writer, config_path, check_paths, error_code)

    stage_report = _make_stage_report(StageName.VALIDATE_CONFIG, outcome_kind, error_code, started_at, stage_message)

    report_status = RunStatus.SUCCESS if error_code == ErrorCode.OK else RunStatus.FAILURE
    finished_at = datetime.now(UTC)
    total_duration_ms = int((finished_at - started_at).total_seconds() * 1000)

    run_report = RunReport(
        schema_version=1,
        run_id=run_id,
        orchestrator_version=__version__,
        mode="validate",
        status=report_status,
        error_code=error_code,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=total_duration_ms,
        stages=(stage_report,),
    )

    if log_writer is not None:
        _safe_close_log(log_writer)

    _write_report(run_report, report_dir)

    if error_code != ErrorCode.OK:
        typer.echo(f"Validation FAILED [{error_code.value}]", err=True)
        raise typer.Exit(code=1)

    typer.echo("Validation OK.")


@app.command()
def plan(
    config: str = typer.Option(  # noqa: B008
        ..., "--config", "-c", help="Path to TOML configuration file."
    ),
    check_paths: bool = typer.Option(  # noqa: B008
        False, "--check-paths", help="Also verify that executable paths exist on disk."
    ),
) -> None:
    """Print a static execution plan — no external programs are launched."""
    run_id = str(uuid.uuid4())
    config_path = Path(config).resolve()
    started_at = datetime.now(UTC)
    error_code = ErrorCode.OK
    stage_reports: list[StageReport] = []
    log_dir = Path("logs")
    report_dir = Path("run-results")
    log_writer: JsonlLogWriter | None = None

    try:
        cfg, errs = load_config(config_path, check_paths=check_paths)
        if errs:
            error_code = errs[0]
            log_dir_guessed = Path(cfg.orchestrator.log_dir) if cfg else Path("logs")
            log_writer = _open_log(log_dir_guessed, run_id, log_writer)
            if log_writer is not None:
                log_writer.error(
                    "config.invalid",
                    f"Config load failed: {error_code.value}",
                    {"errors": [e.value for e in errs]},
                )
            typer.echo(f"Configuration error: {error_code.value}", err=True)

            stage_reports.append(
                _make_stage_report(
                    StageName.VALIDATE_CONFIG,
                    OutcomeKind.FAILURE,
                    error_code,
                    started_at,
                    f"Configuration validation failed: {error_code.value}",
                )
            )
            _finish_and_exit(1, run_id, started_at, "plan", stage_reports, error_code, log_writer, report_dir)
            return

        app_config = cfg
        log_dir = Path(app_config.orchestrator.log_dir) if app_config else Path("logs")
        report_dir = Path(app_config.orchestrator.report_dir) if app_config else Path("run-results")

    except Exception:
        error_code = ErrorCode.INTERNAL_ERROR
        if _is_debug():
            traceback.print_exc()

    log_writer = _open_log(log_dir, run_id, log_writer)
    if log_writer is not None:
        log_writer.info("plan.start", "Execution plan requested", {"config": str(config_path)})

    if error_code != ErrorCode.OK:
        stage_reports.append(
            _make_stage_report(
                StageName.VALIDATE_CONFIG,
                OutcomeKind.FAILURE,
                error_code,
                started_at,
                f"Error: {error_code.value}",
            )
        )
        _finish_and_exit(1, run_id, started_at, "plan", stage_reports, error_code, log_writer, report_dir)
        return

    stage_reports.append(
        _make_stage_report(
            StageName.VALIDATE_CONFIG,
            OutcomeKind.SUCCESS,
            ErrorCode.OK,
            started_at,
            "Configuration validated.",
        )
    )

    typer.echo(PLAN_HEADER)
    typer.echo()

    plan_stages = build_plan()
    for idx, stage_name in enumerate(plan_stages, 1):
        typer.echo(f"  {idx:2d}. {stage_name.value}")

    for stage_name in plan_stages:
        if stage_name == StageName.VALIDATE_CONFIG:
            continue
        stage_reports.append(
            StageReport(
                stage=stage_name,
                outcome=OutcomeKind.SKIPPED,
                error_code=ErrorCode.SKIPPED,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                duration_ms=0,
                message="Skipped in plan mode.",
            )
        )

    typer.echo()
    typer.echo("End of plan.")

    _finish_and_exit(0, run_id, started_at, "plan", stage_reports, ErrorCode.OK, log_writer, report_dir)


def _finish_and_exit(
    exit_code: int,
    run_id: str,
    started_at: datetime,
    mode: str,
    stage_reports: list[StageReport],
    error_code: ErrorCode,
    log_writer: JsonlLogWriter | None,
    report_dir: Path,
) -> None:
    finished_at = datetime.now(UTC)
    total_duration_ms = int((finished_at - started_at).total_seconds() * 1000)

    report_status = RunStatus.SUCCESS if error_code == ErrorCode.OK else RunStatus.FAILURE
    run_report = RunReport(
        schema_version=1,
        run_id=run_id,
        orchestrator_version=__version__,
        mode=mode,
        status=report_status,
        error_code=error_code,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=total_duration_ms,
        stages=tuple(stage_reports),
    )

    if log_writer is not None:
        _safe_close_log(log_writer)

    _write_report(run_report, report_dir)
    raise typer.Exit(code=exit_code)


def _open_log(log_dir: Path, run_id: str, existing: JsonlLogWriter | None) -> JsonlLogWriter | None:
    if existing is not None:
        return existing
    try:
        writer = JsonlLogWriter(log_dir / f"run-{run_id}.jsonl", run_id)
        return writer.__enter__()
    except Exception:
        if _is_debug():
            traceback.print_exc()
        return None


def _safe_close_log(writer: JsonlLogWriter) -> None:
    try:
        writer.__exit__(None, None, None)
    except Exception:
        if _is_debug():
            traceback.print_exc()


def _log_validation(
    writer: JsonlLogWriter | None,
    config_path: Path,
    check_paths: bool,
    error_code: ErrorCode,
) -> None:
    if writer is None:
        return
    try:
        writer.info(
            "validate.run",
            "Validation complete",
            {
                "config": str(config_path),
                "check_paths": check_paths,
                "error_code": error_code.value,
            },
        )
    except Exception:
        if _is_debug():
            traceback.print_exc()


def _write_report(report: RunReport, report_dir: Path) -> None:
    try:
        write_report_atomic(report, report_dir)
    except Exception:
        if _is_debug():
            traceback.print_exc()
