"""Phase 7B2A tests for the hidden, in-process isolated workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autogame_orchestrator.cli import app
from autogame_orchestrator.diagnostics.packaged_isolated_workflow import (
    ISOLATED_WORKFLOW_CONFIRMATION,
    MAX_ISOLATED_DEADLINE_SECONDS,
    execute_isolated_workflow,
    validate_isolated_deadline,
    validate_isolated_workspace,
)
from autogame_orchestrator.models import ErrorCode, OutcomeKind, RunStatus, WorkflowMode
from autogame_orchestrator.reporter import validate_run_report_json
from autogame_orchestrator.workflow.production.application import ProductionApplicationDependencies
from autogame_orchestrator.workflow.production.factory import build_production_executor_factory
from autogame_orchestrator.workflow.production.ports import RuntimeFactories

runner = CliRunner()


def _isolated_args(workspace: Path, confirmation: str = ISOLATED_WORKFLOW_CONFIRMATION) -> list[str]:
    return [
        "_isolated-workflow-smoke",
        "--workspace",
        str(workspace),
        "--deadline-seconds",
        "30",
        "--confirm-isolated-execution",
        confirmation,
    ]


def test_isolated_workflow_reuses_formal_external_runner_and_reports(tmp_path: Path) -> None:
    workspace = tmp_path / "empty"
    workspace.mkdir()

    result = execute_isolated_workflow(workspace, 30.0)

    from autogame_orchestrator.run_application import EXTERNAL_RUN_STAGES

    assert result.report.mode == WorkflowMode.ISOLATED.value
    assert result.report.status == RunStatus.SUCCESS
    assert result.report.error_code == ErrorCode.OK
    assert tuple(item.stage for item in result.report.stages) == EXTERNAL_RUN_STAGES
    assert len(result.report.stages) == 11
    assert all(item.outcome == OutcomeKind.SUCCESS and item.error_code == ErrorCode.OK for item in result.report.stages)

    sync_stage = result.report.stages[1]
    update_stage = result.report.stages[2]
    merge_stage = result.report.stages[3]
    assert sync_stage.diagnostics == {"enabled": False, "changed": False}
    assert update_stage.diagnostics == {"enabled": False, "executed": False}
    assert merge_stage.diagnostics == {"enabled": False, "executed": False}
    for index in (4, 5):
        assert result.report.stages[index].diagnostics["source_status"] == "ready"
        assert result.report.stages[index].diagnostics["source_error_code"] == "OK"
    for index in (7, 8):
        assert result.report.stages[index].diagnostics["owned_process_cleaned"] is True
    assert result.report.stages[9].diagnostics["owned_process_cleaned"] is True
    assert result.report.stages[9].stage.value == "run_maa"
    assert result.report.stages[10].stage.value == "write_run_report"

    ledger = result.ledger
    assert ledger.elevation_is_elevated_calls == 0
    assert ledger.elevation_relaunch_calls == 0
    assert ledger.default_runtime_factory_calls == 0
    assert ledger.process_launch_calls == 0
    assert ledger.tcp_probe_calls == 0
    assert ledger.adb_calls == 0
    assert ledger.mumu_factory_calls == 1
    assert ledger.mumu_ensure_external_ready_calls == 1
    assert ledger.mumu_status_calls == 1
    assert ledger.starrail_factory_calls == 1
    assert ledger.starrail_run_calls == 1
    assert ledger.maa_factory_calls == 1
    assert ledger.maa_run_calls == 1
    assert ledger.aalc_factory_calls == 0
    assert ledger.aalc_run_calls == 0
    assert ledger.maa_sync_factory_calls == 0
    assert ledger.maa_update_factory_calls == 0
    assert ledger.forbidden_calls == 0

    reports = list((workspace / "run-results").glob("run-report-*.json"))
    logs = list((workspace / "logs").glob("run-*.jsonl"))
    assert len(reports) == 1
    assert len(logs) == 1
    payload = json.loads(reports[0].read_text(encoding="utf-8"))
    valid, message = validate_run_report_json(payload)
    assert valid, message
    assert payload["mode"] == "workflow_isolated"
    log_records = [json.loads(line) for line in logs[0].read_text(encoding="utf-8").splitlines()]
    assert sum(record["event"] == "workflow.start" for record in log_records) == 1
    assert sum(record["event"] == "workflow.stage.finished" for record in log_records) == 11
    assert all(str(workspace) not in json.dumps(record, ensure_ascii=False) for record in log_records)
    assert str(workspace) not in reports[0].read_text(encoding="utf-8")

    assert {item.name for item in workspace.iterdir()} == {
        "synthetic-config.toml",
        "synthetic-bin",
        "synthetic-work",
        "logs",
        "run-results",
    }


def test_isolated_command_is_hidden_but_runs_formal_source_path(tmp_path: Path) -> None:
    workspace = tmp_path / "empty"
    workspace.mkdir()

    result = runner.invoke(app, _isolated_args(workspace))

    assert result.exit_code == 0
    assert result.stdout.strip() == (
        "Isolated workflow completed: status=success error_code=OK mode=workflow_isolated stages=11 forbidden_calls=0"
    )

    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "_isolated-workflow-smoke" not in help_result.stdout
    assert "--_elevation-child" not in help_result.stdout
    for command in ("version", "validate", "plan", "run"):
        assert command in help_result.stdout


def test_wrong_isolated_confirmation_is_fail_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "empty"
    workspace.mkdir()

    result = runner.invoke(app, _isolated_args(workspace, "I_UNDERSTAND_THIS_RUNS_REAL_PROGRAMS"))

    assert result.exit_code == 2
    assert "ISOLATED_CONFIRMATION_REQUIRED" in result.stderr
    assert list(workspace.iterdir()) == []
    assert str(workspace) not in result.output


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), float("-inf"), 120.1, True, False, "30", None])
def test_isolated_deadline_is_strictly_bounded(value: object) -> None:
    assert validate_isolated_deadline(value) == "ISOLATED_DEADLINE_INVALID"


def test_isolated_deadline_limit_is_lower_than_public_run_limit() -> None:
    assert MAX_ISOLATED_DEADLINE_SECONDS == 120.0
    assert validate_isolated_deadline(MAX_ISOLATED_DEADLINE_SECONDS) is None


def test_workspace_safety_rejects_invalid_shapes(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert validate_isolated_workspace(missing) == "ISOLATED_WORKSPACE_INVALID"

    file_path = tmp_path / "file"
    file_path.write_text("x", encoding="utf-8")
    assert validate_isolated_workspace(file_path) == "ISOLATED_WORKSPACE_INVALID"

    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "user-file").write_text("x", encoding="utf-8")
    assert validate_isolated_workspace(nonempty) == "ISOLATED_WORKSPACE_NOT_EMPTY"

    relative = Path("relative-isolated-workspace")
    assert validate_isolated_workspace(relative) == "ISOLATED_WORKSPACE_INVALID"
    assert validate_isolated_workspace(Path.cwd()) == "ISOLATED_WORKSPACE_INVALID"

    bundle = tmp_path / "dist" / "OrchestratoRRR"
    bundle.mkdir(parents=True)
    assert validate_isolated_workspace(bundle) == "ISOLATED_WORKSPACE_INVALID"

    build = tmp_path / "build" / "pyinstaller"
    build.mkdir(parents=True)
    assert validate_isolated_workspace(build) == "ISOLATED_WORKSPACE_INVALID"


def test_symlink_workspace_is_rejected_when_supported(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable in this environment")
    assert validate_isolated_workspace(link) == "ISOLATED_WORKSPACE_INVALID"


def test_isolated_success_does_not_touch_default_runtime_or_platform_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from autogame_orchestrator.probes import adb_client, tcp
    from autogame_orchestrator.process import supervisor
    from autogame_orchestrator.workflow.production import application, runtime_bindings

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("forbidden boundary called")

    monkeypatch.setattr(runtime_bindings, "build_default_runtime_factories", forbidden)
    monkeypatch.setattr(application, "default_production_dependencies", forbidden)
    monkeypatch.setattr(application, "WindowsElevationGateway", forbidden)
    monkeypatch.setattr(supervisor.ProcessSupervisor, "run", forbidden)
    monkeypatch.setattr(tcp, "probe_tcp_endpoint", forbidden)
    monkeypatch.setattr(adb_client.AdbClient, "_run_adb_command", forbidden)

    workspace = tmp_path / "empty"
    workspace.mkdir()
    result = execute_isolated_workflow(workspace, 30.0)

    assert result.report.mode == "workflow_isolated"
    assert result.ledger.forbidden_calls == 0


def test_default_production_dependency_mode_is_external() -> None:
    assert ProductionApplicationDependencies.__dataclass_fields__["workflow_mode"].default == WorkflowMode.EXTERNAL


def test_production_executor_factory_remains_injection_only() -> None:
    assert build_production_executor_factory.__module__.endswith("production.factory")
    assert RuntimeFactories.__module__.endswith("production.ports")
