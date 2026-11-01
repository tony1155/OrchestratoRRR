"""运行时管理子包。

MuMu 生命周期适配器、StarRailCopilot / MAA / AALC / BetterGI / MaaFgo
任务 Adapter，以及 FGO Android 应用精确退出（STOP_FGO）。
"""

from autogame_orchestrator.runtime.aalc import AALCAdapter
from autogame_orchestrator.runtime.aalc_models import (
    AALCAttemptResult,
    AALCAttemptStatus,
    AALCCompletionMode,
    AALCErrorCode,
    AALCRunResult,
    AALCRunStatus,
)
from autogame_orchestrator.runtime.maa import MAAAdapter
from autogame_orchestrator.runtime.maa_models import MAAErrorCode, MAARunResult, MAARunStatus
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
    "MAAAdapter",
    "MAARunResult",
    "MAARunStatus",
    "MAAErrorCode",
    "AALCAdapter",
    "AALCRunResult",
    "AALCAttemptResult",
    "AALCRunStatus",
    "AALCAttemptStatus",
    "AALCCompletionMode",
    "AALCErrorCode",
    "StarRailAdapter",
    "StarRailRunResult",
    "StarRailRunStatus",
    "StarRailCompletionMode",
    "StarRailErrorCode",
]
