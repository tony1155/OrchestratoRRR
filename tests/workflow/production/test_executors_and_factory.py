"""生产 StageExecutor、惰性 Runtime factory 和状态隔离测试。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from autogame_orchestrator.config_model import AppConfig, MuMuConfig, MumuLifecycleMode
from autogame_orchestrator.models import ErrorCode, OutcomeKind, StageName
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.runtime.models import MumuRuntimeStatus
from autogame_orchestrator.workflow.contracts import StageExecutionContext
from autogame_orchestrator.workflow.plan import build_execution_plan
from autogame_orchestrator.workflow.production.factory import build_production_executor_factory
from autogame_orchestrator.workflow.production.ports import RuntimeFactories
from autogame_orchestrator.workflow.production.runtime_bindings import (
    RuntimeBindingError,
    build_default_runtime_factories,
    parse_local_adb_serial,
)
from autogame_orchestrator.workflow.runner import WorkflowRunner
from tests.workflow.fakes import MemorySink
from tests.workflow.production.fakes import (
    FakeMumuPort,
    FakeRunPort,
    aalc_result,
    maa_result,
    mumu_result,
    starrail_result,
    valid_config,
)


class CountingFactory:
    def __init__(self, name: str, value: object, counts: Counter[str]) -> None:
        self.name = name
        self.value = value
        self.counts = counts

    def __call__(self):
        self.counts[self.name] += 1
        return self.value


def factories(
    counts: Counter[str] | None = None,
    *,
    starrail=None,
    maa=None,
    aalc=None,
    mumu=None,
) -> tuple[RuntimeFactories, Counter[str]]:
    counter = counts or Counter()
    return (
        RuntimeFactories(
            CountingFactory("starrail", starrail or FakeRunPort(starrail_result()), counter),
            CountingFactory("maa", maa or FakeRunPort(maa_result()), counter),
            CountingFactory("aalc", aalc or FakeRunPort(aalc_result()), counter),
            CountingFactory("mumu", mumu or FakeMumuPort(mumu_result(MumuRuntimeStatus.READY)), counter),
        ),
        counter,
    )


def context(
    stage: StageName,
    *,
    deadline: Deadline | None = None,
    cancel: CancellationToken | None = None,
) -> StageExecutionContext:
    return StageExecutionContext("00000000-0000-0000-0000-000000000001", stage, deadline, cancel or CancellationToken())


def execute(config: AppConfig, stage: StageName, runtime_factories: RuntimeFactories, *, deadline=None, cancel=None):
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    return factory(stage).execute(context(stage, deadline=deadline, cancel=cancel)), factory


def test_validate_config_success(tmp_path: Path) -> None:
    runtime_factories, counts = factories()
    report, _ = execute(valid_config(tmp_path), StageName.VALIDATE_CONFIG, runtime_factories)
    assert (report.outcome, report.error_code) == (OutcomeKind.SUCCESS, ErrorCode.OK)
    assert counts == Counter()


def test_validate_config_structure_failure_constructs_no_runtime() -> None:
    runtime_factories, counts = factories()
    report, _ = execute(AppConfig(), StageName.VALIDATE_CONFIG, runtime_factories)
    assert report.error_code == ErrorCode.CONFIG_SCHEMA_ERROR
    assert report.diagnostics["error_count"] > 0
    assert counts == Counter()


def test_validate_path_failure_does_not_expose_path(tmp_path: Path) -> None:
    config = valid_config(tmp_path)
    Path(config.maa.executable).unlink()
    runtime_factories, _ = factories()
    report, _ = execute(config, StageName.VALIDATE_CONFIG, runtime_factories)
    assert report.error_code == ErrorCode.CONFIG_PATH_NOT_FOUND
    assert str(tmp_path) not in str(dict(report.diagnostics))


@pytest.mark.parametrize(
    ("stage", "blocker"),
    [
        (StageName.STOP_MUMU, "mumu_stop_not_approved"),
        (StageName.START_MUMU, "mumu_start_not_approved"),
    ],
)
def test_unapproved_stage_is_explicitly_blocked_in_external(stage: StageName, blocker: str) -> None:
    """external 模式下编排器不得接管模拟器生命周期，仍然硬阻断。"""
    runtime_factories, counts = factories()
    config = AppConfig(mumu=MuMuConfig(lifecycle_mode=MumuLifecycleMode.EXTERNAL))
    report, _ = execute(config, stage, runtime_factories)
    assert (report.outcome, report.error_code) == (OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_BLOCKED)
    assert report.diagnostics == {"blocker": blocker}
    assert counts == Counter()


def test_default_plan_passes_disabled_update_before_mumu_deadline_gate(tmp_path: Path) -> None:
    config = valid_config(tmp_path)
    runtime_factories, counts = factories()
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    report = WorkflowRunner(build_execution_plan(config), factory, MemorySink()).run()
    assert report.stages[0].outcome == OutcomeKind.SUCCESS
    assert report.stages[1].outcome == OutcomeKind.SUCCESS
    assert report.stages[2].outcome == OutcomeKind.SUCCESS
    assert report.stages[3].error_code == ErrorCode.WORKFLOW_DEADLINE_REQUIRED
    assert all(item.outcome == OutcomeKind.SKIPPED for item in report.stages[4:-1])
    assert counts == Counter()


def test_mumu_requires_parent_deadline() -> None:
    runtime_factories, counts = factories()
    report, _ = execute(AppConfig(), StageName.ENSURE_MUMU_RUNNING, runtime_factories)
    assert report.error_code == ErrorCode.WORKFLOW_DEADLINE_REQUIRED
    assert counts == Counter()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (MumuRuntimeStatus.READY, ErrorCode.OK),
        (MumuRuntimeStatus.STOPPED, ErrorCode.WORKFLOW_STAGE_BLOCKED),
        (MumuRuntimeStatus.NOT_READY, ErrorCode.WORKFLOW_STAGE_FAILED),
        (MumuRuntimeStatus.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT),
        (MumuRuntimeStatus.CANCELLED, ErrorCode.WORKFLOW_CANCELLED),
        (MumuRuntimeStatus.FAILED, ErrorCode.WORKFLOW_STAGE_FAILED),
    ],
)
def test_ensure_mumu_status_mapping(status: MumuRuntimeStatus, expected: ErrorCode) -> None:
    port = FakeMumuPort(mumu_result(status))
    runtime_factories, _ = factories(mumu=port)
    report, _ = execute(AppConfig(), StageName.ENSURE_MUMU_RUNNING, runtime_factories, deadline=Deadline.after(30))
    assert report.error_code == expected
    assert port.calls == 1


def test_managed_stopped_mumu_calls_start() -> None:
    """managed 模式下 ENSURE_MUMU_RUNNING 应调用 start() 而非仅查状态。"""
    port = FakeMumuPort(mumu_result(MumuRuntimeStatus.STOPPED))
    runtime_factories, _ = factories(mumu=port)
    execute(AppConfig(), StageName.ENSURE_MUMU_RUNNING, runtime_factories, deadline=Deadline.after(30))
    assert port.start_calls == 1
    assert port.status_calls == 0


def test_mumu_receives_same_deadline_and_token() -> None:
    port = FakeMumuPort(mumu_result(MumuRuntimeStatus.READY))
    deadline = Deadline.after(30)
    token = CancellationToken()
    runtime_factories, _ = factories(mumu=port)
    execute(AppConfig(), StageName.WAIT_MUMU_ADB_READY, runtime_factories, deadline=deadline, cancel=token)
    assert port.deadline is deadline
    assert port.cancel is token


@pytest.mark.parametrize("stage", [StageName.WAIT_MUMU_ADB_READY, StageName.WAIT_MUMU_ADB_READY_AFTER_RESTART])
def test_wait_mumu_calls_status_once(stage: StageName) -> None:
    port = FakeMumuPort(mumu_result(MumuRuntimeStatus.READY))
    runtime_factories, _ = factories(mumu=port)
    report, _ = execute(AppConfig(), stage, runtime_factories, deadline=Deadline.after(30))
    assert report.outcome == OutcomeKind.SUCCESS
    assert port.calls == 1


def test_verify_mumu_stopped_only_reads_status() -> None:
    port = FakeMumuPort(mumu_result(MumuRuntimeStatus.STOPPED))
    runtime_factories, _ = factories(mumu=port)
    report, _ = execute(AppConfig(), StageName.VERIFY_MUMU_STOPPED, runtime_factories, deadline=Deadline.after(30))
    assert report.outcome == OutcomeKind.SUCCESS
    assert port.calls == 1


def test_starrail_receives_same_budget_objects() -> None:
    port = FakeRunPort(starrail_result())
    deadline = Deadline.after(30)
    token = CancellationToken()
    runtime_factories, _ = factories(starrail=port)
    execute(AppConfig(), StageName.RUN_STARRAIL, runtime_factories, deadline=deadline, cancel=token)
    assert port.deadline is deadline
    assert port.cancel is token


def test_starrail_success_updates_only_safe_state() -> None:
    runtime_factories, _ = factories()
    report, factory = execute(AppConfig(), StageName.RUN_STARRAIL, runtime_factories)
    assert report.outcome == OutcomeKind.SUCCESS
    assert factory.state.starrail_run_reached is True
    assert factory.state.starrail_completed is True
    assert factory.state.starrail_owned_process_cleaned is True
    assert set(vars(factory.state)) == {
        "starrail_run_reached",
        "starrail_completed",
        "starrail_owned_process_cleaned",
    }


def test_stop_starrail_succeeds_from_owned_cleanup_evidence() -> None:
    runtime_factories, _ = factories()
    factory = build_production_executor_factory(AppConfig(), runtime_factories=runtime_factories)
    factory(StageName.RUN_STARRAIL).execute(context(StageName.RUN_STARRAIL))
    report = factory(StageName.STOP_STARRAIL).execute(context(StageName.STOP_STARRAIL))
    assert report.outcome == OutcomeKind.SUCCESS


@pytest.mark.parametrize("stage", [StageName.STOP_STARRAIL, StageName.VERIFY_STARRAIL_STOPPED])
def test_starrail_postcondition_fails_without_run_state(stage: StageName) -> None:
    runtime_factories, counts = factories()
    report, _ = execute(AppConfig(), stage, runtime_factories)
    assert report.error_code == ErrorCode.WORKFLOW_STAGE_FAILED
    assert counts == Counter()


def test_verify_starrail_uses_no_process_scanner() -> None:
    runtime_factories, counts = factories()
    execute(AppConfig(), StageName.VERIFY_STARRAIL_STOPPED, runtime_factories)
    assert counts == Counter()


@pytest.mark.parametrize("stage", [StageName.RUN_MAA, StageName.RUN_AALC])
def test_run_adapters_receive_same_budget(stage: StageName) -> None:
    maa = FakeRunPort(maa_result())
    aalc = FakeRunPort(aalc_result())
    deadline = Deadline.after(30)
    token = CancellationToken()
    runtime_factories, _ = factories(maa=maa, aalc=aalc)
    execute(AppConfig(), stage, runtime_factories, deadline=deadline, cancel=token)
    port = maa if stage == StageName.RUN_MAA else aalc
    assert port.deadline is deadline
    assert port.cancel is token
    assert port.calls == 1


def test_aalc_attempt_count_is_not_modified() -> None:
    runtime_factories, _ = factories(aalc=FakeRunPort(aalc_result()))
    report, _ = execute(AppConfig(), StageName.RUN_AALC, runtime_factories)
    assert report.diagnostics["configured_attempts"] == 3
    assert report.diagnostics["attempts_started"] == 1


def test_runtime_is_constructed_at_most_once_per_factory() -> None:
    port = FakeMumuPort(mumu_result(MumuRuntimeStatus.READY))
    runtime_factories, counts = factories(mumu=port)
    factory = build_production_executor_factory(AppConfig(), runtime_factories=runtime_factories)
    deadline = Deadline.after(30)
    for stage in (StageName.ENSURE_MUMU_RUNNING, StageName.WAIT_MUMU_ADB_READY):
        factory(stage).execute(context(stage, deadline=deadline))
    assert counts["mumu"] == 1
    assert port.calls == 2


def test_factory_construction_is_lazy() -> None:
    runtime_factories, counts = factories()
    build_production_executor_factory(AppConfig(), runtime_factories=runtime_factories)
    assert counts == Counter()


def test_two_factories_have_isolated_state() -> None:
    runtime_factories, _ = factories()
    first = build_production_executor_factory(AppConfig(), runtime_factories=runtime_factories)
    second = build_production_executor_factory(AppConfig(), runtime_factories=runtime_factories)
    first.state.starrail_run_reached = True
    assert second.state.starrail_run_reached is False


def test_write_report_is_not_registered() -> None:
    runtime_factories, _ = factories()
    factory = build_production_executor_factory(AppConfig(), runtime_factories=runtime_factories)
    with pytest.raises(KeyError):
        factory(StageName.WRITE_RUN_REPORT)


@pytest.mark.parametrize(
    ("serial", "expected"),
    [("127.0.0.1:1", ("127.0.0.1", 1)), ("127.0.0.1:65535", ("127.0.0.1", 65535))],
)
def test_local_mumu_endpoint_is_accepted(serial: str, expected: tuple[str, int]) -> None:
    assert parse_local_adb_serial(serial) == expected


@pytest.mark.parametrize("serial", ["10.0.0.1:16384", "localhost:16384", "127.0.0.1:0", "127.0.0.1:65536", "bad"])
def test_unsafe_mumu_endpoint_is_rejected(serial: str) -> None:
    with pytest.raises(RuntimeBindingError):
        parse_local_adb_serial(serial)


def test_invalid_mumu_endpoint_fails_before_adapter_construction() -> None:
    config = AppConfig(mumu=MuMuConfig(adb_serial="remote.example:1234"))
    runtime_factories = build_default_runtime_factories(config)
    with pytest.raises(RuntimeBindingError):
        runtime_factories.mumu()


def test_invalid_mumu_endpoint_stage_is_configuration_failure() -> None:
    config = AppConfig(mumu=MuMuConfig(adb_serial="remote.example:1234"))
    factory = build_production_executor_factory(config)
    stage = StageName.WAIT_MUMU_ADB_READY
    report = factory(stage).execute(context(stage, deadline=Deadline.after(30)))
    assert report.error_code == ErrorCode.CONFIG_SCHEMA_ERROR


def test_managed_stop_mumu_stage_maps_stopped_to_success() -> None:
    """managed 下 STOP_MUMU 必须调 stop() 且把 STOPPED 判为成功。

    回归保护：执行器曾只对 VERIFY_MUMU_STOPPED 传递 “期望已停止” 语义，
    导致真实停止成功的 STOP_MUMU 阶段被误判为 WORKFLOW_STAGE_FAILED。
    """
    port = FakeMumuPort(mumu_result(MumuRuntimeStatus.STOPPED))
    runtime_factories, _ = factories(mumu=port)
    report, _ = execute(AppConfig(), StageName.STOP_MUMU, runtime_factories, deadline=Deadline.after(30))
    assert (report.outcome, report.error_code) == (OutcomeKind.SUCCESS, ErrorCode.OK)
    assert port.stop_calls == 1
    assert port.status_calls == 0


def test_managed_verify_mumu_stopped_stage_still_reads_status() -> None:
    """VERIFY_MUMU_STOPPED 仍应只读查状态，不得调用 stop()。"""
    port = FakeMumuPort(mumu_result(MumuRuntimeStatus.STOPPED))
    runtime_factories, _ = factories(mumu=port)
    report, _ = execute(AppConfig(), StageName.VERIFY_MUMU_STOPPED, runtime_factories, deadline=Deadline.after(30))
    assert (report.outcome, report.error_code) == (OutcomeKind.SUCCESS, ErrorCode.OK)
    assert port.status_calls == 1
    assert port.stop_calls == 0
