"""WorkflowRunner 的 fail-fast、预算和报告最终化测试。"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from autogame_orchestrator.models import ErrorCode, OutcomeKind, RunStatus, StageName, StageReport
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.reporter import validate_run_report_json
from autogame_orchestrator.workflow.plan import ExecutionPlan
from autogame_orchestrator.workflow.runner import WorkflowRunner
from tests.workflow.fakes import FakeExecutor, MemorySink, RecordingFactory, make_stage_report

STAGES = (
    StageName.VALIDATE_CONFIG,
    StageName.RUN_MAA,
    StageName.RUN_AALC,
    StageName.WRITE_RUN_REPORT,
)


def make_runner(
    factory: RecordingFactory | None = None,
    sink: MemorySink | None = None,
    *,
    event_sink=None,
) -> tuple[WorkflowRunner, RecordingFactory, MemorySink]:
    selected_factory = factory or RecordingFactory()
    selected_sink = sink or MemorySink()
    runner = WorkflowRunner(
        ExecutionPlan(STAGES, False),
        selected_factory,
        selected_sink,
        event_sink=event_sink,
    )
    return runner, selected_factory, selected_sink


def test_all_success_returns_success() -> None:
    report = make_runner()[0].run()
    assert report.status == RunStatus.SUCCESS
    assert report.error_code == ErrorCode.OK


def test_stage_reports_follow_plan_order() -> None:
    report = make_runner()[0].run()
    assert tuple(item.stage for item in report.stages) == STAGES


def test_factory_is_lazy_and_ordered() -> None:
    runner, factory, _ = make_runner()
    assert factory.calls == []
    runner.run()
    assert factory.calls == list(STAGES[:-1])


def test_write_report_never_requests_executor() -> None:
    runner, factory, _ = make_runner()
    runner.run()
    assert StageName.WRITE_RUN_REPORT not in factory.calls


def test_each_reached_factory_is_called_once() -> None:
    runner, factory, _ = make_runner()
    runner.run()
    assert all(factory.calls.count(stage) == 1 for stage in STAGES[:-1])


def test_run_id_is_shared_by_all_stages() -> None:
    runner, factory, _ = make_runner()
    run_id = str(uuid.uuid4())
    runner.run(run_id=run_id)
    contexts = [context for executor in factory.executors.values() for context in executor.contexts]
    assert {context.run_id for context in contexts} == {run_id}


def test_cancellation_token_instance_is_shared() -> None:
    runner, factory, _ = make_runner()
    token = CancellationToken()
    runner.run(cancel=token)
    assert all(executor.contexts[0].cancel is token for executor in factory.executors.values())


def test_parent_deadline_instance_is_shared() -> None:
    runner, factory, _ = make_runner()
    deadline = Deadline.after(30)
    runner.run(deadline=deadline)
    assert all(executor.contexts[0].deadline is deadline for executor in factory.executors.values())


@pytest.mark.parametrize("failed_stage", STAGES[:-1])
def test_failure_at_any_business_position_is_fail_fast(failed_stage: StageName) -> None:
    factory = RecordingFactory()
    factory.executors[failed_stage] = FakeExecutor(
        lambda context: make_stage_report(
            context.stage,
            OutcomeKind.FAILURE,
            ErrorCode.CONFIG_SCHEMA_ERROR,
        )
    )
    runner, _, _ = make_runner(factory)
    report = runner.run()
    assert report.status == RunStatus.FAILURE
    assert report.error_code == ErrorCode.WORKFLOW_STAGE_FAILED
    assert factory.calls == list(STAGES[: STAGES.index(failed_stage) + 1])


def test_remaining_business_stages_are_omitted_after_failure() -> None:
    factory = RecordingFactory()
    factory.executors[StageName.RUN_MAA] = FakeExecutor(
        lambda context: make_stage_report(context.stage, OutcomeKind.FAILURE, ErrorCode.CONFIG_SCHEMA_ERROR)
    )
    report = make_runner(factory)[0].run()
    assert report.stages[2].outcome == OutcomeKind.SKIPPED
    assert report.stages[2].error_code == ErrorCode.SKIPPED


def test_stage_timeout_is_preserved() -> None:
    factory = RecordingFactory()
    factory.executors[StageName.RUN_MAA] = FakeExecutor(
        lambda context: make_stage_report(context.stage, OutcomeKind.TIMEOUT, ErrorCode.INTERNAL_ERROR)
    )
    report = make_runner(factory)[0].run()
    assert report.error_code == ErrorCode.WORKFLOW_STAGE_TIMEOUT
    assert report.stages[1].outcome == OutcomeKind.TIMEOUT


def test_pre_cancel_constructs_no_business_executor() -> None:
    token = CancellationToken()
    token.cancel()
    runner, factory, _ = make_runner()
    report = runner.run(cancel=token)
    assert factory.calls == []
    assert report.status == RunStatus.CANCELLED
    assert all(item.outcome == OutcomeKind.SKIPPED for item in report.stages[:-1])


def test_cancellation_inside_stage_is_not_timeout() -> None:
    token = CancellationToken()
    factory = RecordingFactory()

    def cancel_stage(context):
        token.cancel()
        return make_stage_report(context.stage, OutcomeKind.CANCELLED, ErrorCode.INTERNAL_ERROR)

    factory.executors[StageName.RUN_MAA] = FakeExecutor(cancel_stage)
    report = make_runner(factory)[0].run(cancel=token)
    assert report.status == RunStatus.CANCELLED
    assert report.error_code == ErrorCode.WORKFLOW_CANCELLED
    assert report.stages[1].outcome == OutcomeKind.CANCELLED


def test_expired_deadline_constructs_no_executor() -> None:
    runner, factory, _ = make_runner()
    report = runner.run(deadline=Deadline.at(0))
    assert factory.calls == []
    assert report.stages[0].outcome == OutcomeKind.TIMEOUT
    assert report.error_code == ErrorCode.WORKFLOW_STAGE_TIMEOUT


def test_deadline_expiring_between_stages_stops_construction() -> None:
    deadline = Deadline.after(30)
    factory = RecordingFactory()

    def expire(context):
        deadline._target = 0  # noqa: SLF001
        return make_stage_report(context.stage)

    factory.executors[StageName.VALIDATE_CONFIG] = FakeExecutor(expire)
    report = make_runner(factory)[0].run(deadline=deadline)
    assert factory.calls == [StageName.VALIDATE_CONFIG]
    assert report.stages[1].outcome == OutcomeKind.TIMEOUT


def test_missing_executor_is_structured() -> None:
    factory = RecordingFactory()
    factory.missing.add(StageName.RUN_MAA)
    report = make_runner(factory)[0].run()
    assert report.error_code == ErrorCode.WORKFLOW_EXECUTOR_NOT_REGISTERED
    assert report.stages[1].error_code == ErrorCode.WORKFLOW_EXECUTOR_NOT_REGISTERED


def test_factory_exception_is_internal_error() -> None:
    factory = RecordingFactory()
    factory.factory_error.add(StageName.RUN_MAA)
    report = make_runner(factory)[0].run()
    assert report.error_code == ErrorCode.INTERNAL_ERROR


def test_executor_exception_is_internal_error() -> None:
    factory = RecordingFactory()
    factory.executors[StageName.RUN_MAA] = FakeExecutor(lambda context: (_ for _ in ()).throw(RuntimeError()))
    report = make_runner(factory)[0].run()
    assert report.error_code == ErrorCode.INTERNAL_ERROR
    assert report.stages[1].error_code == ErrorCode.INTERNAL_ERROR


def test_wrong_result_type_is_rejected() -> None:
    factory = RecordingFactory()
    factory.executors[StageName.RUN_MAA] = FakeExecutor(lambda context: "not-a-report")
    report = make_runner(factory)[0].run()
    assert report.error_code == ErrorCode.WORKFLOW_STAGE_RESULT_INVALID


def test_wrong_stage_name_is_rejected() -> None:
    factory = RecordingFactory()
    factory.executors[StageName.RUN_MAA] = FakeExecutor(lambda context: make_stage_report(StageName.RUN_AALC))
    report = make_runner(factory)[0].run()
    assert report.stages[1].error_code == ErrorCode.WORKFLOW_STAGE_RESULT_INVALID


def test_invalid_success_error_pair_is_rejected_at_runner_boundary() -> None:
    bad = object.__new__(StageReport)
    now = datetime.now(UTC)
    for name, value in {
        "stage": StageName.RUN_MAA,
        "outcome": OutcomeKind.SUCCESS,
        "error_code": ErrorCode.INTERNAL_ERROR,
        "started_at": now,
        "finished_at": now,
        "duration_ms": 0,
        "message": "",
        "diagnostics": {},
    }.items():
        object.__setattr__(bad, name, value)
    factory = RecordingFactory()
    factory.executors[StageName.RUN_MAA] = FakeExecutor(lambda context: bad)
    assert make_runner(factory)[0].run().error_code == ErrorCode.WORKFLOW_STAGE_RESULT_INVALID


def test_report_sink_is_attempted_exactly_once_on_success() -> None:
    runner, _, sink = make_runner()
    runner.run()
    assert len(sink.reports) == 1


def test_report_sink_is_attempted_exactly_once_on_business_failure() -> None:
    factory = RecordingFactory()
    factory.missing.add(StageName.VALIDATE_CONFIG)
    runner, _, sink = make_runner(factory)
    runner.run()
    assert len(sink.reports) == 1


def test_report_write_failure_becomes_top_level_error() -> None:
    sink = MemorySink(fail=True)
    report = make_runner(sink=sink)[0].run()
    assert report.status == RunStatus.FAILURE
    assert report.error_code == ErrorCode.RUN_REPORT_WRITE_ERROR
    assert report.stages[-1].error_code == ErrorCode.RUN_REPORT_WRITE_ERROR


def test_business_error_is_retained_when_report_write_fails() -> None:
    factory = RecordingFactory()
    factory.missing.add(StageName.VALIDATE_CONFIG)
    report = make_runner(factory, MemorySink(fail=True))[0].run()
    assert report.error_code == ErrorCode.RUN_REPORT_WRITE_ERROR
    assert report.diagnostics["source_error_code"] == ErrorCode.WORKFLOW_EXECUTOR_NOT_REGISTERED.value


def test_candidate_report_records_successful_write_stage() -> None:
    runner, _, sink = make_runner()
    runner.run()
    assert sink.reports[0].stages[-1].outcome == OutcomeKind.SUCCESS


def test_event_fields_are_json_serializable() -> None:
    events = []
    make_runner(event_sink=events.append)[0].run()
    json.dumps(events)
    assert len(events) == len(STAGES)


def test_event_sink_failure_does_not_retry_or_fail_workflow() -> None:
    calls = 0

    def broken_event(event):
        nonlocal calls
        calls += 1
        raise RuntimeError

    report = make_runner(event_sink=broken_event)[0].run()
    assert report.status == RunStatus.SUCCESS
    assert calls == len(STAGES)


def test_report_is_json_serializable() -> None:
    json.dumps(make_runner()[0].run().to_json_encodable())


def test_workflow_report_validates_against_run_report_v1() -> None:
    factory = RecordingFactory()
    factory.missing.add(StageName.RUN_MAA)
    valid, message = validate_run_report_json(make_runner(factory)[0].run().to_json_encodable())
    assert valid, message


def test_runner_contains_no_whole_workflow_retry() -> None:
    runner, factory, _ = make_runner()
    runner.run()
    assert sum(executor.calls for executor in factory.executors.values()) == len(STAGES) - 1
