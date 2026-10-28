"""Retry interrupted CLI downloads while preserving the stage deadline and cache."""

from __future__ import annotations

import os
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from autogame_orchestrator.process import CancellationToken, Deadline
from autogame_orchestrator.runtime.maa import MAAAdapter
from autogame_orchestrator.runtime.maa_models import MAAErrorCode, MAARunResult, MAARunStatus

MAX_UPDATE_ATTEMPTS = 512
MAX_STALLED_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 1.0
_NETWORK_ERRORS = (
    "peer disconnected",
    "peer closed connection",
    "connection reset",
    "connection aborted",
    "failed to send download request",
    "timed out",
    "unexpected eof",
)


def _retryable_download_failure(result: MAARunResult) -> bool:
    if (
        result.status != MAARunStatus.FAILED
        or result.error_code != MAAErrorCode.PROCESS_EXIT_NONZERO
        or not result.owned_process_cleaned
    ):
        return False
    output = (result.stdout_excerpt + "\n" + result.stderr_excerpt).casefold()
    return "failed to install maacore" in output and any(error in output for error in _NETWORK_ERRORS)


class MAAUpdateAdapter(MAAAdapter):
    """Let maa-cli resume its partial package after transient network failures.

    Only the update binding uses this adapter. Task execution and non-network
    installation errors are never retried. Continued cache growth permits more
    attempts; a stalled connection stops after five failures.
    """

    def _cache_progress(self) -> dict[str, int]:
        directory = next(
            (value for key, value in self._config.environment_overrides if key.casefold() == "maa_cache_dir"),
            os.environ.get("MAA_CACHE_DIR", ""),
        )
        if not directory:
            return {}
        try:
            return {path.name: path.stat().st_size for path in Path(directory).glob("*.partial") if path.is_file()}
        except OSError:
            return {}

    def run(self, deadline: Deadline | None = None, cancel: CancellationToken | None = None) -> MAARunResult:
        if self._config.validate():
            return super().run(deadline, cancel)
        started_at = datetime.now(UTC)
        started = time.monotonic()
        effective = Deadline.after(
            min(float(self._config.timeout_seconds), deadline.remaining_seconds)
            if deadline is not None
            else float(self._config.timeout_seconds)
        )
        progress = self._cache_progress()
        stalled = 0
        for attempt in range(1, MAX_UPDATE_ATTEMPTS + 1):
            result = super().run(effective, cancel)
            current = self._cache_progress()
            advanced = any(size > progress.get(name, 0) for name, size in current.items())
            for name, size in current.items():
                progress[name] = max(progress.get(name, 0), size)
            stalled = 0 if advanced else stalled + 1
            if (
                not _retryable_download_failure(result)
                or stalled >= MAX_STALLED_ATTEMPTS
                or attempt == MAX_UPDATE_ATTEMPTS
            ):
                break
            delay = effective.clamp_timeout(RETRY_DELAY_SECONDS)
            if cancel is None:
                time.sleep(delay)
            else:
                cancel.wait(delay)
        return replace(
            result,
            started_at=started_at,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            diagnostics={**result.diagnostics, "update_attempts": attempt},
        )
