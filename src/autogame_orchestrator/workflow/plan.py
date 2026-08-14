"""Phase 6A 的冻结执行计划。"""

from __future__ import annotations

from dataclasses import dataclass

from autogame_orchestrator.config_model import AppConfig, MumuLifecycleMode
from autogame_orchestrator.models import StageName
from autogame_orchestrator.planning import build_plan


@dataclass(frozen=True)
class ExecutionPlan:
    """经结构校验的不可变工作流计划。"""

    stages: tuple[StageName, ...]
    requires_administrator: bool

    def __post_init__(self) -> None:
        if not isinstance(self.stages, tuple) or not self.stages:
            raise ValueError("工作流计划必须包含非空 tuple 阶段")
        if any(not isinstance(stage, StageName) for stage in self.stages):
            raise ValueError("工作流计划只能包含 StageName")
        if len(set(self.stages)) != len(self.stages):
            raise ValueError("工作流计划不得包含重复阶段")
        if self.stages[0] != StageName.VALIDATE_CONFIG:
            raise ValueError("VALIDATE_CONFIG 必须是首个阶段")
        if self.stages[-1] != StageName.WRITE_RUN_REPORT:
            raise ValueError("WRITE_RUN_REPORT 必须是最后阶段")
        if self.stages.count(StageName.WRITE_RUN_REPORT) != 1:
            raise ValueError("WRITE_RUN_REPORT 必须且只能出现一次")
        if type(self.requires_administrator) is not bool:
            raise ValueError("requires_administrator 必须是严格 bool")


def build_execution_plan(
    config: AppConfig,
    *,
    stages: tuple[StageName, ...] | None = None,
) -> ExecutionPlan:
    """纯函数构建执行计划，不做路径、进程或权限操作。"""
    selected = build_plan() if stages is None else stages
    if stages is None and config.mumu.lifecycle_mode == MumuLifecycleMode.EXTERNAL:
        removed = {
            StageName.STOP_MUMU,
            StageName.VERIFY_MUMU_STOPPED,
            StageName.START_MUMU,
            StageName.WAIT_MUMU_ADB_READY_AFTER_RESTART,
            StageName.SHUTDOWN_MUMU,
        }
        selected = tuple(stage for stage in selected if stage not in removed)
    requires_administrator = (
        StageName.SYNC_MAA_CONFIG in selected
        and config.maa_sync.enabled is True
        and config.maa_sync.requires_administrator is True
    ) or (
        StageName.UPDATE_MAA in selected
        and config.maa_update.enabled is True
        and config.maa_update.requires_administrator is True
    )
    return ExecutionPlan(stages=selected, requires_administrator=requires_administrator)
