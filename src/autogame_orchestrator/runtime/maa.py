"""MAA CLI 的有界运行时适配器。"""
# mypy: disable-error-code=arg-type

from __future__ import annotations

import locale
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from autogame_orchestrator.config_model import MAAConfig
from autogame_orchestrator.process import CancellationToken, Deadline, ProcessSpec, ProcessSupervisor
from autogame_orchestrator.process.errors import TerminationReason
from autogame_orchestrator.runtime.maa_models import MAAErrorCode, MAARunResult, MAARunStatus

DEFAULT_POLL_INTERVAL_SECONDS = 0.05
MAX_STDOUT_BYTES = 64 * 1024
MAX_STDERR_BYTES = 64 * 1024
MAX_OUTPUT_EXCERPT_CHARS = 8 * 1024


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


class MAAAdapter:
    """仅以退出码判定 MAA CLI 是否成功的适配器。"""

    def __init__(self, config: MAAConfig, *, poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("轮询间隔必须为正数")
        self._config = config
        self._poll_interval_seconds = poll_interval_seconds

    def run(self, deadline: Deadline | None = None, cancel: CancellationToken | None = None) -> MAARunResult:
        started_at = datetime.now(UTC)
        started_mono = time.monotonic()

        def result(status: MAARunStatus, code: MAAErrorCode, **kwargs: object) -> MAARunResult:
            return MAARunResult.from_monotonic(
                status=status, error_code=code, started_at=started_at, started_at_monotonic=started_mono, **kwargs
            )

        if cancel is not None and cancel.is_cancelled:
            return result(
                MAARunStatus.CANCELLED, MAAErrorCode.CANCELLED, pid=None, termination_reason=TerminationReason.CANCELLED
            )
        if self._config.validate():
            return result(MAARunStatus.FAILED, MAAErrorCode.INVALID_CONFIGURATION, pid=None)
        executable = Path(self._config.executable)
        working_directory = Path(self._config.working_directory)
        if not executable.is_file():
            return result(MAARunStatus.FAILED, MAAErrorCode.EXECUTABLE_NOT_FOUND, pid=None)
        if not working_directory.is_dir():
            return result(MAARunStatus.FAILED, MAAErrorCode.WORKING_DIRECTORY_NOT_FOUND, pid=None)
        config_deadline = Deadline.after(float(self._config.timeout_seconds))
        if deadline is not None and deadline.expired:
            return result(
                MAARunStatus.TIMEOUT,
                MAAErrorCode.PROCESS_TIMEOUT,
                pid=None,
                termination_reason=TerminationReason.TIMEOUT,
            )
        effective_deadline = (
            config_deadline
            if deadline is None
            else Deadline.after(min(config_deadline.remaining_seconds, deadline.remaining_seconds))
        )
        try:
            with tempfile.TemporaryDirectory(prefix="orchestratorrr-maa-") as temporary_directory:
                stdout_path = Path(temporary_directory) / "stdout.bin"
                stderr_path = Path(temporary_directory) / "stderr.bin"
                spec = ProcessSpec(
                    name="maa_cli",
                    executable=executable,
                    arguments=self._config.arguments,
                    working_directory=working_directory,
                    environment_overrides=dict(self._config.environment_overrides),
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
                stdout, stdout_truncated, stdout_failed = _read_output_excerpt(stdout_path, byte_limit=MAX_STDOUT_BYTES)
                stderr, stderr_truncated, stderr_failed = _read_output_excerpt(stderr_path, byte_limit=MAX_STDERR_BYTES)
                diagnostics = {"stdout_read_failed": stdout_failed, "stderr_read_failed": stderr_failed}
                if close_failed:
                    status = MAARunStatus.FAILED
                    if process_result is not None and process_result.termination_reason == TerminationReason.TIMEOUT:
                        status = MAARunStatus.TIMEOUT
                    if process_result is not None and process_result.termination_reason == TerminationReason.CANCELLED:
                        status = MAARunStatus.CANCELLED
                    return result(
                        status,
                        MAAErrorCode.CLEANUP_FAILED,
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
                        MAARunStatus.FAILED, MAAErrorCode.INTERNAL_ERROR, pid=None, owned_process_cleaned=False
                    )
                mapping = {
                    TerminationReason.NORMAL_EXIT: (MAARunStatus.COMPLETED, MAAErrorCode.OK, True),
                    TerminationReason.NONZERO_EXIT: (MAARunStatus.FAILED, MAAErrorCode.PROCESS_EXIT_NONZERO, True),
                    TerminationReason.TIMEOUT: (MAARunStatus.TIMEOUT, MAAErrorCode.PROCESS_TIMEOUT, True),
                    TerminationReason.CANCELLED: (MAARunStatus.CANCELLED, MAAErrorCode.CANCELLED, True),
                    TerminationReason.START_FAILED: (MAARunStatus.FAILED, MAAErrorCode.PROCESS_START_FAILED, True),
                    TerminationReason.WAIT_FAILED: (MAARunStatus.FAILED, MAAErrorCode.WAIT_FAILED, False),
                    TerminationReason.TERMINATION_FAILED: (MAARunStatus.FAILED, MAAErrorCode.CLEANUP_FAILED, False),
                    TerminationReason.STOPPED: (MAARunStatus.FAILED, MAAErrorCode.INTERNAL_ERROR, False),
                }
                status, code, cleaned = mapping[process_result.termination_reason]
                if process_result.termination_reason == TerminationReason.TERMINATION_FAILED:
                    if cancel is not None and cancel.is_cancelled:
                        status = MAARunStatus.CANCELLED
                    elif effective_deadline.expired:
                        status = MAARunStatus.TIMEOUT
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
            return result(MAARunStatus.FAILED, MAAErrorCode.PROCESS_START_FAILED, pid=None)
