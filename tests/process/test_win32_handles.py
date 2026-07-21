"""Win32 句柄单元测试。

测试 ``OwnedHandle``（有状态幂等关闭）和底层 ``close_handle``。
"""

from __future__ import annotations

import pytest

from autogame_orchestrator.process.win32_handles import OwnedHandle, Win32HandleError, close_handle, is_valid_handle


def test_close_none() -> None:
    """关闭 None 不产生异常。"""
    close_handle(None)


def test_close_zero() -> None:
    """关闭 0 不产生异常。"""
    close_handle(0)


def test_close_invalid_raises() -> None:
    """关闭无效句柄抛出 Win32HandleError。"""
    with pytest.raises(Win32HandleError):
        close_handle(99999999)


def test_is_valid_handle_none() -> None:
    """None 不是有效句柄。"""
    assert not is_valid_handle(None)


def test_is_valid_handle_zero() -> None:
    """0 不是有效句柄。"""
    assert not is_valid_handle(0)


def test_owned_handle_close_once() -> None:
    """OwnedHandle 关闭一次后 value 变为 None。"""
    # 使用一个立即关闭的 dummy 句柄
    import ctypes

    h = ctypes.windll.kernel32.GetCurrentProcess()
    owned = OwnedHandle(h)
    assert owned.value is not None
    owned.close()
    assert owned.value is None


def test_owned_handle_double_close() -> None:
    """OwnedHandle 重复关闭不会导致二次 CloseHandle。"""
    import ctypes

    h = ctypes.windll.kernel32.GetCurrentProcess()
    owned = OwnedHandle(h)
    owned.close()
    # 第二次 close 无操作
    owned.close()
    assert owned.value is None


def test_owned_handle_bool() -> None:
    """OwnedHandle 的 bool 检查由 value 决定。"""
    owned = OwnedHandle(42)
    assert bool(owned) is True
    owned.close()
    assert bool(owned) is False
