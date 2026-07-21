"""运行时管理子包。

MuMu 生命周期适配器
StarRailCopilot 任务 Adapter
"""

from autogame_orchestrator.runtime.models import MumuAction, MumuRuntimeErrorCode, MumuRuntimeResult, MumuRuntimeStatus
from autogame_orchestrator.runtime.mumu import MumuAdapter
from autogame_orchestrator.runtime.starrail import StarRailAdapter
from autogame_orchestrator.runtime.starrail_models import (
    StarRailCompletionMode,
    StarRailErrorCode,
    StarRailRunResult,
    StarRailRunStatus,
)

__all__ = [
    "MumuAdapter",
    "MumuAction",
    "MumuRuntimeStatus",
    "MumuRuntimeErrorCode",
    "MumuRuntimeResult",
    "StarRailAdapter",
    "StarRailRunResult",
    "StarRailRunStatus",
    "StarRailCompletionMode",
    "StarRailErrorCode",
]
