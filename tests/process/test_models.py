"""ProcessSpec 单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from autogame_orchestrator.process.models import ProcessSpec


def test_valid_spec() -> None:
    """合法 spec 构造成功。"""
    s = ProcessSpec(
        name="测试进程",
        executable=Path("C:/python.exe"),
        arguments=("--version",),
    )
    assert s.name == "测试进程"
    assert s.executable == Path("C:/python.exe")
    assert s.arguments == ("--version",)
    assert s.inherit_parent_environment is True
    assert s.create_new_process_group is False


def test_empty_name_rejected() -> None:
    """空 name 被拒绝。"""
    with pytest.raises(ValueError, match="name 不能为空"):
        ProcessSpec(name="", executable=Path("notepad.exe"))


def test_empty_executable_rejected() -> None:
    """空 executable 被拒绝。"""
    # Path("") resolves to ".", so use a path that is trivially not-existent
    # but also verify the spec validation rejects truly empty strings
    with pytest.raises(ValueError, match="executable 不能为空"):
        ProcessSpec(name="test", executable=Path(" "))


def test_arguments_immutable() -> None:
    """arguments 不可变（tuple）。"""
    s = ProcessSpec(name="test", executable=Path("cmd.exe"))
    assert isinstance(s.arguments, tuple)


def test_unicode_arguments() -> None:
    """Unicode 参数被正确保留。"""
    s = ProcessSpec(
        name="测试",
        executable=Path("C:/test.exe"),
        arguments=("中文参数", "🎮"),
    )
    assert "中文参数" in s.arguments
    assert "🎮" in s.arguments


def test_path_with_spaces() -> None:
    """路径包含空格被正确保留。"""
    s = ProcessSpec(
        name="test",
        executable=Path("C:/Program Files/test.exe"),
    )
    assert " " in str(s.executable)


def test_environment_overrides() -> None:
    """环境变量覆盖被正确存储。"""
    overrides = {"KEY": "VALUE", "PATH": "/custom"}
    s = ProcessSpec(
        name="test",
        executable=Path("cmd.exe"),
        environment_overrides=overrides,
    )
    assert s.environment_overrides["KEY"] == "VALUE"


def test_stdout_stderr_paths() -> None:
    """stdout/stderr 路径可为 None 或有值。"""
    s1 = ProcessSpec(name="test", executable=Path("cmd.exe"))
    assert s1.stdout_path is None

    s2 = ProcessSpec(
        name="test",
        executable=Path("cmd.exe"),
        stdout_path=Path("/tmp/out.log"),
    )
    assert s2.stdout_path == Path("/tmp/out.log")
