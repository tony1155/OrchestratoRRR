"""Fail-closed, in-process synthetic workflow support for Phase 7B2."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from autogame_orchestrator.entry_runtime import (
    ElevationLaunchSpec,
    EntryRuntime,
    EntryRuntimeKind,
    detect_entry_runtime,
)
from autogame_orchestrator.models import (
    ErrorCode,
    OutcomeKind,
    RunReport,
    RunStatus,
    WorkflowMode,
)
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.process.errors import TerminationReason
from autogame_orchestrator.runtime.aalc_models import (
    AALCAttemptResult,
    AALCAttemptStatus,
    AALCCompletionMode,
    AALCErrorCode,
    AALCRunResult,
    AALCRunStatus,
)
from autogame_orchestrator.runtime.maa_models import MAAErrorCode, MAARunResult, MAARunStatus
from autogame_orchestrator.runtime.models import MumuAction, MumuRuntimeErrorCode, MumuRuntimeResult, MumuRuntimeStatus
from autogame_orchestrator.runtime.starrail_models import (
    StarRailCompletionMode,
    StarRailErrorCode,
    StarRailRunResult,
    StarRailRunStatus,
)
from autogame_orchestrator.workflow.contracts import ElevationGatewayResult
from autogame_orchestrator.workflow.production.application import ProductionApplicationDependencies
from autogame_orchestrator.workflow.production.ports import (
    AALCRunPort,
    MAARunPort,
    MAASyncPort,
    MAAUpdatePort,
    MumuRuntimePort,
    RuntimeFactories,
    StarRailRunPort,
)

ISOLATED_WORKFLOW_CONFIRMATION: Final = "I_UNDERSTAND_THIS_RUNS_ONLY_SYNTHETIC_IN_PROCESS_FAKES"
MAX_ISOLATED_DEADLINE_SECONDS: Final = 120.0
_ALLOWED_WORKSPACE_NAMES: Final = {
    "synthetic-config.toml",
    "synthetic-bin",
    "synthetic-work",
    "logs",
    "run-results",
}


class IsolatedWorkflowError(RuntimeError):
    """Stable, path-free error for the hidden isolated command."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class IsolatedCallLedger:
    """Non-sensitive in-process call counts used by tests and diagnostics."""

    elevation_is_elevated_calls: int = 0
    elevation_relaunch_calls: int = 0
    default_runtime_factory_calls: int = 0
    process_launch_calls: int = 0
    tcp_probe_calls: int = 0
    adb_calls: int = 0
    mumu_factory_calls: int = 0
    mumu_ensure_external_ready_calls: int = 0
    mumu_status_calls: int = 0
    starrail_factory_calls: int = 0
    starrail_run_calls: int = 0
    maa_factory_calls: int = 0
    maa_run_calls: int = 0
    aalc_factory_calls: int = 0
    aalc_run_calls: int = 0
    maa_sync_factory_calls: int = 0
    maa_update_factory_calls: int = 0

    @property
    def forbidden_calls(self) -> int:
        return sum(
            (
                self.elevation_is_elevated_calls,
                self.elevation_relaunch_calls,
                self.default_runtime_factory_calls,
                self.process_launch_calls,
                self.tcp_probe_calls,
                self.adb_calls,
            )
        )


@dataclass(frozen=True)
class IsolatedWorkflowResult:
    """Validated result of one synthetic workflow invocation."""

    report: RunReport
    ledger: IsolatedCallLedger
    config_path: Path


def validate_isolated_deadline(value: object) -> str | None:
    """Validate the smaller deadline contract used by the hidden command."""

    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "ISOLATED_DEADLINE_INVALID"
    if not math.isfinite(value) or value <= 0 or value > MAX_ISOLATED_DEADLINE_SECONDS:
        return "ISOLATED_DEADLINE_INVALID"
    return None


def _has_symlink_component(path: Path) -> bool:
    current = path
    while True:
        if current.is_symlink():
            return True
        if current.parent == current:
            return False
        current = current.parent


def _is_within(candidate: Path, parent: Path) -> bool:
    return candidate == parent or parent in candidate.parents


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _protected_roots(runtime: EntryRuntime) -> tuple[Path, ...]:
    roots = [
        _repository_root() / "dist" / "OrchestratoRRR",
        _repository_root() / "build" / "pyinstaller",
    ]
    if runtime.kind is EntryRuntimeKind.FROZEN:
        roots.append(runtime.executable.resolve().parent)
    return tuple(root.resolve() for root in roots)


def _has_protected_leaf_shape(path: Path) -> bool:
    current = path
    while True:
        if current.name.casefold() == "pyinstaller" and current.parent.name.casefold() == "build":
            return True
        if current.name.casefold() == "orchestratorrr" and current.parent.name.casefold() == "dist":
            return True
        if current.parent == current:
            return False
        current = current.parent


def validate_isolated_workspace(workspace: Path, runtime: EntryRuntime | None = None) -> str | None:
    """Return a stable rejection code without changing the candidate directory."""

    selected_runtime = detect_entry_runtime() if runtime is None else runtime
    if not workspace.is_absolute():
        return "ISOLATED_WORKSPACE_INVALID"
    try:
        if not workspace.exists():
            return "ISOLATED_WORKSPACE_INVALID"
        if _has_symlink_component(workspace):
            return "ISOLATED_WORKSPACE_INVALID"
        if not workspace.is_dir():
            return "ISOLATED_WORKSPACE_INVALID"
        resolved = workspace.resolve(strict=True)
        if resolved == Path.cwd().resolve():
            return "ISOLATED_WORKSPACE_INVALID"
        if _has_protected_leaf_shape(resolved):
            return "ISOLATED_WORKSPACE_INVALID"
        if any(_is_within(resolved, root) for root in _protected_roots(selected_runtime)):
            return "ISOLATED_WORKSPACE_INVALID"
        if next(resolved.iterdir(), None) is not None:
            return "ISOLATED_WORKSPACE_NOT_EMPTY"
    except (OSError, RuntimeError, ValueError):
        return "ISOLATED_WORKSPACE_INVALID"
    return None


def _workspace_child(workspace: Path, relative: str) -> Path:
    candidate = (workspace / relative).resolve()
    if not _is_within(candidate, workspace):
        raise IsolatedWorkflowError("ISOLATED_CONFIG_BUILD_FAILED")
    return candidate


def _toml_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _build_synthetic_config(workspace: Path) -> Path:
    binary_dir = _workspace_child(workspace, "synthetic-bin")
    work_dir = _workspace_child(workspace, "synthetic-work")
    log_dir = _workspace_child(workspace, "logs")
    report_dir = _workspace_child(workspace, "run-results")
    binary_dir.mkdir()
    work_dir.mkdir()
    log_dir.mkdir()
    report_dir.mkdir()

    paths = {
        name: _workspace_child(binary_dir, name)
        for name in (
            "emulator.placeholder",
            "adb.placeholder",
            "starrail.placeholder",
            "maa.placeholder",
            "aalc.placeholder",
        )
    }
    for path in paths.values():
        path.write_text("synthetic placeholder\n", encoding="utf-8")

    config_path = _workspace_child(workspace, "synthetic-config.toml")
    starrail_log = _workspace_child(workspace, "synthetic-work/starrail-{date}.log")
    config = f"""[orchestrator]
log_dir = {_toml_literal(str(log_dir))}
report_dir = {_toml_literal(str(report_dir))}
heartbeat_interval_seconds = 2
poll_interval_seconds = 1

[mumu]
lifecycle_mode = "external"
executable = {_toml_literal(str(paths["emulator.placeholder"]))}
adb_executable = {_toml_literal(str(paths["adb.placeholder"]))}
adb_serial = "127.0.0.1:59999"
start_timeout_seconds = 2
stop_timeout_seconds = 1
start_arguments = []
stop_arguments = []

[starrail]
executable = {_toml_literal(str(paths["starrail.placeholder"]))}
working_directory = {_toml_literal(str(work_dir))}
arguments = ["synthetic-input"]
log_path_template = {_toml_literal(str(starrail_log))}
success_keywords = ["synthetic-success"]
failure_keywords = ["synthetic-failure"]
task_timeout_seconds = 2
stop_timeout_seconds = 1

[starrail.environment]

[maa]
executable = {_toml_literal(str(paths["maa.placeholder"]))}
working_directory = {_toml_literal(str(work_dir))}
arguments = []
timeout_seconds = 2
stop_timeout_seconds = 1

[maa.environment]

[maa_sync]
enabled = false
gui_settings_source = ""
gui_tasks_source = ""
cli_profile_destination = ""
cli_tasks_destination = ""
backup_enabled = false
requires_administrator = false

[maa_update]
enabled = false
allow_network = false
requires_administrator = false
arguments = ["update"]
timeout_seconds = 2

[aalc]
executable = {_toml_literal(str(paths["aalc.placeholder"]))}
working_directory = {_toml_literal(str(work_dir))}
arguments = []
attempts = 1
attempt_timeout_seconds = 2
stop_timeout_seconds = 1
requires_administrator = false

[aalc.environment]
"""
    config_path.write_text(config, encoding="utf-8")
    return config_path


def _ensure_workspace_contents_confined(workspace: Path) -> None:
    try:
        names = {item.name for item in workspace.iterdir()}
    except OSError:
        raise IsolatedWorkflowError("ISOLATED_RUNTIME_CONTRACT_FAILED") from None
    if not names.issubset(_ALLOWED_WORKSPACE_NAMES):
        raise IsolatedWorkflowError("ISOLATED_RUNTIME_CONTRACT_FAILED")


class _SyntheticElevationGateway:
    def __init__(self, ledger: IsolatedCallLedger) -> None:
        self._ledger = ledger

    def is_elevated(self) -> bool:
        self._ledger.elevation_is_elevated_calls += 1
        raise IsolatedWorkflowError("ISOLATED_RUNTIME_CONTRACT_FAILED")

    def relaunch(self, spec: ElevationLaunchSpec) -> ElevationGatewayResult:
        del spec
        self._ledger.elevation_relaunch_calls += 1
        raise IsolatedWorkflowError("ISOLATED_RUNTIME_CONTRACT_FAILED")


class _SyntheticMumu:
    def __init__(self, ledger: IsolatedCallLedger) -> None:
        self._ledger = ledger

    def _ready(self) -> MumuRuntimeResult:
        now = datetime.now(UTC)
        return MumuRuntimeResult(
            action=MumuAction.STATUS,
            status=MumuRuntimeStatus.READY,
            error_code=MumuRuntimeErrorCode.OK,
            started_at=now,
            finished_at=now,
            duration_ms=0,
            changed=False,
            diagnostics={"source_status": MumuRuntimeStatus.READY.value},
        )

    def ensure_external_ready(
        self,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> MumuRuntimeResult:
        del deadline, cancel
        self._ledger.mumu_ensure_external_ready_calls += 1
        return self._ready()

    def status(
        self,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> MumuRuntimeResult:
        del deadline, cancel
        self._ledger.mumu_status_calls += 1
        return self._ready()


class _SyntheticStarRail:
    def __init__(self, ledger: IsolatedCallLedger) -> None:
        self._ledger = ledger

    def run(
        self,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
    ) -> StarRailRunResult:
        del deadline, cancel
        self._ledger.starrail_run_calls += 1
        now = datetime.now(UTC)
        return StarRailRunResult(
            status=StarRailRunStatus.COMPLETED,
            error_code=StarRailErrorCode.OK,
            completion_mode=StarRailCompletionMode.LOG_SUCCESS,
            started_at=now,
            finished_at=now,
            duration_ms=0,
            pid=None,
            exit_code=0,
            matched_keyword="synthetic-success",
            log_path="",
            owned_process_cleaned=True,
            stdout_excerpt="",
            stderr_excerpt="",
            stdout_truncated=False,
            stderr_truncated=False,
        )


class _SyntheticMaa:
    def __init__(self, ledger: IsolatedCallLedger) -> None:
        self._ledger = ledger

    def run(
        self,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
    ) -> MAARunResult:
        del deadline, cancel
        self._ledger.maa_run_calls += 1
        now = datetime.now(UTC)
        return MAARunResult(
            status=MAARunStatus.COMPLETED,
            error_code=MAAErrorCode.OK,
            started_at=now,
            finished_at=now,
            duration_ms=0,
            pid=None,
            exit_code=0,
            termination_reason=TerminationReason.NORMAL_EXIT,
            owned_process_cleaned=True,
            stdout_excerpt="",
            stderr_excerpt="",
            stdout_truncated=False,
            stderr_truncated=False,
        )


class _SyntheticAalc:
    def __init__(self, ledger: IsolatedCallLedger) -> None:
        self._ledger = ledger

    def run(
        self,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
    ) -> AALCRunResult:
        del deadline, cancel
        self._ledger.aalc_run_calls += 1
        now = datetime.now(UTC)
        attempt = AALCAttemptResult(
            attempt_number=1,
            status=AALCAttemptStatus.COMPLETED,
            error_code=AALCErrorCode.OK,
            started_at=now,
            finished_at=now,
            duration_seconds=0.0,
            pid=None,
            exit_code=0,
            owned_process_cleaned=True,
        )
        return AALCRunResult(
            status=AALCRunStatus.COMPLETED,
            error_code=AALCErrorCode.OK,
            completion_mode=AALCCompletionMode.NORMAL_EXIT,
            started_at=now,
            finished_at=now,
            duration_seconds=0.0,
            configured_attempts=1,
            attempts_started=1,
            successful_attempt_number=1,
            attempt_results=(attempt,),
            diagnostics={"attempts_executed": 1, "successful_attempt": 1},
        )


def build_isolated_dependencies(
    ledger: IsolatedCallLedger | None = None,
) -> tuple[ProductionApplicationDependencies, IsolatedCallLedger]:
    """Build only in-process Runtime implementations."""

    selected = IsolatedCallLedger() if ledger is None else ledger

    def starrail_factory() -> StarRailRunPort:
        selected.starrail_factory_calls += 1
        return _SyntheticStarRail(selected)

    def maa_factory() -> MAARunPort:
        selected.maa_factory_calls += 1
        return _SyntheticMaa(selected)

    def aalc_factory() -> AALCRunPort:
        selected.aalc_factory_calls += 1
        return _SyntheticAalc(selected)

    def mumu_factory() -> MumuRuntimePort:
        selected.mumu_factory_calls += 1
        return _SyntheticMumu(selected)

    def poison_sync_factory() -> MAASyncPort:
        selected.maa_sync_factory_calls += 1
        raise IsolatedWorkflowError("ISOLATED_RUNTIME_CONTRACT_FAILED")

    def poison_update_factory() -> MAAUpdatePort:
        selected.maa_update_factory_calls += 1
        raise IsolatedWorkflowError("ISOLATED_RUNTIME_CONTRACT_FAILED")

    factories = RuntimeFactories(
        starrail=starrail_factory,
        maa=maa_factory,
        aalc=aalc_factory,
        mumu=mumu_factory,
        maa_sync=poison_sync_factory,
        maa_update=poison_update_factory,
    )
    dependencies = ProductionApplicationDependencies(
        elevation_gateway=_SyntheticElevationGateway(selected),
        runtime_factories=factories,
        workflow_mode=WorkflowMode.ISOLATED,
    )
    return dependencies, selected


def _validate_isolated_result(result: RunReport, workspace: Path) -> None:
    from autogame_orchestrator.run_application import EXTERNAL_RUN_STAGES

    if result.mode != WorkflowMode.ISOLATED.value:
        raise IsolatedWorkflowError("ISOLATED_REPORT_INVALID")
    if result.status != RunStatus.SUCCESS or result.error_code != ErrorCode.OK:
        raise IsolatedWorkflowError("ISOLATED_REPORT_INVALID")
    if tuple(item.stage for item in result.stages) != EXTERNAL_RUN_STAGES:
        raise IsolatedWorkflowError("ISOLATED_PLAN_INVALID")
    if any(item.outcome != OutcomeKind.SUCCESS or item.error_code != ErrorCode.OK for item in result.stages):
        raise IsolatedWorkflowError("ISOLATED_REPORT_INVALID")
    payload = json.dumps(result.to_json_encodable(), ensure_ascii=False)
    if str(workspace) in payload or "127.0.0.1:59999" in payload:
        raise IsolatedWorkflowError("ISOLATED_REPORT_INVALID")


def execute_isolated_workflow(
    workspace: Path,
    deadline_seconds: float,
    *,
    entry_runtime: EntryRuntime | None = None,
) -> IsolatedWorkflowResult:
    """Prepare a bounded synthetic workspace and reuse the formal run path."""

    deadline_error = validate_isolated_deadline(deadline_seconds)
    if deadline_error is not None:
        raise IsolatedWorkflowError(deadline_error)
    runtime = detect_entry_runtime() if entry_runtime is None else entry_runtime
    workspace_error = validate_isolated_workspace(workspace, runtime)
    if workspace_error is not None:
        raise IsolatedWorkflowError(workspace_error)
    workspace = workspace.resolve(strict=True)
    try:
        config_path = _build_synthetic_config(workspace)
    except (OSError, RuntimeError, ValueError):
        raise IsolatedWorkflowError("ISOLATED_CONFIG_BUILD_FAILED") from None
    _ensure_workspace_contents_confined(workspace)

    from autogame_orchestrator.run_application import RUN_CONFIRMATION, RunRequest, execute_run_request

    dependencies, ledger = build_isolated_dependencies()
    result = execute_run_request(
        RunRequest(
            config_path=config_path,
            deadline_seconds=deadline_seconds,
            confirmation=RUN_CONFIRMATION,
        ),
        dependencies=dependencies,
        entry_runtime=runtime,
    )
    _ensure_workspace_contents_confined(workspace)
    if result.report is None:
        raise IsolatedWorkflowError("ISOLATED_REPORT_INVALID")
    _validate_isolated_result(result.report, workspace)
    return IsolatedWorkflowResult(result.report, ledger, config_path)


__all__ = [
    "ISOLATED_WORKFLOW_CONFIRMATION",
    "MAX_ISOLATED_DEADLINE_SECONDS",
    "IsolatedCallLedger",
    "IsolatedWorkflowError",
    "IsolatedWorkflowResult",
    "build_isolated_dependencies",
    "execute_isolated_workflow",
    "validate_isolated_deadline",
    "validate_isolated_workspace",
]
