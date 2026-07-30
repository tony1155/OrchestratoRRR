"""操作系统平台能力。"""

from autogame_orchestrator.platform.windows_elevation import (
    ElevationErrorCode,
    ElevationResult,
    is_process_elevated,
    relaunch_current_process_elevated,
)

__all__ = [
    "ElevationErrorCode",
    "ElevationResult",
    "is_process_elevated",
    "relaunch_current_process_elevated",
]
