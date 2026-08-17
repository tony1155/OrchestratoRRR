"""MuMu 生命周期适配器。

通过管理命令（短进程）控制 MuMu 模拟器的启动/停止，
通过 MumuReadinessProbe 验证 ADB 就绪状态。

管理命令由 ProcessSupervisor 执行（短生命周期），
实际模拟器进程不由阶段 2B 的 Job Object 长期持有。

管理命令使用 ``descendants_survive_close=True``：``MuMuManager.exe`` 是引信型短命令，
触发后立即退出，但其派生的模拟器进程必须活过命令本身。若沛用默认的
``KILL_ON_JOB_CLOSE``，命令退出并关闭 Job 句柄时会连带终止刚启动的模拟器，
表现为命令报告成功但 readiness 永不到达。
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autogame_orchestrator.models import JsonValue
from autogame_orchestrator.probes.adb_client import AdbClient, AdbClientConfig
from autogame_orchestrator.probes.models import ProbeErrorCode, ProbeResult, ProbeStatus
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
_CONTROLLED_CONNECT_RETRY_INTERVAL = 3.0  # cooldown between controlled local adb connects
_OFFLINE_RECOVERY_GRACE_SECONDS = 3.0
_PROBE_STEP_ALLOWLIST = {
    "tcp_probe",
    "adb_devices",
    "select_device",
    "adb_get_state",
    "adb_boot_completed",
    "adb_connect",
    "none",
}
_CONNECT_STATUS_ALLOWLIST = {"not_attempted", "connected", "already_connected", "failed"}
_CONNECT_DIAGNOSTIC_KEYS = (
    "adb_connect_attempted",
    "adb_connect_status",
    "adb_connect_error",
    "readiness_rechecked_after_connect",
)


@dataclass(frozen=True)
class _OfflineRecoveryResult:
    succeeded: bool
    status: MumuRuntimeStatus
    error_code: MumuRuntimeErrorCode


def _safe_probe_diagnostics(result: ProbeResult) -> dict[str, JsonValue]:
    step = result.diagnostics.get("step", "none")
    safe_step = step if isinstance(step, str) and step in _PROBE_STEP_ALLOWLIST else "none"
    safe: dict[str, JsonValue] = {
        "probe_status": result.status.value,
        "probe_error": result.error_code.value,
        "probe_step": safe_step,
    }
    attempted = result.diagnostics.get("adb_connect_attempted")
    if isinstance(attempted, bool):
        safe["adb_connect_attempted"] = attempted
    connect_status = result.diagnostics.get("adb_connect_status")
    if isinstance(connect_status, str) and connect_status in _CONNECT_STATUS_ALLOWLIST:
        safe["adb_connect_status"] = connect_status
    connect_error = result.diagnostics.get("adb_connect_error")
    allowed_errors = {"none", *(code.value for code in ProbeErrorCode)}
    if isinstance(connect_error, str) and connect_error in allowed_errors:
        safe["adb_connect_error"] = connect_error
    rechecked = result.diagnostics.get("readiness_rechecked_after_connect")
    if isinstance(rechecked, bool):
        safe["readiness_rechecked_after_connect"] = rechecked
    return safe


def _safe_wait_diagnostics(
    last_result: ProbeResult | None,
    connect_diagnostics: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    safe = _safe_probe_diagnostics(last_result) if last_result is not None else {}
    safe.update(connect_diagnostics)
    return safe


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
        if isinstance(adb_port, bool) or not isinstance(adb_port, int) or not 1 <= adb_port <= 65535:
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
                MumuAction.STATUS,
                MumuRuntimeStatus.READY,
                MumuRuntimeErrorCode.OK,
                started_at,
                changed=False,
                diagnostics=_safe_probe_diagnostics(result),
            )
        # 只有 PORT_CLOSED 才是「已停止」的证据。DEVICE_NOT_FOUND 不是：
        # MuMu 的 ADB 是网络设备（127.0.0.1:16384），宿主 ADB server 一旦重启
        # 就会忘掉网络设备注册，此时 TCP 端口仍 OPEN（模拟器活着）但
        # `adb devices -l` 是空列表，probe 在 select_device 步骤抛 DEVICE_NOT_FOUND。
        # 把它当成 STOPPED 会让 stop() 走幂等短路，shutdown 命令永不执行。
        # DEVICE_NOT_FOUND 落到本方法末尾的 NOT_READY 分支。
        if result.error_code == ProbeErrorCode.PORT_CLOSED:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS,
                MumuRuntimeStatus.STOPPED,
                MumuRuntimeErrorCode.OK,
                started_at,
                changed=False,
                diagnostics=_safe_probe_diagnostics(result),
            )
        if result.status == ProbeStatus.TIMEOUT:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS,
                MumuRuntimeStatus.TIMEOUT,
                MumuRuntimeErrorCode.READINESS_FAILED,
                started_at,
                changed=False,
                diagnostics=_safe_probe_diagnostics(result),
            )
        if result.error_code == ProbeErrorCode.ADB_CANCELLED:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS,
                MumuRuntimeStatus.CANCELLED,
                MumuRuntimeErrorCode.CANCELLED,
                started_at,
                changed=False,
                diagnostics=_safe_probe_diagnostics(result),
            )
        return MumuRuntimeResult.from_monotonic(
            MumuAction.STATUS,
            MumuRuntimeStatus.NOT_READY,
            MumuRuntimeErrorCode.READINESS_FAILED,
            started_at,
            changed=False,
            diagnostics=_safe_probe_diagnostics(result),
        )

    def ensure_external_ready(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        """Explicit external readiness with one controlled local ADB connect."""
        started_at = time.monotonic()
        probe = self._create_probe()
        result = probe.ensure_ready(self._adb_host, self._adb_port, self._adb_serial, deadline, cancel)

        if result.status == ProbeStatus.READY:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS,
                MumuRuntimeStatus.READY,
                MumuRuntimeErrorCode.OK,
                started_at,
                changed=False,
                diagnostics=_safe_probe_diagnostics(result),
            )
        if result.status == ProbeStatus.TIMEOUT:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS,
                MumuRuntimeStatus.TIMEOUT,
                MumuRuntimeErrorCode.READINESS_FAILED,
                started_at,
                changed=False,
                diagnostics=_safe_probe_diagnostics(result),
            )
        if result.error_code == ProbeErrorCode.ADB_CANCELLED:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS,
                MumuRuntimeStatus.CANCELLED,
                MumuRuntimeErrorCode.CANCELLED,
                started_at,
                changed=False,
                diagnostics=_safe_probe_diagnostics(result),
            )
        return MumuRuntimeResult.from_monotonic(
            MumuAction.STATUS,
            MumuRuntimeStatus.NOT_READY,
            MumuRuntimeErrorCode.READINESS_FAILED,
            started_at,
            changed=False,
            diagnostics=_safe_probe_diagnostics(result),
        )

    def start(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        """启动 MuMu 并在 Deadline 内等待 readiness。"""
        started_at = time.monotonic()
        operation_deadline = Deadline.at(started_at + deadline.clamp_timeout(self._start_timeout))

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
        st = self.status(operation_deadline, cancel)
        if st.status == MumuRuntimeStatus.READY:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.START,
                MumuRuntimeStatus.STARTED,
                MumuRuntimeErrorCode.OK,
                started_at,
                changed=False,
                diagnostics=st.diagnostics,
            )
        if st.status == MumuRuntimeStatus.CANCELLED:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.START,
                MumuRuntimeStatus.CANCELLED,
                MumuRuntimeErrorCode.CANCELLED,
                started_at,
                changed=False,
                diagnostics=st.diagnostics,
            )
        if operation_deadline.expired:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.START,
                MumuRuntimeStatus.TIMEOUT,
                MumuRuntimeErrorCode.START_TIMEOUT,
                started_at,
                changed=False,
                diagnostics=st.diagnostics,
            )
        if st.status == MumuRuntimeStatus.TIMEOUT:
            # ADB commands have a shorter child deadline than this operation.
            # An inconclusive initial probe must not launch MuMu again, but it
            # can continue readonly readiness polling inside the same budget.
            return self._wait_readiness(
                MumuAction.START,
                MumuRuntimeStatus.STARTED,
                started_at,
                operation_deadline,
                cancel,
                changed=False,
            )
        if st.status == MumuRuntimeStatus.FAILED:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.START,
                MumuRuntimeStatus.FAILED,
                st.error_code,
                started_at,
                changed=False,
                diagnostics=st.diagnostics,
            )
        if st.status == MumuRuntimeStatus.NOT_READY:
            return self._wait_readiness(
                MumuAction.START,
                MumuRuntimeStatus.STARTED,
                started_at,
                operation_deadline,
                cancel,
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
        cmd_result = self._run_manager_command(
            self._start_args,
            operation_deadline,
            cancel,
            MumuRuntimeErrorCode.START_TIMEOUT,
        )
        if not cmd_result["ok"]:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.START,
                cmd_result["status"],
                cmd_result["error_code"],
                started_at,
                changed=True,
                diagnostics=cmd_result["diag"],
            )

        # 轮询 readiness
        return self._wait_readiness(
            MumuAction.START,
            MumuRuntimeStatus.STARTED,
            started_at,
            operation_deadline,
            cancel,
            changed=True,
        )

    def stop(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        """停止 MuMu 并在 Deadline 内确认停止。"""
        started_at = time.monotonic()
        operation_deadline = Deadline.at(started_at + deadline.clamp_timeout(self._stop_timeout))

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
        st = self.status(operation_deadline, cancel)
        if st.status == MumuRuntimeStatus.STOPPED:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STOP,
                MumuRuntimeStatus.STOPPED,
                MumuRuntimeErrorCode.OK,
                started_at,
                changed=False,
                diagnostics=st.diagnostics,
            )
        if st.status == MumuRuntimeStatus.CANCELLED:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STOP,
                MumuRuntimeStatus.CANCELLED,
                MumuRuntimeErrorCode.CANCELLED,
                started_at,
                changed=False,
                diagnostics=st.diagnostics,
            )
        if operation_deadline.expired:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STOP,
                MumuRuntimeStatus.TIMEOUT,
                MumuRuntimeErrorCode.STOP_TIMEOUT,
                started_at,
                changed=False,
                diagnostics=st.diagnostics,
            )
        # A shorter ADB command deadline may make the initial status probe
        # inconclusive while the stop operation still has budget. Continue to
        # the idempotent manager shutdown command instead of returning early.
        if st.status == MumuRuntimeStatus.FAILED:
            return MumuRuntimeResult.from_monotonic(
                MumuAction.STOP,
                MumuRuntimeStatus.FAILED,
                st.error_code,
                started_at,
                changed=False,
                diagnostics=st.diagnostics,
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
        cmd_result = self._run_manager_command(
            self._stop_args,
            operation_deadline,
            cancel,
            MumuRuntimeErrorCode.STOP_TIMEOUT,
        )
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
        return self._wait_stopped(started_at, operation_deadline, cancel)

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
        if cancel is not None and cancel.is_cancelled:
            return {
                "ok": False,
                "status": MumuRuntimeStatus.CANCELLED,
                "error_code": MumuRuntimeErrorCode.CANCELLED,
                "diag": {},
            }
        if deadline.expired:
            return {
                "ok": False,
                "status": MumuRuntimeStatus.TIMEOUT,
                "error_code": timeout_code,
                "diag": {},
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
                    descendants_survive_close=True,
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

    def _offline_recovery_is_allowed(self, result: ProbeResult) -> bool:
        return (
            result.error_code == ProbeErrorCode.DEVICE_OFFLINE
            and result.diagnostics.get("step") == "select_device"
            and self._adb_host == "127.0.0.1"
            and self._adb_serial == f"{self._adb_host}:{self._adb_port}"
        )

    def _recover_offline_transport(
        self,
        deadline: Deadline,
        cancel: CancellationToken | None,
    ) -> _OfflineRecoveryResult:
        """Restart one managed instance without creating a new time budget."""
        stop_command = self._run_manager_command(
            self._stop_args,
            deadline,
            cancel,
            MumuRuntimeErrorCode.START_TIMEOUT,
        )
        if not stop_command["ok"]:
            return _OfflineRecoveryResult(
                False,
                stop_command["status"],
                stop_command["error_code"],
            )

        stopped = self._wait_stopped(time.monotonic(), deadline, cancel)
        if stopped.status != MumuRuntimeStatus.STOPPED:
            error_code = (
                MumuRuntimeErrorCode.START_TIMEOUT
                if stopped.status == MumuRuntimeStatus.TIMEOUT
                else stopped.error_code
            )
            return _OfflineRecoveryResult(False, stopped.status, error_code)

        start_command = self._run_manager_command(
            self._start_args,
            deadline,
            cancel,
            MumuRuntimeErrorCode.START_TIMEOUT,
        )
        if not start_command["ok"]:
            return _OfflineRecoveryResult(
                False,
                start_command["status"],
                start_command["error_code"],
            )
        return _OfflineRecoveryResult(
            True,
            MumuRuntimeStatus.STARTED,
            MumuRuntimeErrorCode.OK,
        )

    def _wait_readiness(
        self,
        action: MumuAction,
        success_status: MumuRuntimeStatus,
        started_at: float,
        deadline: Deadline,
        cancel: CancellationToken | None,
        *,
        changed: bool,
    ) -> MumuRuntimeResult:
        """轮询直到 readiness 或 deadline 到期。

        使用 ``ensure_ready()`` 而非只读 ``probe()``：新启动的模拟器尚未被 adb 登记，
        必须经一次受控 ``adb connect`` 才能出现在设备列表中；仅靠只读探测会永远等不到就绪。
        """
        last_probe_result: ProbeResult | None = None
        wait_diagnostics: dict[str, JsonValue] = {}
        next_controlled_connect_at = 0.0
        connect_established = False
        offline_since: float | None = None
        offline_recovery_attempted = False

        while not deadline.expired:
            if cancel is not None and cancel.is_cancelled:
                return MumuRuntimeResult.from_monotonic(
                    action,
                    MumuRuntimeStatus.CANCELLED,
                    MumuRuntimeErrorCode.CANCELLED,
                    started_at,
                    changed=changed,
                    diagnostics=_safe_wait_diagnostics(last_probe_result, wait_diagnostics),
                )

            probe = self._create_probe()
            if connect_established or time.monotonic() < next_controlled_connect_at:
                result = probe.probe(self._adb_host, self._adb_port, self._adb_serial, deadline, cancel)
            else:
                result = probe.ensure_ready(self._adb_host, self._adb_port, self._adb_serial, deadline, cancel)
                safe_result = _safe_probe_diagnostics(result)
                if safe_result.get("adb_connect_attempted") is True:
                    wait_diagnostics.update(
                        {key: safe_result[key] for key in _CONNECT_DIAGNOSTIC_KEYS if key in safe_result}
                    )
                    connect_status = safe_result.get("adb_connect_status")
                    connect_established = connect_status in {"connected", "already_connected"} and not (
                        safe_result.get("probe_error") == ProbeErrorCode.DEVICE_NOT_FOUND.value
                        and safe_result.get("probe_step") == "select_device"
                    )
                    if not connect_established:
                        next_controlled_connect_at = time.monotonic() + _CONTROLLED_CONNECT_RETRY_INTERVAL
            last_probe_result = result

            if result.status == ProbeStatus.READY:
                return MumuRuntimeResult.from_monotonic(
                    action,
                    success_status,
                    MumuRuntimeErrorCode.OK,
                    started_at,
                    changed=changed,
                    diagnostics=_safe_wait_diagnostics(last_probe_result, wait_diagnostics),
                )

            now = time.monotonic()
            if self._offline_recovery_is_allowed(result):
                if offline_since is None:
                    offline_since = now
                    if not offline_recovery_attempted:
                        wait_diagnostics.update(
                            {
                                "offline_recovery_attempted": False,
                                "offline_recovery_count": 0,
                            }
                        )
                elif not offline_recovery_attempted and now - offline_since >= _OFFLINE_RECOVERY_GRACE_SECONDS:
                    offline_recovery_attempted = True
                    changed = True
                    wait_diagnostics.update(
                        {
                            "offline_recovery_attempted": True,
                            "offline_recovery_count": 1,
                            "offline_recovery_status": "started",
                        }
                    )
                    recovery = self._recover_offline_transport(deadline, cancel)
                    wait_diagnostics["offline_recovery_status"] = "completed" if recovery.succeeded else "failed"
                    if not recovery.succeeded:
                        return MumuRuntimeResult.from_monotonic(
                            action,
                            recovery.status,
                            recovery.error_code,
                            started_at,
                            changed=True,
                            diagnostics=_safe_wait_diagnostics(
                                last_probe_result,
                                wait_diagnostics,
                            ),
                        )
                    offline_since = None
                    connect_established = False
                    next_controlled_connect_at = 0.0
                    continue
            else:
                offline_since = None

            wait_sec = min(_POLL_INTERVAL, deadline.remaining_seconds)
            if cancel is not None:
                cancelled = cancel.wait(timeout_seconds=wait_sec)
                if cancelled:
                    return MumuRuntimeResult.from_monotonic(
                        action,
                        MumuRuntimeStatus.CANCELLED,
                        MumuRuntimeErrorCode.CANCELLED,
                        started_at,
                        changed=changed,
                        diagnostics=_safe_wait_diagnostics(last_probe_result, wait_diagnostics),
                    )
            else:
                time.sleep(wait_sec)

        return MumuRuntimeResult.from_monotonic(
            action,
            MumuRuntimeStatus.TIMEOUT,
            MumuRuntimeErrorCode.START_TIMEOUT,
            started_at,
            changed=changed,
            diagnostics=_safe_wait_diagnostics(last_probe_result, wait_diagnostics),
        )

    def _wait_stopped(
        self, started_at: float, deadline: Deadline, cancel: CancellationToken | None
    ) -> MumuRuntimeResult:
        """轮询直到端口关闭或设备消失。"""
        last_probe_result: ProbeResult | None = None
        while not deadline.expired:
            if cancel is not None and cancel.is_cancelled:
                return MumuRuntimeResult.from_monotonic(
                    MumuAction.STOP,
                    MumuRuntimeStatus.CANCELLED,
                    MumuRuntimeErrorCode.CANCELLED,
                    started_at,
                    changed=True,
                    diagnostics=_safe_wait_diagnostics(last_probe_result, {}),
                )

            probe = self._create_probe()
            result = probe.probe(self._adb_host, self._adb_port, self._adb_serial, deadline, cancel)
            last_probe_result = result

            # 停止确认只接受 PORT_CLOSED。DEVICE_NOT_FOUND 不构成已停止的证据：
            # 执行 shutdown 后若宿主 ADB server 恰好为空，会立刻误判成功返回，
            # 而 VM 进程其实还在。只认 PORT_CLOSED 时这种情况会诚实地等到
            # STOP_TIMEOUT，而不是谎报 success。
            if result.error_code == ProbeErrorCode.PORT_CLOSED:
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
                        diagnostics=_safe_wait_diagnostics(last_probe_result, {}),
                    )
            else:
                time.sleep(wait_sec)

        return MumuRuntimeResult.from_monotonic(
            MumuAction.STOP,
            MumuRuntimeStatus.TIMEOUT,
            MumuRuntimeErrorCode.STOP_TIMEOUT,
            started_at,
            changed=True,
            diagnostics=_safe_wait_diagnostics(last_probe_result, {}),
        )
