"""ADB 命令客户端。

通过 ProcessSupervisor 执行 ADB 命令，自动管理临时输出文件和目录。
每条命令创建一个独立的 ProcessSupervisor 上下文，确保资源隔离。
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
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
_DIAG_MAX = 1_024  # diagnostics 摘要最大字符数


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

    return data.decode("utf-8", errors="replace"), exceeded


@dataclass(frozen=True)
class AdbClientConfig:
    """ADB 客户端配置。"""

    executable: Path
    base_arguments: tuple[str, ...] = ()
    working_directory: Path | None = None


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
                    proc_result = supervisor.run(spec, deadline, cancel)

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
        except OSError:
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
