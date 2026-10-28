"""Scoped Android app teardown for STOP_FGO.

等价于 ``adb.exe -s <expected serial> shell am force-stop <exact package>``：
serial 来自 ``config.mumu.adb_serial``（仅 127.0.0.1:port），package 来自
``[fgo] package_name``（严格白名单正则）。始终使用 argument array，不做任何
shell 字符串拼接；deadline 有界、cancellation 感知。force-stop 成功后可选做
一次有界的 ``pidof`` 验证；验证不确定不判失败，仍然输出已执行的事实。
"""

import time
from datetime import UTC, datetime
from pathlib import Path

from autogame_orchestrator.config_model import _ANDROID_PACKAGE_RE
from autogame_orchestrator.process import CancellationToken, Deadline, ProcessSpec, ProcessSupervisor
from autogame_orchestrator.process.errors import TerminationReason
from autogame_orchestrator.runtime.fgo_models import (
    FgoAppStopErrorCode as Code,
)
from autogame_orchestrator.runtime.fgo_models import (
    FgoAppStopResult,
    FgoStopVerification,
)
from autogame_orchestrator.runtime.fgo_models import (
    FgoAppStopStatus as Status,
)


def _parse_local_serial(serial: str) -> tuple[str, int]:
    """仅接受 ``127.0.0.1:<1-65535>``；与 runtime_bindings 同规则，避免反向依赖。"""
    if not isinstance(serial, str) or serial.count(":") != 1:
        raise ValueError("Invalid ADB serial")
    host, raw_port = serial.split(":", 1)
    if host != "127.0.0.1" or not raw_port.isascii() or not raw_port.isdecimal():
        raise ValueError("Invalid ADB serial")
    port = int(raw_port)
    if not 1 <= port <= 65535:
        raise ValueError("Invalid ADB serial")
    return host, port


class FgoAppStopper:
    """窄职责 Android 应用退出；不接触 Windows 进程名，不做全局操作。"""

    def __init__(
        self,
        *,
        adb_executable: Path,
        adb_serial: str,
        package_name: str,
        stop_timeout_seconds: float = 20.0,
    ) -> None:
        _parse_local_serial(adb_serial)
        if not isinstance(package_name, str) or not _ANDROID_PACKAGE_RE.fullmatch(package_name):
            raise ValueError("Invalid Android package name")
        if not adb_executable.is_absolute():
            raise ValueError("adb executable must be absolute")
        self._adb_executable = adb_executable
        self._adb_serial = adb_serial
        self._package_name = package_name
        self._stop_timeout = float(stop_timeout_seconds)

    def stop(
        self,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
    ) -> FgoAppStopResult:
        started, mono = datetime.now(UTC), time.monotonic()

        def result(
            status: Status,
            code: Code,
            verification: FgoStopVerification = FgoStopVerification.SKIPPED,
        ) -> FgoAppStopResult:
            return FgoAppStopResult(
                status,
                code,
                started,
                datetime.now(UTC),
                max(0, int((time.monotonic() - mono) * 1000)),
                verification,
            )

        def control_status(effective: Deadline | None) -> Status | None:
            if cancel is not None and cancel.is_cancelled:
                return Status.CANCELLED
            if effective is not None and effective.expired:
                return Status.TIMEOUT
            return None

        effective = Deadline.after(
            min(self._stop_timeout, deadline.remaining_seconds if deadline else float("inf"))
        )
        control = control_status(deadline) or control_status(effective)
        if control is Status.CANCELLED:
            return result(Status.CANCELLED, Code.CANCELLED)
        if control is Status.TIMEOUT:
            return result(Status.TIMEOUT, Code.TIMEOUT)
        try:
            outcome = self._force_stop(effective, cancel)
        except Exception:
            return result(Status.FAILED, Code.INTERNAL_ERROR)
        if outcome != (Status.STOPPED, Code.OK):
            return result(outcome[0], outcome[1])
        verification = self._verify_stopped(effective, cancel)
        if verification is FgoStopVerification.FAILED:
            return result(Status.FAILED, Code.VERIFY_FAILED, FgoStopVerification.FAILED)
        return result(Status.STOPPED, Code.OK, verification)

    def _force_stop(
        self, effective: Deadline, cancel: CancellationToken | None
    ) -> tuple[Status, Code]:
        spec = ProcessSpec(
            name="adb-force-stop",
            executable=self._adb_executable,
            arguments=("-s", self._adb_serial, "shell", "am", "force-stop", self._package_name),
            working_directory=None,
            stdout_path=None,
            stderr_path=None,
            descendants_survive_close=False,
        )
        with ProcessSupervisor(kill_confirmation_seconds=min(self._stop_timeout, 10.0)) as supervisor:
            process_result = supervisor.run(spec, effective, cancel)
        reason = process_result.termination_reason
        if reason is TerminationReason.NORMAL_EXIT and process_result.exit_code == 0:
            return (Status.STOPPED, Code.OK)
        if reason in (TerminationReason.NORMAL_EXIT, TerminationReason.NONZERO_EXIT):
            return (Status.FAILED, Code.ADB_COMMAND_FAILED)
        if reason is TerminationReason.START_FAILED:
            return (Status.FAILED, Code.ADB_START_FAILED)
        if reason is TerminationReason.TIMEOUT:
            return (Status.TIMEOUT, Code.TIMEOUT)
        if reason is TerminationReason.CANCELLED:
            return (Status.CANCELLED, Code.CANCELLED)
        return (Status.FAILED, Code.INTERNAL_ERROR)

    def _verify_stopped(self, effective: Deadline, cancel: CancellationToken | None) -> FgoStopVerification:
        """``adb -s <serial> shell pidof <package>``：无输出/退出1 => 已停止。"""
        import tempfile

        for attempt in range(2):
            with tempfile.TemporaryDirectory(prefix="orr-fgo-verify-") as scratch:
                output_path = Path(scratch) / "pidof-output.txt"
                spec = ProcessSpec(
                    name="adb-pidof",
                    executable=self._adb_executable,
                    arguments=("-s", self._adb_serial, "shell", "pidof", self._package_name),
                    working_directory=None,
                    stdout_path=output_path,
                    stderr_path=None,
                    descendants_survive_close=False,
                )
                try:
                    with ProcessSupervisor(kill_confirmation_seconds=min(self._stop_timeout, 10.0)) as supervisor:
                        process_result = supervisor.run(spec, effective, cancel)
                except Exception:
                    return FgoStopVerification.INCONCLUSIVE
                reason = process_result.termination_reason
                if reason is TerminationReason.NORMAL_EXIT:
                    exit_code = process_result.exit_code or 0
                elif reason is TerminationReason.NONZERO_EXIT:
                    exit_code = process_result.exit_code if process_result.exit_code is not None else -1
                else:
                    return FgoStopVerification.INCONCLUSIVE
                try:
                    output = output_path.read_text(encoding="utf-8", errors="replace").strip()
                except OSError:
                    return FgoStopVerification.INCONCLUSIVE
                if not output and exit_code in (0, 1):
                    # pidof 约定：无匹配进程 => 空输出 + 退出 0/1。
                    return FgoStopVerification.VERIFIED
                if output and exit_code == 0:
                    # 设备侧报告仍有进程；短暂等待后复查一次，避开退出竞态。
                    if attempt == 0:
                        time.sleep(0.5)
                        continue
                    return FgoStopVerification.FAILED
                return FgoStopVerification.INCONCLUSIVE
        return FgoStopVerification.INCONCLUSIVE
