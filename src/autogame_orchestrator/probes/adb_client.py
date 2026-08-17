"""ADB 命令客户端。

通过 ProcessSupervisor 执行 ADB 命令，自动管理临时输出文件和目录。
每条命令创建一个独立的 ProcessSupervisor 上下文，确保资源隔离。
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

    # ── 公开方法 ──────────────────────────────────────────────

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
