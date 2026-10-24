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

# FGO（Mash）生产计划：Orchestrator 拥有 MuMu 生命周期，Mash 只消费已就绪的
# ADB 设备，不做 MAA 那样的中途重启（单游戏单运行）。managed 变体在收尾关闭
# MuMu；external 变体由 ``build_execution_plan`` 的 external 过滤移除
# SHUTDOWN_MUMU。
_FGO_MANAGED_PLAN: tuple[StageName, ...] = (
    StageName.VALIDATE_CONFIG,
    StageName.ENSURE_MUMU_RUNNING,
    StageName.WAIT_MUMU_ADB_READY,
    StageName.RUN_MASH,
    StageName.SHUTDOWN_MUMU,
    StageName.WRITE_RUN_REPORT,
)


def build_plan() -> tuple[StageName, ...]:
    """Return the static execution plan (no dynamic resolution)."""
    return _DEFAULT_PLAN


def build_fgo_plan() -> tuple[StageName, ...]:
    """Return the static FGO (Mash) execution plan."""
    return _FGO_MANAGED_PLAN


PLAN_HEADER = "DRY PLAN — no external programs will be executed"
