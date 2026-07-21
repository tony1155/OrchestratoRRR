"""Job Object 集成测试。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from autogame_orchestrator.process import win32_handles, win32_job, win32_process


def _fake_stage_path() -> str:
    return str(Path(__file__).resolve().parent.parent / "fakes" / "fake_stage.py")


def _start_suspended_fake(args: list[str]) -> tuple[int, int, int]:
    full_args = (str(sys.executable), str(_fake_stage_path()), *args)
    proc_info = win32_process.create_suspended_process(
        executable=str(sys.executable),
        arguments=full_args[1:],
        working_directory=None,
        environment_block=None,
        stdout_handle=None,
        stderr_handle=None,
        create_new_process_group=False,
        inherit_handles=False,
    )
    return proc_info.hProcess, proc_info.hThread, proc_info.dwProcessId


def _cleanup(proc_h: int, thread_h: int, job_h: int | None = None) -> None:
    if job_h is not None:
        try:
            win32_job.terminate_job(job_h)
        except Exception:
            pass
    for h in (thread_h, proc_h):
        try:
            win32_handles.close_handle(h)
        except Exception:
            pass


def test_job_create_success() -> None:
    jh = win32_job.create_job_object()
    assert jh != 0
    try:
        win32_job.configure_job_kill_on_close(jh)
    finally:
        win32_handles.close_handle(jh)


def test_job_configure_kill_on_close() -> None:
    jh = win32_job.create_job_object()
    try:
        win32_job.configure_job_kill_on_close(jh)
    finally:
        win32_handles.close_handle(jh)


def test_job_assign_suspended_process() -> None:
    proc_h, thread_h, pid = _start_suspended_fake(["--sleep-seconds", "0.5"])
    jh = win32_job.create_job_object()
    try:
        win32_job.configure_job_kill_on_close(jh)
        win32_job.assign_process_to_job(jh, proc_h)
        win32_process.resume_thread(thread_h)
        time.sleep(0.7)
    finally:
        _cleanup(proc_h, thread_h, jh)


def test_job_terminate_kills_process() -> None:
    proc_h, thread_h, pid = _start_suspended_fake(["--sleep-forever"])
    jh = win32_job.create_job_object()
    try:
        win32_job.configure_job_kill_on_close(jh)
        win32_job.assign_process_to_job(jh, proc_h)
        win32_process.resume_thread(thread_h)
        time.sleep(0.1)
        win32_job.terminate_job(jh)
        for _ in range(20):
            if win32_process.get_exit_code(proc_h) is not None:
                break
            time.sleep(0.1)
        assert win32_process.get_exit_code(proc_h) is not None
    finally:
        _cleanup(proc_h, thread_h, jh)


def test_job_close_kills_process() -> None:
    proc_h, thread_h, pid = _start_suspended_fake(["--sleep-forever"])
    jh = win32_job.create_job_object()
    try:
        win32_job.configure_job_kill_on_close(jh)
        win32_job.assign_process_to_job(jh, proc_h)
        win32_process.resume_thread(thread_h)
        time.sleep(0.1)
        win32_handles.close_handle(jh)
        for _ in range(20):
            if win32_process.get_exit_code(proc_h) is not None:
                break
            time.sleep(0.1)
        assert win32_process.get_exit_code(proc_h) is not None
    finally:
        _cleanup(proc_h, thread_h, None)


def test_job_close_no_pid_residual() -> None:
    proc_h, thread_h, pid = _start_suspended_fake(["--sleep-forever"])
    jh = win32_job.create_job_object()
    try:
        win32_job.configure_job_kill_on_close(jh)
        win32_job.assign_process_to_job(jh, proc_h)
        win32_process.resume_thread(thread_h)
        time.sleep(0.1)
        win32_handles.close_handle(jh)
        for _ in range(30):
            if win32_process.get_exit_code(proc_h) is not None:
                break
            time.sleep(0.1)
        assert win32_process.get_exit_code(proc_h) is not None
    finally:
        try:
            win32_handles.close_handle(thread_h)
        except Exception:
            pass
        try:
            win32_handles.close_handle(proc_h)
        except Exception:
            pass


def test_job_handle_double_close() -> None:
    jh = win32_job.create_job_object()
    win32_job.configure_job_kill_on_close(jh)
    owned = win32_handles.OwnedHandle(jh)
    owned.close()
    assert owned.value is None
    owned.close()
    assert owned.value is None
