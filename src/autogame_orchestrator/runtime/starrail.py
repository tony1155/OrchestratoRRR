"""StarRailCopilot 任务 Adapter。

管理由本次 Adapter 启动的 StarRailCopilot 进程树，
通过增量日志监控实现成功/失败完成判定。
"""

from __future__ import annotations

import locale
import tempfile
import time
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _StoppedProcessOutput:
    process_result: ProcessResult | None
    cleaned: bool
    stdout_excerpt: str
    stderr_excerpt: str
    stdout_truncated: bool
    stderr_truncated: bool


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

        config_seconds = float(self._config.task_timeout_seconds)
        if deadline is None:
            effective_deadline = Deadline.after(config_seconds)
        else:
            effective_deadline = Deadline.after(min(config_seconds, deadline.remaining_seconds))

        try:
            log_cursor = capture_log_cursor(log_path)
        except OSError as exc:
            return StarRailRunResult.from_monotonic(
                status=StarRailRunStatus.FAILED,
                error_code=StarRailErrorCode.LOG_READ_FAILED,
                completion_mode=StarRailCompletionMode.LOG_ERROR,
                started_at=started_at,
                started_at_monotonic=started_at_mono,
                pid=None,
                log_path=str(log_path),
                owned_process_cleaned=True,
                diagnostics={"exception_type": type(exc).__name__},
            )

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

            while True:
                if cancel is not None and cancel.is_cancelled:
                    out = self._stop_and_collect(supervisor, managed, stdout_path, stderr_path)
                    ec = out.process_result.exit_code if out.process_result else None
                    code = StarRailErrorCode.CLEANUP_FAILED if not out.cleaned else StarRailErrorCode.CANCELLED
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.CANCELLED,
                        error_code=code,
                        completion_mode=StarRailCompletionMode.CANCELLATION,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        exit_code=ec,
                        log_path=str(log_path),
                        owned_process_cleaned=out.cleaned,
                        stdout_excerpt=out.stdout_excerpt,
                        stderr_excerpt=out.stderr_excerpt,
                        stdout_truncated=out.stdout_truncated,
                        stderr_truncated=out.stderr_truncated,
                    )

                if effective_deadline.expired:
                    out = self._stop_and_collect(supervisor, managed, stdout_path, stderr_path)
                    ec = out.process_result.exit_code if out.process_result else None
                    code = StarRailErrorCode.TASK_TIMEOUT if out.cleaned else StarRailErrorCode.CLEANUP_FAILED
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.TIMEOUT,
                        error_code=code,
                        completion_mode=StarRailCompletionMode.TASK_TIMEOUT,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        exit_code=ec,
                        log_path=str(log_path),
                        owned_process_cleaned=out.cleaned,
                        stdout_excerpt=out.stdout_excerpt,
                        stderr_excerpt=out.stderr_excerpt,
                        stdout_truncated=out.stdout_truncated,
                        stderr_truncated=out.stderr_truncated,
                    )

                try:
                    update = read_log_update(log_cursor, max_bytes=MAX_LOG_READ_BYTES)
                except OSError as exc:
                    out = self._stop_and_collect(supervisor, managed, stdout_path, stderr_path)
                    code = StarRailErrorCode.LOG_READ_FAILED if out.cleaned else StarRailErrorCode.CLEANUP_FAILED
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.FAILED,
                        error_code=code,
                        completion_mode=StarRailCompletionMode.LOG_ERROR,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        log_path=str(log_path),
                        owned_process_cleaned=out.cleaned,
                        stdout_excerpt=out.stdout_excerpt,
                        stderr_excerpt=out.stderr_excerpt,
                        stdout_truncated=out.stdout_truncated,
                        stderr_truncated=out.stderr_truncated,
                        diagnostics={"primary_error": "LOG_READ_FAILED", "exception_type": type(exc).__name__},
                    )

                if update.overflow:
                    out = self._stop_and_collect(supervisor, managed, stdout_path, stderr_path)
                    code = StarRailErrorCode.LOG_OUTPUT_LIMIT if out.cleaned else StarRailErrorCode.CLEANUP_FAILED
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.FAILED,
                        error_code=code,
                        completion_mode=StarRailCompletionMode.LOG_ERROR,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        log_path=str(log_path),
                        owned_process_cleaned=out.cleaned,
                        stdout_excerpt=out.stdout_excerpt,
                        stderr_excerpt=out.stderr_excerpt,
                        stdout_truncated=out.stdout_truncated,
                        stderr_truncated=out.stderr_truncated,
                        diagnostics={"primary_error": "LOG_OUTPUT_LIMIT"},
                    )

                match = match_starrail_keyword(
                    log_cursor.rolling_text,
                    success_keywords=self._config.success_keywords,
                    failure_keywords=self._config.failure_keywords,
                )
                if match and match.kind == "failure":
                    out = self._stop_and_collect(supervisor, managed, stdout_path, stderr_path)
                    if out.cleaned:
                        return StarRailRunResult.from_monotonic(
                            status=StarRailRunStatus.FAILED,
                            error_code=StarRailErrorCode.FAILURE_KEYWORD,
                            completion_mode=StarRailCompletionMode.LOG_FAILURE,
                            started_at=started_at,
                            started_at_monotonic=started_at_mono,
                            pid=pid,
                            matched_keyword=match.keyword,
                            log_path=str(log_path),
                            owned_process_cleaned=True,
                            stdout_excerpt=out.stdout_excerpt,
                            stderr_excerpt=out.stderr_excerpt,
                            stdout_truncated=out.stdout_truncated,
                            stderr_truncated=out.stderr_truncated,
                            diagnostics={"primary_error": "FAILURE_KEYWORD"},
                        )
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.FAILED,
                        error_code=StarRailErrorCode.CLEANUP_FAILED,
                        completion_mode=StarRailCompletionMode.LOG_FAILURE,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        matched_keyword=match.keyword,
                        log_path=str(log_path),
                        owned_process_cleaned=False,
                        stdout_excerpt=out.stdout_excerpt,
                        stderr_excerpt=out.stderr_excerpt,
                        stdout_truncated=out.stdout_truncated,
                        stderr_truncated=out.stderr_truncated,
                        diagnostics={"primary_error": "FAILURE_KEYWORD"},
                    )

                if match and match.kind == "success":
                    out = self._stop_and_collect(supervisor, managed, stdout_path, stderr_path)
                    if out.cleaned:
                        return StarRailRunResult.from_monotonic(
                            status=StarRailRunStatus.COMPLETED,
                            error_code=StarRailErrorCode.OK,
                            completion_mode=StarRailCompletionMode.LOG_SUCCESS,
                            started_at=started_at,
                            started_at_monotonic=started_at_mono,
                            pid=pid,
                            matched_keyword=match.keyword,
                            log_path=str(log_path),
                            owned_process_cleaned=True,
                            stdout_excerpt=out.stdout_excerpt,
                            stderr_excerpt=out.stderr_excerpt,
                            stdout_truncated=out.stdout_truncated,
                            stderr_truncated=out.stderr_truncated,
                        )
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.FAILED,
                        error_code=StarRailErrorCode.CLEANUP_FAILED,
                        completion_mode=StarRailCompletionMode.LOG_SUCCESS,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        matched_keyword=match.keyword,
                        log_path=str(log_path),
                        owned_process_cleaned=False,
                        stdout_excerpt=out.stdout_excerpt,
                        stderr_excerpt=out.stderr_excerpt,
                        stdout_truncated=out.stdout_truncated,
                        stderr_truncated=out.stderr_truncated,
                        diagnostics={"primary_completion": "LOG_SUCCESS"},
                    )

                exit_code = managed.poll()
                if exit_code is not None:
                    out = self._stop_and_collect(supervisor, managed, stdout_path, stderr_path)
                    ec = exit_code
                    if out.cleaned:
                        if ec != 0:
                            return StarRailRunResult.from_monotonic(
                                status=StarRailRunStatus.FAILED,
                                error_code=StarRailErrorCode.PROCESS_EXIT_NONZERO,
                                completion_mode=StarRailCompletionMode.PROCESS_EXIT,
                                started_at=started_at,
                                started_at_monotonic=started_at_mono,
                                pid=pid,
                                exit_code=ec,
                                log_path=str(log_path),
                                owned_process_cleaned=True,
                                stdout_excerpt=out.stdout_excerpt,
                                stderr_excerpt=out.stderr_excerpt,
                                stdout_truncated=out.stdout_truncated,
                                stderr_truncated=out.stderr_truncated,
                            )
                        return StarRailRunResult.from_monotonic(
                            status=StarRailRunStatus.FAILED,
                            error_code=StarRailErrorCode.PROCESS_EXIT_BEFORE_SUCCESS,
                            completion_mode=StarRailCompletionMode.PROCESS_EXIT,
                            started_at=started_at,
                            started_at_monotonic=started_at_mono,
                            pid=pid,
                            exit_code=ec,
                            log_path=str(log_path),
                            owned_process_cleaned=True,
                            stdout_excerpt=out.stdout_excerpt,
                            stderr_excerpt=out.stderr_excerpt,
                            stdout_truncated=out.stdout_truncated,
                            stderr_truncated=out.stderr_truncated,
                        )
                    primary = "PROCESS_EXIT_NONZERO" if ec != 0 else "PROCESS_EXIT_BEFORE_SUCCESS"
                    return StarRailRunResult.from_monotonic(
                        status=StarRailRunStatus.FAILED,
                        error_code=StarRailErrorCode.CLEANUP_FAILED,
                        completion_mode=StarRailCompletionMode.PROCESS_EXIT,
                        started_at=started_at,
                        started_at_monotonic=started_at_mono,
                        pid=pid,
                        exit_code=ec,
                        log_path=str(log_path),
                        owned_process_cleaned=False,
                        stdout_excerpt=out.stdout_excerpt,
                        stderr_excerpt=out.stderr_excerpt,
                        stdout_truncated=out.stdout_truncated,
                        stderr_truncated=out.stderr_truncated,
                        diagnostics={"primary_error": primary},
                    )

                wait_sec = min(self._poll_interval, effective_deadline.remaining_seconds)
                if cancel is not None:
                    cancelled = cancel.wait(timeout_seconds=wait_sec)
                    if cancelled:
                        continue
                else:
                    time.sleep(wait_sec)

        except Exception as exc:
            collected: _StoppedProcessOutput | None = None
            if managed is not None:
                try:
                    collected = self._stop_and_collect(supervisor, managed, stdout_path, stderr_path)
                except Exception:
                    pass
            code = (
                StarRailErrorCode.INTERNAL_ERROR
                if (collected and collected.cleaned)
                else StarRailErrorCode.CLEANUP_FAILED
            )
            return StarRailRunResult.from_monotonic(
                status=StarRailRunStatus.FAILED,
                error_code=code,
                completion_mode=StarRailCompletionMode.PROCESS_EXIT,
                started_at=started_at,
                started_at_monotonic=started_at_mono,
                pid=managed.pid if managed else None,
                log_path=str(log_path) if managed else "",
                owned_process_cleaned=collected.cleaned if collected else False,
                diagnostics={"exception_type": type(exc).__name__},
            )
        finally:
            try:
                supervisor.close()
            except Exception:
                pass
            try:
                tmp_dir.cleanup()
            except Exception:
                pass

    def _stop_owned_process(
        self, supervisor: ProcessSupervisor, managed: ManagedProcess
    ) -> tuple[ProcessResult | None, bool]:
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

    def _stop_and_collect(
        self, supervisor: ProcessSupervisor, managed: ManagedProcess, stdout_path: Path, stderr_path: Path
    ) -> _StoppedProcessOutput:
        process_result, cleaned = self._stop_owned_process(supervisor, managed)
        stdout_excerpt, stdout_truncated = _read_output_excerpt(stdout_path, MAX_STDOUT_BYTES)
        stderr_excerpt, stderr_truncated = _read_output_excerpt(stderr_path, MAX_STDERR_BYTES)
        return _StoppedProcessOutput(
            process_result=process_result,
            cleaned=cleaned,
            stdout_excerpt=stdout_excerpt,
            stderr_excerpt=stderr_excerpt,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )


def _read_output_excerpt(path: Path, byte_limit: int) -> tuple[str, bool]:
    """有界读取输出文件摘录。"""
    try:
        with path.open("rb") as stream:
            data = stream.read(byte_limit + 1)
    except OSError:
        return "", False

    truncated = len(data) > byte_limit
    if truncated:
        data = data[:byte_limit]

    text: str | None = None
    if data.startswith(b"\xef\xbb\xbf"):
        text = data.decode("utf-8-sig", errors="strict")
    else:
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            pass

    if text is None:
        preferred = locale.getpreferredencoding(False)
        try:
            text = data.decode(preferred, errors="strict")
        except (LookupError, UnicodeDecodeError):
            text = data.decode("utf-8", errors="replace")

    if text is None:
        text = ""

    if len(text) > MAX_OUTPUT_EXCERPT_CHARS:
        text = text[:MAX_OUTPUT_EXCERPT_CHARS]
        truncated = True

    return text.strip(), truncated
