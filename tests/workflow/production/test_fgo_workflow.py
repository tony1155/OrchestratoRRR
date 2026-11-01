"""FGO（MaaFgo）链路：计划、阶段与完整 managed/external 工作流测试。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autogame_orchestrator.config_model import (
    AppConfig,
    FgoConfig,
    GameSelection,
    MuMuConfig,
    MumuLifecycleMode,
    OrchestratorConfig,
)
from autogame_orchestrator.maafgo_evidence import ARTIFACT_SCHEMA_VERSION
from autogame_orchestrator.models import ErrorCode, OutcomeKind, RunStatus, StageName
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.process.errors import TerminationReason
from autogame_orchestrator.run_application import (
    FGO_EXTERNAL_RUN_STAGES,
    FGO_MANAGED_RUN_STAGES,
    validate_external_plan,
)
from autogame_orchestrator.runtime.fgo_models import (
    FgoAppStopErrorCode,
    FgoAppStopResult,
    FgoAppStopStatus,
    FgoStopVerification,
)
from autogame_orchestrator.runtime.maafgo_models import (
    MaaFgoArtifactValidationState,
    MaaFgoErrorCode,
    MaaFgoRunResult,
    MaaFgoRunStatus,
)
from autogame_orchestrator.runtime.models import MumuRuntimeStatus
from autogame_orchestrator.workflow.contracts import StageExecutionContext
from autogame_orchestrator.workflow.plan import build_execution_plan
from autogame_orchestrator.workflow.production.factory import build_production_executor_factory
from autogame_orchestrator.workflow.production.ports import RuntimeFactories
from autogame_orchestrator.workflow.runner import WorkflowRunner
from tests.fakes.maafgo_support import SERIAL, make_native_project
from tests.workflow.production.fakes import FakeMumuPort, mumu_result

NOW = datetime.now(UTC)
LATER = NOW + timedelta(seconds=2)


def fgo_config(tmp_path: Path, *, lifecycle: MumuLifecycleMode = MumuLifecycleMode.MANAGED) -> AppConfig:
    root = tmp_path / "fgowork"
    root.mkdir(parents=True, exist_ok=True)
    (root / "mumu.exe").write_text("fake", encoding="utf-8")
    (root / "adb.exe").write_text("fake", encoding="utf-8")
    project = make_native_project(tmp_path / "maafgo-dist")
    managed = lifecycle is MumuLifecycleMode.MANAGED
    mumu = MuMuConfig(
        lifecycle_mode=lifecycle,
        executable=str(root / "mumu.exe"),
        adb_executable=str(root / "adb.exe"),
        adb_serial=SERIAL,
        start_arguments=("--fake-start",) if managed else (),
        stop_arguments=("--fake-stop",) if managed else (),
    )
    return AppConfig(
        orchestrator=OrchestratorConfig(log_dir=str(root / "logs"), report_dir=str(root / "reports")),
        mumu=mumu,
        game=GameSelection.FGO,
        fgo=FgoConfig(package_name="com.bilibili.fatego"),
        maafgo=project,
    )


def maafgo_result(
    status: MaaFgoRunStatus = MaaFgoRunStatus.SUCCESS,
    code: MaaFgoErrorCode = MaaFgoErrorCode.OK,
) -> MaaFgoRunResult:
    reason = {
        MaaFgoRunStatus.SUCCESS: TerminationReason.NORMAL_EXIT,
        MaaFgoRunStatus.FAILED: TerminationReason.NORMAL_EXIT,
        MaaFgoRunStatus.TIMEOUT: TerminationReason.TIMEOUT,
        MaaFgoRunStatus.CANCELLED: TerminationReason.CANCELLED,
    }[status]
    exit_code = {MaaFgoRunStatus.SUCCESS: 0, MaaFgoRunStatus.FAILED: 7}.get(status)
    confirmed = status is MaaFgoRunStatus.SUCCESS
    return MaaFgoRunResult(
        status,
        code,
        NOW,
        LATER,
        2000,
        exit_code,
        reason,
        True,
        True,
        confirmed,
        2,
        2 if confirmed else 0,
        completion_evidence_schema_version=ARTIFACT_SCHEMA_VERSION if confirmed else 0,
        plan_digest_match=confirmed,
        artifact_validation_state=(
            MaaFgoArtifactValidationState.VERIFIED if confirmed else MaaFgoArtifactValidationState.NOT_ATTEMPTED
        ),
    )


def stop_result(
    status: FgoAppStopStatus = FgoAppStopStatus.STOPPED,
    code: FgoAppStopErrorCode = FgoAppStopErrorCode.OK,
    verification: FgoStopVerification = FgoStopVerification.VERIFIED,
) -> FgoAppStopResult:
    return FgoAppStopResult(status, code, NOW, LATER, 100, verification)


class FakeMaaFgoFactory:
    """捕获 PREPARE 创建的 contract，供 fake port 模拟 reporter 行为。"""

    def __init__(self, port: FakeMaaFgoPort) -> None:
        self._port = port
        self.contracts: list[object] = []

    def __call__(self, contract):
        self.contracts.append(contract)
        self._port.contract = contract
        return self._port


class FakeMaaFgoPort:
    def __init__(self, result: MaaFgoRunResult, *, write_artifact: bool = False) -> None:
        self.result = result
        self.write_artifact = write_artifact
        self.calls = 0
        self.contract = None

    def run(self, deadline=None, cancel=None):
        self.calls += 1
        if self.write_artifact and self.contract is not None:
            document = {
                "schema_version": 1,
                "run_id": self.contract.run_id,
                "plan_digest": self.contract.plan_digest,
                "outcome": "success",
                "tasks": [
                    {"name": name, "entry": entry, "terminal": "success"}
                    for name, entry in self.contract.expected_tasks
                ],
                "unexpected_entries": [],
                "stop_signal_observed": False,
            }
            self.contract.result_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return self.result


class FgoMumuPort(FakeMumuPort):
    """managed FGO 链路的 MuMu 行为：start→STARTED、readiness→READY、stop→STOPPED。"""

    def __init__(self) -> None:
        super().__init__(
            mumu_result(MumuRuntimeStatus.STARTED, changed=True),
            ensure_result=mumu_result(MumuRuntimeStatus.STARTED, changed=True),
        )

    def status(self, deadline=None, cancel=None):
        self.status_calls += 1
        return mumu_result(MumuRuntimeStatus.READY)

    def stop(self, deadline=None, cancel=None):
        self.stop_calls += 1
        self.result = mumu_result(MumuRuntimeStatus.STOPPED, changed=True)
        return self.result


class FakeFgoStopPort:
    def __init__(self, result: FgoAppStopResult | None = None) -> None:
        self.result = result or stop_result()
        self.calls = 0

    def stop(self, deadline=None, cancel=None):
        self.calls += 1
        return self.result


def fgo_factories(
    config: AppConfig,
    *,
    maafgo_port: FakeMaaFgoPort | None = None,
    fgo_stop: FakeFgoStopPort | None = None,
    mumu: FakeMumuPort | None = None,
) -> tuple[RuntimeFactories, FakeMaaFgoFactory, FakeFgoStopPort]:
    maafgo_port = maafgo_port or FakeMaaFgoPort(maafgo_result())
    maafgo_factory = FakeMaaFgoFactory(maafgo_port)
    fgo_stop = fgo_stop or FakeFgoStopPort()
    mumu = mumu or FgoMumuPort()
    return (
        RuntimeFactories(
            starrail=lambda: pytest.fail("StarRail must not be constructed for FGO runs"),
            maa=lambda: pytest.fail("MAA must not be constructed for FGO runs"),
            aalc=lambda: pytest.fail("AALC must not be constructed for FGO runs"),
            mumu=lambda: mumu,
            maafgo=maafgo_factory,
            fgo_app_stop=lambda: fgo_stop,
        ),
        maafgo_factory,
        fgo_stop,
    )


def context(stage: StageName, *, deadline: Deadline | None = "default", cancel=None) -> StageExecutionContext:
    """生产阶段默认携带父 Deadline；STOP_FGO 与 MuMu 阶段都要求有界预算。"""
    if deadline == "default":
        deadline = Deadline.after(30)
    return StageExecutionContext("00000000-0000-0000-0000-000000000002", stage, deadline, cancel or CancellationToken())


# ── 计划 ────────────────────────────────────────────────────────────────────

MANAGED_FGO_STAGES = (
    StageName.VALIDATE_CONFIG,
    StageName.ENSURE_MUMU_RUNNING,
    StageName.WAIT_MUMU_ADB_READY,
    StageName.PREPARE_MAAFGO_RUN,
    StageName.RUN_MAAFGO,
    StageName.STOP_FGO,
    StageName.SHUTDOWN_MUMU,
    StageName.WRITE_RUN_REPORT,
)


def test_fgo_managed_plan_is_exact(tmp_path):
    plan = build_execution_plan(fgo_config(tmp_path / "p1", lifecycle=MumuLifecycleMode.MANAGED))
    assert plan.stages == FGO_MANAGED_RUN_STAGES == MANAGED_FGO_STAGES
    assert plan.requires_administrator is False


def test_fgo_external_plan_is_exact(tmp_path):
    plan = build_execution_plan(fgo_config(tmp_path / "p2", lifecycle=MumuLifecycleMode.EXTERNAL))
    assert plan.stages == FGO_EXTERNAL_RUN_STAGES
    assert StageName.SHUTDOWN_MUMU not in plan.stages


def test_fgo_plan_excludes_starrail_and_maa_stages(tmp_path):
    stages = build_execution_plan(fgo_config(tmp_path / "p3")).stages
    for stage in (
        StageName.RUN_STARRAIL,
        StageName.STOP_STARRAIL,
        StageName.RUN_MAA,
        StageName.SYNC_MAA_CONFIG,
        StageName.UPDATE_MAA,
        StageName.MERGE_MAA_RESOURCE,
        StageName.RUN_BETTERGI,
    ):
        assert stage not in stages


def test_bettergi_not_inserted_into_fgo_plan(tmp_path):
    config = fgo_config(tmp_path)
    from dataclasses import replace

    from autogame_orchestrator.bettergi_config import BetterGIConfig

    config = replace(config, bettergi=BetterGIConfig(enabled=True))
    plan = build_execution_plan(config)
    assert StageName.RUN_BETTERGI not in plan.stages


def test_validate_external_plan_accepts_fgo_plans(tmp_path):
    plan = build_execution_plan(fgo_config(tmp_path / "p4"))
    assert validate_external_plan(plan) is None


def test_validate_external_plan_accepts_fgo_external_plans(tmp_path):
    """FGO external 7 阶段计划必须被 external 计划闸门直接接受（管理/外部两种生命周期都覆盖）。"""
    plan = build_execution_plan(fgo_config(tmp_path / "p5", lifecycle=MumuLifecycleMode.EXTERNAL))
    assert plan.stages == FGO_EXTERNAL_RUN_STAGES
    assert StageName.SHUTDOWN_MUMU not in plan.stages
    assert validate_external_plan(plan) is None


# ── 阶段 ────────────────────────────────────────────────────────────────────

def test_prepare_creates_run_scoped_contract(tmp_path):
    config = fgo_config(tmp_path)
    runtime_factories, maafgo_factory, _ = fgo_factories(config)
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    report = factory(StageName.PREPARE_MAAFGO_RUN).execute(context(StageName.PREPARE_MAAFGO_RUN))
    assert (report.outcome, report.error_code) == (OutcomeKind.SUCCESS, ErrorCode.OK)
    contract = factory.state.maafgo_run_contract
    assert contract is not None and maafgo_factory.contracts == []
    assert contract.expected_tasks == (("登录", "登录识别"), ("日常战斗", "日常战斗"))
    assert contract.result_path.parent == contract.run_directory
    assert contract.run_directory.is_dir()
    assert contract.run_directory.parent.name == "maafgo"
    assert report.diagnostics["expected_task_count"] == 2


def test_prepare_policy_failure_fails_closed(tmp_path):
    config = fgo_config(tmp_path)
    profile = json.loads(config.maafgo.profile_path.read_text(encoding="utf-8"))
    profile["task"] = [{"name": "登录", "option": []}, {"name": "关闭游戏", "option": []}]
    config.maafgo.profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    runtime_factories, _, _ = fgo_factories(config)
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    report = factory(StageName.PREPARE_MAAFGO_RUN).execute(context(StageName.PREPARE_MAAFGO_RUN))
    assert report.outcome is OutcomeKind.FAILURE
    assert report.diagnostics["source_error_code"] == MaaFgoErrorCode.PROFILE_POLICY_REJECTED.value
    assert factory.state.maafgo_run_contract is None


def test_prepare_distribution_failure_fails_closed(tmp_path):
    config = fgo_config(tmp_path)
    (Path(config.maafgo.working_directory) / "distribution-manifest.json").unlink()
    runtime_factories, _, _ = fgo_factories(config)
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    report = factory(StageName.PREPARE_MAAFGO_RUN).execute(context(StageName.PREPARE_MAAFGO_RUN))
    assert report.outcome is OutcomeKind.FAILURE
    assert report.diagnostics["source_error_code"] == MaaFgoErrorCode.DISTRIBUTION_UNVERIFIED.value


def test_run_maafgo_blocked_without_prepare(tmp_path):
    config = fgo_config(tmp_path)
    runtime_factories, maafgo_factory, _ = fgo_factories(config)
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    report = factory(StageName.RUN_MAAFGO).execute(context(StageName.RUN_MAAFGO))
    assert (report.outcome, report.error_code) == (OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_BLOCKED)
    assert report.diagnostics == {"blocker": "maafgo_run_not_prepared"}
    assert maafgo_factory.contracts == []


def test_run_maafgo_success_projection(tmp_path):
    config = fgo_config(tmp_path)
    runtime_factories, _, _ = fgo_factories(config, maafgo_port=FakeMaaFgoPort(maafgo_result()))
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    factory(StageName.PREPARE_MAAFGO_RUN).execute(context(StageName.PREPARE_MAAFGO_RUN))
    report = factory(StageName.RUN_MAAFGO).execute(context(StageName.RUN_MAAFGO))
    assert (report.outcome, report.error_code) == (OutcomeKind.SUCCESS, ErrorCode.OK)
    # 白名单精确集合（docs/maafgo-full-workflow.md「RunReport / projection」）。
    assert set(report.diagnostics) == {
        "source_error_code",
        "provider",
        "termination_reason",
        "exit_code",
        "owned_process_cleaned",
        "configuration_confirmed",
        "completion_confirmed",
        "expected_task_count",
        "confirmed_task_count",
        "completion_evidence_schema_version",
        "plan_digest_match",
        "artifact_validation_state",
        "output_capture",
    }
    assert report.diagnostics["provider"] == "maafgo"
    assert report.diagnostics["completion_confirmed"] is True
    assert report.diagnostics["confirmed_task_count"] == 2
    assert report.diagnostics["completion_evidence_schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert report.diagnostics["plan_digest_match"] is True
    assert report.diagnostics["artifact_validation_state"] == MaaFgoArtifactValidationState.VERIFIED.value
    assert factory.state.maafgo_run_reached is True


def test_prepare_distribution_precedes_policy(tmp_path):
    """分发校验先于 policy（docs「Profile policy」括注）：双重失效时先透出
    DISTRIBUTION_UNVERIFIED，而不是 PROFILE_POLICY_REJECTED。"""
    config = fgo_config(tmp_path)
    profile = json.loads(config.maafgo.profile_path.read_text(encoding="utf-8"))
    profile["task"] = [{"name": "登录", "option": []}, {"name": "关闭游戏", "option": []}]
    config.maafgo.profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    (Path(config.maafgo.working_directory) / "distribution-manifest.json").unlink()
    runtime_factories, _, _ = fgo_factories(config)
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    report = factory(StageName.PREPARE_MAAFGO_RUN).execute(context(StageName.PREPARE_MAAFGO_RUN))
    assert report.outcome is OutcomeKind.FAILURE
    assert report.diagnostics["source_error_code"] == MaaFgoErrorCode.DISTRIBUTION_UNVERIFIED.value


def test_run_maafgo_without_registered_runtime(tmp_path):
    config = fgo_config(tmp_path)
    runtime_factories, _, _ = fgo_factories(config)
    stripped = RuntimeFactories(
        starrail=runtime_factories.starrail,
        maa=runtime_factories.maa,
        aalc=runtime_factories.aalc,
        mumu=runtime_factories.mumu,
    )
    factory = build_production_executor_factory(config, runtime_factories=stripped)
    prepared = factory(StageName.PREPARE_MAAFGO_RUN).execute(context(StageName.PREPARE_MAAFGO_RUN))
    assert prepared.outcome is OutcomeKind.SUCCESS
    report = factory(StageName.RUN_MAAFGO).execute(context(StageName.RUN_MAAFGO))
    assert (report.outcome, report.error_code) == (OutcomeKind.FAILURE, ErrorCode.CONFIG_SCHEMA_ERROR)


def test_stop_fgo_success(tmp_path):
    config = fgo_config(tmp_path)
    runtime_factories, _, stop = fgo_factories(config)
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    report = factory(StageName.STOP_FGO).execute(context(StageName.STOP_FGO))
    assert (report.outcome, report.error_code) == (OutcomeKind.SUCCESS, ErrorCode.OK)
    assert report.diagnostics["verification"] == FgoStopVerification.VERIFIED.value
    assert stop.calls == 1


def test_stop_fgo_disabled(tmp_path):
    from dataclasses import replace as dc_replace

    config = dc_replace(
        fgo_config(tmp_path), fgo=FgoConfig(package_name="com.bilibili.fatego", stop_game_on_exit=False)
    )
    runtime_factories, _, stop = fgo_factories(config)
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    report = factory(StageName.STOP_FGO).execute(context(StageName.STOP_FGO))
    assert (report.outcome, report.error_code) == (OutcomeKind.SUCCESS, ErrorCode.OK)
    assert report.diagnostics == {"stopped": False, "reason": "stop_game_on_exit_disabled"}
    assert stop.calls == 0


def test_stop_fgo_failure(tmp_path):
    config = fgo_config(tmp_path)
    runtime_factories, _, _ = fgo_factories(config, fgo_stop=FakeFgoStopPort(stop_result(
        FgoAppStopStatus.FAILED, FgoAppStopErrorCode.ADB_COMMAND_FAILED, FgoStopVerification.SKIPPED
    )))
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    report = factory(StageName.STOP_FGO).execute(context(StageName.STOP_FGO))
    assert (report.outcome, report.error_code) == (OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED)
    assert report.diagnostics["source_error_code"] == FgoAppStopErrorCode.ADB_COMMAND_FAILED.value


# ── 完整工作流 ──────────────────────────────────────────────────────────────

def run_workflow(config, runtime_factories, *, deadline=None, cancel=None):
    factory = build_production_executor_factory(config, runtime_factories=runtime_factories)
    sink_records: list[object] = []

    class Sink:
        def write(self, report):
            sink_records.append(report)

    managed = config.mumu.lifecycle_mode is MumuLifecycleMode.MANAGED
    runner = WorkflowRunner(
        build_execution_plan(config),
        factory,
        Sink(),
        failure_cleanup_stages=(
            (StageName.STOP_FGO, StageName.SHUTDOWN_MUMU) if managed else (StageName.STOP_FGO,)
        ),
        failure_cleanup_required=factory.failure_cleanup_required,
        failure_cleanup_timeout_seconds=5.0,
    )
    fixed_deadline = deadline if deadline is not None else Deadline.after(30)
    report = runner.run(
        deadline=fixed_deadline, cancel=cancel, run_id="00000000-0000-0000-0000-000000000003"
    )
    return report, factory, sink_records


def test_managed_fgo_workflow_success(tmp_path):
    config = fgo_config(tmp_path)
    runtime_factories, maafgo_factory, stop = fgo_factories(
        config, maafgo_port=FakeMaaFgoPort(maafgo_result(), write_artifact=True)
    )
    report, factory, sinks = run_workflow(config, runtime_factories)
    assert report.status is RunStatus.SUCCESS and report.error_code is ErrorCode.OK
    assert [s.stage for s in report.stages] == list(MANAGED_FGO_STAGES)
    assert sinks and sinks[0].status is RunStatus.SUCCESS
    contract = factory.state.maafgo_run_contract
    assert contract is not None
    assert maafgo_factory.contracts == [contract]
    assert contract.result_path.is_file()
    assert stop.calls == 1
    assert factory.state.mumu_managed_owned is False  # shutdown 后已释放
    assert len(sinks) == 1


def test_external_fgo_workflow_success_leaves_mumu_running(tmp_path):
    config = fgo_config(tmp_path, lifecycle=MumuLifecycleMode.EXTERNAL)
    runtime_factories, maafgo_factory, stop = fgo_factories(config)
    report, factory, _ = run_workflow(config, runtime_factories)
    assert report.status is RunStatus.SUCCESS
    assert StageName.SHUTDOWN_MUMU not in [s.stage for s in report.stages]
    assert stop.calls == 1
    assert maafgo_factory.contracts


def test_managed_fgo_business_failure_runs_both_cleanups(tmp_path):
    config = fgo_config(tmp_path)
    runtime_factories, _, stop = fgo_factories(
        config,
        maafgo_port=FakeMaaFgoPort(maafgo_result(MaaFgoRunStatus.FAILED, MaaFgoErrorCode.TASK_FAILED)),
        mumu=FgoMumuPort(),
    )
    report, factory, _ = run_workflow(config, runtime_factories)
    assert report.status is RunStatus.FAILURE
    assert report.error_code is ErrorCode.WORKFLOW_STAGE_FAILED
    reports = {s.stage: s for s in report.stages}
    assert reports[StageName.RUN_MAAFGO].outcome is OutcomeKind.FAILURE
    assert reports[StageName.STOP_FGO].outcome is OutcomeKind.SUCCESS
    assert reports[StageName.STOP_FGO].diagnostics["failure_cleanup"] is True
    assert reports[StageName.SHUTDOWN_MUMU].outcome is OutcomeKind.SUCCESS
    assert reports[StageName.SHUTDOWN_MUMU].diagnostics["failure_cleanup"] is True
    assert stop.calls == 1
    assert report.diagnostics["failure_cleanup_attempted"] is True


def test_managed_fgo_timeout_runs_cleanups(tmp_path):
    config = fgo_config(tmp_path)
    runtime_factories, _, stop = fgo_factories(
        config, maafgo_port=FakeMaaFgoPort(maafgo_result(MaaFgoRunStatus.TIMEOUT, MaaFgoErrorCode.TASK_TIMEOUT))
    )
    report, _, _ = run_workflow(config, runtime_factories)
    reports = {s.stage: s for s in report.stages}
    assert report.status is RunStatus.FAILURE and report.error_code is ErrorCode.WORKFLOW_STAGE_TIMEOUT
    assert reports[StageName.RUN_MAAFGO].outcome is OutcomeKind.TIMEOUT
    assert reports[StageName.STOP_FGO].outcome is OutcomeKind.SUCCESS
    assert reports[StageName.SHUTDOWN_MUMU].outcome is OutcomeKind.SUCCESS
    assert stop.calls == 1


def test_managed_fgo_cancellation_preserves_environment(tmp_path):
    """用户取消：不主动破坏用户环境 —— 不停 FGO、不关 MuMu；owned 进程树由适配器终止。"""
    config = fgo_config(tmp_path)
    runtime_factories, _, stop = fgo_factories(
        config, maafgo_port=FakeMaaFgoPort(maafgo_result(MaaFgoRunStatus.CANCELLED, MaaFgoErrorCode.CANCELLED))
    )
    report, _, _ = run_workflow(config, runtime_factories)
    reports = {s.stage: s for s in report.stages}
    assert report.status is RunStatus.CANCELLED
    assert reports[StageName.RUN_MAAFGO].outcome is OutcomeKind.CANCELLED
    assert reports[StageName.STOP_FGO].outcome is OutcomeKind.SKIPPED
    assert reports[StageName.SHUTDOWN_MUMU].outcome is OutcomeKind.SKIPPED
    assert stop.calls == 0
    assert "failure_cleanup_attempted" not in report.diagnostics


def test_prepare_failure_skips_fgo_cleanup(tmp_path):
    """PREPARE 失败 = FGO 从未运行：STOP_FGO cleanup 不得执行。"""
    config = fgo_config(tmp_path)
    (Path(config.maafgo.working_directory) / "distribution-manifest.json").unlink()
    runtime_factories, _, stop = fgo_factories(config)
    report, _, _ = run_workflow(config, runtime_factories)
    assert report.status is RunStatus.FAILURE
    reports = {s.stage: s for s in report.stages}
    assert reports[StageName.PREPARE_MAAFGO_RUN].outcome is OutcomeKind.FAILURE
    # FGO 从未运行：STOP_FGO cleanup 跳过；但 managed MuMu 已被启动，必须安全关闭。
    assert reports[StageName.STOP_FGO].outcome is OutcomeKind.SKIPPED
    assert stop.calls == 0
    assert reports[StageName.SHUTDOWN_MUMU].outcome is OutcomeKind.SUCCESS
    assert reports[StageName.SHUTDOWN_MUMU].diagnostics["failure_cleanup"] is True
