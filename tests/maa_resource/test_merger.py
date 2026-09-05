"""MaaResource 覆盖合并的行为、边界与安全测试。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from autogame_orchestrator.config_model import MAAResourceMergeConfig
from autogame_orchestrator.maa_resource import (
    MAAResourceMergeErrorCode,
    MAAResourceMerger,
    MAAResourceMergeStatus,
)
from autogame_orchestrator.models import ErrorCode
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline


def _layout(root: Path) -> tuple[Path, Path, MAAResourceMergeConfig]:
    """构造 ``<root>/MaaResource/resource`` 与 ``<root>/resource`` 两个真实目录。"""
    source = root / "MaaResource" / "resource"
    destination = root / "resource"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    return (
        source,
        destination,
        MAAResourceMergeConfig(
            enabled=True,
            source_directory=str(source),
            destination_directory=str(destination),
        ),
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_disabled_merge_touches_nothing(tmp_path: Path) -> None:
    source, destination, config = _layout(tmp_path)
    _write(source / "infrast.json", "new")
    _write(destination / "infrast.json", "old")
    result = MAAResourceMerger(replace(config, enabled=False)).run()
    assert (result.status, result.error_code) == (MAAResourceMergeStatus.COMPLETED, MAAResourceMergeErrorCode.OK)
    assert result.files_scanned == 0
    assert result.changed is False
    assert (destination / "infrast.json").read_text(encoding="utf-8") == "old"


def test_differing_file_is_overwritten(tmp_path: Path) -> None:
    """核心行为：新版资源必须真正覆盖旧版，否则 CLI 侧叠加冲突不会消失。"""
    source, destination, config = _layout(tmp_path)
    _write(source / "infrast.json", "new-with-lappland")
    _write(destination / "infrast.json", "old")
    result = MAAResourceMerger(config).run()
    assert result.status == MAAResourceMergeStatus.COMPLETED
    assert (result.files_scanned, result.files_copied, result.files_identical) == (1, 1, 0)
    assert result.changed is True
    assert (destination / "infrast.json").read_text(encoding="utf-8") == "new-with-lappland"


def test_identical_file_is_skipped_without_write(tmp_path: Path) -> None:
    """8/01–8/23 期间两份资源逐字节相同；这种情况不应产生任何写入。"""
    source, destination, config = _layout(tmp_path)
    _write(source / "infrast.json", "same")
    _write(destination / "infrast.json", "same")
    before = (destination / "infrast.json").stat().st_mtime_ns
    result = MAAResourceMerger(config).run()
    assert (result.files_scanned, result.files_copied, result.files_identical) == (1, 0, 1)
    assert result.changed is False
    assert (destination / "infrast.json").stat().st_mtime_ns == before


def test_same_size_different_content_is_still_copied(tmp_path: Path) -> None:
    """大小相同但内容不同必须被识别；仅比较 size 会漏掉这种变更。"""
    source, destination, config = _layout(tmp_path)
    _write(source / "version.json", "AAAA")
    _write(destination / "version.json", "BBBB")
    result = MAAResourceMerger(config).run()
    assert result.files_copied == 1
    assert (destination / "version.json").read_text(encoding="utf-8") == "AAAA"


def test_new_nested_file_creates_directories(tmp_path: Path) -> None:
    """新版资源新增了 template/infrast 下的模板图，目标目录需按需创建。

    ``directories_created`` 记录的是「需要新建父目录的拷贝次数」，一次 mkdir
    可能一次性建出多层，因此这里是 1 而不是层数。
    """
    source, destination, config = _layout(tmp_path)
    _write(source / "template" / "infrast" / "Bskill_tra_lappland1.png", "binary")
    result = MAAResourceMerger(config).run()
    assert result.files_copied == 1
    assert result.directories_created == 1
    assert (destination / "template" / "infrast" / "Bskill_tra_lappland1.png").is_file()


def test_second_file_in_same_new_directory_is_not_counted_twice(tmp_path: Path) -> None:
    source, destination, config = _layout(tmp_path)
    _write(source / "template" / "infrast" / "one.png", "a")
    _write(source / "template" / "infrast" / "two.png", "b")
    result = MAAResourceMerger(config).run()
    assert result.files_copied == 2
    assert result.directories_created == 1


def test_destination_only_files_are_preserved(tmp_path: Path) -> None:
    """合并是覆盖而非镜像：core 自带的 onnx/OCR 等文件不得被删除。"""
    source, destination, config = _layout(tmp_path)
    _write(source / "infrast.json", "new")
    _write(destination / "config.json", "core-only")
    _write(destination / "onnx" / "model.onnx", "core-only")
    MAAResourceMerger(config).run()
    assert (destination / "config.json").read_text(encoding="utf-8") == "core-only"
    assert (destination / "onnx" / "model.onnx").is_file()


def test_bytes_and_counts_are_reported(tmp_path: Path) -> None:
    source, destination, config = _layout(tmp_path)
    _write(source / "a.json", "12345")
    _write(source / "b.json", "678")
    _write(destination / "b.json", "678")
    result = MAAResourceMerger(config).run()
    assert (result.files_scanned, result.files_copied, result.files_identical) == (2, 1, 1)
    assert result.bytes_copied == 5


def test_missing_source_is_reported(tmp_path: Path) -> None:
    _, destination, config = _layout(tmp_path)
    config = replace(config, source_directory=str(tmp_path / "absent"))
    result = MAAResourceMerger(config).run()
    assert (result.status, result.error_code) == (
        MAAResourceMergeStatus.FAILED,
        MAAResourceMergeErrorCode.SOURCE_NOT_FOUND,
    )


def test_missing_destination_is_reported(tmp_path: Path) -> None:
    """目标不存在意味着 MaaCore 未安装；此时不应擅自创建整棵资源树。"""
    source, _, config = _layout(tmp_path)
    _write(source / "infrast.json", "new")
    config = replace(config, destination_directory=str(tmp_path / "absent"))
    result = MAAResourceMerger(config).run()
    assert result.error_code == MAAResourceMergeErrorCode.DESTINATION_NOT_FOUND


def test_too_many_files_is_bounded(tmp_path: Path) -> None:
    source, _, config = _layout(tmp_path)
    for index in range(4):
        _write(source / f"{index}.json", str(index))
    result = MAAResourceMerger(replace(config, max_files=2)).run()
    assert result.error_code == MAAResourceMergeErrorCode.SOURCE_TOO_MANY_FILES


def test_oversized_file_is_bounded(tmp_path: Path) -> None:
    source, _, config = _layout(tmp_path)
    _write(source / "huge.json", "x" * 100)
    result = MAAResourceMerger(replace(config, max_file_bytes=10)).run()
    assert result.error_code == MAAResourceMergeErrorCode.SOURCE_FILE_TOO_LARGE


def test_pre_cancelled_run_copies_nothing(tmp_path: Path) -> None:
    source, destination, config = _layout(tmp_path)
    _write(source / "infrast.json", "new")
    _write(destination / "infrast.json", "old")
    token = CancellationToken()
    token.cancel()
    result = MAAResourceMerger(config).run(cancel=token)
    assert (result.status, result.error_code) == (
        MAAResourceMergeStatus.CANCELLED,
        MAAResourceMergeErrorCode.CANCELLED,
    )
    assert result.files_copied == 0
    assert (destination / "infrast.json").read_text(encoding="utf-8") == "old"


def test_expired_deadline_copies_nothing(tmp_path: Path) -> None:
    source, destination, config = _layout(tmp_path)
    _write(source / "infrast.json", "new")
    _write(destination / "infrast.json", "old")
    result = MAAResourceMerger(config).run(deadline=Deadline.after(0.0))
    assert (result.status, result.error_code) == (
        MAAResourceMergeStatus.TIMEOUT,
        MAAResourceMergeErrorCode.PARENT_DEADLINE,
    )
    assert (destination / "infrast.json").read_text(encoding="utf-8") == "old"


def test_no_temporary_files_are_left_behind(tmp_path: Path) -> None:
    source, destination, config = _layout(tmp_path)
    _write(source / "a" / "b.json", "new")
    MAAResourceMerger(config).run()
    leftovers = [path.name for path in destination.rglob("*") if path.name.startswith(".orchestratorrr")]
    assert leftovers == []


def test_result_never_contains_paths(tmp_path: Path) -> None:
    """结果只含计数与稳定错误码，不得泄漏本机路径。"""
    source, destination, config = _layout(tmp_path)
    _write(source / "infrast.json", "new")
    result = MAAResourceMerger(config).run()
    encoded = json.dumps(
        {
            "status": result.status.value,
            "error_code": result.error_code.value,
            "files_scanned": result.files_scanned,
            "files_copied": result.files_copied,
        },
        ensure_ascii=False,
    )
    assert str(tmp_path) not in encoded
    assert str(tmp_path) not in repr(result)


def test_invalid_configuration_is_rejected_before_any_scan(tmp_path: Path) -> None:
    source, _, config = _layout(tmp_path)
    _write(source / "infrast.json", "new")
    result = MAAResourceMerger(replace(config, destination_directory="")).run()
    assert result.error_code == MAAResourceMergeErrorCode.INVALID_CONFIGURATION
    assert result.files_scanned == 0


@pytest.mark.parametrize("field", ["max_files", "max_file_bytes", "timeout_seconds"])
def test_non_positive_bounds_are_schema_errors(field: str) -> None:
    config = MAAResourceMergeConfig(**{field: 0})  # type: ignore[arg-type]
    assert ErrorCode.CONFIG_SCHEMA_ERROR in config.validate()


def test_identical_source_and_destination_is_rejected(tmp_path: Path) -> None:
    shared = tmp_path / "resource"
    shared.mkdir()
    config = MAAResourceMergeConfig(
        enabled=True,
        source_directory=str(shared),
        destination_directory=str(shared),
    )
    assert ErrorCode.CONFIG_SCHEMA_ERROR in config.validate()


def test_nested_source_and_destination_is_rejected(tmp_path: Path) -> None:
    """源在目标之下会导致自我覆盖或无限递归，必须在校验期拒绝。"""
    destination = tmp_path / "resource"
    source = destination / "MaaResource" / "resource"
    source.mkdir(parents=True)
    config = MAAResourceMergeConfig(
        enabled=True,
        source_directory=str(source),
        destination_directory=str(destination),
    )
    assert ErrorCode.CONFIG_SCHEMA_ERROR in config.validate()


def test_disabled_configuration_skips_path_checks() -> None:
    assert MAAResourceMergeConfig().check_paths() == []


def test_enabled_configuration_reports_missing_directories(tmp_path: Path) -> None:
    config = MAAResourceMergeConfig(
        enabled=True,
        source_directory=str(tmp_path / "absent-source"),
        destination_directory=str(tmp_path / "absent-destination"),
    )
    assert config.check_paths() == [ErrorCode.CONFIG_PATH_NOT_FOUND, ErrorCode.CONFIG_PATH_NOT_FOUND]


def test_enabled_configuration_rejects_file_in_place_of_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    occupied = tmp_path / "occupied"
    occupied.write_text("not a directory", encoding="utf-8")
    config = MAAResourceMergeConfig(
        enabled=True,
        source_directory=str(source),
        destination_directory=str(occupied),
    )
    assert config.check_paths() == [ErrorCode.CONFIG_PATH_NOT_DIRECTORY]
