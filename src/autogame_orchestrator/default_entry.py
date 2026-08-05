"""Deterministic interactive policy for the native ``start`` command."""

from __future__ import annotations

import math
import os
import stat
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from autogame_orchestrator.config_loader import load_config
from autogame_orchestrator.config_model import AppConfig
from autogame_orchestrator.models import ErrorCode
from autogame_orchestrator.run_application import (
    EXTERNAL_RUN_STAGES,
    RUN_CONFIRMATION,
    RunCommandResult,
    RunRequest,
    execute_run_request,
    validate_external_plan,
    validate_run_v1_config,
)
from autogame_orchestrator.workflow.plan import ExecutionPlan, build_execution_plan

DEFAULT_START_DEADLINE_SECONDS = 21600.0
MAX_START_DEADLINE_SECONDS = 86400.0

CONFIG_TOKEN = r"%LOCALAPPDATA%\OrchestratoRRR\config\orchestrator.toml"
LOG_TOKEN = r"%LOCALAPPDATA%\OrchestratoRRR\logs"
REPORT_TOKEN = r"%LOCALAPPDATA%\OrchestratoRRR\run-results"


class DefaultEntryErrorCode(StrEnum):
    INTERACTIVE_CONSOLE_REQUIRED = "START_INTERACTIVE_CONSOLE_REQUIRED"
    DEADLINE_INVALID = "START_DEADLINE_INVALID"
    LOCALAPPDATA_UNAVAILABLE = "START_LOCALAPPDATA_UNAVAILABLE"
    CONFIG_NOT_FOUND = "START_CONFIG_NOT_FOUND"
    CONFIG_INVALID = "START_CONFIG_INVALID"
    PATH_POLICY_INVALID = "START_PATH_POLICY_INVALID"
    RUN_V1_GATE_FAILED = "START_RUN_V1_GATE_FAILED"
    CONFIG_PATH_CHECK_FAILED = "START_CONFIG_PATH_CHECK_FAILED"
    PLAN_INVALID = "START_PLAN_INVALID"
    RUNTIME_DIRECTORY_UNAVAILABLE = "START_RUNTIME_DIRECTORY_UNAVAILABLE"
    LOG_DIRECTORY_UNAVAILABLE = "START_LOG_DIRECTORY_UNAVAILABLE"
    REPORT_DIRECTORY_UNAVAILABLE = "START_REPORT_DIRECTORY_UNAVAILABLE"
    CONFIRMATION_REJECTED = "START_CONFIRMATION_REJECTED"
    INTERNAL_ERROR = "START_INTERNAL_ERROR"


@dataclass(frozen=True)
class DefaultEntryPaths:
    install_directory: Path
    config_directory: Path
    config_path: Path
    runtime_directory: Path
    log_directory: Path
    report_directory: Path


@dataclass(frozen=True)
class DefaultEntryResult:
    exit_code: int
    status: str
    error_code: str


class DefaultEntryIO(Protocol):
    def stdin_isatty(self) -> bool: ...

    def stdout_isatty(self) -> bool: ...

    def write(self, message: str) -> None: ...

    def read(self, prompt: str) -> str: ...


class ConsoleDefaultEntryIO:
    def stdin_isatty(self) -> bool:
        return sys.stdin.isatty()

    def stdout_isatty(self) -> bool:
        return sys.stdout.isatty()

    def write(self, message: str) -> None:
        print(message)

    def read(self, prompt: str) -> str:
        return input(prompt)


ConfigLoader = Callable[[Path], tuple[AppConfig | None, list[ErrorCode]]]
RunExecutor = Callable[[RunRequest], RunCommandResult]
PlanBuilder = Callable[[AppConfig], ExecutionPlan]


@dataclass(frozen=True)
class DefaultEntryDependencies:
    environment: Mapping[str, str]
    io: DefaultEntryIO
    config_loader: ConfigLoader
    plan_builder: PlanBuilder
    run_executor: RunExecutor


def default_entry_dependencies() -> DefaultEntryDependencies:
    """Capture process boundaries only when ``start`` is invoked."""
    return DefaultEntryDependencies(
        environment=os.environ,
        io=ConsoleDefaultEntryIO(),
        config_loader=lambda path: load_config(path, check_paths=False),
        plan_builder=build_execution_plan,
        run_executor=execute_run_request,
    )


def validate_start_deadline(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and 0 < value <= MAX_START_DEADLINE_SECONDS
    )


def resolve_default_entry_paths(environment: Mapping[str, str]) -> DefaultEntryPaths | None:
    raw = environment.get("LOCALAPPDATA")
    if raw is None or not raw.strip():
        return None
    try:
        base = Path(raw)
        if not base.is_absolute() or (base.exists() and not base.is_dir()):
            return None
        base = base.resolve(strict=False)
    except (OSError, ValueError):
        return None
    product = base / "OrchestratoRRR"
    return DefaultEntryPaths(
        install_directory=base / "Programs" / "OrchestratoRRR",
        config_directory=product / "config",
        config_path=product / "config" / "orchestrator.toml",
        runtime_directory=product / "runtime",
        log_directory=product / "logs",
        report_directory=product / "run-results",
    )


def _is_reparse_point(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _prepare_directory(path: Path, error: DefaultEntryErrorCode, *, probe: bool) -> DefaultEntryErrorCode | None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir() or path.is_symlink() or _is_reparse_point(path):
            return error
        if not probe:
            return None
        sentinel = path / f".orchestrator-write-probe-{uuid.uuid4().hex}.tmp"
        try:
            with sentinel.open("x", encoding="utf-8"):
                pass
            sentinel.unlink()
        except OSError:
            try:
                sentinel.unlink(missing_ok=True)
            except OSError:
                pass
            return error
        if sentinel.exists():
            return error
    except OSError:
        return error
    return None


def _pause(io: DefaultEntryIO) -> None:
    io.read("Press Enter to close.")


def _fail(
    io: DefaultEntryIO,
    code: DefaultEntryErrorCode,
    exit_code: int,
    *,
    detail: str | None = None,
    guidance: str | None = None,
) -> DefaultEntryResult:
    io.write(code.value if detail is None else f"{code.value}: {detail}")
    if guidance is not None:
        io.write(guidance)
    _pause(io)
    return DefaultEntryResult(exit_code, "rejected", code.value)


def execute_default_entry(
    deadline_seconds: float = DEFAULT_START_DEADLINE_SECONDS,
    *,
    dependencies: DefaultEntryDependencies | None = None,
) -> DefaultEntryResult:
    """Run deterministic preflight, prompt once, then call the formal run boundary once."""
    selected = default_entry_dependencies() if dependencies is None else dependencies
    io = selected.io
    if not io.stdin_isatty() or not io.stdout_isatty():
        io.write(DefaultEntryErrorCode.INTERACTIVE_CONSOLE_REQUIRED.value)
        return DefaultEntryResult(2, "rejected", DefaultEntryErrorCode.INTERACTIVE_CONSOLE_REQUIRED.value)
    if not validate_start_deadline(deadline_seconds):
        return _fail(io, DefaultEntryErrorCode.DEADLINE_INVALID, 2)

    paths = resolve_default_entry_paths(selected.environment)
    if paths is None:
        return _fail(io, DefaultEntryErrorCode.LOCALAPPDATA_UNAVAILABLE, 3)
    if not paths.config_path.is_file():
        return _fail(
            io,
            DefaultEntryErrorCode.CONFIG_NOT_FOUND,
            2,
            guidance=f"Create {CONFIG_TOKEN} before starting.",
        )

    try:
        config, config_errors = selected.config_loader(paths.config_path)
    except Exception:
        return _fail(io, DefaultEntryErrorCode.INTERNAL_ERROR, 8)
    if config is None or config_errors:
        return _fail(io, DefaultEntryErrorCode.CONFIG_INVALID, 2)

    path_issues = config.check_default_entry_paths(
        canonical_log_directory=paths.log_directory,
        canonical_report_directory=paths.report_directory,
    )
    if path_issues:
        return _fail(io, DefaultEntryErrorCode.PATH_POLICY_INVALID, 2, detail=path_issues[0].field)
    if validate_run_v1_config(config) is not None:
        return _fail(io, DefaultEntryErrorCode.RUN_V1_GATE_FAILED, 2)
    if config.check_paths():
        return _fail(io, DefaultEntryErrorCode.CONFIG_PATH_CHECK_FAILED, 3)

    try:
        plan = selected.plan_builder(config)
    except Exception:
        return _fail(io, DefaultEntryErrorCode.INTERNAL_ERROR, 8)
    if validate_external_plan(plan) is not None or plan.stages != EXTERNAL_RUN_STAGES:
        return _fail(io, DefaultEntryErrorCode.PLAN_INVALID, 2)

    for directory, error, probe in (
        (paths.runtime_directory, DefaultEntryErrorCode.RUNTIME_DIRECTORY_UNAVAILABLE, False),
        (paths.log_directory, DefaultEntryErrorCode.LOG_DIRECTORY_UNAVAILABLE, True),
        (paths.report_directory, DefaultEntryErrorCode.REPORT_DIRECTORY_UNAVAILABLE, True),
    ):
        directory_error = _prepare_directory(directory, error, probe=probe)
        if directory_error is not None:
            return _fail(io, directory_error, 3)

    io.write("External workflow plan \u2014 real programs may be started.")
    for index, stage in enumerate(plan.stages, 1):
        io.write(f"{index}. {stage.value}")
    io.write(
        "WARNING: This starts real programs, may request administrator privileges, and executes 11 external stages."
    )
    io.write("The synthetic isolated smoke is not used by this entry. A mismatched confirmation cancels execution.")
    confirmation = io.read(f"Type {RUN_CONFIRMATION} to continue: ")
    if confirmation != RUN_CONFIRMATION:
        return _fail(io, DefaultEntryErrorCode.CONFIRMATION_REJECTED, 2)

    request = RunRequest(paths.config_path, float(deadline_seconds), RUN_CONFIRMATION, False)
    original_cwd = Path.cwd()
    run_failed = False
    try:
        os.chdir(paths.runtime_directory)
        run_result = selected.run_executor(request)
    except Exception:
        run_failed = True
    finally:
        os.chdir(original_cwd)
    if run_failed:
        return _fail(io, DefaultEntryErrorCode.INTERNAL_ERROR, 8)

    if run_result.exit_code == 0 and run_result.status == "success" and run_result.error_code == "OK":
        io.write("Workflow completed: status=success error_code=OK")
    else:
        io.write(f"Workflow finished: status={run_result.status} error_code={run_result.error_code}")
    io.write(f"Reports: {REPORT_TOKEN}")
    _pause(io)
    return DefaultEntryResult(run_result.exit_code, run_result.status, run_result.error_code)


__all__ = [
    "CONFIG_TOKEN",
    "DEFAULT_START_DEADLINE_SECONDS",
    "DefaultEntryDependencies",
    "DefaultEntryErrorCode",
    "DefaultEntryIO",
    "DefaultEntryPaths",
    "DefaultEntryResult",
    "LOG_TOKEN",
    "MAX_START_DEADLINE_SECONDS",
    "REPORT_TOKEN",
    "default_entry_dependencies",
    "execute_default_entry",
    "resolve_default_entry_paths",
    "validate_start_deadline",
]
