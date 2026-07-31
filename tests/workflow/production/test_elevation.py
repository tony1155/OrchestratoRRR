from __future__ import annotations

from pathlib import Path

from autogame_orchestrator.entry_runtime import ElevationLaunchSpec
from autogame_orchestrator.platform.windows_elevation import ElevationErrorCode, ElevationResult
from autogame_orchestrator.workflow.production import elevation


def test_production_gateway_forwards_complete_launch_spec(monkeypatch) -> None:
    spec = ElevationLaunchSpec(
        executable=Path(r"C:Program FilesOrchestratoRRROrchestratoRRR.exe"),
        arguments=("run", "--config", r"C:Program Filesconfig.toml"),
        working_directory=Path(r"C:Program FilesOrchestratoRRR"),
    )
    captured: list[ElevationLaunchSpec] = []

    def relaunch(value: ElevationLaunchSpec) -> ElevationResult:
        captured.append(value)
        return ElevationResult(ElevationErrorCode.OK, 37)

    monkeypatch.setattr(elevation, "relaunch_current_process_elevated", relaunch)
    result = elevation.WindowsElevationGateway().relaunch(spec)

    assert captured == [spec]
    assert result.error_code == ElevationErrorCode.OK
    assert result.exit_code == 37
