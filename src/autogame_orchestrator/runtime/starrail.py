"""StarRailCopilot 任务 Adapter。

管理由本次 Adapter 启动的 StarRailCopilot 进程树，
通过增量日志监控实现成功/失败完成判定。
"""

from __future__ import annotations

import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from autogame_orchestrator.config_model import StarRailConfig
from autogame_orchestrator.process import (
    CancellationToken,
    Deadline,
    ManagedProcess,
    ProcessResult,
    ProcessSpec,
    ProcessSupervisor,
)
from autogame_orchestrator.process.errors import TerminationReason
from autogame_orchestrator.runtime.starrail_log import (
    MAX_LOG_READ_BYTES,
    capture_log_cursor,
    match_starrail_keyword,
    read_log_update,
    resolve_starrail_log_path,
)
from autogame_orchestrator.runtime.starrail_models import (
    MAX_OUTPUT_EXCERPT_CHARS,
    StarRailCompletionMode,
    StarRailErrorCode,
    StarRailRunResult,
    StarRailRunStatus,
)

DEFAULT_POLL_INTERVAL_SECONDS = 0.05
MAX_STDOUT_BYTES = 64 * 1024
MAX_STDERR_BYTES = 64 * 1024


class StarRailAdapter:
    """StarRailCopilot 任务 Adapter。

    启动受管进程，监控增量日志，通过关键词判定完成状态。
    """

    def __init__(self, config: StarRailConfig, *, poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS) -> None:
        if poll_interval_seconds <= 0:
            msg = f"poll_interval_seconds 必须 > 0，收到 {poll_interval_seconds}"
            raise ValueError(msg)
        self._config = config
        self._poll_interval = poll_interval_seconds

    def run(self, deadline: Deadline | None = None, cancel: CancellationToken | None = None) -> StarRailRunResult:
        started_at = datetime.now(UTC)
        started_at_mono = time.monotonic()

        if cancel is not None and cancel.is_cancelled:
            return StarRailRunResult.from_monotonic(
                status=StarRailRunStatus.CANCELLED,
                error_code=StarRailErrorCode.CANCELLED,
                completion_mode=StarRailCompletionMode.CANCELLATION,
                started_at=started_at,
                started_at_monotonic=started_at_mono,
                pid=None,
                owned_process_cleaned=True,
            )

        # 验证配置
        config_errors = self._config.validate()
        if config_errors:
            return StarRailRunResult.from_monotonic(
                status=StarRailRunStatus.FAILED,
                error_code=StarRailErrorCode.INVALID_CONFIGURATION,
                completion_mode=StarRailCompletionMode.START_FAILURE,
                started_at=started_at,
                started_at_monotonic=started_at_mono,
                pid=None,
                owned_process_cleaned=True,
            )

        # 验证路径
        executable = Path(self._config.executable)
        wd = Path(self._config.working_directory)

        if not executable.is_file():
            return StarRailRunResult.from_monotonic(
                status=StarRailRunStatus.FAILED,
                error_code=StarRailErrorCode.EXECUTABLE_NOT_FOUND,
                completion_mode=StarRailCompletionMode.START_FAILURE,
                started_at=started_at,
                started_at_monotonic=started_at_mono,
                pid=None,
                owned_process_cleaned=True,
            )

        if not wd.is_dir():
            return StarRailRunResult.from_monotonic(
                status=StarRailRunStatus.FAILED,
                error_code=StarRailErrorCode.WORKING_DIRECTORY_NOT_FOUND,
                completion_mode=StarRailCompletionMode.START_FAILURE,
                started_at=started_at,
                started_at_monotonic=started_at_mono,
                pid=None,
                owned_process_cleaned=True,
            )

        # 解析日志路径 + 验证父目录
        log_path = resolve_starrail_log_path(self._config)
        if not log_path.parent.is_dir():
            return StarRailRunResult.from_monotonic(
                status=StarRailRunStatus.FAILED,
                error_code=StarRailErrorCode.LOG_PARENT_NOT_FOUND,
                completion_mode=StarRailCompletionMode.START_FAILURE,
                started_at=started_at,
                started_at_monotonic=started_at_mono,
                pid=None,
                owned_process_cleaned=True,
            )

        # 建立 Deadline
        config_seconds = float(self._config.task_timeout_seconds)
        if deadline is None:
            effective_deadline = Deadline.after(config_seconds)
        else:
            effective_deadline = Deadline.after(min(config_seconds, deadline.remaining_seconds))

        # 启动前捕获日志游标
        log_cursor = capture_log_cursor(log_path)

        # 准备输出文件
        try:
            tmp_dir = tempfile.TemporaryDirectory(prefix="orchestratorrr-starrail-")
        except OSError:
            return StarRailRunResult.from_monotonic(
                status=StarRailRunStatus.FAILED,
                error_code=StarRailErrorCode.PROCESS_START_FAILED,
                completion_mode=StarRailCompletionMode.START_FAILURE,
                started_at=started_at,
                started_at_monotonic=started_at_mono,
                pid=None,
                owned_process_cleaned=True,
            )

        td = Path(tmp_dir.name)
        stdout_path = td / "stdout.bin"
        stderr_path = td / "stderr.bin"

        env_overrides = dict(self._config.environment_overrides)

        spec = ProcessSpec(
            name="starrail_copilot",
            executable=executable,
            arguments=self._config.arguments,
            working_directory=wd,
            environment_overrides=env_overrides,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        supervisor = ProcessSupervisor()
        managed: ManagedProcess | None = None

        try:
            try:
                managed = supervisor.launch(spec)
            except Exception:
                tmp_dir.cleanup()
                return StarRailRunResult.from_monotonic(
                    status=StarRailRunStatus.FAILED,
                    error_code=StarRailErrorCode.PROCESS_START_FAILED,
                    completion_mode=StarRailCompletionMode.START_FAILURE,
                    started_at=started_at,
                    started_at_monotonic=started_at_mono,
                    pid=None,
                    owned_process_cleaned=True,
                )

            pid = managed.pid

            # 主循环
            while True:
                # A. cancellation
                if cancel is not None and cancel.is_cancelled:
                    stop_result, cleaned = self._stop_owned_process(supervisor, managed)
                    out_ex, out_trunc = _read_output_excerpt(stdout_path, MAX_STDOUT_BYTES)
                    err_ex, err_trunc = _read_output_excerpt(stderr_path, MAX_STDERR_BYTES)
                    tmp_dir.cleanup()
                    ec = stop_result.exit_code if stop_result else None
                    if not cleaned:
                        return StarRailRunResult.from_monotonic(
                            status=StarRailRunStatus.CANCELLED,
                            error_code=StarRailErrorCode.CLEANUP_FAILED,
                            completion_mode=StarRailCompletionMode.CANCELLATION,
                            started_at=started_at,
                            started_at_monotonic=started_at_mono,
                            pid=pid,
                            exit_code=ec,
                            owned_process_cleaned=False,
                            stdout_excerpt=out_ex,
                            stderr_excerpt=err_ex,
                            stdout_truncated=out_trunc,
                            stderr_truncated=err_trunc,
                        )
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.CANCELLED,
                        error_code=StarRailErrorCode.CANCELLED,
                        completion_mode=StarRailCompletionMode.CANCELLATION,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        exit_code=ec,
                        owned_process_cleaned=True,
                        stdout_excerpt=out_ex,
                        stderr_excerpt=err_ex,
                        stdout_truncated=out_trunc,
                        stderr_truncated=err_trunc,
                    )

                # B. deadline
                if effective_deadline.expired:
                    stop_result, cleaned = self._stop_owned_process(supervisor, managed)
                    out_ex, out_trunc = _read_output_excerpt(stdout_path, MAX_STDOUT_BYTES)
                    err_ex, err_trunc = _read_output_excerpt(stderr_path, MAX_STDERR_BYTES)
                    tmp_dir.cleanup()
                    ec = stop_result.exit_code if stop_result else None
                    code = StarRailErrorCode.TASK_TIMEOUT if cleaned else StarRailErrorCode.CLEANUP_FAILED
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.TIMEOUT,
                        error_code=code,
                        completion_mode=StarRailCompletionMode.TASK_TIMEOUT,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        exit_code=ec,
                        owned_process_cleaned=cleaned,
                        stdout_excerpt=out_ex,
                        stderr_excerpt=err_ex,
                        stdout_truncated=out_trunc,
                        stderr_truncated=err_trunc,
                    )

                # C. 读取新增日志
                try:
                    update = read_log_update(log_cursor, max_bytes=MAX_LOG_READ_BYTES)
                except OSError:
                    self._stop_owned_process(supervisor, managed)
                    out_ex, out_trunc = _read_output_excerpt(stdout_path, MAX_STDOUT_BYTES)
                    err_ex, err_trunc = _read_output_excerpt(stderr_path, MAX_STDERR_BYTES)
                    tmp_dir.cleanup()
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.FAILED,
                        error_code=StarRailErrorCode.LOG_READ_FAILED,
                        completion_mode=StarRailCompletionMode.LOG_ERROR,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        owned_process_cleaned=True,
                        stdout_excerpt=out_ex,
                        stderr_excerpt=err_ex,
                        stdout_truncated=out_trunc,
                        stderr_truncated=err_trunc,
                    )

                # D. 日志超限
                if update.overflow:
                    self._stop_owned_process(supervisor, managed)
                    out_ex, out_trunc = _read_output_excerpt(stdout_path, MAX_STDOUT_BYTES)
                    err_ex, err_trunc = _read_output_excerpt(stderr_path, MAX_STDERR_BYTES)
                    tmp_dir.cleanup()
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.FAILED,
                        error_code=StarRailErrorCode.LOG_OUTPUT_LIMIT,
                        completion_mode=StarRailCompletionMode.LOG_ERROR,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        owned_process_cleaned=True,
                        stdout_excerpt=out_ex,
                        stderr_excerpt=err_ex,
                        stdout_truncated=out_trunc,
                        stderr_truncated=err_trunc,
                    )

                # E. failure keyword (在 rolling_text 中搜索，包含增量历史)
                match = match_starrail_keyword(
                    log_cursor.rolling_text,
                    success_keywords=self._config.success_keywords,
                    failure_keywords=self._config.failure_keywords,
                )
                if match and match.kind == "failure":
                    self._stop_owned_process(supervisor, managed)
                    out_ex, out_trunc = _read_output_excerpt(stdout_path, MAX_STDOUT_BYTES)
                    err_ex, err_trunc = _read_output_excerpt(stderr_path, MAX_STDERR_BYTES)
                    tmp_dir.cleanup()
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.FAILED,
                        error_code=StarRailErrorCode.FAILURE_KEYWORD,
                        completion_mode=StarRailCompletionMode.LOG_FAILURE,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        matched_keyword=match.keyword,
                        owned_process_cleaned=True,
                        stdout_excerpt=out_ex,
                        stderr_excerpt=err_ex,
                        stdout_truncated=out_trunc,
                        stderr_truncated=err_trunc,
                        diagnostics={"primary_error": "FAILURE_KEYWORD"},
                    )

                # F. success keyword
                if match and match.kind == "success":
                    self._stop_owned_process(supervisor, managed)
                    out_ex, out_trunc = _read_output_excerpt(stdout_path, MAX_STDOUT_BYTES)
                    err_ex, err_trunc = _read_output_excerpt(stderr_path, MAX_STDERR_BYTES)
                    tmp_dir.cleanup()
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.COMPLETED,
                        error_code=StarRailErrorCode.OK,
                        completion_mode=StarRailCompletionMode.LOG_SUCCESS,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        matched_keyword=match.keyword,
                        owned_process_cleaned=True,
                        stdout_excerpt=out_ex,
                        stderr_excerpt=err_ex,
                        stdout_truncated=out_trunc,
                        stderr_truncated=err_trunc,
                    )

                # G. 检查进程退出
                exit_code = managed.poll()
                if exit_code is not None:
                    stop_result, _ = self._stop_owned_process(supervisor, managed)
                    out_ex, out_trunc = _read_output_excerpt(stdout_path, MAX_STDOUT_BYTES)
                    err_ex, err_trunc = _read_output_excerpt(stderr_path, MAX_STDERR_BYTES)
                    tmp_dir.cleanup()
                    ec = exit_code
                    if ec != 0:
                        return StarRailRunResult.from_monotonic(
                            status=StarRailRunStatus.FAILED,
                            error_code=StarRailErrorCode.PROCESS_EXIT_NONZERO,
                            completion_mode=StarRailCompletionMode.PROCESS_EXIT,
                            started_at=started_at,
                            started_at_monotonic=started_at_mono,
                            pid=pid,
                            exit_code=ec,
                            owned_process_cleaned=True,
                            stdout_excerpt=out_ex,
                            stderr_excerpt=err_ex,
                            stdout_truncated=out_trunc,
                            stderr_truncated=err_trunc,
                        )
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.FAILED,
                        error_code=StarRailErrorCode.PROCESS_EXIT_BEFORE_SUCCESS,
                        completion_mode=StarRailCompletionMode.PROCESS_EXIT,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        exit_code=ec,
                        owned_process_cleaned=True,
                        stdout_excerpt=out_ex,
                        stderr_excerpt=err_ex,
                        stdout_truncated=out_trunc,
                        stderr_truncated=err_trunc,
                    )

                # H. 有限等待
                wait_sec = min(self._poll_interval, effective_deadline.remaining_seconds)
                if cancel is not None:
                    cancelled = cancel.wait(timeout_seconds=wait_sec)
                    if cancelled:
                        continue
                else:
                    time.sleep(wait_sec)

        except Exception:
            # 确保清理
            if managed is not None:
                try:
                    self._stop_owned_process(supervisor, managed)
                except Exception:
                    pass
            try:
                tmp_dir.cleanup()
            except Exception:
                pass
            return StarRailRunResult.from_monotonic(
                status=StarRailRunStatus.FAILED,
                error_code=StarRailErrorCode.PROCESS_START_FAILED,
                completion_mode=StarRailCompletionMode.START_FAILURE,
                started_at=started_at,
                started_at_monotonic=started_at_mono,
                pid=managed.pid if managed else None,
                owned_process_cleaned=False,
            )

    def _stop_owned_process(
        self, supervisor: ProcessSupervisor, managed: ManagedProcess
    ) -> tuple[ProcessResult | None, bool]:
        """停止受管进程树，返回 (ProcessResult, 是否已清理)。"""
        try:
            stop_result = supervisor.stop(
                managed, confirmation_deadline=Deadline.after(float(self._config.stop_timeout_seconds))
            )
            reason = stop_result.termination_reason
            cleaned = reason in (
                TerminationReason.STOPPED,
                TerminationReason.NORMAL_EXIT,
                TerminationReason.NONZERO_EXIT,
            )
            return stop_result, cleaned
        except Exception:
            return None, False


def _read_output_excerpt(path: Path, byte_limit: int) -> tuple[str, bool]:
    """有界读取输出文件摘录。"""
    import locale

    try:
        with path.open("rb") as stream:
            data = stream.read(byte_limit + 1)
    except OSError:
        return "", False

    truncated = len(data) > byte_limit
    if truncated:
        data = data[:byte_limit]

    try:
        text = data.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        try:
            text = data.decode(locale.getpreferredencoding(False), errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = data.decode("utf-8", errors="replace")

    if len(text) > MAX_OUTPUT_EXCERPT_CHARS:
        text = text[:MAX_OUTPUT_EXCERPT_CHARS]
        truncated = True

    return text.strip(), truncated
