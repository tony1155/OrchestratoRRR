from dataclasses import replace
from datetime import UTC, datetime

import pytest

from autogame_orchestrator.bettergi_config import BetterGIConfig
from autogame_orchestrator.config_model import AppConfig, MumuLifecycleMode
from autogame_orchestrator.models import OutcomeKind, StageName
from autogame_orchestrator.process import CancellationToken, Deadline
from autogame_orchestrator.run_application import validate_external_plan
from autogame_orchestrator.runtime.bettergi_models import BetterGIErrorCode as Code
from autogame_orchestrator.runtime.bettergi_models import BetterGIRunResult
from autogame_orchestrator.runtime.bettergi_models import BetterGIRunStatus as Status
from autogame_orchestrator.workflow.contracts import StageExecutionContext
from autogame_orchestrator.workflow.plan import build_execution_plan
from autogame_orchestrator.workflow.production.factory import build_production_executor_factory
from autogame_orchestrator.workflow.production.runtime_bindings import build_default_runtime_factories


@pytest.mark.parametrize("mode", list(MumuLifecycleMode))
def test_optional_plan_order_and_elevation(mode):
    config = AppConfig()
    config = replace(config, mumu=replace(config.mumu, lifecycle_mode=mode))
    original = build_execution_plan(config)
    assert StageName.RUN_BETTERGI not in original.stages
    enabled = replace(config, bettergi=BetterGIConfig(enabled=True))
    plan = build_execution_plan(enabled)
    assert plan.stages == (*original.stages[:-1], StageName.RUN_BETTERGI, StageName.WRITE_RUN_REPORT)
    assert plan.requires_administrator
    assert validate_external_plan(plan) is None
    if mode == MumuLifecycleMode.MANAGED:
        assert plan.stages[-3] == StageName.SHUTDOWN_MUMU


@pytest.mark.parametrize(
    "status,code,outcome",
    [
        (Status.COMPLETED, Code.OK, OutcomeKind.SUCCESS),
        (Status.FAILED, Code.COMPLETION_UNCONFIRMED, OutcomeKind.FAILURE),
        (Status.TIMEOUT, Code.TASK_TIMEOUT, OutcomeKind.TIMEOUT),
        (Status.CANCELLED, Code.CANCELLED, OutcomeKind.CANCELLED),
    ],
)
def test_lazy_binding_projection_and_budget(status, code, outcome):
    now = datetime.now(UTC)
    success = status == Status.COMPLETED
    result = BetterGIRunResult(status, code, now, now, 0, 0 if success else None, True, success, success)
    config = replace(AppConfig(), bettergi=BetterGIConfig(enabled=True))
    calls = []

    class Fake:
        def run(self, deadline, cancel):
            calls.append((deadline, cancel))
            return result

    def build():
        calls.append("build")
        return Fake()

    factories = replace(build_default_runtime_factories(config), bettergi=build)
    factory = build_production_executor_factory(config, runtime_factories=factories)
    executor = factory(StageName.RUN_BETTERGI)
    assert not calls
    deadline, token = Deadline.after(2), CancellationToken()
    report = executor.execute(StageExecutionContext("fake-run", StageName.RUN_BETTERGI, deadline, token))
    assert calls == ["build", (deadline, token)]
    assert report.outcome == outcome
    assert report.diagnostics["source_error_code"] == code.value
    assert "pid" not in report.diagnostics and "config_name" not in report.diagnostics


def test_disabled_explicit_stage_does_not_launch():
    config = AppConfig()
    factory = build_production_executor_factory(config)
    report = factory(StageName.RUN_BETTERGI).execute(
        StageExecutionContext("fake-run", StageName.RUN_BETTERGI, Deadline.after(2), CancellationToken())
    )
    assert report.outcome == OutcomeKind.FAILURE


@pytest.mark.parametrize("fail_stage", [None, StageName.RUN_MAA, StageName.RUN_BETTERGI])
def test_workflow_order_failure_propagation_and_report_schema(fail_stage):
    from autogame_orchestrator.models import ErrorCode, RunStatus
    from autogame_orchestrator.reporter import validate_run_report_json
    from autogame_orchestrator.workflow.runner import WorkflowRunner
    from tests.workflow.fakes import FakeExecutor, MemorySink, RecordingFactory, make_stage_report

    config = replace(AppConfig(), bettergi=BetterGIConfig(enabled=True))
    config = replace(config, mumu=replace(config.mumu, lifecycle_mode=MumuLifecycleMode.MANAGED))
    plan = build_execution_plan(config)
    factory = RecordingFactory()
    if fail_stage is not None:
        factory.executors[fail_stage] = FakeExecutor(
            lambda ctx: make_stage_report(ctx.stage, OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED)
        )
    sink = MemorySink()
    report = WorkflowRunner(plan, factory, sink).run(deadline=Deadline.after(10))
    assert report.status == (RunStatus.SUCCESS if fail_stage is None else RunStatus.FAILURE)
    assert bool(StageName.RUN_BETTERGI in factory.calls) == (fail_stage != StageName.RUN_MAA)
    assert sink.reports == [report]
    assert validate_run_report_json(report.to_json_encodable())[0]
