"""MaaResource 增量资源的安全覆盖合并。"""

from autogame_orchestrator.maa_resource.merger import MAAResourceMerger
from autogame_orchestrator.maa_resource.models import (
    MAAResourceMergeErrorCode,
    MAAResourceMergeResult,
    MAAResourceMergeStatus,
)

__all__ = [
    "MAAResourceMergeErrorCode",
    "MAAResourceMergeResult",
    "MAAResourceMergeStatus",
    "MAAResourceMerger",
]
