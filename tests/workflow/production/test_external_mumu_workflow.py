"""external MuMu 模式的生产绑定 Fake 工作流验收。"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from autogame_orchestrator.config_model import AppConfig, MumuLifecycleMode
from autogame_orchestrator.models import ErrorCode, OutcomeKind, RunStatus, StageName
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.runtime.aalc_models import AALCRunStatus
from autogame_orchestrator.runtime.maa_models import MAARunStatus
from autogame_orchestrator.runtime.models import MumuRuntimeResult, MumuRuntimeStatus
from autogame_orchestrator.runtime.starrail_models import StarRailRunStatus
from autogame_orchestrator.workflow.contracts import StageExecutionContext
from autogame_orchestrator.workflow.plan import build_execution_plan
from autogame_orchestrator.workflow.production.factory import build_production_executor_factory
from autogame_orchestrator.workflow.production.ports import RuntimeFactories
from autogame_orchestrator.workflow.production.runtime_bindings import build_default_runtime_factories
from autogame_orchestrator.workflow.runner import WorkflowRunner
from tests.workflow.fakes import MemorySink
from tests.workflow.production.fakes import (
    FakeExternalMumuStatusPort,
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
        self._name = name
        self._value = value
        self._counts = counts

    def __call__(self):
        self._counts[self._name] += 1
        return self._value


class RecordingMumuPort(FakeMumuPort):
    def __init__(self, result: MumuRuntimeResult) -> None:
        super().__init__(result)
        self.deadlines: list[Deadline] = []
        self.tokens: list[CancellationToken | None] = []

    def status(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        self.deadlines.append(deadline)
        self.tokens.append(cancel)
        return super().status(deadline, cancel)

    def ensure_external_ready(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        self.deadlines.append(deadline)
        self.tokens.append(cancel)
        return super().ensure_external_ready(deadline, cancel)

    def start(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        self.deadlines.append(deadline)
        self.tokens.append(cancel)
        return super().start(deadline, cancel)

    def stop(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        self.deadlines.append(deadline)
        self.tokens.append(cancel)
        return super().stop(deadline, cancel)


def _external_config(root: Path) -> AppConfig:
    config = valid_config(root)
    return replace(
        config,
        mumu=replace(
            config.mumu,
            lifecycle_mode=MumuLifecycleMode.EXTERNAL,
            executable="",
            start_arguments=(),
            stop_arguments=(),
        ),
    )


def _factories(
    *,
    mumu_status: MumuRuntimeStatus = MumuRuntimeStatus.READY,
    starrail_status: StarRailRunStatus = StarRailRunStatus.COMPLETED,
    maa_status: MAARunStatus = MAARunStatus.COMPLETED,
    aalc_status: AALCRunStatus = AALCRunStatus.COMPLETED,
    mumu_port: FakeMumuPort | None = None,
) -> tuple[RuntimeFactories, Counter[str], FakeMumuPort, FakeRunPort, FakeRunPort, FakeRunPort]:
    counts: Counter[str] = Counter()
    selected_mumu = mumu_port or FakeMumuPort(mumu_result(mumu_status))
    starrail = FakeRunPort(starrail_result(starrail_status))
    maa = FakeRunPort(maa_result(maa_status))
    aalc = FakeRunPort(aalc_result(aalc_status))
    return (
        RuntimeFactories(
            CountingFactory("starrail", starrail, counts),
            CountingFactory("maa", maa, counts),
            CountingFactory("aalc", aalc, counts),
            CountingFactory("mumu", selected_mumu, counts),
        ),
        counts,
        selected_mumu,
        starrail,
        maa,
        aalc,
    )


def _run(
    config: AppConfig,
    runtime_factories: RuntimeFactories,
    *,
    deadline: Deadline | None = None,
    cancel: CancellationToken | None = None,
):
    plan = build_execution_plan(config)
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    report = WorkflowRunner(plan, factory, MemorySink()).run(
        deadline=deadline or Deadline.after(30),
        cancel=cancel,
    )
    return report, factory


def test_plan_and_validate_do_not_call_mumu_ensure(tmp_path: Path) -> None:
    config = _external_config(tmp_path)
    runtime_factories, _, mumu, *_ = _factories()
    plan = build_execution_plan(config)
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    report = factory(StageName.VALIDATE_CONFIG).execute(
        StageExecutionContext("validate-test", StageName.VALIDATE_CONFIG, Deadline.after(30), CancellationToken())
    )

    assert len(plan.stages) == 11
    assert report.outcome == OutcomeKind.SUCCESS
    assert (mumu.calls, mumu.ensure_calls) == (0, 0)


def test_external_complete_fake_workflow_succeeds(tmp_path: Path) -> None:
    config = _external_config(tmp_path)
    runtime_factories, counts, mumu, starrail, maa, aalc = _factories()
    report, _ = _run(config, runtime_factories)

    assert (report.status, report.error_code) == (RunStatus.SUCCESS, ErrorCode.OK)
    assert len(report.stages) == 11
    assert tuple(stage.stage for stage in report.stages) == build_execution_plan(config).stages
    assert all(stage.outcome == OutcomeKind.SUCCESS for stage in report.stages)
    assert counts == Counter({"mumu": 1, "starrail": 1, "maa": 1})
    assert (mumu.calls, starrail.calls, maa.calls, aalc.calls) == (2, 1, 1, 0)
    assert (mumu.ensure_calls, mumu.status_calls) == (1, 1)


@pytest.mark.parametrize(
    "stage",
    [
        StageName.STOP_MUMU,
        StageName.VERIFY_MUMU_STOPPED,
        StageName.START_MUMU,
        StageName.WAIT_MUMU_ADB_READY_AFTER_RESTART,
    ],
)
def test_external_success_report_omits_lifecycle_stage(tmp_path: Path, stage: StageName) -> None:
    runtime_factories, *_ = _factories()
    report, _ = _run(_external_config(tmp_path), runtime_factories)
    assert stage not in {item.stage for item in report.stages}


def test_external_success_reaches_maa_without_aalc(tmp_path: Path) -> None:
    runtime_factories, _, _, _, maa, aalc = _factories()
    report, _ = _run(_external_config(tmp_path), runtime_factories)
    assert report.status == RunStatus.SUCCESS
    assert maa.calls == 1
    assert aalc.calls == 0
    assert report.stages[-2].stage == StageName.RUN_MAA
    assert report.stages[-1].stage == StageName.WRITE_RUN_REPORT


def test_external_success_never_exposes_lifecycle_methods(tmp_path: Path) -> None:
    status_only = FakeExternalMumuStatusPort(mumu_result(MumuRuntimeStatus.READY))
    runtime_factories, _, mumu, *_ = _factories(mumu_port=status_only)
    _run(_external_config(tmp_path), runtime_factories)
    assert not hasattr(mumu, "start")
    assert not hasattr(mumu, "stop")
    assert not hasattr(mumu, "restart")


def test_default_external_runtime_port_only_exposes_status(tmp_path: Path) -> None:
    port = build_default_runtime_factories(_external_config(tmp_path)).mumu()
    assert callable(port.status)
    assert callable(port.ensure_external_ready)
    assert not hasattr(port, "start")
    assert not hasattr(port, "stop")
    assert not hasattr(port, "restart")


def test_external_stopped_is_blocked_without_repair(tmp_path: Path) -> None:
    runtime_factories, counts, mumu, starrail, maa, aalc = _factories(mumu_status=MumuRuntimeStatus.STOPPED)
    report, _ = _run(_external_config(tmp_path), runtime_factories)
    ensure = report.stages[4]
    assert (ensure.outcome, ensure.error_code) == (OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_BLOCKED)
    assert ensure.diagnostics["blocker"] == "mumu_external_not_ready"
    assert mumu.calls == 1
    assert mumu.ensure_calls == 1
    assert (starrail.calls, maa.calls, aalc.calls) == (0, 0, 0)
    assert counts == Counter({"mumu": 1})
    assert all(stage.outcome == OutcomeKind.SKIPPED for stage in report.stages[5:-1])


@pytest.mark.parametrize(
    ("status", "outcome", "error_code"),
    [
        (MumuRuntimeStatus.NOT_READY, OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED),
        (MumuRuntimeStatus.TIMEOUT, OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT),
        (MumuRuntimeStatus.CANCELLED, OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED),
        (MumuRuntimeStatus.FAILED, OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED),
    ],
)
def test_external_readiness_failure_is_fail_fast(
    tmp_path: Path,
    status: MumuRuntimeStatus,
    outcome: OutcomeKind,
    error_code: ErrorCode,
) -> None:
    runtime_factories, _, mumu, starrail, maa, aalc = _factories(mumu_status=status)
    report, _ = _run(_external_config(tmp_path), runtime_factories)
    assert (report.stages[4].outcome, report.stages[4].error_code) == (outcome, error_code)
    assert mumu.calls == 1
    assert (mumu.start_calls, mumu.stop_calls) == (0, 0)
    assert (starrail.calls, maa.calls, aalc.calls) == (0, 0, 0)
    assert all(stage.outcome == OutcomeKind.SKIPPED for stage in report.stages[5:-1])
    assert StageName.SHUTDOWN_MUMU not in {stage.stage for stage in report.stages}
    assert "failure_cleanup_attempted" not in report.diagnostics


def test_external_starrail_failure_never_runs_later_adapter(tmp_path: Path) -> None:
    runtime_factories, _, mumu, starrail, maa, aalc = _factories(starrail_status=StarRailRunStatus.FAILED)
    report, _ = _run(_external_config(tmp_path), runtime_factories)
    assert report.stages[6].stage == StageName.RUN_STARRAIL
    assert report.stages[6].outcome == OutcomeKind.FAILURE
    assert (mumu.calls, starrail.calls, maa.calls, aalc.calls) == (2, 1, 0, 0)


def test_external_maa_failure_does_not_run_later_adapters(tmp_path: Path) -> None:
    runtime_factories, _, mumu, _, maa, aalc = _factories(maa_status=MAARunStatus.FAILED)
    report, _ = _run(_external_config(tmp_path), runtime_factories)
    assert report.stages[9].stage == StageName.RUN_MAA
    assert report.stages[9].outcome == OutcomeKind.FAILURE
    assert (mumu.calls, maa.calls, aalc.calls) == (2, 1, 0)
    assert StageName.START_MUMU not in {stage.stage for stage in report.stages}


def test_external_preserves_deadline_and_cancellation_identity(tmp_path: Path) -> None:
    port = RecordingMumuPort(mumu_result(MumuRuntimeStatus.READY))
    runtime_factories, _, _, *_ = _factories(mumu_port=port)
    deadline = Deadline.after(30)
    token = CancellationToken()
    _run(_external_config(tmp_path), runtime_factories, deadline=deadline, cancel=token)
    assert port.deadlines == [deadline, deadline]
    assert port.tokens == [token, token]


def test_external_mumu_diagnostics_are_safe_enum_projection(tmp_path: Path) -> None:
    runtime_factories, *_ = _factories()
    report, _ = _run(_external_config(tmp_path), runtime_factories)
    for stage in report.stages:
        if stage.stage in {StageName.ENSURE_MUMU_RUNNING, StageName.WAIT_MUMU_ADB_READY}:
            assert stage.diagnostics["lifecycle_mode"] == "external"
            assert set(stage.diagnostics) == {"source_error_code", "action", "changed", "lifecycle_mode"}


def test_external_run_report_does_not_record_device_address(tmp_path: Path) -> None:
    config = _external_config(tmp_path)
    runtime_factories, *_ = _factories()
    report, _ = _run(config, runtime_factories)
    payload = json.dumps(report.to_json_encodable(), ensure_ascii=False)
    assert config.mumu.adb_serial not in payload
    assert "RPC" + "_INSTANCE" not in payload
    assert "." + "nemu" not in payload.casefold()


def test_external_mode_does_not_add_mumu_elevation(tmp_path: Path) -> None:
    assert build_execution_plan(_external_config(tmp_path)).requires_administrator is False


def test_managed_start_failure_still_blocks(tmp_path: Path) -> None:
    """managed 下调用 start() 后仍为 STOPPED，投影层必须阻断而不是放行。"""
    config = valid_config(tmp_path)
    runtime_factories, _, mumu, *_ = _factories(mumu_status=MumuRuntimeStatus.STOPPED)
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    stage = StageName.ENSURE_MUMU_RUNNING
    report = factory(stage).execute(
        StageExecutionContext("managed-test", stage, Deadline.after(30), CancellationToken())
    )
    assert report.error_code == ErrorCode.WORKFLOW_STAGE_BLOCKED
    assert report.diagnostics["blocker"] == "mumu_start_not_approved"
    assert report.diagnostics["lifecycle_mode"] == "managed"
    assert (mumu.ensure_calls, mumu.start_calls) == (0, 1)


def test_production_external_code_contains_no_control_or_scan_implementation() -> None:
    root = Path("src/autogame_orchestrator/workflow/production")
    content = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py")).casefold()
    for forbidden in ("taskkill", "get-process", "win32_process", "nemushell", "rpc_instance", ".nemu"):
        assert forbidden not in content
