"""生产工作流入口的 Windows elevation gateway。"""

from dataclasses import dataclass

from autogame_orchestrator.entry_runtime import ElevationLaunchSpec
from autogame_orchestrator.platform.windows_elevation import (
    is_process_elevated,
    relaunch_current_process_elevated,
)
from autogame_orchestrator.workflow.contracts import ElevationGatewayResult


@dataclass(frozen=True)
class _StableElevationResult:
    error_code: str
    exit_code: int


class WindowsElevationGateway:
    """复用平台层实现，不复制任何 Win32 提权逻辑。"""

    def is_elevated(self) -> bool:
        return is_process_elevated()

    def relaunch(self, spec: ElevationLaunchSpec) -> ElevationGatewayResult:
        result = relaunch_current_process_elevated(spec)
        return _StableElevationResult(
            error_code=result.error_code,
            exit_code=result.exit_code if result.exit_code is not None else 10,
        )
