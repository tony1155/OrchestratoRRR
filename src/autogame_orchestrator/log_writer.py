"""Synchronous JSONL structured-log writer.

Every log record is written as a single line of JSON with the following
guaranteed keys: ``timestamp``, ``level``, ``event``, ``run_id``,
``message``, ``details``.

Usage::

    from autogame_orchestrator.log_writer import JsonlLogWriter

    with JsonlLogWriter(Path("logs/run-abc.jsonl"), run_id="abc123") as log:
        log.info("orchestrator.started", "Orchestrator started", {"mode": "plan"})
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import TextIOWrapper
from pathlib import Path
from typing import TYPE_CHECKING

from autogame_orchestrator.models import ErrorCode, is_json_serializable

if TYPE_CHECKING:
    pass


class LogWriteError(RuntimeError):
    """Raised when a JSONL write operation fails."""

    def __init__(self, msg: str, error_code: ErrorCode) -> None:
        super().__init__(msg)
        self.error_code = error_code


class JsonlLogWriter:
    """Synchronous, line-oriented JSON log writer.

    Opens the target file on enter and closes it on exit.
    Every call to ``_emit`` flushes immediately.
    """

    def __init__(self, path: Path, run_id: str) -> None:
        self._path = path
        self._run_id = run_id
        self._fh: TextIOWrapper | None = None

    def __enter__(self) -> JsonlLogWriter:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self._path, "w", encoding="utf-8")  # noqa: SIM115
        except OSError as exc:
            raise LogWriteError(
                f"Failed to open log file {self._path}: {exc}",
                ErrorCode.LOG_WRITE_ERROR,
            ) from exc
        return self

    def __exit__(self, *args: object) -> None:
        if self._fh is not None:
            try:
                self._fh.flush()
            except OSError:
                pass
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    def info(self, event: str, message: str, details: dict[str, object] | None = None) -> None:
        self._emit("INFO", event, message, details)

    def warning(self, event: str, message: str, details: dict[str, object] | None = None) -> None:
        self._emit("WARNING", event, message, details)

    def error(self, event: str, message: str, details: dict[str, object] | None = None) -> None:
        self._emit("ERROR", event, message, details)

    def _emit(
        self,
        level: str,
        event: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        det: dict[str, object] = details or {}
        if not is_json_serializable(det):
            raise LogWriteError(
                "Log details contain values that are not JSON-serializable",
                ErrorCode.LOG_WRITE_ERROR,
            )

        record: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "event": event,
            "run_id": self._run_id,
            "message": message,
            "details": det,
        }

        try:
            line = json.dumps(record, ensure_ascii=False) + "\n"
        except (TypeError, ValueError) as exc:
            raise LogWriteError(
                f"Failed to serialize log record: {exc}",
                ErrorCode.LOG_WRITE_ERROR,
            ) from exc

        if self._fh is None:
            raise LogWriteError(
                "Log writer is not open (use as context manager)",
                ErrorCode.LOG_WRITE_ERROR,
            )

        try:
            self._fh.write(line)
            self._fh.flush()
        except OSError as exc:
            raise LogWriteError(
                f"Failed to write log record: {exc}",
                ErrorCode.LOG_WRITE_ERROR,
            ) from exc
