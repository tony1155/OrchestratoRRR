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
from autogame_orchestrator.maafgo_evidence import (
    ARTIFACT_SCHEMA_VERSION,
    MaaFgoEvidenceError,
    MaaFgoRunContract,
    read_completion_artifact,
    verify_completion_artifact,
)
from autogame_orchestrator.process import (
    CancellationToken,
    Deadline,
    ProcessExecutionErrorCode,
    ProcessResult,
    ProcessSupervisor,
    TerminationReason,
)
from autogame_orchestrator.runtime.maafgo import MaaFgoAdapter
from autogame_orchestrator.runtime.maafgo_models import MaaFgoArtifactValidationState as ArtifactState
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
                environment_overrides={**spec.environment_overrides, "FAKE_MAAFGO_MODE": self.mode},
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


def test_model_artifact_evidence_invariants():
    """完成证据观测字段的不变量：VERIFIED ⇔ 身份成立；confirmed ⇒ VERIFIED。"""
    now = datetime.now(UTC)
    verified = MaaFgoRunResult(
        Status.SUCCESS,
        Code.OK,
        now,
        now,
        0,
        0,
        TerminationReason.NORMAL_EXIT,
        True,
        True,
        True,
        2,
        2,
        completion_evidence_schema_version=ARTIFACT_SCHEMA_VERSION,
        plan_digest_match=True,
        artifact_validation_state=ArtifactState.VERIFIED,
    )
    assert verified.provider == "maafgo"
    for changes in (
        {"artifact_validation_state": ArtifactState.REJECTED},
        {"artifact_validation_state": ArtifactState.NOT_ATTEMPTED},
        {"artifact_validation_state": "verified"},
        {"plan_digest_match": False},
        {"plan_digest_match": 1},
        {"completion_evidence_schema_version": 0},
        {"completion_evidence_schema_version": ARTIFACT_SCHEMA_VERSION + 1},
        {"completion_evidence_schema_version": True},
        {"provider": "other"},
    ):
        with pytest.raises(ValueError):
            replace(verified, **changes)
    rejected = MaaFgoRunResult(
        Status.FAILED,
        Code.RESULT_ID_MISMATCH,
        now,
        now,
        0,
        0,
        TerminationReason.NORMAL_EXIT,
        True,
        True,
        False,
        2,
        0,
        artifact_validation_state=ArtifactState.REJECTED,
    )
    with pytest.raises(ValueError):
        replace(rejected, completion_confirmed=True)
    # VERIFIED 但 cleanup 失败（status 非 SUCCESS）仍合法：artifact 校验确实通过了。
    MaaFgoRunResult(
        Status.FAILED,
        Code.CLEANUP_FAILED,
        now,
        now,
        0,
        None,
        TerminationReason.TERMINATION_FAILED,
        False,
        True,
        False,
        2,
        0,
        completion_evidence_schema_version=ARTIFACT_SCHEMA_VERSION,
        plan_digest_match=True,
        artifact_validation_state=ArtifactState.VERIFIED,
    )


# ── run-scoped completion evidence ──────────────────────────────────────────

EXPECTED_PAIRS = (("登录", "登录识别"), ("日常战斗", "日常战斗"))


def contracted(config, mode, tmp_path, pairs=EXPECTED_PAIRS):
    contract = MaaFgoRunContract.create(tmp_path / "runs", pairs)
    instance, supervisor = adapter(config, mode)
    return MaaFgoAdapter(
        config,
        expected_adb_serial=SERIAL,
        supervisor_factory=lambda: supervisor,
        contract=contract,
    ), supervisor, contract


def test_contract_create_is_run_scoped(tmp_path):
    first = MaaFgoRunContract.create(tmp_path / "runs", EXPECTED_PAIRS)
    second = MaaFgoRunContract.create(tmp_path / "runs", EXPECTED_PAIRS)
    assert first.run_id != second.run_id
    assert first.run_directory != second.run_directory
    assert first.result_path.parent == first.run_directory
    written = json.loads(first.expected_tasks_path.read_text(encoding="utf-8"))
    assert written == [{"name": name, "entry": entry} for name, entry in EXPECTED_PAIRS]
    assert len(first.plan_digest) == 64


def test_contract_rejects_bad_task_lists(tmp_path):
    for index, pairs in enumerate(
        ([], [("x", "y"), ("x", "y")], [("", "y")], [("n" * 300, "e")], [("dup", "a"), ("dup", "b")])
    ):
        with pytest.raises(MaaFgoEvidenceError):
            MaaFgoRunContract.create(tmp_path / f"runs-{index}", pairs)  # type: ignore[arg-type]


def test_contract_env_binding(tmp_path):
    contract = MaaFgoRunContract.create(tmp_path / "runs", EXPECTED_PAIRS)
    env = contract.environment_overrides()
    assert env["ORR_MAAFGO_RUN_ID"] == contract.run_id
    assert env["ORR_MAAFGO_PLAN_DIGEST"] == contract.plan_digest
    assert env["ORR_MAAFGO_RESULT_PATH"] == str(contract.result_path)
    assert env["ORR_MAAFGO_EXPECTED_TASKS_PATH"] == str(contract.expected_tasks_path)
    assert env["ORR_MAAFGO_RESULT_SCHEMA_VERSION"] == "1"


@pytest.mark.parametrize(
    "mode,code",
    [
        ("artifact-ok", Code.OK),
        ("artifact-missing", Code.RESULT_MISSING),
        ("artifact-malformed", Code.RESULT_INVALID),
        ("artifact-wrong-run-id", Code.RESULT_ID_MISMATCH),
        ("artifact-wrong-digest", Code.RESULT_ID_MISMATCH),
        ("artifact-missing-task", Code.RESULT_INVALID),
        ("artifact-duplicate-task", Code.RESULT_INVALID),
        ("artifact-unknown-task", Code.RESULT_INVALID),
        ("artifact-entry-drift", Code.RESULT_INVALID),
        ("artifact-task-failed", Code.TASK_FAILED),
        ("artifact-incomplete", Code.COMPLETION_UNCONFIRMED),
        ("artifact-unexpected-entry", Code.RESULT_INVALID),
    ],
)
def test_artifact_validation_drives_outcome(config, tmp_path, mode, code):
    instance, _, contract = contracted(config, mode, tmp_path)
    result = instance.run()
    assert result.exit_code == 0
    assert result.error_code == code
    assert result.expected_task_count == len(EXPECTED_PAIRS)
    if code is Code.OK:
        assert result.status is Status.SUCCESS
        assert result.completion_confirmed and result.confirmed_task_count == len(EXPECTED_PAIRS)
        assert result.artifact_validation_state is ArtifactState.VERIFIED
        assert result.plan_digest_match
        assert result.completion_evidence_schema_version == ARTIFACT_SCHEMA_VERSION
    else:
        assert result.status is Status.FAILED and not result.completion_confirmed
        assert result.artifact_validation_state is ArtifactState.REJECTED
        assert not result.plan_digest_match


def test_success_artifact_validates_through_production_verifier(config, tmp_path):
    """The Fake artifact must satisfy the same verifier as the real reporter."""
    instance, _, contract = contracted(config, "artifact-ok", tmp_path)
    result = instance.run()
    assert result.status is Status.SUCCESS
    artifact = read_completion_artifact(contract.result_path)
    assert verify_completion_artifact(
        artifact,
        run_id=contract.run_id,
        plan_digest=contract.plan_digest,
        expected_tasks=contract.expected_tasks,
    ) == len(EXPECTED_PAIRS)


def test_verified_artifact_state_survives_cleanup_failure(config, tmp_path):
    """artifact 通过严格校验后 owned tree cleanup 才失败：artifact_validation_state
    保持 VERIFIED（校验确实通过了，不谎报为 REJECTED），但控制面结果优先，
    不判 SUCCESS、completion_confirmed=False。"""
    instance, supervisor, _ = contracted(config, "artifact-ok", tmp_path)
    original_close = supervisor.close

    def broken_close():
        original_close()
        raise OSError(config.working_directory)

    supervisor.close = broken_close
    result = instance.run()
    assert result.status is Status.FAILED and result.error_code is Code.CLEANUP_FAILED
    assert not result.owned_process_cleaned and not result.completion_confirmed
    assert result.artifact_validation_state is ArtifactState.VERIFIED
    assert result.plan_digest_match
    assert result.completion_evidence_schema_version == ARTIFACT_SCHEMA_VERSION
    assert config.working_directory not in json.dumps(result.diagnostics)


def test_nonzero_exit_cannot_rescue_success_artifact(config, tmp_path):
    """A success artifact beside a nonzero exit is ignored: process evidence first."""
    instance, _, contract = contracted(config, "nonzero", tmp_path)
    document = {
        "schema_version": 1,
        "run_id": contract.run_id,
        "plan_digest": contract.plan_digest,
        "outcome": "success",
        "tasks": [
            {"name": name, "entry": entry, "terminal": "success"}
            for name, entry in contract.expected_tasks
        ],
        "unexpected_entries": [],
        "stop_signal_observed": False,
    }
    contract.result_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    result = instance.run()
    assert result.status is Status.FAILED and result.error_code is Code.PROCESS_EXIT_NONZERO
    assert not result.completion_confirmed


def test_timeout_dominates_late_success_artifact(config, tmp_path):
    instance, _, _ = contracted(config, "artifact-ok-then-hang", tmp_path)
    result = instance.run(Deadline.after(1.5))
    assert result.status is Status.TIMEOUT and result.error_code is Code.TASK_TIMEOUT
    assert not result.completion_confirmed
    # The artifact WAS written before the hang; the control plane still wins.
    assert result.expected_task_count == len(EXPECTED_PAIRS)
    # 控制面结果优先：artifact 校验从未被尝试。
    assert result.artifact_validation_state is ArtifactState.NOT_ATTEMPTED


def test_cancel_dominates_late_success_artifact(config, tmp_path):
    instance, _, _ = contracted(config, "artifact-ok-then-hang", tmp_path)
    cancel, results = CancellationToken(), []
    thread = threading.Thread(target=lambda: results.append(instance.run(cancel=cancel)))
    thread.start()
    time.sleep(1.0)
    cancel.cancel()
    thread.join(8)
    assert results and results[0].status is Status.CANCELLED
    assert not results[0].completion_confirmed


def test_fresh_directory_blocks_stale_artifact(config, tmp_path):
    """A completed run's artifact is invisible to a later contract run."""
    first_instance, _, first_contract = contracted(config, "artifact-ok", tmp_path)
    assert first_instance.run().status is Status.SUCCESS
    stale_bytes = first_contract.result_path.read_bytes()
    second_instance, _, second_contract = contracted(config, "artifact-missing", tmp_path)
    result = second_instance.run()
    assert second_contract.result_path != first_contract.result_path
    assert result.status is Status.FAILED and result.error_code is Code.RESULT_MISSING
    # 旧 artifact 未被删除或改写：隔离靠全新目录，而不是覆盖同一全局文件。
    assert first_contract.result_path.read_bytes() == stale_bytes


def test_no_contract_keeps_phase_one_semantics(config):
    instance, _ = adapter(config, "zero")
    result = instance.run()
    assert result.status is Status.FAILED and result.error_code is Code.COMPLETION_UNCONFIRMED
    assert result.completion_confirmed is False
    assert result.diagnostics["expected_task_count"] == 0
    assert result.artifact_validation_state is ArtifactState.NOT_ATTEMPTED
    assert result.diagnostics["artifact_validation_state"] == "not_attempted"
    assert result.diagnostics["plan_digest_match"] is False
    assert result.diagnostics["provider"] == "maafgo"
