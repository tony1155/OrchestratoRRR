"""单次生产工作流使用的最小安全状态。"""

from dataclasses import dataclass


@dataclass
class ProductionWorkflowState:
    """不保存 PID、路径、输出、句柄或完整 Runtime 结果。"""

    starrail_run_reached: bool = False
    starrail_completed: bool = False
    starrail_owned_process_cleaned: bool = False
