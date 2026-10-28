"""单次生产工作流使用的最小安全状态。"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autogame_orchestrator.maafgo_evidence import MaaFgoRunContract


@dataclass
class ProductionWorkflowState:
    """不保存 PID、输出、句柄或完整 Runtime 结果。

    例外：``maafgo_run_contract`` 保存 PREPARE 阶段创建的 run 契约（含本地
    run 目录路径），仅供同一工作流的 RUN_MAAFGO 使用；路径永不进入 RunReport。
    """

    starrail_run_reached: bool = False
    starrail_completed: bool = False
    starrail_owned_process_cleaned: bool = False
    mumu_managed_owned: bool = False
    maafgo_run_contract: "MaaFgoRunContract | None" = None
    maafgo_run_reached: bool = False
