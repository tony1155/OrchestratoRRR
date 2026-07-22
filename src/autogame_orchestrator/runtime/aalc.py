"""AALC 进程的有界重试运行时适配器。"""
# mypy: disable-error-code=arg-type

from __future__ import annotations

import locale
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from autogame_orchestrator.config_model import AALCConfig
from autogame_orchestrator.process import CancellationToken, Deadline, ProcessSpec, ProcessSupervisor
from autogame_orchestrator.process.errors import TerminationReason
from autogame_orchestrator.runtime.aalc_models import (
    AALCAttemptResult,
    AALCAttemptStatus,
    AALCCompletionMode,
    AALCErrorCode,
    AALCRunResult,
    AALCRunStatus,
)

DEFAULT_POLL_INTERVAL_SECONDS = 0.05
MAX_OUTPUT_BYTES = 64 * 1024
MAX_OUTPUT_EXCERPT_CHARS = 8 * 1024


def _read_excerpt(path: Path) -> tuple[str, bool, bool]:
    try:
        raw = path.open("rb").read(MAX_OUTPUT_BYTES + 1)
    except FileNotFoundError:
        return "", False, False
    except OSError:
        return "", False, True
    truncated = len(raw) > MAX_OUTPUT_BYTES
    raw = raw[:MAX_OUTPUT_BYTES]
    try:
        if raw.startswith(b"\xef\xbb\xbf"):
            text = raw.decode("utf-8-sig")
        elif raw.startswith(b"\xff\xfe") or b"\x00" in raw:
            text = raw.decode("utf-16")
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode(locale.getpreferredencoding(False))
    except (LookupError, UnicodeDecodeError):
        text = raw.decode("utf-8", errors="replace")
    if len(text) > MAX_OUTPUT_EXCERPT_CHARS:
        return text[:MAX_OUTPUT_EXCERPT_CHARS], True, False
    return text, truncated, False


class AALCAdapter:
    """只依据退出码执行 AALC，最多进行三次有界尝试。"""

    def __init__(self, config: AALCConfig, *, poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("轮询间隔必须为正数")
        self._config = config
        self._poll_interval_seconds = poll_interval_seconds

    def run(self, deadline: Deadline | None = None, cancel: CancellationToken | None = None) -> AALCRunResult:
        started_at = datetime.now(UTC)
        started_mono = time.monotonic()
        attempts: list[AALCAttemptResult] = []

        def finish(
            status: AALCRunStatus, code: AALCErrorCode, mode: AALCCompletionMode, success: int | None = None
        ) -> AALCRunResult:
            return AALCRunResult(
                status,
                code,
                mode,
                started_at,
                datetime.now(UTC),
                max(0.0, time.monotonic() - started_mono),
                self._config.attempts,
                len(attempts),
                success,
                tuple(attempts),
                {},
            )

        if cancel is not None and cancel.is_cancelled:
            return finish(AALCRunStatus.CANCELLED, AALCErrorCode.CANCELLED, AALCCompletionMode.CANCELLATION)
        if self._config.validate():
            return finish(AALCRunStatus.FAILED, AALCErrorCode.INVALID_CONFIGURATION, AALCCompletionMode.START_FAILURE)
        executable = Path(self._config.executable)
        working_directory = Path(self._config.working_directory)
        if not executable.is_file():
            return finish(AALCRunStatus.FAILED, AALCErrorCode.EXECUTABLE_NOT_FOUND, AALCCompletionMode.START_FAILURE)
        if not working_directory.is_dir():
            return finish(
                AALCRunStatus.FAILED, AALCErrorCode.WORKING_DIRECTORY_NOT_FOUND, AALCCompletionMode.START_FAILURE
            )
        for attempt_number in range(1, self._config.attempts + 1):
            if cancel is not None and cancel.is_cancelled:
                return finish(AALCRunStatus.CANCELLED, AALCErrorCode.CANCELLED, AALCCompletionMode.CANCELLATION)
            if deadline is not None and deadline.expired:
                return finish(AALCRunStatus.TIMEOUT, AALCErrorCode.PARENT_DEADLINE, AALCCompletionMode.PARENT_DEADLINE)
            attempt_started = datetime.now(UTC)
            attempt_mono = time.monotonic()
            parent_limited = deadline is not None and deadline.remaining_seconds <= self._config.attempt_timeout_seconds
            seconds = float(self._config.attempt_timeout_seconds)
            if deadline is not None:
                seconds = min(seconds, deadline.remaining_seconds)
            effective_deadline = Deadline.after(seconds)
            with tempfile.TemporaryDirectory(
                prefix="orchestratorrr-aalc-", ignore_cleanup_errors=True
            ) as temporary_directory:
                stdout_path = Path(temporary_directory) / "stdout.bin"
                stderr_path = Path(temporary_directory) / "stderr.bin"
                environment = dict(self._config.environment_overrides)
                environment["AALC_ATTEMPT_NUMBER"] = str(attempt_number)
                spec = ProcessSpec(
                    name="aalc",
                    executable=executable,
                    arguments=self._config.arguments,
                    working_directory=working_directory,
                    environment_overrides=environment,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                )
                supervisor = ProcessSupervisor(
                    poll_interval_seconds=self._poll_interval_seconds,
                    kill_confirmation_seconds=float(self._config.stop_timeout_seconds),
                )
                process_result = None
                close_failed = False
                try:
                    process_result = supervisor.run(spec, effective_deadline, cancel)
                finally:
                    try:
                        supervisor.close()
                    except Exception:
                        close_failed = True
                stdout, stdout_truncated, stdout_failed = _read_excerpt(stdout_path)
                stderr, stderr_truncated, stderr_failed = _read_excerpt(stderr_path)
            reason = process_result.termination_reason
            if reason == TerminationReason.NORMAL_EXIT:
                attempt_status, attempt_code, cleaned = AALCAttemptStatus.COMPLETED, AALCErrorCode.OK, True
            elif reason == TerminationReason.NONZERO_EXIT:
                attempt_status, attempt_code, cleaned = (
                    AALCAttemptStatus.FAILED,
                    AALCErrorCode.PROCESS_EXIT_NONZERO,
                    True,
                )
            elif reason == TerminationReason.CANCELLED:
                attempt_status, attempt_code, cleaned = AALCAttemptStatus.CANCELLED, AALCErrorCode.CANCELLED, True
            elif reason == TerminationReason.TIMEOUT:
                attempt_status = AALCAttemptStatus.TIMEOUT
                cleaned = True
                attempt_code = AALCErrorCode.PARENT_DEADLINE if parent_limited else AALCErrorCode.ATTEMPT_TIMEOUT
            elif reason == TerminationReason.START_FAILED:
                attempt_status, attempt_code, cleaned = (
                    AALCAttemptStatus.FAILED,
                    AALCErrorCode.PROCESS_START_FAILED,
                    True,
                )
            else:
                attempt_status, attempt_code, cleaned = AALCAttemptStatus.FAILED, AALCErrorCode.INTERNAL_ERROR, False
            if close_failed:
                cleaned = False
                attempt_code = AALCErrorCode.CLEANUP_FAILED
                if attempt_status == AALCAttemptStatus.COMPLETED:
                    attempt_status = AALCAttemptStatus.FAILED
            diagnostics = {
                "stdout_read_failed": stdout_failed,
                "stderr_read_failed": stderr_failed,
                "process_error_code": process_result.error_code.value,
            }
            attempts.append(
                AALCAttemptResult(
                    attempt_number,
                    attempt_status,
                    attempt_code,
                    attempt_started,
                    datetime.now(UTC),
                    max(0.0, time.monotonic() - attempt_mono),
                    process_result.pid,
                    process_result.exit_code,
                    cleaned,
                    stdout,
                    stderr,
                    stdout_truncated,
                    stderr_truncated,
                    diagnostics,
                )
            )
            if close_failed:
                status = {
                    AALCAttemptStatus.TIMEOUT: AALCRunStatus.TIMEOUT,
                    AALCAttemptStatus.CANCELLED: AALCRunStatus.CANCELLED,
                }.get(attempt_status, AALCRunStatus.FAILED)
                return finish(status, AALCErrorCode.CLEANUP_FAILED, AALCCompletionMode.CLEANUP_FAILURE)
            if attempt_status == AALCAttemptStatus.COMPLETED:
                return finish(AALCRunStatus.COMPLETED, AALCErrorCode.OK, AALCCompletionMode.NORMAL_EXIT, attempt_number)
            if attempt_status == AALCAttemptStatus.CANCELLED:
                return finish(AALCRunStatus.CANCELLED, AALCErrorCode.CANCELLED, AALCCompletionMode.CANCELLATION)
            if attempt_code == AALCErrorCode.PARENT_DEADLINE or (deadline is not None and deadline.expired):
                return finish(AALCRunStatus.TIMEOUT, AALCErrorCode.PARENT_DEADLINE, AALCCompletionMode.PARENT_DEADLINE)
            if attempt_code not in {AALCErrorCode.PROCESS_EXIT_NONZERO, AALCErrorCode.ATTEMPT_TIMEOUT}:
                return finish(AALCRunStatus.FAILED, attempt_code, AALCCompletionMode.START_FAILURE)
        return finish(AALCRunStatus.FAILED, AALCErrorCode.RETRIES_EXHAUSTED, AALCCompletionMode.RETRIES_EXHAUSTED)
