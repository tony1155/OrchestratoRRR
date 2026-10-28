import json
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from autogame_orchestrator.bettergi_config import BetterGIConfig
from autogame_orchestrator.process import CancellationToken, Deadline, ProcessSpec, ProcessSupervisor
from autogame_orchestrator.runtime.bettergi import BetterGIAdapter
from autogame_orchestrator.runtime.bettergi_log import SOURCE, BetterGILog, Evidence
from autogame_orchestrator.runtime.bettergi_models import BetterGIErrorCode as Code
from autogame_orchestrator.runtime.bettergi_models import BetterGIRunStatus as Status

FAKE = Path(__file__).parents[1] / "fakes" / "fake_bettergi.py"


@pytest.fixture
def config(tmp_path):
    executable = tmp_path / "BetterGI.exe"
    executable.touch()  # never executed: the supervisor below launches Python
    folder = tmp_path / "User" / "OneDragon"
    folder.mkdir(parents=True)
    (folder / "Orchestrator-Daily.json").write_text(
        json.dumps(
            {
                "Name": "Orchestrator-Daily",
                "CompletionAction": "关闭软件",
                "TaskEnabledList": {"mail": True},
            }
        ),
        encoding="utf-8",
    )
    return BetterGIConfig(True, str(executable), str(tmp_path), timeout_seconds=10, stop_timeout_seconds=2)


class FakeSupervisor(ProcessSupervisor):
    def __init__(self, mode, config):
        super().__init__()
        self.mode, self.config = mode, config
        self.process = None
        self.stop_called = False

    def launch(self, spec):
        assert spec.arguments == ("startOneDragon", "Orchestrator-Daily")
        self.process = super().launch(
            ProcessSpec(
                name="fake_bettergi",
                executable=Path(sys._base_executable),
                arguments=(
                    str(FAKE),
                    self.mode,
                    str(Path(self.config.working_directory) / "log"),
                    self.config.config_name,
                ),
                working_directory=Path(self.config.working_directory),
            )
        )
        return self.process

    def stop(self, process, confirmation_deadline=None):
        self.stop_called = True
        return super().stop(process, confirmation_deadline)


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("success", Code.OK),
        ("early_exit", Code.COMPLETION_UNCONFIRMED),
        ("other_instance", Code.COMPLETION_UNCONFIRMED),
        ("wrong_config", Code.TASK_FAILED),
        ("failure", Code.TASK_FAILED),
        ("caught_failure", Code.TASK_FAILED),
        ("cancelled", Code.CANCELLED),
        ("interrupt", Code.TASK_FAILED),
        ("nonzero", Code.PROCESS_EXIT_NONZERO),
        ("overflow", Code.LOG_CONTRACT_FAILED),
    ],
)
def test_real_fake_process(config, mode, expected):
    supervisor = FakeSupervisor(mode, config)
    result = BetterGIAdapter(config, instance_check=lambda: False, supervisor_factory=lambda: supervisor).run()
    assert result.error_code == expected
    assert result.owned_process_cleaned
    assert supervisor.stop_called and supervisor.process.closed
    assert (result.status == Status.COMPLETED) == (expected == Code.OK)


@pytest.mark.parametrize("mode", ["hang", "completed_but_alive"])
def test_parent_deadline_kills_owned_fake(config, mode):
    supervisor = FakeSupervisor(mode, config)
    result = BetterGIAdapter(config, instance_check=lambda: False, supervisor_factory=lambda: supervisor).run(
        Deadline.after(0.5)
    )
    assert result.status == Status.TIMEOUT
    assert result.error_code == Code.TASK_TIMEOUT
    assert result.duration_ms < 5000
    assert result.owned_process_cleaned and supervisor.process.closed


def test_cancellation_cleans_owned_fake(config):
    supervisor = FakeSupervisor("hang", config)
    cancel = CancellationToken()
    timer = threading.Timer(0.5, cancel.cancel)
    timer.start()
    try:
        result = BetterGIAdapter(config, instance_check=lambda: False, supervisor_factory=lambda: supervisor).run(
            cancel=cancel
        )
    finally:
        timer.join()
    assert result.status == Status.CANCELLED
    assert result.owned_process_cleaned and supervisor.process.closed


def test_conflict_does_not_construct_supervisor(config):
    def forbidden():
        pytest.fail("Must not launch or attach")

    result = BetterGIAdapter(config, instance_check=lambda: True, supervisor_factory=forbidden).run()
    assert result.error_code == Code.INSTANCE_CONFLICT


def test_instance_probe_fails_closed(config):
    def broken():
        raise OSError("unavailable")

    assert BetterGIAdapter(config, instance_check=broken).run().error_code == Code.INSTANCE_CHECK_FAILED


def test_invalid_profile_does_not_probe_or_launch(config):
    config = replace(config, config_name="missing")

    def forbidden():
        pytest.fail("Invalid profile must fail before process operations")

    assert BetterGIAdapter(config, instance_check=forbidden).run().error_code == Code.INVALID_CONFIGURATION


def record(pid, message, level="INF"):
    return f"[12:00:00.000] [{level}] [Primary:S1:P{pid}:T123] {SOURCE}\n{message}\n\n".encode()


def test_old_logs_and_split_utf8_and_midnight(tmp_path):
    old = tmp_path / "better-genshin-impact20260906.log"
    old.write_bytes(record(42, "启用一条龙配置：中文") + record(42, "一条龙和配置组任务结束"))
    log = BetterGILog(tmp_path)
    evidence = Evidence(42, "中文")
    log.read(evidence, final=True)
    assert not evidence.completion_confirmed
    today = tmp_path / "better-genshin-impact20260907.log"
    data = record(42, "启用一条龙配置：中文") + record(42, "一条龙和配置组任务结束")
    for part in (data[:81], data[81:]):
        with today.open("ab") as stream:
            stream.write(part)
        log.read(evidence)
    log.read(evidence, final=True)
    assert evidence.configuration_confirmed and evidence.completion_confirmed


def test_truncated_log_fails_closed(tmp_path):
    path = tmp_path / "better-genshin-impact20260907.log"
    path.write_bytes(b"old log")
    log = BetterGILog(tmp_path)
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="truncated"):
        log.read(Evidence(42, "Daily"))


@pytest.mark.parametrize("mode,expected", [("success", Code.CLEANUP_FAILED), ("failure", Code.TASK_FAILED)])
def test_cleanup_failure_never_hides_primary_failure(config, mode, expected, monkeypatch):
    from autogame_orchestrator.runtime import bettergi

    supervisor = FakeSupervisor(mode, config)
    monkeypatch.setattr(bettergi, "stop_owned_job", lambda process, deadline: False)
    result = BetterGIAdapter(config, instance_check=lambda: False, supervisor_factory=lambda: supervisor).run()
    assert result.status == Status.FAILED and result.error_code == expected
    assert not result.owned_process_cleaned


def test_expired_or_cancelled_before_launch(config):
    def forbidden():
        pytest.fail("Must not inspect or launch")

    adapter = BetterGIAdapter(config, instance_check=forbidden)
    assert adapter.run(Deadline.after(0)).status == Status.TIMEOUT
    token = CancellationToken()
    token.cancel()
    assert adapter.run(cancel=token).status == Status.CANCELLED


def test_copied_old_identity_and_child_instance_cannot_complete(tmp_path):
    log = BetterGILog(tmp_path)
    path = tmp_path / "better-genshin-impact20260907.log"
    data = record(42, "启用一条龙配置：Daily") + record(42, "一条龙和配置组任务结束")
    path.write_bytes(data + data.replace(b"Primary", b"ChildSession"))
    evidence = Evidence(42, "Daily", started_after_ms=1000)
    log.read(evidence, final=True)
    assert not evidence.configuration_confirmed and not evidence.completion_confirmed


def test_success_reaps_owned_child(config):
    from tests.runtime.test_starrail_runtime import _check_pid_exited

    supervisor = FakeSupervisor("child", config)
    result = BetterGIAdapter(config, instance_check=lambda: False, supervisor_factory=lambda: supervisor).run()
    assert result.status == Status.COMPLETED and result.owned_process_cleaned
    child_pid = int((Path(config.working_directory) / "log" / "child.pid").read_text())
    _check_pid_exited(child_pid, "BetterGI fake child")
