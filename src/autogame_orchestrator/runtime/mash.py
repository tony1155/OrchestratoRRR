"""mash-cli（FGO headless 自动化）的有界运行时适配器。

与 MAA 适配器共享同一进程监督模型，差异在于 mash-cli 提供了显式的
优雅停止入口（``mash-cli cancel``，文件信号 + 轮询），因此取消与
超时路径先请求优雅停止，超过宽限窗口才升级为 Job Object 终止。
"""

# mypy: disable-error-code=arg-type
from __future__ import annotations

import json
import locale
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from autogame_orchestrator.config_model import MashConfig, MashRepeatMode
from autogame_orchestrator.models import JsonValue
from autogame_orchestrator.process import CancellationToken, Deadline, ProcessSpec, ProcessSupervisor
from autogame_orchestrator.process import launcher as process_launcher
from autogame_orchestrator.process.errors import ProcessExecutionErrorCode, TerminationReason
from autogame_orchestrator.process.result import ProcessResult
from autogame_orchestrator.runtime.mash_models import MashErrorCode, MashRunResult, MashRunStatus

if TYPE_CHECKING:
    pass

DEFAULT_POLL_INTERVAL_SECONDS = 0.05
MAX_STDOUT_BYTES = 64 * 1024
MAX_STDERR_BYTES = 64 * 1024
MAX_OUTPUT_EXCERPT_CHARS = 8 * 1024

# mash-cli 退出码契约（docs/02-mash-cli-spec.md）。
MASH_EXIT_FINISHED = 0
MASH_EXIT_FAILED = 1
MASH_EXIT_CANCELLED = 2
MASH_EXIT_WATCHDOG_TIMEOUT = 3

# mash-cli watchdog 触发后的内部固定宽限（cancel → 120s → 强退）。
WATCHDOG_GRACE_SECONDS = 120
# timeout 预算低于该值不注入默认 watchdog：watchdog 必须 ≥ 内部宽限 + 余量，
# 否则 mash-cli 会在阶段 deadline 之前就自行动手。
MIN_WATCHDOG_TIMEOUT_SECONDS = 300


def build_run_arguments(config: MashConfig) -> tuple[str, ...]:
    """由配置生成 ``mash-cli run`` 参数。"""
    arguments: list[str] = [
        "run",
        "--project",
        config.project_id,
        "--server",
        config.server.value,
        "--result-file",
        config.result_file,
        "--events",
        config.events,
    ]
    if config.adb_serial:
        arguments.extend(("--device", config.adb_serial))
    if config.repeat_mode == MashRepeatMode.INFINITE:
        arguments.extend(("--repeat", "infinite"))
    elif config.repeat_mode == MashRepeatMode.COUNT:
        arguments.extend(("--repeat", f"count:{config.repeat_count}"))
    # 审计 P1-1（方案 3）：超时路径让 mash-cli 的内部 watchdog 先行——它会
    # 优雅取消、留出固定宽限、写齐结果文件、清理 current.json，并以契约
    # 退出码 3（timeout）上报（含引擎响应取消优雅收尾的主流形态，见
    # mash-cli 侧 final_outcome 的 watchdog 映射）；外部硬杀只剩兜底作用。
    # 预算不足（timeout_seconds < 300，恰好 300 会注入 180）或用户已显式
    # 配置 --watchdog 时不注入（mash-cli 取首个出现的 --watchdog）。
    if "--watchdog" not in config.extra_arguments and config.timeout_seconds >= MIN_WATCHDOG_TIMEOUT_SECONDS:
        arguments.extend(("--watchdog", str(config.timeout_seconds - WATCHDOG_GRACE_SECONDS)))
    arguments.extend(config.extra_arguments)
    return tuple(arguments)


def _build_environment(config: MashConfig) -> dict[str, str]:
    environment = dict(config.environment_overrides)
    if config.resource_dir and "MASH_RESOURCE_DIR" not in environment:
        environment["MASH_RESOURCE_DIR"] = config.resource_dir
    return environment


def _map_process_result(
    process_result: ProcessResult,
    *,
    cancelled: bool,
    deadline_expired: bool,
    graceful_stop_requested: bool,
) -> tuple[MashRunStatus, MashErrorCode, bool]:
    """将进程结果按 mash-cli 退出码契约映射为稳定结果。

    ``STOPPED`` 只出现在适配器主动升级硬终止之后；此时若此前已请求
    优雅停止但宽限窗口耗尽，标记 ``GRACEFUL_STOP_FAILED``（进程树仍
    被本阶段清理，因此 ``owned_process_cleaned`` 为真）。
    """
    reason = process_result.termination_reason
    exit_code = process_result.exit_code
    if reason == TerminationReason.NORMAL_EXIT:
        if exit_code == MASH_EXIT_FINISHED:
            return MashRunStatus.COMPLETED, MashErrorCode.OK, True
        if exit_code == MASH_EXIT_CANCELLED:
            return MashRunStatus.CANCELLED, MashErrorCode.CANCELLED, True
        if exit_code == MASH_EXIT_WATCHDOG_TIMEOUT:
            return MashRunStatus.TIMEOUT, MashErrorCode.PROCESS_TIMEOUT, True
        return MashRunStatus.FAILED, MashErrorCode.PROCESS_EXIT_NONZERO, True
    if reason == TerminationReason.NONZERO_EXIT:
        if exit_code == MASH_EXIT_CANCELLED:
            return MashRunStatus.CANCELLED, MashErrorCode.CANCELLED, True
        if exit_code == MASH_EXIT_WATCHDOG_TIMEOUT:
            return MashRunStatus.TIMEOUT, MashErrorCode.PROCESS_TIMEOUT, True
        return MashRunStatus.FAILED, MashErrorCode.PROCESS_EXIT_NONZERO, True
    if reason == TerminationReason.STOPPED:
        if cancelled:
            code = MashErrorCode.GRACEFUL_STOP_FAILED if graceful_stop_requested else MashErrorCode.CANCELLED
            return MashRunStatus.CANCELLED, code, True
        if deadline_expired:
            code = MashErrorCode.GRACEFUL_STOP_FAILED if graceful_stop_requested else MashErrorCode.PROCESS_TIMEOUT
            return MashRunStatus.TIMEOUT, code, True
        return MashRunStatus.FAILED, MashErrorCode.INTERNAL_ERROR, True
    if reason == TerminationReason.CANCELLED:
        return MashRunStatus.CANCELLED, MashErrorCode.CANCELLED, True
    if reason == TerminationReason.TIMEOUT:
        return MashRunStatus.TIMEOUT, MashErrorCode.PROCESS_TIMEOUT, True
    if reason == TerminationReason.START_FAILED:
        return MashRunStatus.FAILED, MashErrorCode.PROCESS_START_FAILED, True
    if reason == TerminationReason.WAIT_FAILED:
        return MashRunStatus.FAILED, MashErrorCode.WAIT_FAILED, False
    if reason == TerminationReason.TERMINATION_FAILED:
        if cancelled:
            return MashRunStatus.CANCELLED, MashErrorCode.CLEANUP_FAILED, False
        if deadline_expired:
            return MashRunStatus.TIMEOUT, MashErrorCode.CLEANUP_FAILED, False
        return MashRunStatus.FAILED, MashErrorCode.CLEANUP_FAILED, False
    return MashRunStatus.FAILED, MashErrorCode.INTERNAL_ERROR, False


def _read_output_excerpt(path: Path, *, byte_limit: int) -> tuple[str, bool, bool]:
    """安全读取有限输出，不将读取或解码错误向外传播。"""
    try:
        raw = path.open("rb").read(byte_limit + 1)
    except FileNotFoundError:
        return "", False, False
    except OSError:
        return "", False, True
    truncated = len(raw) > byte_limit
    raw = raw[:byte_limit]
    try:
        if raw.startswith(b"\xef\xbb\xbf"):
            text = raw.decode("utf-8-sig")
        elif raw.startswith(b"\xff\xfe") or b"\x00" in raw:
            text = raw.decode("utf-16")
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode(locale.getpreferredencoding(False), errors="strict")
    except (LookupError, UnicodeDecodeError):
        text = raw.decode("utf-8", errors="replace")
    if len(text) > MAX_OUTPUT_EXCERPT_CHARS:
        return text[:MAX_OUTPUT_EXCERPT_CHARS], True, False
    return text, truncated, False


def _stable_process_diagnostics(process_result: ProcessResult) -> dict[str, str | int]:
    """只保留不会泄漏本机路径的稳定进程诊断字段。"""
    diagnostics: dict[str, str | int] = {"process_error_code": process_result.error_code.value}
    if process_result.error_code == ProcessExecutionErrorCode.START_FAILED:
        for key in ("launch_error_code", "win32_code"):
            value = process_result.diagnostics.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                diagnostics[key] = value
    return diagnostics


def _read_result_file(path: Path) -> dict[str, str | int | None]:
    """读取 mash-cli 的 run-result JSON，只提取稳定内容字段。"""
    payload: dict[str, str | int | None] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return payload
    if not isinstance(raw, dict):
        return payload
    for key in ("runId", "outcome", "message"):
        value = raw.get(key)
        if isinstance(value, str):
            payload[key] = value
    for key in ("completedRuns",):
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            payload[key] = value
    return payload


class MashAdapter:
    """驱动一次 ``mash-cli run`` 的适配器；取消路径先优雅后硬终止。"""

    def __init__(self, config: MashConfig, *, poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("轮询间隔必须为正数")
        self._config = config
        self._poll_interval_seconds = poll_interval_seconds

    def run(self, deadline: Deadline | None = None, cancel: CancellationToken | None = None) -> MashRunResult:
        started_at = datetime.now(UTC)
        started_mono = time.monotonic()

        def result(status: MashRunStatus, code: MashErrorCode, **kwargs: object) -> MashRunResult:
            return MashRunResult.from_monotonic(
                status=status, error_code=code, started_at=started_at, started_at_monotonic=started_mono, **kwargs
            )

        if cancel is not None and cancel.is_cancelled:
            return result(
                MashRunStatus.CANCELLED,
                MashErrorCode.CANCELLED,
                pid=None,
                termination_reason=TerminationReason.CANCELLED,
            )
        if self._config.validate():
            return result(MashRunStatus.FAILED, MashErrorCode.INVALID_CONFIGURATION, pid=None)
        executable = Path(self._config.executable)
        working_directory = Path(self._config.working_directory)
        if not executable.is_file():
            return result(MashRunStatus.FAILED, MashErrorCode.EXECUTABLE_NOT_FOUND, pid=None)
        if not working_directory.is_dir():
            return result(MashRunStatus.FAILED, MashErrorCode.WORKING_DIRECTORY_NOT_FOUND, pid=None)
        config_deadline = Deadline.after(float(self._config.timeout_seconds))
        # 审计 P1-2：固定路径的 result_file 在硬杀场景下来不及被覆盖，
        # launch 前先删除，避免把上一次的 runId/outcome 读进本阶段诊断。
        try:
            Path(self._config.result_file).unlink(missing_ok=True)
        except OSError:
            pass
        if deadline is not None and deadline.expired:
            return result(
                MashRunStatus.TIMEOUT,
                MashErrorCode.PROCESS_TIMEOUT,
                pid=None,
                termination_reason=TerminationReason.TIMEOUT,
            )
        effective_deadline = (
            config_deadline
            if deadline is None
            else Deadline.after(min(config_deadline.remaining_seconds, deadline.remaining_seconds))
        )
        try:
            with tempfile.TemporaryDirectory(prefix="orchestratorrr-mash-") as temporary_directory:
                stdout_path = Path(temporary_directory) / "stdout.bin"
                stderr_path = Path(temporary_directory) / "stderr.bin"
                spec = ProcessSpec(
                    name="mash_cli_run",
                    executable=executable,
                    arguments=(*self._config.launcher_arguments, *build_run_arguments(self._config)),
                    working_directory=working_directory,
                    environment_overrides=_build_environment(self._config),
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                )
                supervisor = ProcessSupervisor(
                    poll_interval_seconds=self._poll_interval_seconds,
                    kill_confirmation_seconds=float(self._config.stop_timeout_seconds),
                )
                process_result: ProcessResult | None
                graceful_stop_requested = False
                close_failed = False
                try:
                    process_result, graceful_stop_requested = self._launch_and_watch(
                        supervisor,
                        spec,
                        effective_deadline,
                        cancel,
                    )
                finally:
                    try:
                        supervisor.close()
                    except Exception:
                        close_failed = True
                stdout, stdout_truncated, stdout_failed = _read_output_excerpt(stdout_path, byte_limit=MAX_STDOUT_BYTES)
                stderr, stderr_truncated, stderr_failed = _read_output_excerpt(stderr_path, byte_limit=MAX_STDERR_BYTES)
                diagnostics: dict[str, JsonValue] = {
                    "stdout_read_failed": stdout_failed,
                    "stderr_read_failed": stderr_failed,
                    "graceful_stop_requested": graceful_stop_requested,
                }
                if process_result is not None:
                    diagnostics.update(_stable_process_diagnostics(process_result))
                for key, value in _read_result_file(Path(self._config.result_file)).items():
                    diagnostics[key] = value
                if close_failed:
                    status = MashRunStatus.FAILED
                    if process_result is not None and process_result.termination_reason == TerminationReason.TIMEOUT:
                        status = MashRunStatus.TIMEOUT
                    if process_result is not None and process_result.termination_reason == TerminationReason.CANCELLED:
                        status = MashRunStatus.CANCELLED
                    return result(
                        status,
                        MashErrorCode.CLEANUP_FAILED,
                        pid=process_result.pid if process_result else None,
                        exit_code=process_result.exit_code if process_result else None,
                        termination_reason=TerminationReason.TERMINATION_FAILED,
                        owned_process_cleaned=False,
                        stdout_excerpt=stdout,
                        stderr_excerpt=stderr,
                        stdout_truncated=stdout_truncated,
                        stderr_truncated=stderr_truncated,
                        diagnostics=diagnostics,
                    )
                if process_result is None:
                    return result(
                        MashRunStatus.FAILED, MashErrorCode.INTERNAL_ERROR, pid=None, owned_process_cleaned=False
                    )
                status, code, cleaned = _map_process_result(
                    process_result,
                    cancelled=cancel is not None and cancel.is_cancelled,
                    deadline_expired=effective_deadline.expired,
                    graceful_stop_requested=graceful_stop_requested,
                )
                return result(
                    status,
                    code,
                    pid=process_result.pid,
                    exit_code=process_result.exit_code,
                    termination_reason=process_result.termination_reason,
                    owned_process_cleaned=cleaned,
                    stdout_excerpt=stdout,
                    stderr_excerpt=stderr,
                    stdout_truncated=stdout_truncated,
                    stderr_truncated=stderr_truncated,
                    diagnostics=diagnostics,
                )
        except KeyboardInterrupt:
            raise
        except OSError:
            return result(MashRunStatus.FAILED, MashErrorCode.PROCESS_START_FAILED, pid=None)

    def _launch_and_watch(
        self,
        supervisor: ProcessSupervisor,
        spec: ProcessSpec,
        effective_deadline: Deadline,
        cancel: CancellationToken | None,
    ) -> tuple[ProcessResult, bool]:
        """launch → 自有轮询循环 → （必要时）优雅停止 → supervisor.stop 收尾。

        返回 ``(process_result, graceful_stop_requested)``。取消与超时路径
        先运行 ``mash-cli cancel``（有界），再给 ``stop_timeout_seconds``
        宽限；宽限耗尽才由 ``supervisor.stop`` 硬终止 Job。
        """
        try:
            managed = supervisor.launch(spec)
        except process_launcher.LaunchError as exc:
            return (
                ProcessResult.start_failed(
                    name=spec.name,
                    error_code=ProcessExecutionErrorCode.START_FAILED,
                    diagnostics={"detail": str(exc), "launch_error_code": exc.error_code.value},
                ),
                False,
            )
        while True:
            if managed.poll() is not None:
                return supervisor.stop(managed), False
            cancelled_now = cancel is not None and cancel.is_cancelled
            if cancelled_now or effective_deadline.expired:
                self._request_graceful_stop(supervisor, effective_deadline)
                # 审计二轮 P2-5N：deadline 已耗尽时的下限预算不能太小——
                # Windows 上子进程 spawn 在负载下可超过 1s，真实 mash-cli
                # 的取消响应（300ms 轮询 + 战斗检查点）也需要 ≥1s。这两个
                # 下限只作用于“watchdog 未兜住”的兑底路径，允许小幅越过
                # 已到期的 deadline。
                grace_seconds = min(
                    float(self._config.stop_timeout_seconds),
                    max(effective_deadline.remaining_seconds, 2.0),
                )
                grace_deadline = Deadline.after(grace_seconds)
                while managed.poll() is None and not grace_deadline.expired:
                    time.sleep(self._poll_interval_seconds)
                return supervisor.stop(managed), True
            time.sleep(self._poll_interval_seconds)

    def _request_graceful_stop(self, supervisor: ProcessSupervisor, effective_deadline: Deadline) -> None:
        """运行一次有界 ``mash-cli cancel``；结果尽力而为，不抛出。"""
        executable = Path(self._config.executable)
        working_directory = Path(self._config.working_directory)
        spec = ProcessSpec(
            name="mash_cli_cancel",
            executable=executable,
            arguments=(*self._config.launcher_arguments, "cancel", "--wait", str(self._config.stop_timeout_seconds)),
            working_directory=working_directory,
            environment_overrides=_build_environment(self._config),
        )
        # 见上方 P2-5N 注释：cancel 子进程自身的预算下限同步放宽到 3s。
        cancel_budget = min(
            float(self._config.stop_timeout_seconds) + 5.0, max(effective_deadline.remaining_seconds, 3.0)
        )
        try:
            supervisor.run(spec, Deadline.after(cancel_budget))
        except Exception:
            return
