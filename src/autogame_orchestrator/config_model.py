"""Configuration dataclasses and static validation.

Unlike Pydantic, these are plain frozen dataclasses with explicit
validation functions — every error is mapped to a stable *ErrorCode*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from autogame_orchestrator.models import ErrorCode

if TYPE_CHECKING:
    from pathlib import Path


_VALID_PATH_CHARS_RE = re.compile(r'^[^\x00-\x1f\x7f"*:<>?|]+$')


def _validate_path_shape(value: str, label: str) -> list[ErrorCode]:
    errors: list[ErrorCode] = []
    if not value.strip():
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        return errors
    if not _VALID_PATH_CHARS_RE.match(value):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
    return errors


def _validate_positive_int(value: int, label: str, max_val: int | None = None) -> list[ErrorCode]:
    errors: list[ErrorCode] = []
    if value <= 0:
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
    if max_val is not None and value > max_val:
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
    return errors


def _validate_non_empty_str(value: str, label: str) -> list[ErrorCode]:
    if not value.strip():
        return [ErrorCode.CONFIG_SCHEMA_ERROR]
    return []


def _validate_str_list(value: object, label: str) -> list[ErrorCode]:
    if not isinstance(value, list):
        return [ErrorCode.CONFIG_SCHEMA_ERROR]
    if not all(isinstance(item, str) for item in value):
        return [ErrorCode.CONFIG_SCHEMA_ERROR]
    return []


def _check_required_path(path: Path, label: str) -> list[ErrorCode]:
    """Check that *path* exists and is the expected type.

    Only called when ``--check-paths`` is active.
    """
    errors: list[ErrorCode] = []
    if not path.exists():
        errors.append(ErrorCode.CONFIG_PATH_NOT_FOUND)
    return errors


@dataclass(frozen=True)
class OrchestratorConfig:
    log_dir: str = "logs"
    report_dir: str = "run-results"
    heartbeat_interval_seconds: int = 10
    poll_interval_seconds: int = 1

    def validate(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        errors.extend(_validate_non_empty_str(self.log_dir, "log_dir"))
        errors.extend(_validate_non_empty_str(self.report_dir, "report_dir"))
        errors.extend(_validate_positive_int(self.heartbeat_interval_seconds, "heartbeat_interval_seconds"))
        errors.extend(_validate_positive_int(self.poll_interval_seconds, "poll_interval_seconds"))
        if self.heartbeat_interval_seconds < self.poll_interval_seconds:
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        return errors


@dataclass(frozen=True)
class MuMuConfig:
    executable: str = ""
    adb_executable: str = ""
    adb_serial: str = "127.0.0.1:16384"
    start_timeout_seconds: int = 120
    stop_timeout_seconds: int = 20
    start_arguments: tuple[str, ...] = ()
    stop_arguments: tuple[str, ...] = ()

    def validate(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        errors.extend(_validate_non_empty_str(self.executable, "executable"))
        errors.extend(_validate_non_empty_str(self.adb_executable, "adb_executable"))
        errors.extend(_validate_non_empty_str(self.adb_serial, "adb_serial"))
        errors.extend(_validate_positive_int(self.start_timeout_seconds, "start_timeout_seconds"))
        errors.extend(_validate_positive_int(self.stop_timeout_seconds, "stop_timeout_seconds"))
        if self.start_arguments:
            errors.extend(_validate_str_list(list(self.start_arguments), "start_arguments"))
        if self.stop_arguments:
            errors.extend(_validate_str_list(list(self.stop_arguments), "stop_arguments"))
        return errors

    def check_paths(self) -> list[ErrorCode]:
        from pathlib import Path

        errors: list[ErrorCode] = []
        errors.extend(_check_required_path(Path(self.executable), "executable"))
        errors.extend(_check_required_path(Path(self.adb_executable), "adb_executable"))
        return errors


@dataclass(frozen=True)
class StarRailConfig:
    executable: str = ""
    working_directory: str = ""
    arguments: tuple[str, ...] = ()
    log_path_template: str = ""
    success_keywords: tuple[str, ...] = (
        "No task pending",
        "for task `Restart`",
    )
    failure_keywords: tuple[str, ...] = (
        "ScriptError:",
        "Request human takeover",
        "Retry screenshot() failed",
        "NemuIpcError",
    )
    environment_overrides: tuple[tuple[str, str], ...] = (("PYTHONIOENCODING", "utf-8"),)
    task_timeout_seconds: int = 3600
    stop_timeout_seconds: int = 10

    def validate(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        errors.extend(_validate_non_empty_str(self.executable, "executable"))
        errors.extend(_validate_non_empty_str(self.working_directory, "working_directory"))
        if not self.arguments:
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        for _i, arg in enumerate(self.arguments):
            if not isinstance(arg, str) or not arg.strip():
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        errors.extend(_validate_non_empty_str(self.log_path_template, "log_path_template"))
        rendered = self.log_path_template.replace("{date}", "2026-07-21")
        if "{" in rendered or "}" in rendered:
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if not self.success_keywords:
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        for kw in self.success_keywords:
            if not isinstance(kw, str) or not kw.strip():
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        for kw in self.failure_keywords:
            if not isinstance(kw, str) or not kw.strip():
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        seen_keys: set[str] = set()
        for entry in self.environment_overrides:
            if not isinstance(entry, tuple) or len(entry) != 2:
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
                continue
            key, value = entry
            if not isinstance(key, str) or not key.strip():
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
                continue
            if not isinstance(value, str):
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
            folded = key.casefold()
            if folded in seen_keys:
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
            seen_keys.add(folded)
        errors.extend(_validate_positive_int(self.task_timeout_seconds, "task_timeout_seconds"))
        errors.extend(_validate_positive_int(self.stop_timeout_seconds, "stop_timeout_seconds"))
        return errors

    def check_paths(self) -> list[ErrorCode]:
        from pathlib import Path

        errors: list[ErrorCode] = []

        executable = Path(self.executable)
        if not executable.exists():
            errors.append(ErrorCode.CONFIG_PATH_NOT_FOUND)
        elif not executable.is_file():
            errors.append(ErrorCode.CONFIG_PATH_NOT_FILE)

        working_directory = Path(self.working_directory)
        if not working_directory.exists():
            errors.append(ErrorCode.CONFIG_PATH_NOT_FOUND)
        elif not working_directory.is_dir():
            errors.append(ErrorCode.CONFIG_PATH_NOT_DIRECTORY)

        return errors


@dataclass(frozen=True)
class MAAConfig:
    executable: str = ""
    working_directory: str = ""
    timeout_seconds: int = 1800

    def validate(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        errors.extend(_validate_non_empty_str(self.executable, "executable"))
        errors.extend(_validate_non_empty_str(self.working_directory, "working_directory"))
        errors.extend(_validate_positive_int(self.timeout_seconds, "timeout_seconds"))
        return errors

    def check_paths(self) -> list[ErrorCode]:
        from pathlib import Path

        errors: list[ErrorCode] = []
        errors.extend(_check_required_path(Path(self.executable), "executable"))
        errors.extend(_check_required_path(Path(self.working_directory), "working_directory"))
        return errors


@dataclass(frozen=True)
class AALCConfig:
    executable: str = ""
    working_directory: str = ""
    attempts: int = 3
    attempt_timeout_seconds: int = 7200

    def validate(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        errors.extend(_validate_non_empty_str(self.executable, "executable"))
        errors.extend(_validate_non_empty_str(self.working_directory, "working_directory"))
        if self.attempts < 1 or self.attempts > 3:
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        errors.extend(_validate_positive_int(self.attempt_timeout_seconds, "attempt_timeout_seconds"))
        return errors

    def check_paths(self) -> list[ErrorCode]:
        from pathlib import Path

        errors: list[ErrorCode] = []
        errors.extend(_check_required_path(Path(self.executable), "executable"))
        errors.extend(_check_required_path(Path(self.working_directory), "working_directory"))
        return errors


@dataclass(frozen=True)
class AppConfig:
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    mumu: MuMuConfig = field(default_factory=MuMuConfig)
    starrail: StarRailConfig = field(default_factory=StarRailConfig)
    maa: MAAConfig = field(default_factory=MAAConfig)
    aalc: AALCConfig = field(default_factory=AALCConfig)

    def validate(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        errors.extend(self.orchestrator.validate())
        errors.extend(self.mumu.validate())
        errors.extend(self.starrail.validate())
        errors.extend(self.maa.validate())
        errors.extend(self.aalc.validate())
        return errors

    def check_paths(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        errors.extend(self.mumu.check_paths())
        errors.extend(self.starrail.check_paths())
        errors.extend(self.maa.check_paths())
        errors.extend(self.aalc.check_paths())
        return errors
