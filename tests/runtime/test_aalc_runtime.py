"""AALC Adapter 的重试、所有权和结果模型验收测试。"""

from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autogame_orchestrator.config_model import AALCConfig
from autogame_orchestrator.process import CancellationToken, Deadline, ProcessSupervisor, ProcessSupervisorCloseError
from autogame_orchestrator.runtime import (
    AALCAdapter,
    AALCAttemptResult,
    AALCAttemptStatus,
    AALCCompletionMode,
    AALCErrorCode,
    AALCRunResult,
    AALCRunStatus,
)
from autogame_orchestrator.runtime.aalc import MAX_OUTPUT_EXCERPT_CHARS

FAKE = str((Path(__file__).parents[1] / "fakes" / "fake_aalc.py").resolve())
PY = str(Path(getattr(sys, "_base_executable", sys.executable)).resolve())


def cfg(
    p: Path,
    mode: str,
    *,
    attempts: int = 1,
    timeout: int = 3,
    extra: tuple[str, ...] = (),
    env: tuple[tuple[str, str], ...] = (),
) -> AALCConfig:
    return AALCConfig(PY, str(p.resolve()), (FAKE, "--mode", mode, *extra), env, attempts, timeout, 2)


def wait_pid(path: Path, timeout_seconds: float = 3) -> int:
    end = time.monotonic() + timeout_seconds
    last = ""
    while time.monotonic() < end:
        try:
            last = path.read_text(encoding="utf-8").strip()
            pid = int(last)
        except (FileNotFoundError, OSError, ValueError):
            time.sleep(0.02)
            continue
        if pid > 0:
            return pid
        time.sleep(0.02)
    raise AssertionError(f"等待 PID 文件超时：path={path}, last_text={last!r}")


def exited(pid: int, label: str) -> None:
    end = time.monotonic() + 3
    while time.monotonic() < end:
        h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if h == 0:
            return
        r = ctypes.windll.kernel32.WaitForSingleObject(h, 100)
        ctypes.windll.kernel32.CloseHandle(h)
        if r == 0:
            return
        time.sleep(0.02)
    raise AssertionError(f"{label} PID {pid} 未退出")


def threaded(adapter: AALCAdapter, cancel: CancellationToken) -> tuple[threading.Thread, list[AALCRunResult]]:
    out: list[AALCRunResult] = []
    t = threading.Thread(target=lambda: out.append(adapter.run(cancel=cancel)), daemon=True)
    t.start()
    return t, out


def joined(t: threading.Thread, out: list[AALCRunResult]) -> AALCRunResult:
    t.join(5)
    assert not t.is_alive()
    assert len(out) == 1
    return out[0]


def test_exit_zero_completes_without_retry(tmp_path: Path) -> None:
    r = AALCAdapter(cfg(tmp_path, "exit_zero", attempts=3)).run()
    assert (r.status, r.attempts_started, r.successful_attempt_number) == (AALCRunStatus.COMPLETED, 1, 1)


def test_exit_nonzero_exhausts_single_attempt(tmp_path: Path) -> None:
    r = AALCAdapter(cfg(tmp_path, "exit_nonzero")).run()
    assert r.error_code == AALCErrorCode.RETRIES_EXHAUSTED and r.attempts_started == 1
    assert r.attempt_results[0].exit_code == 7


def test_fail_once_then_success_uses_second_attempt(tmp_path: Path) -> None:
    s = tmp_path / "state"
    r = AALCAdapter(cfg(tmp_path, "fail_once_then_success", attempts=3, extra=("--state-file", str(s)))).run()
    assert (r.status, r.attempts_started, r.successful_attempt_number) == (AALCRunStatus.COMPLETED, 2, 2)


def test_all_nonzero_attempts_are_exhausted(tmp_path: Path) -> None:
    r = AALCAdapter(cfg(tmp_path, "exit_nonzero", attempts=3)).run()
    assert r.error_code == AALCErrorCode.RETRIES_EXHAUSTED and r.attempts_started == 3
    assert all(a.error_code == AALCErrorCode.PROCESS_EXIT_NONZERO for a in r.attempt_results)


def test_attempt_timeout_can_retry_and_succeed(tmp_path: Path) -> None:
    s = tmp_path / "state"
    r = AALCAdapter(
        cfg(tmp_path, "hang_once_then_success", attempts=2, timeout=1, extra=("--state-file", str(s)))
    ).run()
    assert (r.status, r.attempts_started, r.successful_attempt_number) == (AALCRunStatus.COMPLETED, 2, 2)
    assert r.attempt_results[0].error_code == AALCErrorCode.ATTEMPT_TIMEOUT


def test_attempt_timeout_exhausts_all_attempts(tmp_path: Path) -> None:
    r = AALCAdapter(cfg(tmp_path, "hang", attempts=2, timeout=1)).run()
    assert r.error_code == AALCErrorCode.RETRIES_EXHAUSTED and r.attempts_started == 2


def test_parent_deadline_stops_before_next_attempt(tmp_path: Path) -> None:
    r = AALCAdapter(cfg(tmp_path, "hang", attempts=3, timeout=5)).run(Deadline.after(0.2))
    assert (
        r.status == AALCRunStatus.TIMEOUT and r.error_code == AALCErrorCode.PARENT_DEADLINE and r.attempts_started == 1
    )


def test_pre_cancel_does_not_launch(tmp_path: Path) -> None:
    p = tmp_path / "pid"
    c = CancellationToken()
    c.cancel()
    r = AALCAdapter(cfg(tmp_path, "hang", extra=("--pid-file", str(p)))).run(cancel=c)
    assert r.attempts_started == 0 and not p.exists()


def test_cancellation_stops_current_attempt_without_retry(tmp_path: Path) -> None:
    p = tmp_path / "pid"
    c = CancellationToken()
    t, o = threaded(AALCAdapter(cfg(tmp_path, "hang", attempts=3, extra=("--pid-file", str(p)))), c)
    pid = wait_pid(p)
    c.cancel()
    r = joined(t, o)
    assert r.status == AALCRunStatus.CANCELLED and r.attempts_started == 1
    exited(pid, "取消父进程")


def test_start_failure_is_structured_and_not_retried(tmp_path: Path) -> None:
    f = tmp_path / "bad.txt"
    f.write_text("bad")
    r = AALCAdapter(AALCConfig(str(f), str(tmp_path), attempts=3)).run()
    assert r.error_code == AALCErrorCode.PROCESS_START_FAILED and r.attempts_started == 1
    assert r.attempt_results[0].pid is None and r.attempt_results[0].owned_process_cleaned


def test_missing_executable_is_rejected_without_attempt(tmp_path: Path) -> None:
    r = AALCAdapter(AALCConfig(str(tmp_path / "x"), str(tmp_path))).run()
    assert r.error_code == AALCErrorCode.EXECUTABLE_NOT_FOUND and r.attempts_started == 0


def test_missing_working_directory_is_rejected_without_attempt(tmp_path: Path) -> None:
    r = AALCAdapter(AALCConfig(PY, str(tmp_path / "x"))).run()
    assert r.error_code == AALCErrorCode.WORKING_DIRECTORY_NOT_FOUND and r.attempts_started == 0


def test_executable_directory_is_rejected(tmp_path: Path) -> None:
    assert AALCAdapter(AALCConfig(str(tmp_path), str(tmp_path))).run().error_code == AALCErrorCode.EXECUTABLE_NOT_FOUND


def test_working_directory_file_is_rejected(tmp_path: Path) -> None:
    f = tmp_path / "f"
    f.write_text("x")
    assert AALCAdapter(AALCConfig(PY, str(f))).run().error_code == AALCErrorCode.WORKING_DIRECTORY_NOT_FOUND


def test_arguments_working_directory_and_environment_propagate(tmp_path: Path) -> None:
    cap = tmp_path / "cap"
    e = (("PYTHONIOENCODING", "utf-8"), ("AALC_TEST_TOKEN", "secret"))
    r = AALCAdapter(cfg(tmp_path, "capture", extra=("--capture-file", str(cap), "--x", "one", "tail"), env=e)).run()
    d = json.loads(cap.read_text())
    assert (
        d["arguments"] == ["--x", "one", "tail"]
        and Path(d["working_directory"]).resolve() == tmp_path.resolve()
        and d["python_io_encoding"] == "utf-8"
        and d["aalc_test_token"] == "secret"
    )
    assert "secret" not in json.dumps(r.to_dict())


def test_attempt_numbers_propagate(tmp_path: Path) -> None:
    s = tmp_path / "s"
    r = AALCAdapter(cfg(tmp_path, "fail_once_then_success", attempts=2, extra=("--state-file", str(s)))).run()
    assert [a.attempt_number for a in r.attempt_results] == [1, 2] and s.read_text() == "2"


def test_each_retry_uses_a_distinct_pid(tmp_path: Path) -> None:
    s = tmp_path / "s"
    d = tmp_path / "pids"
    r = AALCAdapter(
        cfg(tmp_path, "fail_once_then_success", attempts=2, extra=("--state-file", str(s), "--pid-dir", str(d)))
    ).run()
    p1 = wait_pid(d / "parent-1.pid")
    p2 = wait_pid(d / "parent-2.pid")
    assert p1 != p2 and r.attempts_started == 2
    exited(p1, "尝试1")
    exited(p2, "尝试2")


def test_large_output_is_truncated(tmp_path: Path) -> None:
    a = AALCAdapter(cfg(tmp_path, "large_output")).run().attempt_results[0]
    assert a.stdout_truncated and a.stderr_truncated and len(a.stdout_excerpt) <= MAX_OUTPUT_EXCERPT_CHARS


def test_utf16_output_is_decoded(tmp_path: Path) -> None:
    assert "中文输出" in AALCAdapter(cfg(tmp_path, "utf16_output")).run().attempt_results[0].stdout_excerpt


def test_child_is_cleaned_after_success(tmp_path: Path) -> None:
    c = tmp_path / "child"
    r = AALCAdapter(cfg(tmp_path, "child_exit_zero", extra=("--child-pid-file", str(c)))).run()
    assert r.status == AALCRunStatus.COMPLETED
    assert r.attempt_results[0].pid is not None and r.attempt_results[0].pid > 0 and c.exists()
    child = int(c.read_text())
    assert child > 0
    exited(r.attempt_results[0].pid, "成功父进程")
    exited(child, "成功子进程")


def test_child_is_cleaned_before_retry(tmp_path: Path) -> None:
    d = tmp_path / "pids"
    s = tmp_path / "s"
    r = AALCAdapter(
        cfg(tmp_path, "child_exit_nonzero", attempts=2, extra=("--state-file", str(s), "--pid-dir", str(d)))
    ).run()
    p1 = wait_pid(d / "parent-1.pid")
    c1 = wait_pid(d / "child-1.pid")
    p2 = wait_pid(d / "parent-2.pid")
    assert p1 != p2 and r.attempts_started == 2
    exited(p1, "重试父1")
    exited(c1, "重试子1")


def test_child_is_cleaned_after_timeout(tmp_path: Path) -> None:
    p = tmp_path / "p"
    c = tmp_path / "c"
    r = AALCAdapter(
        cfg(tmp_path, "child_hang", timeout=1, extra=("--pid-file", str(p), "--child-pid-file", str(c)))
    ).run()
    parent = wait_pid(p)
    child = wait_pid(c)
    assert r.attempt_results[0].error_code == AALCErrorCode.ATTEMPT_TIMEOUT
    exited(parent, "超时父")
    exited(child, "超时子")


def test_child_is_cleaned_after_cancellation(tmp_path: Path) -> None:
    p = tmp_path / "p"
    cfile = tmp_path / "c"
    c = CancellationToken()
    t, o = threaded(
        AALCAdapter(cfg(tmp_path, "child_hang", extra=("--pid-file", str(p), "--child-pid-file", str(cfile)))), c
    )
    parent = wait_pid(p)
    child = wait_pid(cfile)
    c.cancel()
    r = joined(t, o)
    assert r.status == AALCRunStatus.CANCELLED
    exited(parent, "取消父")
    exited(child, "取消子")


def _serialized(tmp_path: Path) -> tuple[AALCRunResult, str]:
    state = tmp_path / "state"
    token = "sensitive"
    r = AALCAdapter(
        cfg(
            tmp_path,
            "fail_once_then_success",
            attempts=2,
            extra=("--state-file", str(state)),
            env=(("AALC_TEST_TOKEN", token),),
        )
    ).run()
    return r, json.dumps(r.to_dict(), ensure_ascii=False)


def test_result_does_not_expose_temp_paths(tmp_path: Path) -> None:
    _, text = _serialized(tmp_path)
    assert "orchestratorrr-aalc-" not in text and "stdout.bin" not in text and "stderr.bin" not in text


def test_result_does_not_expose_config_paths(tmp_path: Path) -> None:
    _, text = _serialized(tmp_path)
    assert str(tmp_path.resolve()) not in text and PY not in text


def test_result_does_not_expose_environment_values(tmp_path: Path) -> None:
    _, text = _serialized(tmp_path)
    assert "sensitive" not in text


def test_result_is_json_serializable(tmp_path: Path) -> None:
    r = AALCAdapter(cfg(tmp_path, "exit_zero")).run()
    assert json.loads(json.dumps(r.to_dict()))["status"] == "completed"


def attempt(**kw: object) -> AALCAttemptResult:
    n = datetime.now(UTC)
    v: dict[str, object] = {
        "attempt_number": 1,
        "status": AALCAttemptStatus.COMPLETED,
        "error_code": AALCErrorCode.OK,
        "started_at": n,
        "finished_at": n,
        "duration_seconds": 0.0,
        "pid": 1,
        "exit_code": 0,
        "owned_process_cleaned": True,
    }
    v.update(kw)
    return AALCAttemptResult(**v)  # type: ignore[arg-type]


def runres(items: tuple[AALCAttemptResult, ...], **kw: object) -> AALCRunResult:
    n = datetime.now(UTC)
    v: dict[str, object] = {
        "status": AALCRunStatus.COMPLETED,
        "error_code": AALCErrorCode.OK,
        "completion_mode": AALCCompletionMode.NORMAL_EXIT,
        "started_at": n,
        "finished_at": n,
        "duration_seconds": 0.0,
        "configured_attempts": max(1, len(items)),
        "attempts_started": len(items),
        "successful_attempt_number": len(items),
        "attempt_results": items,
    }
    v.update(kw)
    return AALCRunResult(**v)  # type: ignore[arg-type]


def test_attempt_result_invariants() -> None:
    assert attempt().exit_code == 0
    with pytest.raises(ValueError):
        attempt(attempt_number=0)
    with pytest.raises(ValueError):
        attempt(stdout_excerpt=1)


def test_completed_result_invariants() -> None:
    assert runres((attempt(),)).status == AALCRunStatus.COMPLETED
    with pytest.raises(ValueError):
        runres((attempt(),), successful_attempt_number=None)


def test_retries_exhausted_result_invariants() -> None:
    a = attempt(status=AALCAttemptStatus.FAILED, error_code=AALCErrorCode.PROCESS_EXIT_NONZERO, exit_code=7)
    r = runres(
        (a,),
        status=AALCRunStatus.FAILED,
        error_code=AALCErrorCode.RETRIES_EXHAUSTED,
        completion_mode=AALCCompletionMode.RETRIES_EXHAUSTED,
        successful_attempt_number=None,
    )
    assert r.attempts_started == 1


def test_timeout_result_invariants() -> None:
    a = attempt(status=AALCAttemptStatus.TIMEOUT, error_code=AALCErrorCode.ATTEMPT_TIMEOUT, exit_code=None)
    assert a.status == AALCAttemptStatus.TIMEOUT


def test_cancelled_result_invariants() -> None:
    a = attempt(status=AALCAttemptStatus.CANCELLED, error_code=AALCErrorCode.CANCELLED, exit_code=None)
    assert a.status == AALCAttemptStatus.CANCELLED


def test_cleanup_failed_requires_false() -> None:
    with pytest.raises(ValueError):
        attempt(status=AALCAttemptStatus.FAILED, error_code=AALCErrorCode.CLEANUP_FAILED)


def test_unknown_fake_mode_fails(tmp_path: Path) -> None:
    r = AALCAdapter(cfg(tmp_path, "unknown")).run()
    assert r.attempt_results[0].exit_code == 9 and r.error_code == AALCErrorCode.RETRIES_EXHAUSTED


ORIGINAL_CLOSE = ProcessSupervisor.close


def bad_close(self: ProcessSupervisor) -> None:
    ORIGINAL_CLOSE(self)
    raise ProcessSupervisorCloseError("测试", ())


def test_close_failure_turns_success_into_cleanup_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ProcessSupervisor, "close", bad_close)
    r = AALCAdapter(cfg(tmp_path, "exit_zero", attempts=3)).run()
    assert r.status == AALCRunStatus.FAILED and r.error_code == AALCErrorCode.CLEANUP_FAILED and r.attempts_started == 1


def test_close_failure_prevents_retry_after_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ProcessSupervisor, "close", bad_close)
    r = AALCAdapter(cfg(tmp_path, "exit_nonzero", attempts=3)).run()
    assert r.error_code == AALCErrorCode.CLEANUP_FAILED and r.attempts_started == 1


def test_close_failure_preserves_timeout_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ProcessSupervisor, "close", bad_close)
    r = AALCAdapter(cfg(tmp_path, "hang", attempts=3, timeout=1)).run()
    assert (
        r.status == AALCRunStatus.TIMEOUT and r.error_code == AALCErrorCode.CLEANUP_FAILED and r.attempts_started == 1
    )


def test_close_failure_preserves_cancelled_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ProcessSupervisor, "close", bad_close)
    p = tmp_path / "p"
    c = CancellationToken()
    t, o = threaded(AALCAdapter(cfg(tmp_path, "hang", attempts=3, extra=("--pid-file", str(p)))), c)
    wait_pid(p)
    c.cancel()
    r = joined(t, o)
    assert (
        r.status == AALCRunStatus.CANCELLED and r.error_code == AALCErrorCode.CLEANUP_FAILED and r.attempts_started == 1
    )
