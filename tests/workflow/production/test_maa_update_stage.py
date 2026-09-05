from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from autogame_orchestrator.config_model import AppConfig, MAAUpdateConfig
from autogame_orchestrator.models import ErrorCode, OutcomeKind, StageName
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.runtime.maa_models import MAARunStatus
from autogame_orchestrator.runtime.models import MumuRuntimeStatus
from autogame_orchestrator.workflow.contracts import StageExecutionContext
from autogame_orchestrator.workflow.plan import build_execution_plan
from autogame_orchestrator.workflow.production.factory import build_production_executor_factory
from autogame_orchestrator.workflow.runner import WorkflowRunner
from tests.workflow.fakes import MemorySink
from tests.workflow.production.fakes import FakeMumuPort, FakeRunPort, maa_result, mumu_result, valid_config
from tests.workflow.production.test_executors_and_factory import CountingFactory, factories


def context(deadline=None, cancel=None) -> StageExecutionContext:
    return StageExecutionContext(
        "00000000-0000-0000-0000-000000000001",
        StageName.UPDATE_MAA,
        deadline,
        cancel or CancellationToken(),
    )


def enabled_config() -> AppConfig:
    return AppConfig(maa_update=MAAUpdateConfig(True, True))


def with_update_port(status: MAARunStatus):
    port = FakeRunPort(maa_result(status))
    runtime_factories, counts = factories()
    return replace(runtime_factories, maa_update=CountingFactory("maa_update", port, counts)), counts, port


def test_disabled_update_constructs_no_port() -> None:
    runtime_factories, counts = factories()
    report = build_production_executor_factory(AppConfig(), runtime_factories=runtime_factories)(
        StageName.UPDATE_MAA
    ).execute(context())
    assert (report.outcome, report.error_code) == (OutcomeKind.SUCCESS, ErrorCode.OK)
    assert report.diagnostics == {"enabled": False, "executed": False}
    assert counts == Counter()


def test_enabled_without_network_fails_before_port() -> None:
    runtime_factories, counts = factories()
    config = AppConfig(maa_update=MAAUpdateConfig(enabled=True))
    report = build_production_executor_factory(config, runtime_factories=runtime_factories)(
        StageName.UPDATE_MAA
    ).execute(context())
    assert report.error_code == ErrorCode.CONFIG_SCHEMA_ERROR
    assert counts == Counter()


@pytest.mark.parametrize(
    "status,outcome,code",
    [
        (MAARunStatus.COMPLETED, OutcomeKind.SUCCESS, ErrorCode.OK),
        (MAARunStatus.FAILED, OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED),
        (MAARunStatus.TIMEOUT, OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT),
        (MAARunStatus.CANCELLED, OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED),
    ],
)
def test_update_status_projection(status: MAARunStatus, outcome: OutcomeKind, code: ErrorCode) -> None:
    runtime_factories, counts, _ = with_update_port(status)
    report = build_production_executor_factory(enabled_config(), runtime_factories=runtime_factories)(
        StageName.UPDATE_MAA
    ).execute(context())
    assert (report.outcome, report.error_code) == (outcome, code)
    assert counts["maa_update"] == 1


def test_update_preserves_deadline_and_cancellation_identity() -> None:
    runtime_factories, _, port = with_update_port(MAARunStatus.COMPLETED)
    deadline = Deadline.after(30)
    token = CancellationToken()
    build_production_executor_factory(enabled_config(), runtime_factories=runtime_factories)(
        StageName.UPDATE_MAA
    ).execute(context(deadline, token))
    assert port.deadline is deadline
    assert port.cancel is token


def test_update_projection_is_strict_allowlist() -> None:
    runtime_factories, _, _ = with_update_port(MAARunStatus.COMPLETED)
    report = build_production_executor_factory(enabled_config(), runtime_factories=runtime_factories)(
        StageName.UPDATE_MAA
    ).execute(context())
    assert set(report.diagnostics) == {
        "enabled",
        "executed",
        "source_error_code",
        "termination_reason",
        "exit_code",
        "owned_process_cleaned",
        "stdout_truncated",
        "stderr_truncated",
        "stdout_present",
        "stderr_present",
        "failure_markers",
    }
    assert report.diagnostics["exit_code"] == 0
    assert report.diagnostics["termination_reason"] == "normal_exit"
    assert report.diagnostics["owned_process_cleaned"] is True


def test_update_projection_excludes_sensitive_runtime_fields() -> None:
    runtime_factories, _, _ = with_update_port(MAARunStatus.COMPLETED)
    report = build_production_executor_factory(enabled_config(), runtime_factories=runtime_factories)(
        StageName.UPDATE_MAA
    ).execute(context())
    encoded = repr(report)
    for forbidden in ("654321", "stdout secret", "stderr secret", "private", "TOKEN_VALUE", "--channel", "stable"):
        assert forbidden not in encoded


def test_update_port_constructed_at_most_once() -> None:
    runtime_factories, counts, port = with_update_port(MAARunStatus.COMPLETED)
    factory = build_production_executor_factory(enabled_config(), runtime_factories=runtime_factories)
    factory(StageName.UPDATE_MAA).execute(context())
    factory(StageName.UPDATE_MAA).execute(context())
    assert counts["maa_update"] == 1
    assert port.calls == 2


def test_update_failure_prevents_mumu_construction(tmp_path: Path) -> None:
    config = replace(valid_config(tmp_path), maa_update=MAAUpdateConfig(True, True))
    runtime_factories, counts, _ = with_update_port(MAARunStatus.FAILED)
    report = WorkflowRunner(
        build_execution_plan(config),
        build_production_executor_factory(config, runtime_factories=runtime_factories),
        MemorySink(),
    ).run(deadline=Deadline.after(30))
    assert report.stages[2].error_code == ErrorCode.WORKFLOW_STAGE_FAILED
    assert counts["mumu"] == 0


def test_update_repository_pull_failure_is_visible_in_report() -> None:
    """maa update 阶段也应当暴露稳定 marker：资源仓库 pull 失败会在这里显形。"""
    port = FakeRunPort(
        maa_result(
            MAARunStatus.FAILED,
            stdout_excerpt="",
            stderr_excerpt="Error: Failed to pull resource repository",
        )
    )
    runtime_factories, counts = factories()
    runtime_factories = replace(runtime_factories, maa_update=CountingFactory("maa_update", port, counts))
    report = build_production_executor_factory(enabled_config(), runtime_factories=runtime_factories)(
        StageName.UPDATE_MAA
    ).execute(context())
    assert report.outcome == OutcomeKind.FAILURE
    assert report.diagnostics["failure_markers"] == ["resource_repo_pull_failed"]


def test_disabled_update_reaches_stopped_mumu_gate(tmp_path: Path) -> None:
    config = valid_config(tmp_path)
    mumu = FakeMumuPort(mumu_result(MumuRuntimeStatus.STOPPED))
    runtime_factories, counts = factories(mumu=mumu)
    report = WorkflowRunner(
        build_execution_plan(config),
        build_production_executor_factory(config, runtime_factories=runtime_factories),
        MemorySink(),
    ).run(deadline=Deadline.after(30))
    assert report.stages[2].outcome == OutcomeKind.SUCCESS
    assert report.stages[3].outcome == OutcomeKind.SUCCESS
    assert report.stages[4].error_code == ErrorCode.WORKFLOW_STAGE_BLOCKED
    assert report.stages[4].diagnostics["blocker"] == "mumu_start_not_approved"
    assert counts["mumu"] == 1


def test_ready_mumu_managed_stop_stage_catches_not_stopped(tmp_path: Path) -> None:
    """managed 下 stop_mumu 会真正执行；若模拟器仍报 READY，该阶段自身即应失败。

    Fake 模拟器恒返 READY（不会真停），因此停止阶段就应当场报错，
    而不是放行到下一个验证阶段才发现。
    """
    config = valid_config(tmp_path)
    runtime_factories, _ = factories()
    report = WorkflowRunner(
        build_execution_plan(config),
        build_production_executor_factory(config, runtime_factories=runtime_factories),
        MemorySink(),
    ).run(deadline=Deadline.after(30))
    assert report.stages[2].outcome == OutcomeKind.SUCCESS
    assert report.stages[3].outcome == OutcomeKind.SUCCESS
    assert report.stages[4].outcome == OutcomeKind.SUCCESS
    assert report.stages[9].error_code == ErrorCode.WORKFLOW_STAGE_FAILED
    assert report.stages[10].outcome == OutcomeKind.SKIPPED
