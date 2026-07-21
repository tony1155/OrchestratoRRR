"""进程启动编排器。

协调 ``ProcessSpec`` → Win32 进程创建 → Job Object 配置 → 恢复执行 → ``ManagedProcess`` 的完整流程。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from autogame_orchestrator.process import win32_handles, win32_job, win32_process
from autogame_orchestrator.process.errors import ProcessLaunchErrorCode
from autogame_orchestrator.process.models import ManagedProcess, ProcessSpec


class LaunchError(RuntimeError):
    """进程启动失败。"""

    def __init__(self, message: str, error_code: ProcessLaunchErrorCode, win32_code: int | None = None) -> None:
        detail = f" (Win32 错误码: {win32_code})" if win32_code else ""
        super().__init__(f"{message}{detail}")
        self.error_code = error_code
        self.win32_code = win32_code


def _ensure_dir(path: Path) -> None:
    parent = path.parent
    if parent.exists() and not parent.is_dir():
        msg = f"输出路径的父级不是目录: {parent}"
        raise LaunchError(msg, ProcessLaunchErrorCode.OUTPUT_OPEN_FAILED)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg = f"无法创建输出目录: {path}"
        raise LaunchError(msg, ProcessLaunchErrorCode.OUTPUT_OPEN_FAILED) from exc


def _open_output_file(path: Path) -> int:
    _ensure_dir(path.parent)
    if path.exists() and path.is_dir():
        msg = f"输出路径是目录，无法写入: {path}"
        raise LaunchError(msg, ProcessLaunchErrorCode.OUTPUT_OPEN_FAILED)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_BINARY, 0o644)
    except OSError as exc:
        msg = f"无法打开输出文件: {path}"
        raise LaunchError(msg, ProcessLaunchErrorCode.OUTPUT_OPEN_FAILED) from exc
    return fd


def _build_env_block(overrides: dict[str, str], inherit: bool) -> str | None:
    if inherit and not overrides:
        return None
    env: dict[str, str] = {}
    if inherit:
        env.update(os.environ)
    env.update(overrides)
    parts = [f"{k}={v}" for k, v in env.items()]
    return "\0".join(parts) + "\0\0"


def launch(spec: ProcessSpec) -> ManagedProcess:
    """启动进程并返回 ``ManagedProcess``。

    完整流程：
    1. 校验可执行文件和工作目录。
    2. 打开 stdout/stderr 输出文件。
    3. ``CreateProcessW(CREATE_SUSPENDED)``。
    4. 创建并配置 Job Object (KILL_ON_JOB_CLOSE)。
    5. ``AssignProcessToJobObject``（此时进程仍挂起）。
    6. ``ResumeThread``。
    7. 关闭线程句柄。
    8. 返回 ``ManagedProcess``。

    任何步骤失败都会清理已创建的资源。
    """
    started_at_monotonic = time.monotonic()

    # --- 1. 校验 ---
    if not spec.executable.is_file():
        if spec.executable.is_dir():
            msg = f"可执行文件路径是目录: {spec.executable}"
        else:
            msg = f"可执行文件不存在: {spec.executable}"
        raise LaunchError(msg, ProcessLaunchErrorCode.EXECUTABLE_NOT_FOUND)

    if spec.working_directory is not None:
        if not spec.working_directory.exists():
            msg = f"工作目录不存在: {spec.working_directory}"
            raise LaunchError(msg, ProcessLaunchErrorCode.WORKING_DIRECTORY_NOT_FOUND)
        if not spec.working_directory.is_dir():
            msg = f"工作目录路径不是目录: {spec.working_directory}"
            raise LaunchError(msg, ProcessLaunchErrorCode.WORKING_DIRECTORY_NOT_FOUND)

    # --- 2. 打开输出文件 ---
    stdout_fd: int | None = None
    stderr_fd: int | None = None
    stdout_handle: int | None = None
    stderr_handle: int | None = None

    try:
        inherit_handles = False

        if spec.stdout_path is not None:
            stdout_fd = _open_output_file(spec.stdout_path)
            stdout_handle = _msvcrt_get_osfhandle(stdout_fd)
            win32_process.set_handle_inheritable(stdout_handle, True)
            inherit_handles = True

        if spec.stderr_path is not None:
            if spec.stderr_path == spec.stdout_path:
                stderr_handle = stdout_handle
            else:
                stderr_fd = _open_output_file(spec.stderr_path)
                stderr_handle = _msvcrt_get_osfhandle(stderr_fd)
            if stderr_handle is not None and stderr_handle != stdout_handle:
                win32_process.set_handle_inheritable(stderr_handle, True)
            inherit_handles = True

        # --- 3. 构建环境 ---
        env_block = _build_env_block(dict(spec.environment_overrides), spec.inherit_parent_environment)

        # --- 4. CreateProcessW (挂起) ---
        try:
            proc_info = win32_process.create_suspended_process(
                executable=str(spec.executable),
                arguments=spec.arguments,
                working_directory=str(spec.working_directory) if spec.working_directory else None,
                environment_block=env_block,
                stdout_handle=stdout_handle,
                stderr_handle=stderr_handle,
                create_new_process_group=spec.create_new_process_group,
                inherit_handles=inherit_handles,
            )
        except Exception as exc:
            raise LaunchError(str(exc), ProcessLaunchErrorCode.CREATE_PROCESS_FAILED) from exc

        process_handle = proc_info.hProcess
        thread_handle = proc_info.hThread
        pid = proc_info.dwProcessId

        # --- 恢复父进程侧句柄的不可继承状态 ---
        _restore_handle_flags(stdout_handle, spec.stdout_path)
        _restore_handle_flags(stderr_handle, spec.stderr_path)

        # --- 5. 创建并配置 Job Object ---
        job_handle_value: int | None = None
        try:
            job_handle_value = win32_job.create_job_object()
        except Exception as exc:
            _cleanup_on_launch_failure(process_handle, thread_handle, None, stdout_fd, stderr_fd)
            raise LaunchError(str(exc), ProcessLaunchErrorCode.JOB_CREATE_FAILED) from exc

        try:
            win32_job.configure_job_kill_on_close(job_handle_value)
        except Exception as exc:
            _cleanup_on_launch_failure(process_handle, thread_handle, job_handle_value, stdout_fd, stderr_fd)
            raise LaunchError(str(exc), ProcessLaunchErrorCode.JOB_CONFIGURE_FAILED) from exc

        # --- 6. 分配进程到 Job（此时进程仍挂起） ---
        try:
            win32_job.assign_process_to_job(job_handle_value, process_handle)
        except Exception as exc:
            _cleanup_on_launch_failure(process_handle, thread_handle, job_handle_value, stdout_fd, stderr_fd)
            raise LaunchError(str(exc), ProcessLaunchErrorCode.JOB_ASSIGN_FAILED) from exc

        # --- 7. 恢复执行 ---
        try:
            win32_process.resume_thread(thread_handle)
        except Exception as exc:
            _cleanup_on_launch_failure(process_handle, thread_handle, job_handle_value, stdout_fd, stderr_fd)
            raise LaunchError(str(exc), ProcessLaunchErrorCode.RESUME_THREAD_FAILED) from exc

        # --- 8. 关闭线程句柄 ---
        thread_owned = win32_handles.OwnedHandle(thread_handle)
        thread_owned.close()

        # --- 9. 创建 ManagedProcess ---
        managed = ManagedProcess(
            pid=pid,
            process_handle=process_handle,
            job_handle=job_handle_value,
            stdout_fd=stdout_fd,
            stderr_fd=stderr_fd,
            started_at_monotonic=started_at_monotonic,
        )
        return managed

    except LaunchError:
        raise
    except Exception as exc:
        raise LaunchError(str(exc), ProcessLaunchErrorCode.CREATE_PROCESS_FAILED) from exc


def _restore_handle_flags(handle: int | None, path: Path | None) -> None:
    if handle is not None and path is not None:
        try:
            win32_process.set_handle_inheritable(handle, False)
        except Exception:
            pass


def _cleanup_on_launch_failure(
    process_handle: int,
    thread_handle: int,
    job_handle_value: int | None,
    stdout_fd: int | None,
    stderr_fd: int | None,
) -> None:
    proc_owned = win32_handles.OwnedHandle(process_handle)
    thread_owned = win32_handles.OwnedHandle(thread_handle)
    job_owned = win32_handles.OwnedHandle(job_handle_value)
    if job_owned:
        try:
            win32_job.terminate_job(job_handle_value)  # type: ignore[arg-type]
        except Exception:
            pass
    thread_owned.close()
    job_owned.close()
    proc_owned.close()
    for fd in (stdout_fd, stderr_fd):
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _msvcrt_get_osfhandle(fd: int) -> int:
    import msvcrt

    return msvcrt.get_osfhandle(fd)


__all__ = ["LaunchError", "launch"]
