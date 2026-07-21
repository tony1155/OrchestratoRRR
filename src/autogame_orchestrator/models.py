"""Stable, pure data models for Autogame Orchestrator.

All models are frozen (immutable) dataclasses with validation at construction time.
No external I/O, no side effects — pure data.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    pass

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


JsonScalar: TypeAlias = str | int | float | bool | None

JsonValue: TypeAlias = str | int | float | bool | None | list[Any] | dict[str, Any]
"""Type alias for JSON-serializable values.

Due to mypy limitations with recursive type aliases, this uses ``list[Any]``
and ``dict[str, Any]`` as practical shorthands.  Callers MUST guard actual
JSON serializability with ``is_json_serializable()`` at runtime.
"""


def is_json_serializable(value: object) -> bool:
    """Recursively check whether *value* can be serialised to JSON."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, (list, tuple)):
        return all(is_json_serializable(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and is_json_serializable(v) for k, v in value.items())
    return False


class ErrorCode(StrEnum):
    """Stable machine-readable error codes.

    Every failure path produces exactly one *ErrorCode*.
    ``OK`` signals success — nothing else does.
    """

    OK = "OK"
    CONFIG_FILE_NOT_FOUND = "CONFIG_FILE_NOT_FOUND"
    CONFIG_PARSE_ERROR = "CONFIG_PARSE_ERROR"
    CONFIG_SCHEMA_ERROR = "CONFIG_SCHEMA_ERROR"
    CONFIG_PATH_NOT_FOUND = "CONFIG_PATH_NOT_FOUND"
    CONFIG_PATH_NOT_FILE = "CONFIG_PATH_NOT_FILE"
    CONFIG_PATH_NOT_DIRECTORY = "CONFIG_PATH_NOT_DIRECTORY"
    LOG_WRITE_ERROR = "LOG_WRITE_ERROR"
    RUN_REPORT_SERIALIZATION_ERROR = "RUN_REPORT_SERIALIZATION_ERROR"
    RUN_REPORT_VALIDATION_ERROR = "RUN_REPORT_VALIDATION_ERROR"
    RUN_REPORT_WRITE_ERROR = "RUN_REPORT_WRITE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SKIPPED = "SKIPPED"


class OutcomeKind(StrEnum):
    """Granular result of a single stage."""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    """High-level status of an entire orchestration run."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


class StageName(StrEnum):
    """Every stage the orchestrator knows about.

    The ordering below reflects the *real lifecycle* contract:
    SRP must be stopped, verified-stopped, then MuMu stopped/verified,
    *then* MuMu restarted before MAA/AALC can run.
    """

    VALIDATE_CONFIG = "validate_config"
    SYNC_MAA_CONFIG = "sync_maa_config"
    UPDATE_MAA = "update_maa"
    ENSURE_MUMU_RUNNING = "ensure_mumu_running"
    WAIT_MUMU_ADB_READY = "wait_mumu_adb_ready"
    RUN_STARRAIL = "run_starrail"
    STOP_STARRAIL = "stop_starrail"
    VERIFY_STARRAIL_STOPPED = "verify_starrail_stopped"
    STOP_MUMU = "stop_mumu"
    VERIFY_MUMU_STOPPED = "verify_mumu_stopped"
    START_MUMU = "start_mumu"
    WAIT_MUMU_ADB_READY_AFTER_RESTART = "wait_mumu_adb_ready_after_restart"
    RUN_MAA = "run_maa"
    RUN_AALC = "run_aalc"
    WRITE_RUN_REPORT = "write_run_report"


def _is_stringified_uuid(value: str, /) -> bool:
    return bool(_UUID_RE.fullmatch(value))


def _ensure_tz(dt: datetime, label: str) -> None:
    if dt.tzinfo is None:
        msg = f"{label} must be timezone-aware (got naive datetime)"
        raise ValueError(msg)


@dataclass(frozen=True)
class StageReport:
    """Immutable report for a single orchestration stage."""

    stage: StageName
    outcome: OutcomeKind
    error_code: ErrorCode
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    message: str = ""
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_tz(self.started_at, "started_at")
        _ensure_tz(self.finished_at, "finished_at")

        if self.finished_at < self.started_at:
            msg = f"finished_at ({self.finished_at}) must be >= started_at ({self.started_at})"
            raise ValueError(msg)

        if self.duration_ms < 0:
            msg = f"duration_ms must be >= 0, got {self.duration_ms}"
            raise ValueError(msg)

        if self.outcome == OutcomeKind.SUCCESS and self.error_code != ErrorCode.OK:
            msg = f"SUCCESS outcome requires ErrorCode.OK, got {self.error_code.value}"
            raise ValueError(msg)

        _failure_kinds = {OutcomeKind.FAILURE, OutcomeKind.TIMEOUT, OutcomeKind.CANCELLED, OutcomeKind.SKIPPED}
        if self.outcome in _failure_kinds and self.error_code == ErrorCode.OK:
            msg = f"non-SUCCESS outcome ({self.outcome.value}) must not use ErrorCode.OK"
            raise ValueError(msg)

        if not is_json_serializable(dict(self.diagnostics)):
            msg = "diagnostics contains values that are not JSON-serializable"
            raise ValueError(msg)

    def to_json_encodable(self) -> dict[str, object]:
        """Return a JSON-encodable dictionary representing this report."""
        return {
            "stage": self.stage.value,
            "outcome": self.outcome.value,
            "error_code": self.error_code.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_ms": self.duration_ms,
            "message": self.message,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True)
class RunReport:
    """Immutable report for a complete orchestration run."""

    schema_version: int
    run_id: str
    orchestrator_version: str
    mode: str
    status: RunStatus
    error_code: ErrorCode
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    stages: tuple[StageReport, ...] = ()
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            msg = f"schema_version must be 1, got {self.schema_version}"
            raise ValueError(msg)

        if not _is_stringified_uuid(self.run_id):
            msg = f"run_id must be a valid UUID string, got {self.run_id!r}"
            raise ValueError(msg)

        _ensure_tz(self.started_at, "started_at")
        _ensure_tz(self.finished_at, "finished_at")

        if self.finished_at < self.started_at:
            msg = f"finished_at ({self.finished_at}) must be >= started_at ({self.started_at})"
            raise ValueError(msg)

        if self.duration_ms < 0:
            msg = f"duration_ms must be >= 0, got {self.duration_ms}"
            raise ValueError(msg)

        if self.status == RunStatus.SUCCESS and self.error_code != ErrorCode.OK:
            msg = f"SUCCESS status requires ErrorCode.OK, got {self.error_code.value}"
            raise ValueError(msg)

        if self.status != RunStatus.SUCCESS and self.error_code == ErrorCode.OK:
            msg = f"non-SUCCESS status ({self.status.value}) must not use ErrorCode.OK"
            raise ValueError(msg)

        if not is_json_serializable(dict(self.diagnostics)):
            msg = "diagnostics contains values that are not JSON-serializable"
            raise ValueError(msg)

        _seen_stages = set()
        for s in self.stages:
            if s.stage in _seen_stages:
                msg = f"duplicate stage in RunReport: {s.stage.value}"
                raise ValueError(msg)
            _seen_stages.add(s.stage)

    def to_json_encodable(self) -> dict[str, object]:
        """Return a JSON-encodable dictionary representing this report."""
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "orchestrator_version": self.orchestrator_version,
            "mode": self.mode,
            "status": self.status.value,
            "error_code": self.error_code.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_ms": self.duration_ms,
            "stages": [s.to_json_encodable() for s in self.stages],
            "diagnostics": dict(self.diagnostics),
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        encodable = self.to_json_encodable()
        return json.dumps(encodable, ensure_ascii=False, indent=2, sort_keys=True)
