"""运行时管理子包。

MuMu 生命周期适配器
StarRailCopilot 任务 Adapter
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
from autogame_orchestrator.runtime.mash import MashAdapter
from autogame_orchestrator.runtime.mash_models import MashErrorCode, MashRunResult, MashRunStatus
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
    "MashAdapter",
    "MashRunResult",
    "MashRunStatus",
    "MashErrorCode",
    "StarRailAdapter",
    "StarRailRunResult",
    "StarRailRunStatus",
    "StarRailCompletionMode",
    "StarRailErrorCode",
]
