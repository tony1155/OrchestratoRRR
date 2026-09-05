"""Configuration dataclasses and static validation.

Unlike Pydantic, these are plain frozen dataclasses with explicit
validation functions — every error is mapped to a stable *ErrorCode*.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from autogame_orchestrator.models import ErrorCode

if TYPE_CHECKING:
    from pathlib import Path


_VALID_PATH_CHARS_RE = re.compile(r'^[^\x00-\x1f\x7f"*:<>?|]+$')


@dataclass(frozen=True)
class DefaultEntryPathIssue:
    """A stable field-only diagnostic for the strict default-entry policy."""

    field: str


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


class MumuLifecycleMode(StrEnum):
    """MuMu 生命周期的稳定管理模式。"""

    MANAGED = "managed"
    EXTERNAL = "external"


@dataclass(frozen=True)
class MuMuConfig:
    lifecycle_mode: MumuLifecycleMode = MumuLifecycleMode.MANAGED
    executable: str = ""
    adb_executable: str = ""
    adb_serial: str = "127.0.0.1:16384"
    start_timeout_seconds: int = 120
    stop_timeout_seconds: int = 20
    start_arguments: tuple[str, ...] = ()
    stop_arguments: tuple[str, ...] = ()

    def validate(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        if not isinstance(self.lifecycle_mode, MumuLifecycleMode):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
            return errors
        if not isinstance(self.executable, str):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        elif self.lifecycle_mode == MumuLifecycleMode.MANAGED:
            errors.extend(_validate_non_empty_str(self.executable, "executable"))
        for value in (self.adb_executable, self.adb_serial):
            if not isinstance(value, str) or not value.strip():
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        for timeout in (self.start_timeout_seconds, self.stop_timeout_seconds):
            if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        for arguments in (self.start_arguments, self.stop_arguments):
            if not isinstance(arguments, tuple) or not all(isinstance(item, str) for item in arguments):
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if self.lifecycle_mode == MumuLifecycleMode.EXTERNAL and (self.start_arguments or self.stop_arguments):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        return errors

    def check_paths(self) -> list[ErrorCode]:
        from pathlib import Path

        errors: list[ErrorCode] = []
        if self.lifecycle_mode == MumuLifecycleMode.MANAGED:
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
    arguments: tuple[str, ...] = ()
    environment_overrides: tuple[tuple[str, str], ...] = ()
    timeout_seconds: int = 1800
    stop_timeout_seconds: int = 10

    def validate(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        if not isinstance(self.executable, str):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        else:
            errors.extend(_validate_non_empty_str(self.executable, "executable"))
        if not isinstance(self.working_directory, str):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        else:
            errors.extend(_validate_non_empty_str(self.working_directory, "working_directory"))
        if not isinstance(self.arguments, tuple):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        else:
            for argument in self.arguments:
                if not isinstance(argument, str) or not argument.strip():
                    errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if not isinstance(self.environment_overrides, tuple):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        else:
            seen_keys: set[str] = set()
            for entry in self.environment_overrides:
                if not isinstance(entry, tuple) or len(entry) != 2:
                    errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
                    continue
                key, value = entry
                if not isinstance(key, str) or not key.strip() or not isinstance(value, str):
                    errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
                    continue
                folded = key.casefold()
                if folded in seen_keys:
                    errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
                seen_keys.add(folded)
        for timeout_value in (self.timeout_seconds, self.stop_timeout_seconds):
            if not isinstance(timeout_value, int) or isinstance(timeout_value, bool):
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
            else:
                errors.extend(_validate_positive_int(timeout_value, "timeout"))
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
class AALCConfig:
    executable: str = ""
    working_directory: str = ""
    arguments: tuple[str, ...] = ()
    environment_overrides: tuple[tuple[str, str], ...] = ()
    attempts: int = 3
    attempt_timeout_seconds: int = 7200
    stop_timeout_seconds: int = 10
    requires_administrator: bool = False

    def validate(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        if not isinstance(self.executable, str) or not self.executable.strip():
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if not isinstance(self.working_directory, str) or not self.working_directory.strip():
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if not isinstance(self.arguments, tuple):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        else:
            for argument in self.arguments:
                if not isinstance(argument, str) or not argument.strip():
                    errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if not isinstance(self.environment_overrides, tuple):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        else:
            seen_keys: set[str] = set()
            for entry in self.environment_overrides:
                if not isinstance(entry, tuple) or len(entry) != 2:
                    errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
                    continue
                key, value = entry
                if not isinstance(key, str) or not key.strip() or not isinstance(value, str):
                    errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
                    continue
                folded = key.casefold()
                if folded in seen_keys:
                    errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
                seen_keys.add(folded)
        if not isinstance(self.attempts, int) or isinstance(self.attempts, bool) or not 1 <= self.attempts <= 3:
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        for timeout_value in (self.attempt_timeout_seconds, self.stop_timeout_seconds):
            if not isinstance(timeout_value, int) or isinstance(timeout_value, bool) or timeout_value <= 0:
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if not isinstance(self.requires_administrator, bool):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
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
class MAASyncConfig:
    """MAA GUI 配置到 CLI 配置的安全同步契约。"""

    enabled: bool = False
    gui_settings_source: str = ""
    gui_tasks_source: str = ""
    cli_profile_destination: str = ""
    cli_tasks_destination: str = ""
    backup_enabled: bool = True
    max_source_bytes: int = 4 * 1024 * 1024
    requires_administrator: bool = False

    def validate(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        if not isinstance(self.enabled, bool):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if not isinstance(self.backup_enabled, bool):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if not isinstance(self.requires_administrator, bool):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if (
            not isinstance(self.max_source_bytes, int)
            or isinstance(self.max_source_bytes, bool)
            or self.max_source_bytes <= 0
        ):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if not isinstance(self.enabled, bool):
            return errors
        paths = (
            self.gui_settings_source,
            self.gui_tasks_source,
            self.cli_profile_destination,
            self.cli_tasks_destination,
        )
        if not self.enabled:
            return errors
        if any(not isinstance(value, str) or not value.strip() for value in paths):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
            return errors
        normalized = [os.path.normcase(os.path.abspath(value)) for value in paths]
        sources = normalized[:2]
        targets = normalized[2:]
        if sources[0] == sources[1] or targets[0] == targets[1]:
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if any(target in sources for target in targets):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        return errors

    def check_paths(self) -> list[ErrorCode]:
        from pathlib import Path

        if not self.enabled:
            return []
        errors: list[ErrorCode] = []
        for value in (self.gui_settings_source, self.gui_tasks_source):
            path = Path(value)
            if not path.exists():
                errors.append(ErrorCode.CONFIG_PATH_NOT_FOUND)
            elif not path.is_file():
                errors.append(ErrorCode.CONFIG_PATH_NOT_FILE)
        for value in (self.cli_profile_destination, self.cli_tasks_destination):
            path = Path(value)
            if path.exists() and not path.is_file():
                errors.append(ErrorCode.CONFIG_PATH_NOT_FILE)
        return errors


@dataclass(frozen=True)
class MAAResourceMergeConfig:
    """把 MaaResource 增量资源覆盖合并进 MaaCore 共用资源目录的契约。

    ``maa update`` 只把 MaaResource 仓库 ``git pull`` 到 ``<data>/MaaResource``，
    不会并入随 MaaCore 安装的 ``<data>/resource``。maa-cli 随后让 MaaCore 依次加载
    这两个目录，而 ``InfrastConfig::parse`` 用 ``emplace`` 装填技能表（对已存在的
    key 不覆盖）、再用 ``.at()`` 解析 ``skillsGroup``；因此当新版资源引入「新
    skillsGroup 引用新技能」时，第二遍加载会命中第一遍的旧表并抛
    ``std::out_of_range``，资源加载整体失败。MAA GUI 因为是就地合并成单一份资源
    才不受影响。本阶段复刻 GUI 的合并动作，消除该叠加冲突。

    默认关闭。启用后会写入与 MAA GUI 共用的资源目录，因此逐文件采用「同目录临时
    文件 + fsync + ``os.replace``」提交，且内容相同的文件直接跳过、不产生写入。
    """

    enabled: bool = False
    source_directory: str = ""
    destination_directory: str = ""
    max_files: int = 20000
    max_file_bytes: int = 64 * 1024 * 1024
    timeout_seconds: int = 600

    def validate(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        if not isinstance(self.enabled, bool):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        for value in (self.max_files, self.max_file_bytes, self.timeout_seconds):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if not isinstance(self.enabled, bool) or not self.enabled:
            return errors
        paths = (self.source_directory, self.destination_directory)
        if any(not isinstance(value, str) or not value.strip() for value in paths):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
            return errors
        normalized = [os.path.normcase(os.path.abspath(value)) for value in paths]
        if normalized[0] == normalized[1]:
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        # 源与目标互为祖先时，合并会自我递归或自我覆盖。
        for first, second in (normalized, normalized[::-1]):
            if second.startswith(first + os.sep):
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
                break
        return errors

    def check_paths(self) -> list[ErrorCode]:
        from pathlib import Path

        if not self.enabled:
            return []
        errors: list[ErrorCode] = []
        for value in (self.source_directory, self.destination_directory):
            path = Path(value)
            if not path.exists():
                errors.append(ErrorCode.CONFIG_PATH_NOT_FOUND)
            elif not path.is_dir():
                errors.append(ErrorCode.CONFIG_PATH_NOT_DIRECTORY)
        return errors


@dataclass(frozen=True)
class MAAUpdateConfig:
    """仅允许 MaaCore/资源 update 的安全配置。

    默认关闭，且在 `run` 入口仍被闸门阻断。阻断理由与安全余量：

    maa-cli 的下载环节是安全的（``.partial`` 临时文件 + ``rename``，并带校验和），
    但解压环节非原子：``maa-installer`` 的 ``extract.rs`` 逐文件 ``File::create`` +
    ``io::copy`` 原地覆盖，未使用该项目自有的 ``atomic_fs``，且两个安装器
    （maa_core / resource）均无备份与回滚。因此解压中途被中止时，资源目录会
    停在“部分新版 + 一个被截断文件 + 部分旧版”的混杂状态；若该资源目录与
    MAA GUI 共用，坏状态会同时注入 GUI。

    默认超时取 3600 而非 1800：官方整包为 260 MB 量级、解压为数千文件，较大的
    预算可降低被超时强行终止而留下坏资源的概率。超时并非安全保证，仅为降低风险。
    """

    enabled: bool = False
    allow_network: bool = False
    requires_administrator: bool = False
    arguments: tuple[str, ...] = ("update",)
    timeout_seconds: int = 3600

    def validate(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        for value in (self.enabled, self.allow_network, self.requires_administrator):
            if not isinstance(value, bool):
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if (
            not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if not isinstance(self.arguments, (tuple, list)) or not self.arguments or len(self.arguments) > 16:
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        else:
            forbidden = {"self", "hot-update", "install", "run", "task"}
            for argument in self.arguments:
                if (
                    not isinstance(argument, str)
                    or not argument
                    or len(argument) > 512
                    or any(ord(char) < 32 or ord(char) == 127 for char in argument)
                    or argument.casefold() in forbidden
                ):
                    errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
            if self.arguments[0] != "update":
                errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        if isinstance(self.enabled, bool) and self.enabled and self.allow_network is not True:
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        return errors


@dataclass(frozen=True)
class AppConfig:
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    mumu: MuMuConfig = field(default_factory=MuMuConfig)
    starrail: StarRailConfig = field(default_factory=StarRailConfig)
    maa: MAAConfig = field(default_factory=MAAConfig)
    maa_sync: MAASyncConfig = field(default_factory=MAASyncConfig)
    maa_update: MAAUpdateConfig = field(default_factory=MAAUpdateConfig)
    maa_resource_merge: MAAResourceMergeConfig = field(default_factory=MAAResourceMergeConfig)
    aalc: AALCConfig = field(default_factory=AALCConfig)

    def validate(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        errors.extend(self.orchestrator.validate())
        errors.extend(self.mumu.validate())
        errors.extend(self.starrail.validate())
        errors.extend(self.maa.validate())
        errors.extend(self.maa_sync.validate())
        errors.extend(self.maa_update.validate())
        errors.extend(self.maa_resource_merge.validate())
        return errors

    def check_paths(self) -> list[ErrorCode]:
        errors: list[ErrorCode] = []
        errors.extend(self.mumu.check_paths())
        errors.extend(self.starrail.check_paths())
        errors.extend(self.maa.check_paths())
        errors.extend(self.maa_sync.check_paths())
        errors.extend(self.maa_resource_merge.check_paths())
        return errors

    def check_default_entry_paths(
        self,
        *,
        canonical_log_directory: Path,
        canonical_report_directory: Path,
    ) -> tuple[DefaultEntryPathIssue, ...]:
        """Require deterministic absolute paths for the interactive default entry."""
        from pathlib import Path

        issues: list[DefaultEntryPathIssue] = []

        def require_absolute(field_name: str, value: str, *, allow_empty: bool = False) -> None:
            if allow_empty and not value:
                return
            try:
                absolute = bool(value) and Path(value).is_absolute()
            except (OSError, ValueError):
                absolute = False
            if not absolute:
                issues.append(DefaultEntryPathIssue(field_name))

        def require_canonical(field_name: str, value: str, expected: Path) -> None:
            require_absolute(field_name, value)
            if issues and issues[-1].field == field_name:
                return
            try:
                matches = Path(value).resolve(strict=False) == expected.resolve(strict=False)
            except (OSError, ValueError):
                matches = False
            if not matches:
                issues.append(DefaultEntryPathIssue(field_name))

        require_canonical("orchestrator.log_dir", self.orchestrator.log_dir, canonical_log_directory)
        require_canonical("orchestrator.report_dir", self.orchestrator.report_dir, canonical_report_directory)
        require_absolute(
            "mumu.executable",
            self.mumu.executable,
            allow_empty=self.mumu.lifecycle_mode == MumuLifecycleMode.EXTERNAL,
        )
        require_absolute("mumu.adb_executable", self.mumu.adb_executable)
        require_absolute("starrail.executable", self.starrail.executable)
        require_absolute("starrail.working_directory", self.starrail.working_directory)
        require_absolute("starrail.log_path_template", self.starrail.log_path_template.replace("{date}", "2000-01-01"))
        require_absolute("maa.executable", self.maa.executable)
        require_absolute("maa.working_directory", self.maa.working_directory)
        sync_paths = (
            ("maa_sync.gui_settings_source", self.maa_sync.gui_settings_source),
            ("maa_sync.gui_tasks_source", self.maa_sync.gui_tasks_source),
            ("maa_sync.cli_profile_destination", self.maa_sync.cli_profile_destination),
            ("maa_sync.cli_tasks_destination", self.maa_sync.cli_tasks_destination),
        )
        for field_name, value in sync_paths:
            require_absolute(field_name, value, allow_empty=not self.maa_sync.enabled)
        return tuple(issues)
