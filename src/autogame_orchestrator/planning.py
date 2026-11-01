"""Static execution-plan builder.

Produces a dry-run plan as a list of *StageName* values ordered
according to the real-life lifecycle contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autogame_orchestrator.models import StageName

if TYPE_CHECKING:
    pass

_DEFAULT_PLAN: tuple[StageName, ...] = (
    StageName.VALIDATE_CONFIG,
    StageName.SYNC_MAA_CONFIG,
    StageName.UPDATE_MAA,
    StageName.MERGE_MAA_RESOURCE,
    StageName.ENSURE_MUMU_RUNNING,
    StageName.WAIT_MUMU_ADB_READY,
    StageName.RUN_STARRAIL,
    StageName.STOP_STARRAIL,
    StageName.VERIFY_STARRAIL_STOPPED,
    StageName.STOP_MUMU,
    StageName.VERIFY_MUMU_STOPPED,
    StageName.START_MUMU,
    StageName.WAIT_MUMU_ADB_READY_AFTER_RESTART,
    StageName.RUN_MAA,
    StageName.SHUTDOWN_MUMU,
    StageName.WRITE_RUN_REPORT,
)


def build_plan() -> tuple[StageName, ...]:
    """Return the static execution plan (no dynamic resolution)."""
    return _DEFAULT_PLAN


# FGO（MaaFgo）生产计划：Orchestrator 拥有 MuMu 生命周期与 Android 游戏退出；
# MaaFgo 只消费已就绪的 ADB 设备并自己完成登录→导航→助战/编队→native 战斗。
# PREPARE_MAAFGO_RUN 与 RUN_MAAFGO 分开，使 RunReport 能区分
# profile/分发准备失败、进程启动失败与业务完成失败。
# managed 变体在收尾关闭 MuMu；external 变体由 ``build_execution_plan``
# 的 external 过滤移除 SHUTDOWN_MUMU。
_FGO_MANAGED_PLAN: tuple[StageName, ...] = (
    StageName.VALIDATE_CONFIG,
    StageName.ENSURE_MUMU_RUNNING,
    StageName.WAIT_MUMU_ADB_READY,
    StageName.PREPARE_MAAFGO_RUN,
    StageName.RUN_MAAFGO,
    StageName.STOP_FGO,
    StageName.SHUTDOWN_MUMU,
    StageName.WRITE_RUN_REPORT,
)


def build_fgo_plan() -> tuple[StageName, ...]:
    """Return the static FGO (MaaFgo) execution plan."""
    return _FGO_MANAGED_PLAN


PLAN_HEADER = "DRY PLAN — no external programs will be executed"
