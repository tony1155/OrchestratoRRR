"""将 MaaResource 增量资源覆盖合并进 MaaCore 共用资源目录。

背景（为什么需要这一步）：

``maa update`` 会把 MaaResource 仓库 ``git pull`` 到 ``<data>/MaaResource``，但
**不会**把它合并进随 MaaCore 安装的 ``<data>/resource``。maa-cli 随后按
``resource`` → ``MaaResource/resource`` → ``cache/resource`` 顺序对同一个
MaaCore 单例连续调用 ``AsstLoadResource``；而 MaaCore 的 ``InfrastConfig::parse``
用 ``m_skills.emplace(facility, ...)`` 装填技能表——``emplace`` 对已存在的 key
静默不覆盖，随后解析 ``skillsGroup`` 时又用 ``.at()`` 查找技能 id。于是当新版
资源新增了「新 skillsGroup 引用新技能」的组合时，第二遍加载会命中第一遍留下的
旧技能表，``.at()`` 抛 ``std::out_of_range``，整个资源加载失败，maa-cli 以退出码
1 结束。

MAA GUI 不受影响，因为它更新资源时是把增量包 ``DirectoryMerge`` 就地并入自己的
``resource``，全程只有一份 ``infrast.json``，只解析一次。

本模块做的就是 GUI 那个合并动作，让 CLI 侧也只存在一份自洽资源，从而消除叠加
顺序带来的这类冲突。合并是覆盖式的：源文件内容不同则原子替换目标，相同则跳过。
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from autogame_orchestrator.config_model import MAAResourceMergeConfig
from autogame_orchestrator.maa_resource.models import (
    MAAResourceMergeErrorCode,
    MAAResourceMergeResult,
    MAAResourceMergeStatus,
)
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline

_COMPARE_CHUNK_BYTES = 256 * 1024
_CONTROL_CHECK_INTERVAL = 64


class _MergeFailure(Exception):
    def __init__(self, code: MAAResourceMergeErrorCode) -> None:
        self.code = code


class _BinarySyncStream(Protocol):
    def write(self, data: bytes) -> int: ...

    def flush(self) -> None: ...

    def fileno(self) -> int: ...


@dataclass(frozen=True)
class _PendingCopy:
    relative: Path
    size: int


def _write_and_sync(stream: _BinarySyncStream, data: bytes) -> None:
    stream.write(data)
    stream.flush()
    os.fsync(stream.fileno())


def _digest(path: Path, *, chunk: int = _COMPARE_CHUNK_BYTES) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(chunk)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


class MAAResourceMerger:
    """单次覆盖合并；不执行外部程序，不联网，也不提供重试。"""

    def __init__(self, config: MAAResourceMergeConfig) -> None:
        self._config = config

    def run(
        self,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
    ) -> MAAResourceMergeResult:
        started_at = datetime.now(UTC)
        started_monotonic = time.monotonic()
        state = {
            "files_scanned": 0,
            "files_copied": 0,
            "files_identical": 0,
            "bytes_copied": 0,
            "directories_created": 0,
        }

        def result(
            status: MAAResourceMergeStatus,
            code: MAAResourceMergeErrorCode,
        ) -> MAAResourceMergeResult:
            return MAAResourceMergeResult.from_monotonic(
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
            return result(MAAResourceMergeStatus.COMPLETED, MAAResourceMergeErrorCode.OK)
        if self._config.validate():
            return result(MAAResourceMergeStatus.FAILED, MAAResourceMergeErrorCode.INVALID_CONFIGURATION)

        source_root = Path(self._config.source_directory)
        destination_root = Path(self._config.destination_directory)
        temporary_paths: list[Path] = []
        try:
            if not source_root.is_dir():
                raise _MergeFailure(MAAResourceMergeErrorCode.SOURCE_NOT_FOUND)
            if not destination_root.is_dir():
                raise _MergeFailure(MAAResourceMergeErrorCode.DESTINATION_NOT_FOUND)

            pending: list[_PendingCopy] = []
            for index, entry in enumerate(self._iter_source_files(source_root)):
                state["files_scanned"] += 1
                if state["files_scanned"] > self._config.max_files:
                    raise _MergeFailure(MAAResourceMergeErrorCode.SOURCE_TOO_MANY_FILES)
                if index % _CONTROL_CHECK_INTERVAL == 0:
                    control = self._control(deadline, cancel)
                    if control is not None:
                        return result(*control)
                relative, size = entry
                if size > self._config.max_file_bytes:
                    raise _MergeFailure(MAAResourceMergeErrorCode.SOURCE_FILE_TOO_LARGE)
                if self._is_identical(source_root / relative, destination_root / relative, size):
                    state["files_identical"] += 1
                    continue
                pending.append(_PendingCopy(relative, size))

            for index, item in enumerate(pending):
                if index % _CONTROL_CHECK_INTERVAL == 0:
                    control = self._control(deadline, cancel)
                    if control is not None:
                        return result(*control)
                created = self._copy_atomic(
                    source_root / item.relative,
                    destination_root / item.relative,
                    temporary_paths,
                )
                state["files_copied"] += 1
                state["bytes_copied"] += item.size
                state["directories_created"] += created
            return result(MAAResourceMergeStatus.COMPLETED, MAAResourceMergeErrorCode.OK)
        except _MergeFailure as exc:
            return result(MAAResourceMergeStatus.FAILED, exc.code)
        except Exception:
            return result(MAAResourceMergeStatus.FAILED, MAAResourceMergeErrorCode.INTERNAL_ERROR)
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
    ) -> tuple[MAAResourceMergeStatus, MAAResourceMergeErrorCode] | None:
        if cancel is not None and cancel.is_cancelled:
            return MAAResourceMergeStatus.CANCELLED, MAAResourceMergeErrorCode.CANCELLED
        if deadline is not None and deadline.expired:
            return MAAResourceMergeStatus.TIMEOUT, MAAResourceMergeErrorCode.PARENT_DEADLINE
        return None

    def _iter_source_files(self, source_root: Path) -> Iterator[tuple[Path, int]]:
        """深度优先枚举普通文件；跳过符号链接与越界路径。"""
        try:
            resolved_root = source_root.resolve(strict=True)
        except OSError as exc:
            raise _MergeFailure(MAAResourceMergeErrorCode.SOURCE_NOT_FOUND) from exc
        stack = [resolved_root]
        while stack:
            current = stack.pop()
            try:
                entries = sorted(os.scandir(current), key=lambda item: item.name)
            except OSError as exc:
                raise _MergeFailure(MAAResourceMergeErrorCode.SOURCE_SCAN_FAILED) from exc
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir():
                        stack.append(Path(entry.path))
                        continue
                    if not entry.is_file():
                        continue
                    size = entry.stat().st_size
                except OSError as exc:
                    raise _MergeFailure(MAAResourceMergeErrorCode.SOURCE_SCAN_FAILED) from exc
                candidate = Path(entry.path)
                try:
                    relative = candidate.relative_to(resolved_root)
                except ValueError:
                    continue
                yield relative, size

    def _is_identical(self, source: Path, destination: Path, size: int) -> bool:
        try:
            target_stat = destination.stat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _MergeFailure(MAAResourceMergeErrorCode.TARGET_WRITE_FAILED) from exc
        if not destination.is_file() or destination.is_symlink():
            return False
        if target_stat.st_size != size:
            return False
        try:
            return _digest(source) == _digest(destination)
        except OSError as exc:
            raise _MergeFailure(MAAResourceMergeErrorCode.SOURCE_READ_FAILED) from exc

    def _copy_atomic(self, source: Path, destination: Path, temporary_paths: list[Path]) -> int:
        """先写同目录临时文件并 fsync，再 ``os.replace`` 原子提交。"""
        created = 0
        parent = destination.parent
        if not parent.is_dir():
            try:
                parent.mkdir(parents=True, exist_ok=True)
                created = 1
            except OSError as exc:
                raise _MergeFailure(MAAResourceMergeErrorCode.TARGET_WRITE_FAILED) from exc
        try:
            data = source.read_bytes()
        except OSError as exc:
            raise _MergeFailure(MAAResourceMergeErrorCode.SOURCE_READ_FAILED) from exc
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                prefix=".orchestratorrr-maa-resource-",
                suffix=".tmp",
                dir=parent,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                temporary_paths.append(temporary)
                _write_and_sync(stream, data)
            os.replace(temporary, destination)
            temporary_paths.remove(temporary)
        except OSError as exc:
            raise _MergeFailure(MAAResourceMergeErrorCode.TARGET_WRITE_FAILED) from exc
        return created
