"""MuMu 生命周期适配器。

通过管理命令（短进程）控制 MuMu 模拟器的启动/停止，
通过 MumuReadinessProbe 验证 ADB 就绪状态。

管理命令由 ProcessSupervisor 执行（短生命周期），
实际模拟器进程不由阶段 2B 的 Job Object 长期持有。
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

from autogame_orchestrator.probes.adb_client import AdbClient, AdbClientConfig
from autogame_orchestrator.probes.models import ProbeErrorCode, ProbeStatus
from autogame_orchestrator.probes.mumu_readiness import MumuReadinessProbe
from autogame_orchestrator.process import CancellationToken, Deadline, ProcessSpec, ProcessSupervisor
from autogame_orchestrator.process.errors import TerminationReason
from autogame_orchestrator.runtime.models import (
    MumuAction,
    MumuRuntimeErrorCode,
    MumuRuntimeResult,
    MumuRuntimeStatus,
)

_POLL_INTERVAL = 0.3  # readiness 轮询间隔（秒）
_CommandResult = dict[str, Any]  # _run_manager_command 返回类型


class MumuAdapter:
    """MuMu 生命周期适配器。

    管理命令是小进程，通过 ProcessSupervisor.run() 执行。
    模拟器 readiness 通过组合 TCP + ADB 探测验证。
    """

    def __init__(
        self,
        executable: Path,
        start_arguments: tuple[str, ...],
        stop_arguments: tuple[str, ...],
        adb_executable: Path,
        adb_serial: str,
        adb_host: str = "127.0.0.1",
        adb_port: int = 16384,
        start_timeout_seconds: float = 120.0,
        stop_timeout_seconds: float = 20.0,
    ) -> None:
        if not adb_host or adb_host != "127.0.0.1":
            msg = f"adb_host 必须是 127.0.0.1，收到 {adb_host}"
            raise ValueError(msg)
        if not 1 <= adb_port <= 65535:
            msg = f"adb_port 必须在 1-65535 之间，收到 {adb_port}"
            raise ValueError(msg)

        self._executable = executable
        self._start_args = start_arguments
        self._stop_args = stop_arguments
        self._adb_executable = adb_executable
        self._adb_serial = adb_serial
        self._adb_host = adb_host
        self._adb_port = adb_port
        self._start_timeout = start_timeout_seconds
        self._stop_timeout = stop_timeout_seconds

    # ── 公开 API ──────────────────────────────────────────────────

    def status(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        """查询 MuMu readiness 状态。"""
        started_at = time.monotonic()

        probe = self._create_probe()
        result = probe.probe(self._adb_host, self._adb_port, self._adb_serial, deadline, cancel)

        if result.status == ProbeStatus.READY:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS, MumuRuntimeStatus.READY, MumuRuntimeErrorCode.OK, started_at, changed=False
            )
        if result.error_code in (ProbeErrorCode.PORT_CLOSED, ProbeErrorCode.DEVICE_NOT_FOUND):
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS, MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK, started_at, changed=False
            )
        if result.status == ProbeStatus.TIMEOUT:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS,
                MumuRuntimeStatus.TIMEOUT,
                MumuRuntimeErrorCode.READINESS_FAILED,
                started_at,
                changed=False,
            )
        if result.error_code == ProbeErrorCode.ADB_CANCELLED:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS,
                MumuRuntimeStatus.CANCELLED,
                MumuRuntimeErrorCode.CANCELLED,
                started_at,
                changed=False,
            )
        return MumuRuntimeResult.from_monotonic(
            MumuAction.STATUS,
            MumuRuntimeStatus.NOT_READY,
            MumuRuntimeErrorCode.READINESS_FAILED,
            started_at,
            changed=False,
            diagnostics={"probe_status": result.status.value, "probe_error": result.error_code.value},
        )

    def start(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        """启动 MuMu 并在 Deadline 内等待 readiness。"""
        started_at = time.monotonic()

        # 检查取消
        if cancel is not None and cancel.is_cancelled:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.START, MumuRuntimeStatus.CANCELLED, MumuRuntimeErrorCode.CANCELLED, started_at, changed=False
            )

        # 验证配置
        if not self._executable.is_file():
            return MumuRuntimeResult.from_monotonic(
                MumuAction.START,
                MumuRuntimeStatus.FAILED,
                MumuRuntimeErrorCode.MANAGER_NOT_FOUND,
                started_at,
                changed=False,
                diagnostics={"executable": str(self._executable)},
            )

        # 已 ready → 幂等
        st = self.status(deadline, cancel)
        if st.status == MumuRuntimeStatus.READY:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.START,
                MumuRuntimeStatus.STARTED,
                MumuRuntimeErrorCode.OK,
                started_at,
                changed=False,
            )

        # 未配置启动命令 → 拒绝
        if not self._start_args:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.START,
                MumuRuntimeStatus.FAILED,
                MumuRuntimeErrorCode.INVALID_CONFIGURATION,
                started_at,
                changed=False,
                diagnostics={"reason": "未配置受支持的 MuMu 启动管理命令"},
            )

        # 执行启动管理命令
        cmd_result = self._run_manager_command(self._start_args, deadline, cancel, MumuRuntimeErrorCode.START_TIMEOUT)
        if not cmd_result["ok"]:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.START,
                cmd_result["status"],
                cmd_result["error_code"],
                started_at,
                changed=False,
                diagnostics=cmd_result["diag"],
            )

        # 轮询 readiness
        return self._wait_readiness(MumuAction.START, MumuRuntimeStatus.STARTED, started_at, deadline, cancel)

    def stop(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        """停止 MuMu 并在 Deadline 内确认停止。"""
        started_at = time.monotonic()

        if cancel is not None and cancel.is_cancelled:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STOP, MumuRuntimeStatus.CANCELLED, MumuRuntimeErrorCode.CANCELLED, started_at, changed=False
            )

        if not self._executable.is_file():
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STOP,
                MumuRuntimeStatus.FAILED,
                MumuRuntimeErrorCode.MANAGER_NOT_FOUND,
                started_at,
                changed=False,
                diagnostics={"executable": str(self._executable)},
            )

        # 已 stopped → 幂等
        st = self.status(deadline, cancel)
        if st.status == MumuRuntimeStatus.STOPPED:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STOP,
                MumuRuntimeStatus.STOPPED,
                MumuRuntimeErrorCode.OK,
                started_at,
                changed=False,
            )

        # 未配置停止命令 → 拒绝
        if not self._stop_args:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STOP,
                MumuRuntimeStatus.FAILED,
                MumuRuntimeErrorCode.INVALID_CONFIGURATION,
                started_at,
                changed=False,
                diagnostics={"reason": "未配置受支持的 MuMu 停止管理命令"},
            )

        # 执行停止管理命令
        cmd_result = self._run_manager_command(self._stop_args, deadline, cancel, MumuRuntimeErrorCode.STOP_TIMEOUT)
        if not cmd_result["ok"]:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STOP,
                cmd_result["status"],
                cmd_result["error_code"],
                started_at,
                changed=False,
                diagnostics=cmd_result["diag"],
            )

        # 轮询停止确认
        return self._wait_stopped(started_at, deadline, cancel)

    def restart(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        """重启 MuMu：先 stop，再 start，共享同一个 Deadline。"""
        started_at = time.monotonic()

        if cancel is not None and cancel.is_cancelled:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.RESTART,
                MumuRuntimeStatus.CANCELLED,
                MumuRuntimeErrorCode.CANCELLED,
                started_at,
                changed=False,
            )

        # stop
        stop_result = self.stop(deadline, cancel)
        if stop_result.status not in (MumuRuntimeStatus.STOPPED, MumuRuntimeStatus.READY):
            return MumuRuntimeResult.from_monotonic(
                MumuAction.RESTART,
                stop_result.status,
                stop_result.error_code,
                started_at,
                changed=False,
                diagnostics={"step": "stop", "detail": str(stop_result.diagnostics)},
            )

        # 检查取消和 deadline
        if cancel is not None and cancel.is_cancelled:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.RESTART,
                MumuRuntimeStatus.CANCELLED,
                MumuRuntimeErrorCode.CANCELLED,
                started_at,
                changed=False,
            )
        if deadline.expired:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.RESTART,
                MumuRuntimeStatus.TIMEOUT,
                MumuRuntimeErrorCode.START_TIMEOUT,
                started_at,
                changed=False,
                diagnostics={"step": "start_after_stop"},
            )

        # start
        start_result = self.start(deadline, cancel)
        if start_result.status == MumuRuntimeStatus.STARTED:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.RESTART,
                MumuRuntimeStatus.RESTARTED,
                MumuRuntimeErrorCode.OK,
                started_at,
                changed=True,
                diagnostics={"stop": "ok", "start": "ok"},
            )

        return MumuRuntimeResult.from_monotonic(
            MumuAction.RESTART,
            start_result.status,
            start_result.error_code,
            started_at,
            changed=False,
            diagnostics={"step": "start", "detail": str(start_result.diagnostics)},
        )

    # ── 内部 ──────────────────────────────────────────────────────

    def _create_probe(self) -> MumuReadinessProbe:
        config = AdbClientConfig(executable=self._adb_executable)
        return MumuReadinessProbe(AdbClient(config))

    def _run_manager_command(
        self,
        arguments: tuple[str, ...],
        deadline: Deadline,
        cancel: CancellationToken | None,
        timeout_code: MumuRuntimeErrorCode,
    ) -> _CommandResult:
        """执行管理命令并返回结果摘要。"""
        if not arguments:
            return {
                "ok": False,
                "status": MumuRuntimeStatus.FAILED,
                "error_code": MumuRuntimeErrorCode.INVALID_CONFIGURATION,
                "diag": {"reason": "管理命令参数为空"},
            }

        try:
            with tempfile.TemporaryDirectory(prefix="mumu-mgr-") as tmp_dir:
                td = Path(tmp_dir)
                spec = ProcessSpec(
                    name="mumu_manager",
                    executable=self._executable,
                    arguments=arguments,
                    stdout_path=td / "stdout.log",
                    stderr_path=td / "stderr.log",
                )

                with ProcessSupervisor() as supervisor:
                    proc_result = supervisor.run(spec, deadline, cancel)

                reason = proc_result.termination_reason
                if reason == TerminationReason.NORMAL_EXIT:
                    return {
                        "ok": True,
                        "status": MumuRuntimeStatus.STARTED,
                        "error_code": MumuRuntimeErrorCode.OK,
                        "diag": {},
                    }
                if reason == TerminationReason.NONZERO_EXIT:
                    return {
                        "ok": False,
                        "status": MumuRuntimeStatus.FAILED,
                        "error_code": MumuRuntimeErrorCode.COMMAND_EXIT_NONZERO,
                        "diag": {"exit_code": str(proc_result.exit_code)},
                    }
                if reason == TerminationReason.TIMEOUT:
                    return {
                        "ok": False,
                        "status": MumuRuntimeStatus.TIMEOUT,
                        "error_code": timeout_code,
                        "diag": {},
                    }
                if reason == TerminationReason.CANCELLED:
                    return {
                        "ok": False,
                        "status": MumuRuntimeStatus.CANCELLED,
                        "error_code": MumuRuntimeErrorCode.CANCELLED,
                        "diag": {},
                    }
                if reason == TerminationReason.START_FAILED:
                    return {
                        "ok": False,
                        "status": MumuRuntimeStatus.FAILED,
                        "error_code": MumuRuntimeErrorCode.COMMAND_START_FAILED,
                        "diag": {"detail": str(proc_result.diagnostics.get("detail", ""))},
                    }
                return {
                    "ok": False,
                    "status": MumuRuntimeStatus.FAILED,
                    "error_code": MumuRuntimeErrorCode.COMMAND_START_FAILED,
                    "diag": {},
                }
        except Exception as exc:
            return {
                "ok": False,
                "status": MumuRuntimeStatus.FAILED,
                "error_code": MumuRuntimeErrorCode.COMMAND_START_FAILED,
                "diag": {"error": str(exc)},
            }

    def _wait_readiness(
        self,
        action: MumuAction,
        success_status: MumuRuntimeStatus,
        started_at: float,
        deadline: Deadline,
        cancel: CancellationToken | None,
    ) -> MumuRuntimeResult:
        """轮询直到 readiness 或 deadline 到期。"""
        while not deadline.expired:
            if cancel is not None and cancel.is_cancelled:
                return MumuRuntimeResult.from_monotonic(
                    action, MumuRuntimeStatus.CANCELLED, MumuRuntimeErrorCode.CANCELLED, started_at, changed=True
                )

            probe = self._create_probe()
            result = probe.probe(self._adb_host, self._adb_port, self._adb_serial, deadline, cancel)

            if result.status == ProbeStatus.READY:
                return MumuRuntimeResult.from_monotonic(
                    action, success_status, MumuRuntimeErrorCode.OK, started_at, changed=True
                )

            wait_sec = min(_POLL_INTERVAL, deadline.remaining_seconds)
            if cancel is not None:
                cancelled = cancel.wait(timeout_seconds=wait_sec)
                if cancelled:
                    return MumuRuntimeResult.from_monotonic(
                        action, MumuRuntimeStatus.CANCELLED, MumuRuntimeErrorCode.CANCELLED, started_at, changed=True
                    )
            else:
                time.sleep(wait_sec)

        return MumuRuntimeResult.from_monotonic(
            action, MumuRuntimeStatus.TIMEOUT, MumuRuntimeErrorCode.START_TIMEOUT, started_at, changed=True
        )

    def _wait_stopped(
        self, started_at: float, deadline: Deadline, cancel: CancellationToken | None
    ) -> MumuRuntimeResult:
        """轮询直到端口关闭或设备消失。"""
        while not deadline.expired:
            if cancel is not None and cancel.is_cancelled:
                return MumuRuntimeResult.from_monotonic(
                    MumuAction.STOP,
                    MumuRuntimeStatus.CANCELLED,
                    MumuRuntimeErrorCode.CANCELLED,
                    started_at,
                    changed=True,
                )

            probe = self._create_probe()
            result = probe.probe(self._adb_host, self._adb_port, self._adb_serial, deadline, cancel)

            if result.error_code in (ProbeErrorCode.PORT_CLOSED, ProbeErrorCode.DEVICE_NOT_FOUND):
                return MumuRuntimeResult.from_monotonic(
                    MumuAction.STOP, MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK, started_at, changed=True
                )

            wait_sec = min(_POLL_INTERVAL, deadline.remaining_seconds)
            if cancel is not None:
                cancelled = cancel.wait(timeout_seconds=wait_sec)
                if cancelled:
                    return MumuRuntimeResult.from_monotonic(
                        MumuAction.STOP,
                        MumuRuntimeStatus.CANCELLED,
                        MumuRuntimeErrorCode.CANCELLED,
                        started_at,
                        changed=True,
                    )
            else:
                time.sleep(wait_sec)

        return MumuRuntimeResult.from_monotonic(
            MumuAction.STOP, MumuRuntimeStatus.TIMEOUT, MumuRuntimeErrorCode.STOP_TIMEOUT, started_at, changed=True
        )
