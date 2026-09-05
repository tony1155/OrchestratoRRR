"""ADB 命令客户端。

通过 ProcessSupervisor 执行 ADB 命令，自动管理临时输出文件和目录。
每条命令创建一个独立的 ProcessSupervisor 上下文，确保资源隔离。

adb server（daemon，监听 5037）必须活过单条命令：设备表——包括 ``adb connect``
注册的 TCP 设备——完全保存在该 daemon 的内存里。若 daemon 随命令一起被 Job 回收：

1. ``adb connect`` 写入的 TCP 设备记录随之丢失，下一条 ``adb devices`` 冷启动出空
   daemon，探测得到 ``DEVICE_NOT_FOUND`` / ``step=select_device``；
2. 每条命令都要重新冷启动 daemon（实测 0.06s -> 2.08s），逼近甚至超出单命令预算，
   表现为 ``ADB_TIMEOUT``。

因此 :meth:`AdbClient.ensure_server` 在首条命令前显式拉起一次常驻 daemon。它使用
``descendants_survive_close=True`` 且**不**重定向 stdout/stderr：后者会使 ``launch()``
传 ``bInheritHandles=TRUE``，而那会让存活的 daemon 连带继承编排器自己的 stdout 句柄，
下游读取端永远收不到 EOF。普通命令仍维持默认的 ``KILL_ON_JOB_CLOSE``，
不会泄漏句柄也不会留下游离进程。
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from autogame_orchestrator.probes.adb_parser import AdbParseError, parse_adb_devices
from autogame_orchestrator.probes.models import (
    AdbDevicesResult,
    ProbeErrorCode,
    ProbeResult,
    ProbeStatus,
)
from autogame_orchestrator.process import (
    CancellationToken,
    Deadline,
    ProcessSpec,
    ProcessSupervisor,
)
from autogame_orchestrator.process.errors import (
    TerminationReason,
)

_STDOUT_MAX = 1_048_576  # 1 MiB
_STDERR_MAX = 65_536  # 64 KiB
_LOCAL_ADB_HOST = "127.0.0.1"
_CONNECT_SUCCESS_ALREADY = "already connected to"
_CONNECT_SUCCESS = "connected to"
_CONNECT_FAILURE_MARKERS = ("not connected to", "failed", "cannot", "refused", "unable")
_DISCONNECT_SUCCESS = "disconnected"
_DISCONNECT_FAILURE_MARKERS = ("failed", "cannot", "refused", "unable", "error")
_DIAG_MAX = 1_024  # diagnostics 摘要最大字符数
_DEFAULT_COMMAND_TIMEOUT_SECONDS = 5.0


def _read_limited_text(path: Path, limit: int) -> tuple[str, bool]:
    """有界读取文本文件。

    以二进制方式打开，读取 limit+1 字节，判断是否超限。
    返回 (解码后文本, 是否超限)。
    """
    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError:
        raise

    exceeded = len(data) > limit
    if exceeded:
        data = data[:limit]

    return data.decode("utf-8"), exceeded


@dataclass(frozen=True)
class AdbClientConfig:
    """ADB 客户端配置。"""

    executable: Path
    base_arguments: tuple[str, ...] = ()
    working_directory: Path | None = None
    command_timeout_seconds: float = _DEFAULT_COMMAND_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        timeout = self.command_timeout_seconds
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not isfinite(timeout) or timeout <= 0:
            msg = f"command_timeout_seconds 必须是有限正数，收到 {timeout!r}"
            raise ValueError(msg)


class AdbClient:
    """通过 ProcessSupervisor 执行 ADB 命令。

    每条命令使用独立的 ProcessSupervisor（上下文管理器），
    自动管理临时输出目录和文件。
    """

    def __init__(self, config: AdbClientConfig) -> None:
        self._config = config
        self._server_ensured = False

    # ── 公开方法 ──────────────────────────────────────────────

    def ensure_server(self, deadline: Deadline, cancel: CancellationToken | None = None) -> ProbeResult:
        """确保常驻 adb server 已在运行，且不会被本进程的 Job 回收。

        ``adb start-server`` 属于引信型命令：前台进程立即退出，其 fork 出的 daemon
        必须长期存活，否则每条后续命令都会自行冷启动一个空 daemon，丢掉
        ``adb connect`` 注册的 TCP 设备（见模块 docstring）。

        与其他命令的两点关键差异：

        1. ``descendants_survive_close=True``，让 daemon 活过本命令；
        2. **不**重定向 stdout/stderr。重定向会使 ``launch()`` 传
           ``bInheritHandles=TRUE``，存活的 daemon 会连带继承编排器自己的 stdout
           句柄，使下游读取端永远收不到 EOF（实测会挂住管道）。因此这里放弃输出捕获，
           只依据 ``termination_reason`` 判定结果。

        幂等：同一 client 实例只实际执行一次。失败不抛出，由后续命令自行报错。
        """
        started_at = time.monotonic()
        if self._server_ensured:
            return ProbeResult.from_monotonic(
                "adb_start_server", ProbeStatus.READY, ProbeErrorCode.OK, started_at
            )

        if not self._config.executable.is_file():
            return ProbeResult.from_monotonic(
                "adb_start_server",
                ProbeStatus.FAILED,
                ProbeErrorCode.ADB_NOT_FOUND,
                started_at,
            )
        if cancel is not None and cancel.is_cancelled:
            return ProbeResult.from_monotonic(
                "adb_start_server", ProbeStatus.FAILED, ProbeErrorCode.ADB_CANCELLED, started_at
            )
        if deadline.expired:
            return ProbeResult.from_monotonic(
                "adb_start_server", ProbeStatus.TIMEOUT, ProbeErrorCode.ADB_TIMEOUT, started_at
            )

        command_deadline = Deadline.at(started_at + deadline.clamp_timeout(self._config.command_timeout_seconds))
        spec = ProcessSpec(
            name="adb_start_server",
            executable=self._config.executable,
            arguments=(*self._config.base_arguments, "start-server"),
            working_directory=self._config.working_directory,
            descendants_survive_close=True,
        )

        try:
            with ProcessSupervisor() as supervisor:
                proc_result = supervisor.run(spec, command_deadline, cancel)
        except Exception:
            return ProbeResult.from_monotonic(
                "adb_start_server",
                ProbeStatus.FAILED,
                ProbeErrorCode.ADB_START_FAILED,
                started_at,
            )

        reason = proc_result.termination_reason
        if reason == TerminationReason.NORMAL_EXIT:
            self._server_ensured = True
            return ProbeResult.from_monotonic(
                "adb_start_server", ProbeStatus.READY, ProbeErrorCode.OK, started_at
            )
        if reason == TerminationReason.TIMEOUT:
            return ProbeResult.from_monotonic(
                "adb_start_server", ProbeStatus.TIMEOUT, ProbeErrorCode.ADB_TIMEOUT, started_at
            )
        if reason == TerminationReason.CANCELLED:
            return ProbeResult.from_monotonic(
                "adb_start_server", ProbeStatus.FAILED, ProbeErrorCode.ADB_CANCELLED, started_at
            )
        return ProbeResult.from_monotonic(
            "adb_start_server",
            ProbeStatus.FAILED,
            ProbeErrorCode.ADB_EXIT_NONZERO,
            started_at,
        )

    def version(self, deadline: Deadline, cancel: CancellationToken | None = None) -> ProbeResult:
        """执行 ``adb version``。"""
        return self._run_adb_command(
            probe_name="adb_version",
            arguments=("version",),
            deadline=deadline,
            cancel=cancel,
        )

    def list_devices(self, deadline: Deadline, cancel: CancellationToken | None = None) -> AdbDevicesResult:
        """执行 ``adb devices -l``，返回解析后的设备列表。"""
        started_at = time.monotonic()

        probe = self._run_adb_command(
            probe_name="adb_devices",
            arguments=("devices", "-l"),
            deadline=deadline,
            cancel=cancel,
        )

        if probe.status != ProbeStatus.READY:
            return AdbDevicesResult(probe=probe, devices=())

        # 从 diagnostics 中取原始输出
        raw = probe.diagnostics.get("stdout_trimmed", "")
        if not isinstance(raw, str):
            return AdbDevicesResult(
                probe=ProbeResult.from_monotonic(
                    "adb_devices", ProbeStatus.FAILED, ProbeErrorCode.ADB_OUTPUT_INVALID, started_at
                ),
                devices=(),
            )

        try:
            devices = parse_adb_devices(raw)
        except AdbParseError as exc:
            return AdbDevicesResult(
                probe=ProbeResult.from_monotonic(
                    "adb_devices",
                    ProbeStatus.FAILED,
                    exc.error_code,
                    started_at,
                    {"parse_error": str(exc)},
                ),
                devices=(),
            )

        return AdbDevicesResult(probe=probe, devices=devices)

    def get_state(self, serial: str, deadline: Deadline, cancel: CancellationToken | None = None) -> ProbeResult:
        """执行 ``adb -s <serial> get-state``。"""
        return self._run_adb_command(
            probe_name="adb_get_state",
            arguments=("-s", serial, "get-state"),
            deadline=deadline,
            cancel=cancel,
        )

    def get_boot_completed(
        self, serial: str, deadline: Deadline, cancel: CancellationToken | None = None
    ) -> ProbeResult:
        """执行 ``adb -s <serial> shell getprop sys.boot_completed``。"""
        return self._run_adb_command(
            probe_name="adb_boot_completed",
            arguments=("-s", serial, "shell", "getprop", "sys.boot_completed"),
            deadline=deadline,
            cancel=cancel,
        )

    def connect(
        self,
        host: str,
        port: int,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        """Connect only to the configured local TCP ADB endpoint.

        The underlying command output is deliberately consumed here and never
        exposed through the returned diagnostics.
        """
        started_at = time.monotonic()
        if host != _LOCAL_ADB_HOST:
            return ProbeResult.from_monotonic(
                "adb_connect",
                ProbeStatus.FAILED,
                ProbeErrorCode.NON_LOCAL_ADDRESS_REJECTED,
                started_at,
            )
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
            return ProbeResult.from_monotonic(
                "adb_connect",
                ProbeStatus.FAILED,
                ProbeErrorCode.INVALID_CONFIGURATION,
                started_at,
            )
        if cancel is not None and cancel.is_cancelled:
            return ProbeResult.from_monotonic(
                "adb_connect",
                ProbeStatus.FAILED,
                ProbeErrorCode.ADB_CANCELLED,
                started_at,
            )
        if deadline.expired:
            return ProbeResult.from_monotonic(
                "adb_connect",
                ProbeStatus.TIMEOUT,
                ProbeErrorCode.ADB_TIMEOUT,
                started_at,
            )

        # connect 写入的 TCP 设备仅存于 daemon 内存，必须先保证 daemon 能活过本命令。
        self.ensure_server(deadline, cancel)

        probe = self._run_adb_command(
            probe_name="adb_connect",
            arguments=("connect", f"{host}:{port}"),
            deadline=deadline,
            cancel=cancel,
        )
        if probe.status != ProbeStatus.READY:
            return ProbeResult.from_monotonic(
                "adb_connect",
                probe.status,
                probe.error_code,
                started_at,
                {"connect_status": "failed"},
            )

        output = " ".join(
            value.casefold()
            for key in ("stdout_trimmed", "stderr_trimmed")
            if isinstance(value := probe.diagnostics.get(key), str)
        )
        if any(marker in output for marker in _CONNECT_FAILURE_MARKERS):
            return ProbeResult.from_monotonic(
                "adb_connect",
                ProbeStatus.FAILED,
                ProbeErrorCode.ADB_CONNECT_FAILED,
                started_at,
                {"connect_status": "failed"},
            )
        if _CONNECT_SUCCESS_ALREADY in output:
            return ProbeResult.from_monotonic(
                "adb_connect",
                ProbeStatus.READY,
                ProbeErrorCode.OK,
                started_at,
                {"connect_status": "already_connected"},
            )
        if _CONNECT_SUCCESS in output:
            return ProbeResult.from_monotonic(
                "adb_connect",
                ProbeStatus.READY,
                ProbeErrorCode.OK,
                started_at,
                {"connect_status": "connected"},
            )
        return ProbeResult.from_monotonic(
            "adb_connect",
            ProbeStatus.FAILED,
            ProbeErrorCode.ADB_CONNECT_FAILED,
            started_at,
            {"connect_status": "failed"},
        )

    def disconnect(
        self,
        host: str,
        port: int,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        """Disconnect exactly one configured local TCP ADB endpoint."""
        started_at = time.monotonic()
        if host != _LOCAL_ADB_HOST:
            return ProbeResult.from_monotonic(
                "adb_disconnect",
                ProbeStatus.FAILED,
                ProbeErrorCode.NON_LOCAL_ADDRESS_REJECTED,
                started_at,
                {"disconnect_status": "failed"},
            )
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
            return ProbeResult.from_monotonic(
                "adb_disconnect",
                ProbeStatus.FAILED,
                ProbeErrorCode.INVALID_CONFIGURATION,
                started_at,
                {"disconnect_status": "failed"},
            )
        if cancel is not None and cancel.is_cancelled:
            return ProbeResult.from_monotonic(
                "adb_disconnect",
                ProbeStatus.FAILED,
                ProbeErrorCode.ADB_CANCELLED,
                started_at,
                {"disconnect_status": "failed"},
            )
        if deadline.expired:
            return ProbeResult.from_monotonic(
                "adb_disconnect",
                ProbeStatus.TIMEOUT,
                ProbeErrorCode.ADB_TIMEOUT,
                started_at,
                {"disconnect_status": "failed"},
            )

        probe = self._run_adb_command(
            probe_name="adb_disconnect",
            arguments=("disconnect", f"{host}:{port}"),
            deadline=deadline,
            cancel=cancel,
        )
        if probe.status != ProbeStatus.READY:
            return ProbeResult.from_monotonic(
                "adb_disconnect",
                probe.status,
                probe.error_code,
                started_at,
                {"disconnect_status": "failed"},
            )

        output = " ".join(
            value.casefold()
            for key in ("stdout_trimmed", "stderr_trimmed")
            if isinstance(value := probe.diagnostics.get(key), str)
        )
        if any(marker in output for marker in _DISCONNECT_FAILURE_MARKERS) or _DISCONNECT_SUCCESS not in output:
            return ProbeResult.from_monotonic(
                "adb_disconnect",
                ProbeStatus.FAILED,
                ProbeErrorCode.ADB_DISCONNECT_FAILED,
                started_at,
                {"disconnect_status": "failed"},
            )
        return ProbeResult.from_monotonic(
            "adb_disconnect",
            ProbeStatus.READY,
            ProbeErrorCode.OK,
            started_at,
            {"disconnect_status": "disconnected"},
        )

    def recycle_local_endpoint(
        self,
        host: str,
        port: int,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        """Recycle one exact local transport without touching the global ADB server."""
        started_at = time.monotonic()
        disconnected = self.disconnect(host, port, deadline, cancel)
        disconnect_status = disconnected.diagnostics.get("disconnect_status", "failed")
        diagnostics: dict[str, str] = {
            "disconnect_status": disconnect_status if isinstance(disconnect_status, str) else "failed",
            "connect_status": "not_attempted",
        }
        if disconnected.error_code == ProbeErrorCode.ADB_CANCELLED:
            return ProbeResult.from_monotonic(
                "adb_endpoint_recycle",
                ProbeStatus.FAILED,
                ProbeErrorCode.ADB_CANCELLED,
                started_at,
                diagnostics,
            )
        if deadline.expired:
            return ProbeResult.from_monotonic(
                "adb_endpoint_recycle",
                ProbeStatus.TIMEOUT,
                ProbeErrorCode.ADB_TIMEOUT,
                started_at,
                diagnostics,
            )

        connected = self.connect(host, port, deadline, cancel)
        connect_status = connected.diagnostics.get("connect_status", "failed")
        diagnostics["connect_status"] = connect_status if isinstance(connect_status, str) else "failed"
        return ProbeResult.from_monotonic(
            "adb_endpoint_recycle",
            connected.status,
            connected.error_code,
            started_at,
            diagnostics,
        )

    # ── 内部 ──────────────────────────────────────────────────

    def _run_adb_command(
        self,
        probe_name: str,
        arguments: tuple[str, ...],
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> ProbeResult:
        """执行 ADB 命令并返回 ProbeResult。"""
        started_at = time.monotonic()
        command_deadline = Deadline.at(started_at + deadline.clamp_timeout(self._config.command_timeout_seconds))

        # 预检：可执行文件
        if not self._config.executable.is_file():
            return ProbeResult.from_monotonic(
                probe_name,
                ProbeStatus.FAILED,
                ProbeErrorCode.ADB_NOT_FOUND,
                started_at,
                {"executable": str(self._config.executable)},
            )

        try:
            with tempfile.TemporaryDirectory(prefix="adb-") as tmp_dir:
                td = Path(tmp_dir)
                stdout_path = td / "stdout.log"
                stderr_path = td / "stderr.log"

                args = (*self._config.base_arguments, *arguments)
                spec = ProcessSpec(
                    name=probe_name,
                    executable=self._config.executable,
                    arguments=args,
                    working_directory=self._config.working_directory,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                )

                with ProcessSupervisor() as supervisor:
                    proc_result = supervisor.run(spec, command_deadline, cancel)

                # 映射 ProcessResult → ProbeResult
                reason = proc_result.termination_reason
                if reason == TerminationReason.NORMAL_EXIT:
                    return self._read_output(probe_name, started_at, stdout_path, stderr_path)
                elif reason == TerminationReason.NONZERO_EXIT:
                    return self._read_output(
                        probe_name,
                        started_at,
                        stdout_path,
                        stderr_path,
                        fallback_status=ProbeStatus.FAILED,
                        fallback_code=ProbeErrorCode.ADB_EXIT_NONZERO,
                    )
                elif reason == TerminationReason.TIMEOUT:
                    return ProbeResult.from_monotonic(
                        probe_name, ProbeStatus.TIMEOUT, ProbeErrorCode.ADB_TIMEOUT, started_at
                    )
                elif reason == TerminationReason.CANCELLED:
                    return ProbeResult.from_monotonic(
                        probe_name, ProbeStatus.FAILED, ProbeErrorCode.ADB_CANCELLED, started_at
                    )
                elif reason == TerminationReason.START_FAILED:
                    return ProbeResult.from_monotonic(
                        probe_name,
                        ProbeStatus.FAILED,
                        ProbeErrorCode.ADB_START_FAILED,
                        started_at,
                        {"detail": str(proc_result.diagnostics.get("detail", ""))},
                    )
                else:
                    return ProbeResult.from_monotonic(
                        probe_name, ProbeStatus.FAILED, ProbeErrorCode.ADB_START_FAILED, started_at
                    )
        except Exception as exc:
            return ProbeResult.from_monotonic(
                probe_name,
                ProbeStatus.FAILED,
                ProbeErrorCode.ADB_START_FAILED,
                started_at,
                {"error": str(exc)},
            )

    def _read_output(
        self,
        probe_name: str,
        started_at: float,
        stdout_path: Path,
        stderr_path: Path,
        fallback_status: ProbeStatus | None = None,
        fallback_code: ProbeErrorCode | None = None,
    ) -> ProbeResult:
        """读取 stdout/stderr 文件并构造 ProbeResult。

        使用 ``_read_limited_text`` 有界读取，超限返回 ADB_OUTPUT_INVALID。
        """
        # stdout
        try:
            stdout_text, stdout_exceeded = _read_limited_text(stdout_path, _STDOUT_MAX)
        except (OSError, UnicodeDecodeError):
            if fallback_code:
                return ProbeResult.from_monotonic(
                    probe_name, fallback_status or ProbeStatus.FAILED, fallback_code, started_at
                )
            return ProbeResult.from_monotonic(
                probe_name, ProbeStatus.FAILED, ProbeErrorCode.ADB_OUTPUT_INVALID, started_at
            )

        if stdout_exceeded:
            return ProbeResult.from_monotonic(
                probe_name,
                ProbeStatus.FAILED,
                ProbeErrorCode.ADB_OUTPUT_INVALID,
                started_at,
                {"reason": f"stdout 超过 {_STDOUT_MAX} 字节上限"},
            )

        # stderr
        try:
            stderr_text, stderr_exceeded = _read_limited_text(stderr_path, _STDERR_MAX)
        except UnicodeDecodeError:
            return ProbeResult.from_monotonic(
                probe_name, ProbeStatus.FAILED, ProbeErrorCode.ADB_OUTPUT_INVALID, started_at
            )
        except OSError:
            stderr_text = ""
            stderr_exceeded = False

        if stderr_exceeded:
            return ProbeResult.from_monotonic(
                probe_name,
                ProbeStatus.FAILED,
                ProbeErrorCode.ADB_OUTPUT_INVALID,
                started_at,
                {"reason": f"stderr 超过 {_STDERR_MAX} 字节上限"},
            )

        # 构造 diagnostics 摘要
        diag: dict[str, str] = {
            "stdout_trimmed": stdout_text[:_DIAG_MAX] if len(stdout_text) > _DIAG_MAX else stdout_text,
            "stderr_trimmed": stderr_text[:_DIAG_MAX] if len(stderr_text) > _DIAG_MAX else stderr_text,
        }

        if fallback_code is None:
            return ProbeResult.from_monotonic(
                probe_name,
                ProbeStatus.READY,
                ProbeErrorCode.OK,
                started_at,
                diag,
            )

        return ProbeResult.from_monotonic(
            probe_name,
            fallback_status or ProbeStatus.FAILED,
            fallback_code,
            started_at,
            diag,
        )
