import ctypes
import json
import sys
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autogame_orchestrator.maafgo_config import MaaFgoConfig
from autogame_orchestrator.process import (
    CancellationToken,
    Deadline,
    ProcessExecutionErrorCode,
    ProcessResult,
    ProcessSupervisor,
    TerminationReason,
)
from autogame_orchestrator.runtime.maafgo import MaaFgoAdapter
from autogame_orchestrator.runtime.maafgo_models import MaaFgoErrorCode as Code
from autogame_orchestrator.runtime.maafgo_models import MaaFgoRunResult
from autogame_orchestrator.runtime.maafgo_models import MaaFgoRunStatus as Status
from tests.fakes.maafgo_support import SERIAL, make_project

FAKE = Path(__file__).parents[1] / "fakes" / "fake_maafgo.py"


@pytest.fixture
def config(tmp_path):
    return make_project(tmp_path / "fake project")


class FakeSupervisor(ProcessSupervisor):
    """Only replace invocation; use the real Windows launcher, Job and supervisor."""

    def __init__(self, mode, config):
        super().__init__(kill_confirmation_seconds=config.stop_timeout_seconds)
        self.mode, self.config = mode, config
        self.called = False
        self.closed = False

    def run(self, spec, deadline, cancel=None):
        self.called = True
        assert spec.executable == Path(self.config.executable)
        assert spec.arguments == ("-d",)
        assert spec.working_directory == Path(self.config.working_directory)
        assert spec.stdout_path is None and spec.stderr_path is None
        assert spec.descendants_survive_close is False
        return super().run(
            replace(
                spec,
                executable=Path(sys._base_executable),
                arguments=(str(FAKE), "-d", "--pid-dir", self.config.working_directory),
                environment_overrides={"FAKE_MAAFGO_MODE": self.mode},
            ),
            deadline,
            cancel,
        )

    def close(self):
        super().close()
        self.closed = True


def adapter(config, mode):
    supervisor = FakeSupervisor(mode, config)
    return MaaFgoAdapter(config, expected_adb_serial=SERIAL, supervisor_factory=lambda: supervisor), supervisor


def assert_exited(pid):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if not handle:
            return
        try:
            if ctypes.windll.kernel32.WaitForSingleObject(handle, 100) == 0:
                return
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
        time.sleep(0.02)
    pytest.fail(f"Fake process {pid} survived Job cleanup")


def wait_pid(path):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        try:
            return int(path.read_text())
        except (OSError, ValueError):
            time.sleep(0.02)
    pytest.fail("Fake did not publish its PID")


@pytest.mark.parametrize(
    "mode,exit_code,code",
    [
        ("zero", 0, Code.COMPLETION_UNCONFIRMED),
        ("output", 0, Code.COMPLETION_UNCONFIRMED),
        ("nonzero", 7, Code.PROCESS_EXIT_NONZERO),
    ],
)
def test_real_fake_exit_and_private_output(config, mode, exit_code, code):
    instance, supervisor = adapter(config, mode)
    before = config.profile_path.read_bytes()
    result = instance.run()
    assert result.status == Status.FAILED and result.error_code == code
    assert result.exit_code == exit_code
    assert result.configuration_confirmed and not result.completion_confirmed
    assert result.owned_process_cleaned and supervisor.closed
    assert_exited(wait_pid(Path(config.working_directory) / "parent.pid"))
    serialized = json.dumps(result.diagnostics)
    assert config.working_directory not in serialized
    assert "private stdout" not in serialized and "private stderr" not in serialized
    assert result.diagnostics["output_capture"] == "discarded"
    assert config.profile_path.read_bytes() == before


@pytest.mark.parametrize("mode", ["hang", "spawn"])
def test_parent_deadline_cleans_tree(config, mode):
    instance, supervisor = adapter(config, mode)
    started = time.monotonic()
    result = instance.run(Deadline.after(1.5))
    assert time.monotonic() - started < 5
    assert result.status == Status.TIMEOUT and result.error_code == Code.TASK_TIMEOUT
    assert result.owned_process_cleaned and supervisor.closed
    assert_exited(wait_pid(Path(config.working_directory) / "parent.pid"))
    if mode == "spawn":
        assert_exited(wait_pid(Path(config.working_directory) / "child.pid"))


def test_config_timeout(config):
    instance, _ = adapter(replace(config, timeout_seconds=1), "hang")
    result = instance.run()
    assert result.error_code == Code.TASK_TIMEOUT and result.duration_ms < 5000
    assert_exited(wait_pid(Path(config.working_directory) / "parent.pid"))


@pytest.mark.parametrize("mode", ["spawn_exit", "spawn_nonzero"])
def test_parent_exit_also_kills_living_child(config, mode):
    instance, supervisor = adapter(config, mode)
    result = instance.run()
    assert result.error_code == (Code.COMPLETION_UNCONFIRMED if mode == "spawn_exit" else Code.PROCESS_EXIT_NONZERO)
    assert result.owned_process_cleaned and supervisor.closed
    for name in ("parent.pid", "child.pid"):
        assert_exited(wait_pid(Path(config.working_directory) / name))


def test_cancel_reclaims_child(config):
    instance, supervisor = adapter(config, "spawn")
    cancel, results = CancellationToken(), []
    thread = threading.Thread(target=lambda: results.append(instance.run(cancel=cancel)))
    thread.start()
    try:
        child = wait_pid(Path(config.working_directory) / "child.pid")
    finally:
        cancel.cancel()
        thread.join(6)
    assert not thread.is_alive()
    assert len(results) == 1
    assert results[0].status == Status.CANCELLED and results[0].error_code == Code.CANCELLED
    assert results[0].owned_process_cleaned and supervisor.closed
    assert_exited(child)
    assert_exited(wait_pid(Path(config.working_directory) / "parent.pid"))


def forbidden():
    pytest.fail("Must not construct supervisor or launch")


@pytest.mark.parametrize("pre_cancel", [True, False])
def test_pre_control_does_not_launch(config, pre_cancel):
    cancel = CancellationToken()
    if pre_cancel:
        cancel.cancel()
    result = MaaFgoAdapter(config, expected_adb_serial=SERIAL, supervisor_factory=forbidden).run(
        Deadline.after(0),
        cancel,
    )
    assert result.error_code == (Code.CANCELLED if pre_cancel else Code.TASK_TIMEOUT)
    assert not result.configuration_confirmed


@pytest.mark.parametrize(
    "kind,code",
    [
        ("disabled", Code.INVALID_CONFIGURATION),
        ("timeout", Code.INVALID_CONFIGURATION),
        ("interface", Code.PROJECT_INTERFACE_NOT_FOUND),
        ("profile", Code.PROFILE_NOT_FOUND),
        ("executable", Code.EXECUTABLE_NOT_FOUND),
        ("mismatch", Code.ADB_CONFIGURATION_MISMATCH),
    ],
)
def test_preflight_never_launches(config, kind, code):
    serial = SERIAL
    if kind == "disabled":
        config = MaaFgoConfig()
    elif kind == "timeout":
        config = replace(config, timeout_seconds=True)
    elif kind == "mismatch":
        serial = "127.0.0.1:16416"
    else:
        {"interface": config.interface_path, "profile": config.profile_path, "executable": Path(config.executable)}[
            kind
        ].unlink()
    result = MaaFgoAdapter(config, expected_adb_serial=serial, supervisor_factory=forbidden).run()
    assert result.error_code == code


def test_real_start_failure_is_sanitized(config):
    # An empty placeholder is not a PE executable. It cannot run real business code.
    result = MaaFgoAdapter(config, expected_adb_serial=SERIAL).run()
    assert result.error_code == Code.PROCESS_START_FAILED
    assert result.owned_process_cleaned
    assert config.executable not in json.dumps(result.diagnostics)


@pytest.mark.parametrize("mode", ["zero", "hang"])
def test_close_failure_is_never_hidden(config, mode):
    instance, supervisor = adapter(config, mode)
    original = supervisor.close

    def broken_close():
        original()
        raise OSError(config.working_directory)

    supervisor.close = broken_close
    result = instance.run(Deadline.after(0.7))
    assert result.error_code == Code.CLEANUP_FAILED and not result.owned_process_cleaned
    assert result.status == (Status.TIMEOUT if mode == "hang" else Status.FAILED)
    assert config.working_directory not in json.dumps(result.diagnostics)
    assert_exited(wait_pid(Path(config.working_directory) / "parent.pid"))


def test_control_during_factory_still_closes_and_reports_cleanup_failure(config):
    cancel = CancellationToken()
    supervisor = FakeSupervisor("zero", config)

    def factory():
        cancel.cancel()
        return supervisor

    def broken_close():
        raise OSError("private path")

    supervisor.close = broken_close
    result = MaaFgoAdapter(config, expected_adb_serial=SERIAL, supervisor_factory=factory).run(cancel=cancel)
    assert not supervisor.called
    assert result.status == Status.CANCELLED and result.error_code == Code.CLEANUP_FAILED
    assert not result.owned_process_cleaned


@pytest.mark.parametrize(
    "reason,process_code,expected",
    [
        (TerminationReason.WAIT_FAILED, ProcessExecutionErrorCode.WAIT_FAILED, Code.WAIT_FAILED),
        (TerminationReason.TERMINATION_FAILED, ProcessExecutionErrorCode.TERMINATION_FAILED, Code.CLEANUP_FAILED),
        (TerminationReason.STOPPED, ProcessExecutionErrorCode.STOPPED, Code.INTERNAL_ERROR),
    ],
)
def test_uncertain_cleanup_maps_conservatively(config, reason, process_code, expected):
    instance, supervisor = adapter(config, "zero")
    now = datetime.now(UTC)
    supervisor.run = lambda *args: ProcessResult(
        "maafgo",
        1,
        reason,
        None,
        process_code,
        now,
        now,
        0,
        diagnostics={"detail": config.working_directory},
    )
    result = instance.run()
    assert result.error_code == expected and not result.owned_process_cleaned
    assert supervisor.closed
    assert config.working_directory not in json.dumps(result.diagnostics)


@pytest.mark.parametrize("exception", [RuntimeError("private"), KeyboardInterrupt()])
def test_exception_always_closes(config, exception):
    instance, supervisor = adapter(config, "zero")

    def broken_run(*args):
        raise exception

    supervisor.run = broken_run
    if isinstance(exception, KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            instance.run()
    else:
        result = instance.run()
        assert result.error_code == Code.INTERNAL_ERROR and not result.owned_process_cleaned
    assert supervisor.closed


def test_model_invariants():
    now = datetime.now(UTC)
    valid = MaaFgoRunResult(
        Status.FAILED,
        Code.COMPLETION_UNCONFIRMED,
        now,
        now,
        0,
        0,
        TerminationReason.NORMAL_EXIT,
        True,
        True,
    )
    assert not valid.completion_confirmed
    for changes in (
        {"exit_code": 1},
        {"configuration_confirmed": False},
        {"owned_process_cleaned": False},
        {"duration_ms": True},
        {"duration_ms": -1},
        {"started_at": datetime.now()},
        {"error_code": Code.CLEANUP_FAILED},
        {"status": Status.TIMEOUT},
    ):
        with pytest.raises(ValueError):
            replace(valid, **changes)
