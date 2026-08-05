from __future__ import annotations

import subprocess
from pathlib import Path

from autogame_orchestrator.entry_runtime import ElevationLaunchSpec
from autogame_orchestrator.platform import windows_elevation as elevation


class FakeApi:
    def __init__(self) -> None:
        self.executable = ""
        self.parameters = ""
        self.working_directory = ""
        self.closed: list[int] = []
        self.exit_code = 23

    def is_process_elevated(self) -> bool:
        return True

    def launch_elevated(self, executable: str, parameters: str, working_directory: str) -> int:
        self.executable = executable
        self.parameters = parameters
        self.working_directory = working_directory
        return 101

    def wait_for_exit(self, handle: int) -> int:
        assert handle == 101
        return self.exit_code

    def close_handle(self, handle: int) -> None:
        self.closed.append(handle)


def _spec(arguments: tuple[str, ...] = ("run",)) -> ElevationLaunchSpec:
    return ElevationLaunchSpec(
        executable=Path(r"C:\Program Files\OrchestratoRRR\OrchestratoRRR.exe"),
        arguments=arguments,
        working_directory=Path(r"C:\Program Files\OrchestratoRRR"),
    )


def test_elevation_process_handle_is_closed(monkeypatch) -> None:
    api = FakeApi()
    monkeypatch.setattr(elevation, "_api", api)
    result = elevation.relaunch_current_process_elevated(_spec())
    assert result.exit_code == 23
    assert api.closed == [101]


def test_elevation_preserves_working_directory(monkeypatch) -> None:
    api = FakeApi()
    monkeypatch.setattr(elevation, "_api", api)
    spec = _spec()
    elevation.relaunch_current_process_elevated(spec)
    assert api.working_directory == str(spec.working_directory)
    assert api.executable == str(spec.executable)


def test_elevation_arguments_are_windows_quoted(monkeypatch) -> None:
    api = FakeApi()
    monkeypatch.setattr(elevation, "_api", api)
    arguments = ["-m", "module", "--config", r"C:\path with spaces\config.toml", 'a"b']
    spec = _spec(tuple(arguments))
    elevation.relaunch_current_process_elevated(spec)
    assert api.parameters == subprocess.list2cmdline(list(spec.arguments))


def test_elevation_preserves_unicode_paths_and_argument_boundaries(monkeypatch) -> None:
    api = FakeApi()
    monkeypatch.setattr(elevation, "_api", api)
    spec = ElevationLaunchSpec(
        executable=Path("C:/程序/OrchestratoRRR.exe"),
        arguments=("run", "--config", "C:/配置 目录/配置.toml", r"反斜杠\引号"),
        working_directory=Path("C:/工作 目录/入口"),
    )

    elevation.relaunch_current_process_elevated(spec)

    assert api.executable == str(spec.executable)
    assert api.parameters == subprocess.list2cmdline(list(spec.arguments))
    assert api.working_directory == str(spec.working_directory)


def test_elevation_does_not_expose_config_contents(monkeypatch) -> None:
    api = FakeApi()
    monkeypatch.setattr(elevation, "_api", api)
    elevation.relaunch_current_process_elevated(_spec(("-m", "module", "--config", "local.toml")))
    assert "secret-config-content" not in api.parameters
    assert "environment-value" not in api.parameters


def test_is_process_elevated_uses_api_boundary(monkeypatch) -> None:
    api = FakeApi()
    monkeypatch.setattr(elevation, "_api", api)
    assert elevation.is_process_elevated() is True


def test_uac_cancel_is_structured(monkeypatch) -> None:
    api = FakeApi()

    def cancel(executable: str, parameters: str, working_directory: str) -> int:
        raise elevation.ElevationLaunchError(elevation.ERROR_CANCELLED)

    api.launch_elevated = cancel  # type: ignore[method-assign]
    monkeypatch.setattr(elevation, "_api", api)
    result = elevation.relaunch_current_process_elevated(_spec())
    assert result.error_code == elevation.ElevationErrorCode.ELEVATION_CANCELLED
    assert result.exit_code is None


def test_other_launch_failure_is_structured(monkeypatch) -> None:
    api = FakeApi()

    def fail(executable: str, parameters: str, working_directory: str) -> int:
        raise elevation.ElevationLaunchError(5)

    api.launch_elevated = fail  # type: ignore[method-assign]
    monkeypatch.setattr(elevation, "_api", api)
    result = elevation.relaunch_current_process_elevated(_spec())
    assert result.error_code == elevation.ElevationErrorCode.ELEVATION_FAILED


def test_empty_process_handle_is_structured_without_close(monkeypatch) -> None:
    api = FakeApi()

    def empty_handle(executable: str, parameters: str, working_directory: str) -> int:
        return 0

    api.launch_elevated = empty_handle  # type: ignore[method-assign]
    monkeypatch.setattr(elevation, "_api", api)

    result = elevation.relaunch_current_process_elevated(_spec())

    assert result.error_code == elevation.ElevationErrorCode.ELEVATION_FAILED
    assert api.closed == []


def test_wait_failure_is_structured_and_handle_is_closed(monkeypatch) -> None:
    api = FakeApi()

    def wait_failure(handle: int) -> int:
        raise OSError("wait failed")

    api.wait_for_exit = wait_failure  # type: ignore[method-assign]
    monkeypatch.setattr(elevation, "_api", api)
    result = elevation.relaunch_current_process_elevated(_spec())
    assert result.error_code == elevation.ElevationErrorCode.ELEVATION_FAILED
    assert api.closed == [101]


def test_close_handle_failure_does_not_replace_success(monkeypatch) -> None:
    api = FakeApi()

    def close_failure(handle: int) -> None:
        api.closed.append(handle)
        raise OSError("close failed")

    api.close_handle = close_failure  # type: ignore[method-assign]
    monkeypatch.setattr(elevation, "_api", api)

    result = elevation.relaunch_current_process_elevated(_spec())

    assert result == elevation.ElevationResult(elevation.ElevationErrorCode.OK, 23)
    assert api.closed == [101]
