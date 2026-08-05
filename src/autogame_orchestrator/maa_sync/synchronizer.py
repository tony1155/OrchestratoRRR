"""有界读取、原子替换与双目标回滚实现。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from autogame_orchestrator.config_model import MAASyncConfig
from autogame_orchestrator.maa_sync.models import MAASyncErrorCode, MAASyncResult, MAASyncStatus
from autogame_orchestrator.maa_sync.transformer import MAATransformError, transform_gui_configuration
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline


class _SyncFailure(Exception):
    def __init__(self, code: MAASyncErrorCode) -> None:
        self.code = code


class _BinarySyncStream(Protocol):
    def write(self, data: bytes) -> int: ...

    def flush(self) -> None: ...

    def fileno(self) -> int: ...


def _replace_file(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _write_and_sync(stream: _BinarySyncStream, data: bytes) -> None:
    stream.write(data)
    stream.flush()
    os.fsync(stream.fileno())


class MAASynchronizer:
    """单次安全同步器；不执行外部程序，也不提供重试。"""

    def __init__(self, config: MAASyncConfig) -> None:
        self._config = config

    def run(
        self,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
    ) -> MAASyncResult:
        started_at = datetime.now(UTC)
        started_monotonic = time.monotonic()
        state = {
            "changed": False,
            "profile_written": False,
            "tasks_written": False,
            "profile_backup_written": False,
            "tasks_backup_written": False,
            "rollback_attempted": False,
            "rollback_succeeded": False,
        }

        def result(status: MAASyncStatus, code: MAASyncErrorCode) -> MAASyncResult:
            return MAASyncResult.from_monotonic(
                status=status,
                error_code=code,
                started_at=started_at,
                started_monotonic=started_monotonic,
                enabled=self._config.enabled,
                **state,
            )

        control = self._control(deadline, cancel)
        if control is not None:
            return result(*control)
        if not self._config.enabled:
            return result(MAASyncStatus.COMPLETED, MAASyncErrorCode.OK)
        if self._config.validate():
            return result(MAASyncStatus.FAILED, MAASyncErrorCode.INVALID_CONFIGURATION)

        temporary_paths: list[Path] = []
        try:
            settings = self._read_source(Path(self._config.gui_settings_source))
            control = self._control(deadline, cancel)
            if control is not None:
                return result(*control)
            tasks = self._read_source(Path(self._config.gui_tasks_source))
            control = self._control(deadline, cancel)
            if control is not None:
                return result(*control)
            try:
                profile_object, tasks_object = transform_gui_configuration(settings, tasks)
            except MAATransformError as exc:
                raise _SyncFailure(MAASyncErrorCode.TRANSFORM_FAILED) from exc
            control = self._control(deadline, cancel)
            if control is not None:
                return result(*control)
            profile_bytes = self._encode(profile_object)
            tasks_bytes = self._encode(tasks_object)
            profile_target = Path(self._config.cli_profile_destination)
            tasks_target = Path(self._config.cli_tasks_destination)
            profile_original = self._read_target(profile_target)
            tasks_original = self._read_target(tasks_target)
            profile_changed = profile_original != profile_bytes
            tasks_changed = tasks_original != tasks_bytes
            state["changed"] = profile_changed or tasks_changed
            if not state["changed"]:
                return result(MAASyncStatus.COMPLETED, MAASyncErrorCode.OK)
            control = self._control(deadline, cancel)
            if control is not None:
                return result(*control)
            try:
                profile_target.parent.mkdir(parents=True, exist_ok=True)
                tasks_target.parent.mkdir(parents=True, exist_ok=True)
                profile_temp = (
                    self._prepare_temp(profile_target, profile_bytes, temporary_paths) if profile_changed else None
                )
                tasks_temp = self._prepare_temp(tasks_target, tasks_bytes, temporary_paths) if tasks_changed else None
                if self._config.backup_enabled:
                    if profile_changed and profile_original is not None:
                        self._write_atomic_backup(profile_target, profile_original, temporary_paths)
                        state["profile_backup_written"] = True
                    if tasks_changed and tasks_original is not None:
                        self._write_atomic_backup(tasks_target, tasks_original, temporary_paths)
                        state["tasks_backup_written"] = True
            except OSError as exc:
                raise _SyncFailure(MAASyncErrorCode.TARGET_PREPARE_FAILED) from exc
            control = self._control(deadline, cancel)
            if control is not None:
                return result(*control)
            profile_replaced = False
            if profile_temp is not None:
                try:
                    _replace_file(profile_temp, profile_target)
                    temporary_paths.remove(profile_temp)
                    profile_replaced = True
                    state["profile_written"] = True
                except OSError as exc:
                    raise _SyncFailure(MAASyncErrorCode.TARGET_WRITE_FAILED) from exc
            control = self._control(deadline, cancel)
            if control is not None:
                if profile_replaced and tasks_temp is not None:
                    if not self._rollback(profile_target, profile_original, temporary_paths):
                        state["rollback_attempted"] = True
                        return result(MAASyncStatus.FAILED, MAASyncErrorCode.ROLLBACK_FAILED)
                    state["rollback_attempted"] = True
                    state["rollback_succeeded"] = True
                return result(*control)
            if tasks_temp is not None:
                try:
                    _replace_file(tasks_temp, tasks_target)
                    temporary_paths.remove(tasks_temp)
                    state["tasks_written"] = True
                except OSError:
                    if profile_replaced:
                        state["rollback_attempted"] = True
                        state["rollback_succeeded"] = self._rollback(profile_target, profile_original, temporary_paths)
                        code = (
                            MAASyncErrorCode.TARGET_WRITE_FAILED
                            if state["rollback_succeeded"]
                            else MAASyncErrorCode.ROLLBACK_FAILED
                        )
                        return result(MAASyncStatus.FAILED, code)
                    return result(MAASyncStatus.FAILED, MAASyncErrorCode.TARGET_WRITE_FAILED)
            return result(MAASyncStatus.COMPLETED, MAASyncErrorCode.OK)
        except _SyncFailure as exc:
            return result(MAASyncStatus.FAILED, exc.code)
        except Exception:
            return result(MAASyncStatus.FAILED, MAASyncErrorCode.INTERNAL_ERROR)
        finally:
            for path in temporary_paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _control(
        deadline: Deadline | None,
        cancel: CancellationToken | None,
    ) -> tuple[MAASyncStatus, MAASyncErrorCode] | None:
        if cancel is not None and cancel.is_cancelled:
            return MAASyncStatus.CANCELLED, MAASyncErrorCode.CANCELLED
        if deadline is not None and deadline.expired:
            return MAASyncStatus.TIMEOUT, MAASyncErrorCode.PARENT_DEADLINE
        return None

    def _read_source(self, path: Path) -> dict[str, object]:
        try:
            with path.open("rb") as stream:
                data = stream.read(self._config.max_source_bytes + 1)
        except FileNotFoundError as exc:
            raise _SyncFailure(MAASyncErrorCode.SOURCE_NOT_FOUND) from exc
        except OSError as exc:
            raise _SyncFailure(MAASyncErrorCode.SOURCE_READ_FAILED) from exc
        if len(data) > self._config.max_source_bytes:
            raise _SyncFailure(MAASyncErrorCode.SOURCE_TOO_LARGE)
        try:
            parsed = json.loads(data.decode("utf-8-sig", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _SyncFailure(MAASyncErrorCode.SOURCE_PARSE_FAILED) from exc
        if not isinstance(parsed, dict):
            raise _SyncFailure(MAASyncErrorCode.SOURCE_PARSE_FAILED)
        return parsed

    def _read_target(self, path: Path) -> bytes | None:
        try:
            with path.open("rb") as stream:
                data = stream.read(self._config.max_source_bytes + 1)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise _SyncFailure(MAASyncErrorCode.TARGET_PREPARE_FAILED) from exc
        if len(data) > self._config.max_source_bytes:
            raise _SyncFailure(MAASyncErrorCode.TARGET_PREPARE_FAILED)
        return data

    @staticmethod
    def _encode(value: dict[str, object]) -> bytes:
        try:
            return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise _SyncFailure(MAASyncErrorCode.TRANSFORM_FAILED) from exc

    @staticmethod
    def _prepare_temp(target: Path, data: bytes, temporary_paths: list[Path]) -> Path:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=".orchestratorrr-maa-sync-",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as stream:
            path = Path(stream.name)
            temporary_paths.append(path)
            _write_and_sync(stream, data)
        return path

    def _write_atomic_backup(self, target: Path, data: bytes, temporary_paths: list[Path]) -> None:
        backup = target.with_name(target.name + ".bak")
        temporary = self._prepare_temp(backup, data, temporary_paths)
        _replace_file(temporary, backup)
        temporary_paths.remove(temporary)

    def _rollback(self, target: Path, original: bytes | None, temporary_paths: list[Path]) -> bool:
        try:
            if original is None:
                target.unlink(missing_ok=True)
            else:
                temporary = self._prepare_temp(target, original, temporary_paths)
                _replace_file(temporary, target)
                temporary_paths.remove(temporary)
        except OSError:
            return False
        return True
