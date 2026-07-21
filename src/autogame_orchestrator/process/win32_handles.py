"""Windows 句柄的安全关闭封装。

提供 ``OwnedHandle`` 类（有状态、幂等关闭）和底层 ``close_handle()`` 函数。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes

_INVALID_HANDLE_VALUE = ctypes.wintypes.HANDLE(-1).value

_kernel32 = ctypes.windll.kernel32
_kernel32.CloseHandle.argtypes = (ctypes.wintypes.HANDLE,)
_kernel32.CloseHandle.restype = ctypes.wintypes.BOOL


class Win32HandleError(RuntimeError):
    """关闭 Win32 句柄时发生错误。"""

    def __init__(self, message: str, win32_code: int) -> None:
        super().__init__(f"{message} (Win32 错误码: {win32_code})")
        self.win32_code = win32_code


def close_handle(handle: int | None) -> None:
    """底层关闭 Win32 句柄。

    - ``handle`` 为 ``None`` 或 ``0`` 时不执行任何操作。
    - 不跟踪已关闭的句柄，无法防止对同一有效句柄值二次关闭。
    - 推荐使用 ``OwnedHandle`` 以获得幂等保证。
    """
    if handle is None or handle == 0:
        return

    if handle == _INVALID_HANDLE_VALUE:
        return

    result = _kernel32.CloseHandle(ctypes.wintypes.HANDLE(handle))
    if result == 0:
        code = ctypes.get_last_error()
        msg = f"CloseHandle 失败，句柄值: {handle}"
        raise Win32HandleError(msg, code)


def is_valid_handle(handle: int | None) -> bool:
    """检查句柄是否非空且非 INVALID_HANDLE_VALUE。"""
    return handle is not None and handle != 0 and handle != _INVALID_HANDLE_VALUE


class OwnedHandle:
    """有状态句柄封装，支持幂等关闭。

    关闭后将 ``value`` 设为 ``None``，后续调用 ``close()`` 无操作。
    使用方式::

        h = OwnedHandle(some_win32_handle)
        h.close()   # 第一次：调用 CloseHandle，设 value=None
        h.close()   # 第二次：无操作
    """

    def __init__(self, handle: int | None) -> None:
        self.value: int | None = handle

    def close(self) -> None:
        """关闭句柄（幂等）。关闭后 ``value`` 为 ``None``。"""
        if self.value is None:
            return
        saved = self.value
        self.value = None
        close_handle(saved)

    def __bool__(self) -> bool:
        return self.value is not None
