"""Independent games continue after failures; prerequisites and cancellation remain effective."""

import json
from dataclasses import replace

import pytest

from autogame_orchestrator.bettergi_config import BetterGIConfig
from autogame_orchestrator.config_loader import _parse_orchestrator
from autogame_orchestrator.config_model import AppConfig, FgoConfig, MumuLifecycleMode
from autogame_orchestrator.models import ErrorCode, OutcomeKind, RunStatus
from autogame_orchestrator.models import StageName as S
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.workflow.plan import build_execution_plan
from autogame_orchestrator.workflow.production.dependencies import production_stage_dependencies
from autogame_orchestrator.workflow.production.factory import build_production_executor_factory
from autogame_orchestrator.workflow.production.report_sink import ProductionReportSink
from autogame_orchestrator.workflow.runner import WorkflowRunner
from tests.workflow.fakes import FakeExecutor, MemorySink, RecordingFactory, make_stage_report


def make_plan(mode=MumuLifecycleMode.MANAGED):
    config = AppConfig(fgo=FgoConfig(append_to_workflow=True), bettergi=BetterGIConfig(enabled=True))
    return build_execution_plan(replace(config, mumu=replace(config.mumu, lifecycle_mode=mode)))


def make_runner(factory, *, plan=None, sink=None):
    selected = plan or make_plan()
    return WorkflowRunner(
        selected,
        factory,
        sink or MemorySink(),
        continue_on_failure=True,
        stage_dependencies=production_stage_dependencies(selected),
    )


def fail(factory, stage, outcome=OutcomeKind.FAILURE):
    factory.executors[stage] = FakeExecutor(
        lambda ctx: make_stage_report(ctx.stage, outcome, ErrorCode.WORKFLOW_STAGE_FAILED)
    )


@pytest.mark.parametrize("mode", list(MumuLifecycleMode))
@pytest.mark.parametrize("stage", [S.RUN_STARRAIL, S.RUN_MAA, S.RUN_MAAFGO, S.STOP_FGO, S.SHUTDOWN_MUMU])
def test_failed_game_does_not_block_later_independent_games(mode, stage):
    plan = make_plan(mode)
    if stage not in plan.stages:
        return
    factory = RecordingFactory()
    fail(factory, stage)
    report = make_runner(factory, plan=plan).run(deadline=Deadline.after(10))
    assert report.status == RunStatus.FAILURE
    assert S.RUN_BETTERGI in factory.calls
    if stage in {S.RUN_STARRAIL, S.RUN_MAA}:
        assert S.RUN_MAAFGO in factory.calls
    assert report.diagnostics["failed_stage_count"] == 1


@pytest.mark.parametrize("stage", [S.SYNC_MAA_CONFIG, S.UPDATE_MAA, S.MERGE_MAA_RESOURCE])
def test_maa_preparation_failure_skips_maa_but_runs_fgo_and_bettergi(stage):
    factory = RecordingFactory()
    fail(factory, stage)
    report = make_runner(factory).run()
    assert S.RUN_MAA not in factory.calls
    assert S.RUN_MAAFGO in factory.calls and S.RUN_BETTERGI in factory.calls
    assert next(r for r in report.stages if r.stage == S.RUN_MAA).diagnostics["blocked_by"]


def test_fgo_prepare_failure_does_not_launch_cli_or_block_shutdown():
    factory = RecordingFactory()
    fail(factory, S.PREPARE_MAAFGO_RUN)
    make_runner(factory).run()
    assert S.RUN_MAAFGO not in factory.calls
    assert S.SHUTDOWN_MUMU in factory.calls and S.RUN_BETTERGI in factory.calls


def test_emulator_failure_skips_dependent_games_but_runs_bettergi():
    factory = RecordingFactory()
    fail(factory, S.START_MUMU)
    make_runner(factory).run()
    assert S.RUN_MAA not in factory.calls and S.RUN_MAAFGO not in factory.calls
    assert S.RUN_BETTERGI in factory.calls


@pytest.mark.parametrize("kind", ["exception", "missing", "timeout", "invalid"])
def test_other_failure_forms_also_continue(kind):
    factory = RecordingFactory()
    if kind == "exception":
        factory.factory_error.add(S.RUN_MAA)
    elif kind == "missing":
        factory.missing.add(S.RUN_MAA)
    elif kind == "timeout":
        fail(factory, S.RUN_MAA, OutcomeKind.TIMEOUT)
    else:
        factory.executors[S.RUN_MAA] = FakeExecutor(lambda ctx: None)
    report = make_runner(factory).run()
    assert report.status == RunStatus.FAILURE
    assert S.RUN_MAAFGO in factory.calls and S.RUN_BETTERGI in factory.calls


def test_multiple_failures_are_retained_and_report_is_written(tmp_path):
    factory = RecordingFactory()
    for stage in (S.RUN_STARRAIL, S.RUN_MAA, S.RUN_MAAFGO, S.RUN_BETTERGI):
        fail(factory, stage)
    report = make_runner(factory, sink=ProductionReportSink(str(tmp_path))).run()
    assert report.status == RunStatus.FAILURE
    assert report.diagnostics["failed_stage_count"] == 4
    saved = json.loads(next(tmp_path.glob("run-report-*.json")).read_text("utf-8"))
    assert [r["stage"] for r in saved["stages"] if r["outcome"] == "failure"] == [
        "run_starrail",
        "run_maa",
        "run_maafgo",
        "run_bettergi",
    ]


@pytest.mark.parametrize("stop", ["cancel", "deadline", "invalid_config"])
def test_explicit_stop_or_global_deadline_still_ends_run(stop):
    factory = RecordingFactory()
    token = CancellationToken()
    deadline = Deadline.after(30)

    def stop_here(ctx):
        if stop == "cancel":
            token.cancel()
        elif stop == "deadline":
            deadline._target = 0
        return make_stage_report(ctx.stage)

    if stop == "invalid_config":
        fail(factory, S.VALIDATE_CONFIG)
    else:
        factory.executors[S.RUN_MAA] = FakeExecutor(stop_here)
    report = make_runner(factory).run(cancel=token, deadline=deadline)
    assert S.RUN_MAAFGO not in factory.calls and S.RUN_BETTERGI not in factory.calls
    assert report.status != RunStatus.SUCCESS


@pytest.mark.parametrize("value", [True, False, "true", 1])
def test_continue_flag_requires_a_real_boolean(value):
    config, errors = _parse_orchestrator({"log_dir": "logs", "report_dir": "reports", "continue_on_failure": value})
    assert bool(errors) is (type(value) is not bool)
    if config is not None:
        assert config.continue_on_failure is value


@pytest.mark.parametrize("leaked", ["starrail", "maa"])
def test_uncleaned_process_blocks_shared_device_but_not_bettergi(leaked):
    config = AppConfig()
    config = replace(config, orchestrator=replace(config.orchestrator, continue_on_failure=True))
    factory = build_production_executor_factory(config)
    if leaked == "starrail":
        factory.state.starrail_run_reached = True
        factory.state.starrail_owned_process_cleaned = False
    else:
        factory.state.maa_run_reached = True
        factory.state.maa_owned_process_cleaned = False
    from autogame_orchestrator.workflow.contracts import StageExecutionContext

    report = factory(S.PREPARE_MAAFGO_RUN).execute(
        StageExecutionContext("test", S.PREPARE_MAAFGO_RUN, Deadline.after(10), CancellationToken())
    )
    assert report.error_code == ErrorCode.WORKFLOW_STAGE_BLOCKED
