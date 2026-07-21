"""ProcessSupervisor：同步、串行的进程生命周期管理器。

提供 launch → wait/stop → close 的完整生命周期。
不实现并发 launch、优雅停止（CTRL_BREAK）或应用专用退出协议。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from autogame_orchestrator.process import launcher
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.process.errors import (
    ProcessExecutionErrorCode,
    TerminationReason,
)
from autogame_orchestrator.process.models import ManagedProcess, ProcessSpec
from autogame_orchestrator.process.result import ProcessResult

if TYPE_CHECKING:
    pass


class ProcessSupervisorCloseError(RuntimeError):
    """close() 时部分进程清理失败。"""

    def __init__(self, message: str, failures: tuple[ProcessResult, ...]) -> None:
        super().__init__(message)
        self.failures = failures


class ProcessSupervisor:
    """同步、串行的进程生命周期管理器。

    拥有所有通过 ``launch()`` 创建的 ManagedProcess。
    ``close()`` 清理全部活动进程。

    使用方式::

        with ProcessSupervisor() as sup:
            result = sup.run(spec, Deadline.after(10.0))
    """

    def __init__(
        self,
        *,
        poll_interval_seconds: float = 0.05,
        kill_confirmation_seconds: float = 2.0,
    ) -> None:
        self._poll_interval = poll_interval_seconds
        self._kill_confirmation = kill_confirmation_seconds
        self._launch_lock = threading.Lock()
        self._active: dict[str, ManagedProcess] = {}  # process_id → ManagedProcess
        self._closed = False

    # ── launch ──────────────────────────────────────────────────

    def launch(self, spec: ProcessSpec) -> ManagedProcess:
        """启动进程并注册到 supervisor。

        串行启动：内部持有 launch lock，确保句柄继承安全。
        close 后禁止 launch。
        """
        if self._closed:
            msg = "ProcessSupervisor 已关闭，不能再 launch"
            raise RuntimeError(msg)

        with self._launch_lock:
            managed = launcher.launch(spec)
            self._active[managed._id] = managed
            return managed

    # ── wait ────────────────────────────────────────────────────

    def wait(
        self,
        process: ManagedProcess,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProcessResult:
        """等待进程退出。

        轮询 ``poll()``，检查 deadline 和 cancel。
        正常退出返回 NORMAL_EXIT/NONZERO_EXIT。
        超时或取消时终止 Job 并返回相应结果。
        返回前关闭进程全部句柄，从活动注册表移除。
        """
        if process.closed:
            return ProcessResult.start_failed(
                process._name if hasattr(process, "_name") else "unknown",
                ProcessExecutionErrorCode.WAIT_FAILED,
                {"detail": "进程已关闭"},
            )

        spec_name = self._lookup_name(process)

        # 从注册表获取 monotonic 启动时间
        started_at_mono = self._lookup_started_monotonic(process)

        try:
            while True:
                # 检查取消
                if cancel is not None and cancel.is_cancelled:
                    return self._terminate_and_collect(
                        process,
                        spec_name,
                        started_at_mono,
                        TerminationReason.CANCELLED,
                        ProcessExecutionErrorCode.CANCELLED,
                    )

                # 检查超时
                if deadline.expired:
                    return self._terminate_and_collect(
                        process,
                        spec_name,
                        started_at_mono,
                        TerminationReason.TIMEOUT,
                        ProcessExecutionErrorCode.TIMEOUT,
                    )

                # 检查退出
                exit_code = process.poll()
                if exit_code is not None:
                    result = ProcessResult.from_exit(
                        name=spec_name,
                        pid=process.pid,
                        exit_code=exit_code,
                        started_at_monotonic=started_at_mono,
                        stdout_path=self._lookup_stdout(process),
                        stderr_path=self._lookup_stderr(process),
                    )
                    self._cleanup_managed(process)
                    return result

                # 有限等待
                wait_sec = min(self._poll_interval, deadline.remaining_seconds)
                if cancel is not None:
                    cancelled = cancel.wait(timeout_seconds=wait_sec)
                    if cancelled:
                        return self._terminate_and_collect(
                            process,
                            spec_name,
                            started_at_mono,
                            TerminationReason.CANCELLED,
                            ProcessExecutionErrorCode.CANCELLED,
                        )
                else:
                    time.sleep(wait_sec)

        except Exception as exc:
            # Win32 错误或其他意外
            self._cleanup_managed(process)
            return ProcessResult.terminated(
                name=spec_name,
                pid=process.pid,
                reason=TerminationReason.WAIT_FAILED,
                error_code=ProcessExecutionErrorCode.WAIT_FAILED,
                started_at_monotonic=started_at_mono,
                stdout_path=self._lookup_stdout(process),
                stderr_path=self._lookup_stderr(process),
                diagnostics={"error": str(exc)},
            )

    # ── run ─────────────────────────────────────────────────────

    def run(
        self,
        spec: ProcessSpec,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProcessResult:
        """启动并等待进程退出。最常用入口。

        launch → wait → 自动处理 timeout/cancel。
        无论成功、失败、超时或取消，返回后都不留下受管资源。
        KeyboardInterrupt 先清理后重新抛出。
        """
        try:
            managed = launcher.launch(spec)
        except launcher.LaunchError as exc:
            return ProcessResult.start_failed(
                name=spec.name,
                error_code=ProcessExecutionErrorCode.START_FAILED,
                diagnostics={
                    "detail": str(exc),
                    "launch_error_code": exc.error_code.value,
                    "win32_code": exc.win32_code if exc.win32_code is not None else "",
                },
            )
        except Exception as exc:
            return ProcessResult.start_failed(
                name=spec.name,
                error_code=ProcessExecutionErrorCode.START_FAILED,
                diagnostics={"detail": str(exc)},
            )

        # 注册到活动表
        self._active[managed._id] = managed

        try:
            return self.wait(managed, deadline, cancel)
        except KeyboardInterrupt:
            # 清理后重新抛出
            try:
                self._terminate_and_cleanup(managed)
            except Exception:
                pass
            raise

    # ── stop ────────────────────────────────────────────────────

    def stop(
        self,
        process: ManagedProcess,
        confirmation_deadline: Deadline | None = None,
    ) -> ProcessResult:
        """主动终止进程。本阶段直接 TerminateJobObject。

        - 已退出进程返回原始结果（NORMAL_EXIT/NONZERO_EXIT）。
        - 运行中进程返回 STOPPED。
        - 幂等：重复 stop 不二次终止。
        """
        spec_name = self._lookup_name(process)

        if process.closed:
            return ProcessResult.start_failed(
                spec_name,
                ProcessExecutionErrorCode.WAIT_FAILED,
                {"detail": "进程已关闭"},
            )

        started_at_mono = self._lookup_started_monotonic(process)

        # 检查是否已退出
        exit_code = process.poll()
        if exit_code is not None:
            result = ProcessResult.from_exit(
                name=spec_name,
                pid=process.pid,
                exit_code=exit_code,
                started_at_monotonic=started_at_mono,
                stdout_path=self._lookup_stdout(process),
                stderr_path=self._lookup_stderr(process),
            )
            self._cleanup_managed(process)
            return result

        # 终止 Job
        return self._terminate_and_collect(
            process,
            spec_name,
            started_at_mono,
            TerminationReason.STOPPED,
            ProcessExecutionErrorCode.STOPPED,
            confirmation_deadline=confirmation_deadline,
        )

    # ── close ───────────────────────────────────────────────────

    def close(self) -> None:
        """清理所有活动进程。

        遍历活动注册表，对每个进程执行有界终止。
        一个进程清理失败不阻止其他进程清理。
        可重复调用。
        """
        if self._closed:
            return
        self._closed = True

        failures: list[ProcessResult] = []
        for proc_id in list(self._active.keys()):
            proc = self._active.get(proc_id)
            if proc is None:
                continue
            try:
                self._terminate_and_cleanup(proc)
            except Exception:
                failures.append(
                    ProcessResult.start_failed(
                        self._lookup_name(proc),
                        ProcessExecutionErrorCode.TERMINATION_FAILED,
                    )
                )

        self._active.clear()

        if failures:
            raise ProcessSupervisorCloseError(
                f"关闭时 {len(failures)} 个进程清理失败",
                tuple(failures),
            )

    # ── context manager ─────────────────────────────────────────

    def __enter__(self) -> ProcessSupervisor:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
        return None

    # ── 内部辅助 ────────────────────────────────────────────────

    def _terminate_and_collect(
        self,
        process: ManagedProcess,
        name: str,
        started_at_mono: float,
        reason: TerminationReason,
        error_code: ProcessExecutionErrorCode,
        confirmation_deadline: Deadline | None = None,
    ) -> ProcessResult:
        """终止 Job，确认进程退出，收集 ProcessResult，关闭句柄。"""
        exit_code: int | None = None
        failed = False

        try:
            process.terminate_job()
        except Exception:
            failed = True

        # 有界确认退出
        confirm_dl = confirmation_deadline or Deadline.after(self._kill_confirmation)
        confirmed = False
        while not confirm_dl.expired:
            ec = process.poll()
            if ec is not None:
                exit_code = ec
                confirmed = True
                break
            time.sleep(min(0.05, confirm_dl.remaining_seconds))

        if not confirmed and failed:
            reason = TerminationReason.TERMINATION_FAILED
            error_code = ProcessExecutionErrorCode.TERMINATION_FAILED

        result = ProcessResult.terminated(
            name=name,
            pid=process.pid,
            reason=reason,
            error_code=error_code,
            started_at_monotonic=started_at_mono,
            stdout_path=self._lookup_stdout(process),
            stderr_path=self._lookup_stderr(process),
            exit_code=exit_code,
        )

        self._cleanup_managed(process)
        return result

    def _cleanup_managed(self, process: ManagedProcess) -> None:
        """关闭进程句柄并从活动注册表移除。"""
        try:
            process.close_handles()
        except Exception:
            pass
        self._active.pop(process._id, None)

    def _terminate_and_cleanup(self, process: ManagedProcess) -> None:
        """终止 Job 并关闭句柄。"""
        try:
            process.terminate_job()
        except Exception:
            pass
        try:
            process.close_handles()
        except Exception:
            pass
        self._active.pop(process._id, None)

    def _lookup_name(self, process: ManagedProcess) -> str:
        return process._name

    def _lookup_started_monotonic(self, process: ManagedProcess) -> float:
        return process._started_at_monotonic

    def _lookup_stdout(self, process: ManagedProcess) -> Path | None:
        return process._stdout_path

    def _lookup_stderr(self, process: ManagedProcess) -> Path | None:
        return process._stderr_path
