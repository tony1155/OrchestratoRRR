from __future__ import annotations

import os
import subprocess
import sys

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


def test_elevation_process_handle_is_closed(monkeypatch) -> None:
    api = FakeApi()
    monkeypatch.setattr(elevation, "_api", api)
    result = elevation.relaunch_current_process_elevated(["-m", "module"])
    assert result.exit_code == 23
    assert api.closed == [101]


def test_elevation_preserves_working_directory(monkeypatch) -> None:
    api = FakeApi()
    monkeypatch.setattr(elevation, "_api", api)
    elevation.relaunch_current_process_elevated(["-m", "module"])
    assert api.working_directory == os.getcwd()
    assert api.executable == sys.executable


def test_elevation_arguments_are_windows_quoted(monkeypatch) -> None:
    api = FakeApi()
    monkeypatch.setattr(elevation, "_api", api)
    arguments = ["-m", "module", "--config", r"C:\path with spaces\config.toml", 'a"b']
    elevation.relaunch_current_process_elevated(arguments)
    assert api.parameters == subprocess.list2cmdline(arguments)


def test_elevation_does_not_expose_config_contents(monkeypatch) -> None:
    api = FakeApi()
    monkeypatch.setattr(elevation, "_api", api)
    elevation.relaunch_current_process_elevated(["-m", "module", "--config", "local.toml"])
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
    result = elevation.relaunch_current_process_elevated(["-m", "module"])
    assert result.error_code == elevation.ElevationErrorCode.ELEVATION_CANCELLED
    assert result.exit_code is None


def test_other_launch_failure_is_structured(monkeypatch) -> None:
    api = FakeApi()

    def fail(executable: str, parameters: str, working_directory: str) -> int:
        raise elevation.ElevationLaunchError(5)

    api.launch_elevated = fail  # type: ignore[method-assign]
    monkeypatch.setattr(elevation, "_api", api)
    result = elevation.relaunch_current_process_elevated(["-m", "module"])
    assert result.error_code == elevation.ElevationErrorCode.ELEVATION_FAILED
