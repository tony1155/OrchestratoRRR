"""run v1 production composition 的完整 Fake 执行与 elevation 测试。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from autogame_orchestrator.entry_runtime import EntryRuntime, EntryRuntimeKind
from autogame_orchestrator.models import ErrorCode, OutcomeKind, RunStatus, StageName
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.run_application import RUN_CONFIRMATION, RunRequest, execute_run_request
from autogame_orchestrator.runtime.maa_models import MAARunStatus
from autogame_orchestrator.runtime.models import MumuRuntimeStatus
from autogame_orchestrator.runtime.starrail_models import StarRailRunStatus
from autogame_orchestrator.workflow.plan import ExecutionPlan
from autogame_orchestrator.workflow.production.application import default_production_dependencies
from autogame_orchestrator.workflow.runner import WorkflowRunner
from tests.run_application.helpers import fake_dependencies, write_run_config
from tests.workflow.fakes import (
    ElevationCode,
    FakeElevationGateway,
    FakeElevationResult,
    MemorySink,
    RecordingFactory,
)


def _request(path: Path, *, child: bool = False) -> RunRequest:
    return RunRequest(path, 30, RUN_CONFIRMATION, child)


def test_complete_fake_public_application_succeeds(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path)
    dependencies, counts, sink, logs, mumu, starrail, maa, aalc = fake_dependencies()
    result = execute_run_request(_request(config_path), dependencies=dependencies)

    assert (result.exit_code, result.status, result.error_code) == (0, "success", ErrorCode.OK.value)
    assert result.report is not None
    assert result.report.mode == "workflow_external"
    assert result.report.status == RunStatus.SUCCESS
    assert len(result.report.stages) == 10
    assert counts == {"mumu": 1, "starrail": 1, "maa": 1}
    assert (mumu.calls, starrail.calls, maa.calls, aalc.calls) == (2, 1, 1, 0)
    assert tuple(stage.stage for stage in result.report.stages[-2:]) == (
        StageName.RUN_MAA,
        StageName.WRITE_RUN_REPORT,
    )
    assert len(sink.reports) == 1
    assert len(logs) == 1 and logs[0].entered and logs[0].exited


def test_complete_fake_has_no_mumu_lifecycle_methods(tmp_path: Path) -> None:
    dependencies, _, _, _, mumu, *_ = fake_dependencies()
    execute_run_request(_request(write_run_config(tmp_path)), dependencies=dependencies)
    assert not hasattr(mumu, "start")
    assert not hasattr(mumu, "stop")
    assert not hasattr(mumu, "restart")


def test_complete_fake_does_not_run_legacy_aalc(tmp_path: Path) -> None:
    dependencies, _, _, _, _, _, _, aalc = fake_dependencies()
    result = execute_run_request(_request(write_run_config(tmp_path)), dependencies=dependencies)
    assert result.report is not None
    assert StageName.RUN_AALC not in {stage.stage for stage in result.report.stages}
    assert aalc.calls == 0


@pytest.mark.parametrize(
    ("status", "exit_code", "outcome"),
    [
        (MumuRuntimeStatus.STOPPED, 3, OutcomeKind.FAILURE),
        (MumuRuntimeStatus.NOT_READY, 3, OutcomeKind.FAILURE),
        (MumuRuntimeStatus.TIMEOUT, 4, OutcomeKind.TIMEOUT),
        (MumuRuntimeStatus.CANCELLED, 5, OutcomeKind.CANCELLED),
        (MumuRuntimeStatus.FAILED, 3, OutcomeKind.FAILURE),
    ],
)
def test_mumu_failure_exit_mapping(
    tmp_path: Path,
    status: MumuRuntimeStatus,
    exit_code: int,
    outcome: OutcomeKind,
) -> None:
    dependencies, counts, sink, _, mumu, starrail, maa, aalc = fake_dependencies(mumu_status=status)
    result = execute_run_request(_request(write_run_config(tmp_path)), dependencies=dependencies)
    assert result.exit_code == exit_code
    assert result.report is not None
    assert result.report.stages[3].outcome == outcome
    assert mumu.calls == 1
    assert (starrail.calls, maa.calls, aalc.calls) == (0, 0, 0)
    assert counts == {"mumu": 1}
    assert len(sink.reports) == 1


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (StarRailRunStatus.FAILED, 3),
        (StarRailRunStatus.TIMEOUT, 4),
        (StarRailRunStatus.CANCELLED, 5),
    ],
)
def test_starrail_failure_exit_mapping(tmp_path: Path, status: StarRailRunStatus, expected: int) -> None:
    dependencies, _, _, _, mumu, starrail, maa, aalc = fake_dependencies(starrail_status=status)
    result = execute_run_request(_request(write_run_config(tmp_path)), dependencies=dependencies)
    assert result.exit_code == expected
    assert (mumu.calls, starrail.calls, maa.calls, aalc.calls) == (2, 1, 0, 0)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (MAARunStatus.FAILED, 3),
        (MAARunStatus.TIMEOUT, 4),
        (MAARunStatus.CANCELLED, 5),
    ],
)
def test_maa_failure_exit_mapping(tmp_path: Path, status: MAARunStatus, expected: int) -> None:
    dependencies, _, _, _, _, _, maa, aalc = fake_dependencies(maa_status=status)
    result = execute_run_request(_request(write_run_config(tmp_path)), dependencies=dependencies)
    assert result.exit_code == expected
    assert (maa.calls, aalc.calls) == (1, 0)


def test_invalid_legacy_aalc_config_does_not_block_production_run(tmp_path: Path) -> None:
    dependencies, _, _, _, _, _, _, aalc = fake_dependencies()
    config_path = write_run_config(tmp_path, aalc_attempts=0)
    result = execute_run_request(_request(config_path), dependencies=dependencies)
    assert (result.exit_code, result.status, result.error_code) == (0, "success", ErrorCode.OK.value)
    assert aalc.calls == 0


def test_report_write_failure_maps_exit_seven(tmp_path: Path) -> None:
    dependencies, _, sink, _, *_ = fake_dependencies()
    sink.fail = True
    result = execute_run_request(_request(write_run_config(tmp_path)), dependencies=dependencies)
    assert (result.exit_code, result.error_code) == (7, ErrorCode.RUN_REPORT_WRITE_ERROR.value)
    assert len(sink.reports) == 1


def test_log_open_failure_stops_before_runtime(tmp_path: Path) -> None:
    dependencies, counts, sink, logs, *_ = fake_dependencies(fail_log_open=True)
    result = execute_run_request(_request(write_run_config(tmp_path)), dependencies=dependencies)
    assert (result.exit_code, result.error_code) == (8, ErrorCode.INTERNAL_ERROR.value)
    assert counts == {}
    assert sink.reports == []
    assert len(logs) == 1 and logs[0].entered is False


def test_safe_jsonl_events_contain_no_config_or_device(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path)
    dependencies, _, _, logs, *_ = fake_dependencies()
    execute_run_request(_request(config_path), dependencies=dependencies)
    text = json.dumps(logs[0].records, ensure_ascii=False)
    assert str(config_path) not in text
    assert "127.0.0.1:" + "16384" not in text
    assert "stdout secret" not in text
    assert "654321" not in text


def test_no_elevation_requirement_does_not_check_gateway(tmp_path: Path) -> None:
    dependencies, *_ = fake_dependencies(elevated=False)
    gateway = dependencies.elevation_gateway
    execute_run_request(_request(write_run_config(tmp_path)), dependencies=dependencies)
    assert gateway.check_calls == 0  # type: ignore[attr-defined]
    assert gateway.relaunch_calls == 0  # type: ignore[attr-defined]


def test_already_elevated_runs_without_relaunch(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path, aalc_requires_administrator=True)
    dependencies, counts, *_ = fake_dependencies(elevated=True)
    gateway = dependencies.elevation_gateway
    result = execute_run_request(_request(config_path), dependencies=dependencies)
    assert result.exit_code == 0
    assert gateway.relaunch_calls == 0  # type: ignore[attr-defined]
    assert counts["mumu"] == 1


def test_non_admin_relaunches_before_log_and_runtime(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path, aalc_requires_administrator=True)
    dependencies, counts, sink, logs, *_ = fake_dependencies(elevated=False)
    gateway = dependencies.elevation_gateway
    result = execute_run_request(_request(config_path), dependencies=dependencies)
    assert (result.exit_code, result.status) == (0, "success")
    assert gateway.relaunch_calls == 0  # type: ignore[attr-defined]
    assert counts["mumu"] == 1
    assert sink.reports
    assert logs and logs[0].entered


def test_frozen_non_admin_relaunch_uses_frozen_entry_spec(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path, aalc_requires_administrator=True)
    dependencies, counts, *_ = fake_dependencies(elevated=False)
    runtime = EntryRuntime(
        EntryRuntimeKind.FROZEN,
        tmp_path / "OrchestratoRRR.exe",
        tmp_path / "working directory",
    )
    runtime.working_directory.mkdir()

    result = execute_run_request(
        _request(config_path),
        dependencies=dependencies,
        entry_runtime=runtime,
    )

    gateway = dependencies.elevation_gateway
    assert (result.exit_code, result.status) == (0, "success")
    assert counts["mumu"] == 1
    assert gateway.spec is None  # type: ignore[attr-defined]


def test_uac_cancel_maps_exit_nine(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path, aalc_requires_administrator=True)
    dependencies, counts, *_ = fake_dependencies()
    gateway = FakeElevationGateway(
        elevated=False,
        result=FakeElevationResult(ElevationCode.CANCELLED, 9),
    )
    result = execute_run_request(_request(config_path), dependencies=replace(dependencies, elevation_gateway=gateway))
    assert (result.exit_code, result.error_code) == (0, ErrorCode.OK.value)
    assert counts["mumu"] == 1
    assert gateway.relaunch_calls == 0


def test_elevation_failure_maps_exit_ten(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path, aalc_requires_administrator=True)
    dependencies, counts, *_ = fake_dependencies()
    gateway = FakeElevationGateway(
        elevated=False,
        result=FakeElevationResult(ElevationCode.FAILED, 10),
    )
    result = execute_run_request(_request(config_path), dependencies=replace(dependencies, elevation_gateway=gateway))
    assert (result.exit_code, result.error_code) == (0, ErrorCode.OK.value)
    assert counts["mumu"] == 1
    assert gateway.relaunch_calls == 0


def test_elevated_child_exit_code_is_forwarded(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path, aalc_requires_administrator=True)
    dependencies, *_ = fake_dependencies()
    gateway = FakeElevationGateway(
        elevated=False,
        result=FakeElevationResult(ElevationCode.OK, 37),
    )
    result = execute_run_request(_request(config_path), dependencies=replace(dependencies, elevation_gateway=gateway))
    assert (result.exit_code, result.error_code) == (0, ErrorCode.OK.value)
    assert gateway.relaunch_calls == 0


def test_marker_prevents_recursive_elevation(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path, aalc_requires_administrator=True)
    dependencies, counts, *_ = fake_dependencies(elevated=False)
    gateway = dependencies.elevation_gateway
    result = execute_run_request(_request(config_path, child=True), dependencies=dependencies)
    assert (result.exit_code, result.error_code) == (0, ErrorCode.OK.value)
    assert gateway.relaunch_calls == 0  # type: ignore[attr-defined]
    assert counts["mumu"] == 1


def test_cancellation_token_identity_reaches_runtime(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path)
    dependencies, _, _, _, mumu, starrail, *_ = fake_dependencies()
    token = CancellationToken()
    execute_run_request(_request(config_path), cancel=token, dependencies=dependencies)
    assert mumu.cancel is token
    assert starrail.cancel is token


def test_parent_deadline_identity_reaches_every_runtime(tmp_path: Path) -> None:
    dependencies, _, _, _, mumu, starrail, maa, _ = fake_dependencies()
    execute_run_request(_request(write_run_config(tmp_path)), dependencies=dependencies)
    assert mumu.deadline is starrail.deadline
    assert starrail.deadline is maa.deadline


def test_pre_cancel_still_writes_one_report_without_runtime(tmp_path: Path) -> None:
    dependencies, counts, sink, _, *_ = fake_dependencies()
    token = CancellationToken()
    token.cancel()
    result = execute_run_request(
        _request(write_run_config(tmp_path)),
        cancel=token,
        dependencies=dependencies,
    )
    assert result.exit_code == 5
    assert counts == {}
    assert len(sink.reports) == 1


def test_run_report_has_no_machine_or_output_values(tmp_path: Path) -> None:
    config_path = write_run_config(tmp_path)
    dependencies, *_ = fake_dependencies()
    result = execute_run_request(_request(config_path), dependencies=dependencies)
    assert result.report is not None
    text = json.dumps(result.report.to_json_encodable(), ensure_ascii=False)
    for forbidden in (
        str(config_path),
        "127.0.0.1:" + "16384",
        "stdout secret",
        "stderr secret",
        "654321",
    ):
        assert forbidden not in text


def test_runner_default_mode_remains_workflow_fake() -> None:
    plan = ExecutionPlan((StageName.VALIDATE_CONFIG, StageName.WRITE_RUN_REPORT), False)
    report = WorkflowRunner(plan, RecordingFactory(), MemorySink()).run()
    assert report.mode == "workflow_fake"


def test_runner_rejects_unstable_mode() -> None:
    plan = ExecutionPlan((StageName.VALIDATE_CONFIG, StageName.WRITE_RUN_REPORT), False)
    with pytest.raises(ValueError, match="mode"):
        WorkflowRunner(plan, RecordingFactory(), MemorySink(), mode="user-controlled")


def test_default_composition_construction_has_no_external_effect() -> None:
    dependencies = default_production_dependencies()
    assert dependencies.runtime_factories is None
