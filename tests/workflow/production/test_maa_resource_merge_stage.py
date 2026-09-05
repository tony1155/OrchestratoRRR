"""MERGE_MAA_RESOURCE 阶段的投影、惰性绑定与顺序契约。"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from autogame_orchestrator.config_model import AppConfig, MAAResourceMergeConfig
from autogame_orchestrator.maa_resource.models import MAAResourceMergeStatus
from autogame_orchestrator.models import ErrorCode, OutcomeKind, StageName
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.workflow.contracts import StageExecutionContext
from autogame_orchestrator.workflow.plan import build_execution_plan
from autogame_orchestrator.workflow.production.factory import build_production_executor_factory
from autogame_orchestrator.workflow.runner import WorkflowRunner
from tests.workflow.fakes import MemorySink
from tests.workflow.production.fakes import FakeRunPort, merge_config, merge_result, valid_config
from tests.workflow.production.test_executors_and_factory import factories


def context(deadline=None, cancel=None) -> StageExecutionContext:
    return StageExecutionContext(
        "00000000-0000-0000-0000-000000000001",
        StageName.MERGE_MAA_RESOURCE,
        deadline,
        cancel or CancellationToken(),
    )


def enabled_config(root: Path) -> AppConfig:
    return AppConfig(maa_resource_merge=merge_config(root))


def with_merge_port(status: MAAResourceMergeStatus, *, files_copied: int = 3):
    port = FakeRunPort(merge_result(status, files_copied=files_copied))
    runtime_factories, counts = factories(maa_resource_merge=port)
    return runtime_factories, counts, port


def test_disabled_merge_constructs_no_port() -> None:
    runtime_factories, counts = factories()
    report = build_production_executor_factory(AppConfig(), runtime_factories=runtime_factories)(
        StageName.MERGE_MAA_RESOURCE
    ).execute(context())
    assert (report.outcome, report.error_code) == (OutcomeKind.SUCCESS, ErrorCode.OK)
    assert report.diagnostics == {"enabled": False, "executed": False}
    assert counts == Counter()


def test_invalid_merge_configuration_fails_before_port(tmp_path: Path) -> None:
    runtime_factories, counts = factories()
    config = AppConfig(
        maa_resource_merge=MAAResourceMergeConfig(
            enabled=True,
            source_directory="",
            destination_directory="",
        )
    )
    report = build_production_executor_factory(config, runtime_factories=runtime_factories)(
        StageName.MERGE_MAA_RESOURCE
    ).execute(context())
    assert report.error_code == ErrorCode.CONFIG_SCHEMA_ERROR
    assert counts == Counter()


@pytest.mark.parametrize(
    "status,outcome,code",
    [
        (MAAResourceMergeStatus.COMPLETED, OutcomeKind.SUCCESS, ErrorCode.OK),
        (MAAResourceMergeStatus.FAILED, OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED),
        (MAAResourceMergeStatus.TIMEOUT, OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT),
        (MAAResourceMergeStatus.CANCELLED, OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED),
    ],
)
def test_merge_status_projection(
    tmp_path: Path,
    status: MAAResourceMergeStatus,
    outcome: OutcomeKind,
    code: ErrorCode,
) -> None:
    runtime_factories, counts, _ = with_merge_port(status)
    report = build_production_executor_factory(enabled_config(tmp_path), runtime_factories=runtime_factories)(
        StageName.MERGE_MAA_RESOURCE
    ).execute(context())
    assert (report.outcome, report.error_code) == (outcome, code)
    assert counts["maa_resource_merge"] == 1


def test_merge_preserves_deadline_and_cancellation_identity(tmp_path: Path) -> None:
    runtime_factories, _, port = with_merge_port(MAAResourceMergeStatus.COMPLETED)
    deadline = Deadline.after(30)
    token = CancellationToken()
    build_production_executor_factory(enabled_config(tmp_path), runtime_factories=runtime_factories)(
        StageName.MERGE_MAA_RESOURCE
    ).execute(context(deadline, token))
    assert port.deadline is deadline
    assert port.cancel is token


def test_merge_projection_is_strict_allowlist(tmp_path: Path) -> None:
    runtime_factories, _, _ = with_merge_port(MAAResourceMergeStatus.COMPLETED)
    report = build_production_executor_factory(enabled_config(tmp_path), runtime_factories=runtime_factories)(
        StageName.MERGE_MAA_RESOURCE
    ).execute(context())
    assert set(report.diagnostics) == {
        "enabled",
        "executed",
        "source_error_code",
        "changed",
        "files_scanned",
        "files_copied",
        "files_identical",
        "bytes_copied",
        "directories_created",
    }
    assert report.diagnostics["changed"] is True
    assert report.diagnostics["files_copied"] == 3


def test_merge_projection_reports_no_change_when_nothing_copied(tmp_path: Path) -> None:
    """两份资源已一致时阶段成功且 changed=False，用于区分「无需合并」与「合并过」。"""
    runtime_factories, _, _ = with_merge_port(MAAResourceMergeStatus.COMPLETED, files_copied=0)
    report = build_production_executor_factory(enabled_config(tmp_path), runtime_factories=runtime_factories)(
        StageName.MERGE_MAA_RESOURCE
    ).execute(context())
    assert report.outcome == OutcomeKind.SUCCESS
    assert report.diagnostics["changed"] is False


def test_merge_projection_excludes_paths(tmp_path: Path) -> None:
    runtime_factories, _, _ = with_merge_port(MAAResourceMergeStatus.COMPLETED)
    report = build_production_executor_factory(enabled_config(tmp_path), runtime_factories=runtime_factories)(
        StageName.MERGE_MAA_RESOURCE
    ).execute(context())
    encoded = repr(report)
    assert str(tmp_path) not in encoded
    assert "MaaResource" not in encoded


def test_merge_port_constructed_at_most_once(tmp_path: Path) -> None:
    runtime_factories, counts, port = with_merge_port(MAAResourceMergeStatus.COMPLETED)
    factory = build_production_executor_factory(enabled_config(tmp_path), runtime_factories=runtime_factories)
    factory(StageName.MERGE_MAA_RESOURCE).execute(context())
    factory(StageName.MERGE_MAA_RESOURCE).execute(context())
    assert counts["maa_resource_merge"] == 1
    assert port.calls == 2


def test_merge_runs_immediately_after_update() -> None:
    """顺序契约：合并必须紧跟 update_maa。

    ``maa update`` 先把 MaaResource 仓库 pull 到最新，且 MaaCore 升级会把 resource
    重刷回该版本自带内容；合并只有排在两者之后才能得到正确结果。
    """
    stages = build_execution_plan(AppConfig()).stages
    assert stages.index(StageName.MERGE_MAA_RESOURCE) == stages.index(StageName.UPDATE_MAA) + 1


def test_merge_precedes_every_mumu_and_runtime_stage() -> None:
    stages = build_execution_plan(AppConfig()).stages
    merge_index = stages.index(StageName.MERGE_MAA_RESOURCE)
    for stage in (StageName.ENSURE_MUMU_RUNNING, StageName.RUN_STARRAIL, StageName.RUN_MAA):
        assert merge_index < stages.index(stage)


def test_merge_failure_prevents_mumu_construction(tmp_path: Path) -> None:
    """合并失败即代表资源可能处于混合状态，必须在启动模拟器之前停下。"""
    config = replace(valid_config(tmp_path), maa_resource_merge=merge_config(tmp_path / "maa"))
    runtime_factories, counts, _ = with_merge_port(MAAResourceMergeStatus.FAILED)
    report = WorkflowRunner(
        build_execution_plan(config),
        build_production_executor_factory(config, runtime_factories=runtime_factories),
        MemorySink(),
    ).run(deadline=Deadline.after(30))
    assert report.stages[3].stage == StageName.MERGE_MAA_RESOURCE
    assert report.stages[3].error_code == ErrorCode.WORKFLOW_STAGE_FAILED
    assert counts["mumu"] == 0
    assert all(stage.outcome == OutcomeKind.SKIPPED for stage in report.stages[4:-1])


def test_disabled_merge_does_not_break_default_pipeline(tmp_path: Path) -> None:
    """默认关闭时该阶段必须直通，不影响既有流水线。"""
    config = valid_config(tmp_path)
    runtime_factories, counts = factories()
    report = WorkflowRunner(
        build_execution_plan(config),
        build_production_executor_factory(config, runtime_factories=runtime_factories),
        MemorySink(),
    ).run(deadline=Deadline.after(30))
    assert report.stages[3].stage == StageName.MERGE_MAA_RESOURCE
    assert report.stages[3].outcome == OutcomeKind.SUCCESS
    assert counts["maa_resource_merge"] == 0
