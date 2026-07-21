"""进程基础模型。

定义 ``ProcessSpec``（冻结启动规格）和 ``ManagedProcess``（可变生命周期对象）。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from autogame_orchestrator.process import win32_handles, win32_job


@dataclass(frozen=True)
class ProcessSpec:
    """不可变的进程启动规格。

    在传入启动器之前完成校验。不含 ``shell`` 字段——始终 ``False``。
    """

    name: str
    """进程的人类可读名称，用于日志和诊断。"""

    executable: Path
    """可执行文件的绝对路径或可搜索路径。"""

    arguments: tuple[str, ...] = ()
    """命令行参数列表（不含可执行文件名）。"""

    working_directory: Path | None = None
    """工作目录。``None`` 表示继承父进程工作目录。"""

    environment_overrides: Mapping[str, str] = field(default_factory=dict)
    """额外的环境变量。合并到继承的父环境之上。"""

    inherit_parent_environment: bool = True
    """是否继承父进程的环境变量。"""

    stdout_path: Path | None = None
    """stdout 输出文件路径。``None`` 则丢弃到 ``DEVNULL``。"""

    stderr_path: Path | None = None
    """stderr 输出文件路径。``None`` 则丢弃到 ``DEVNULL``。"""

    create_new_process_group: bool = False
    """是否创建新进程组（用于后续 CTRL_BREAK_EVENT）。"""

    def __post_init__(self) -> None:
        if not self.name.strip():
            msg = "ProcessSpec.name 不能为空"
            raise ValueError(msg)
        if not str(self.executable).strip():
            msg = "ProcessSpec.executable 不能为空"
            raise ValueError(msg)


class ManagedProcess:
    """内部可变资源对象，跟踪单个子进程的完整生命周期。

    句柄所有权（使用 ``OwnedHandle``，幂等关闭）：
    - ``_process_handle``: 由此对象负责关闭
    - ``_job_handle``: 由此对象负责关闭
    - ``_stdout_fd``: 由此对象负责关闭
    - ``_stderr_fd``: 由此对象负责关闭
    """

    def __init__(
        self,
        pid: int,
        process_handle: int,
        job_handle: int | None,
        stdout_fd: int | None,
        stderr_fd: int | None,
        started_at_monotonic: float,
        name: str = "",
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
    ) -> None:
        self._id = str(uuid.uuid4())
        self.pid = pid
        self._process_handle = win32_handles.OwnedHandle(process_handle)
        self._job_handle = win32_handles.OwnedHandle(job_handle)
        self._stdout_fd: int | None = stdout_fd
        self._stderr_fd: int | None = stderr_fd
        self._started_at_monotonic: float = started_at_monotonic
        self._name = name
        self._stdout_path = stdout_path
        self._stderr_path = stderr_path
        self._closed = False

    @property
    def closed(self) -> bool:
        """所有句柄是否已关闭。"""
        return self._closed

    @property
    def process_handle(self) -> int:
        """Win32 进程句柄。"""
        v = self._process_handle.value
        if v is None:
            msg = "进程句柄已关闭"
            raise RuntimeError(msg)
        return v

    @property
    def job_handle(self) -> int | None:
        """Win32 Job Object 句柄。"""
        return self._job_handle.value

    def poll(self) -> int | None:
        """检查进程是否已退出。返回退出码或 ``None``（仍在运行）。

        使用 ``WaitForSingleObject(h, 0)`` 判定存活状态，
        退出码 259 不会被误判为 STILL_ACTIVE。
        """
        from autogame_orchestrator.process import win32_process

        if self._process_handle.value is None:
            return None
        return win32_process.get_exit_code(self._process_handle.value)

    def is_alive(self) -> bool:
        """使用 WaitForSingleObject 判定进程是否仍在运行。"""
        from autogame_orchestrator.process import win32_process

        if self._process_handle.value is None:
            return False
        return win32_process.is_process_alive(self._process_handle.value)

    def terminate_job(self) -> None:
        """强制终止 Job Object 中的所有进程。"""
        if self._job_handle.value is not None:
            win32_job.terminate_job(self._job_handle.value)

    def close_handles(self) -> None:
        """关闭所有资源（幂等）。

        关闭顺序：进程句柄 → Job 句柄 → 输出文件。
        Job 句柄关闭会触发 KILL_ON_JOB_CLOSE（如果尚未终止）。
        每个句柄在关闭后立即设为 None，防止二次 CloseHandle。
        """
        if self._closed:
            return
        self._closed = True

        try:
            self._process_handle.close()
        except Exception:
            pass

        try:
            self._job_handle.close()
        except Exception:
            pass

        for fd in (self._stdout_fd, self._stderr_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
