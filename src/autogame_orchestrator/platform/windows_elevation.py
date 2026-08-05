"""Windows 入口级自提权支持。"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from autogame_orchestrator.entry_runtime import ElevationLaunchSpec

TOKEN_QUERY = 0x0008
TOKEN_ELEVATION_CLASS = 20
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_SHOWNORMAL = 1
WAIT_OBJECT_0 = 0x00000000
INFINITE = 0xFFFFFFFF
ERROR_CANCELLED = 1223


class ElevationErrorCode(StrEnum):
    """入口提权的稳定结果码。"""

    OK = "OK"
    ELEVATION_CANCELLED = "ELEVATION_CANCELLED"
    ELEVATION_FAILED = "ELEVATION_FAILED"


@dataclass(frozen=True)
class ElevationResult:
    """提升后进程的有界结果。"""

    error_code: ElevationErrorCode
    exit_code: int | None


class _TokenElevation(ctypes.Structure):
    _fields_ = [("TokenIsElevated", ctypes.wintypes.DWORD)]


class _ShellExecuteInfoW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("fMask", ctypes.wintypes.ULONG),
        ("hwnd", ctypes.wintypes.HWND),
        ("lpVerb", ctypes.wintypes.LPCWSTR),
        ("lpFile", ctypes.wintypes.LPCWSTR),
        ("lpParameters", ctypes.wintypes.LPCWSTR),
        ("lpDirectory", ctypes.wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.wintypes.LPCWSTR),
        ("hkeyClass", ctypes.wintypes.HKEY),
        ("dwHotKey", ctypes.wintypes.DWORD),
        ("hIconOrMonitor", ctypes.wintypes.HANDLE),
        ("hProcess", ctypes.wintypes.HANDLE),
    ]


class ElevationLaunchError(RuntimeError):
    """ShellExecuteExW 启动失败。"""

    def __init__(self, win32_code: int) -> None:
        super().__init__("入口提权启动失败")
        self.win32_code = win32_code


class _WindowsElevationApi:
    """集中隔离 Win32 API 边界，便于无 UAC 自动测试。"""

    def __init__(self) -> None:
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self._kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
        self._kernel32.WaitForSingleObject.argtypes = (ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD)
        self._kernel32.WaitForSingleObject.restype = ctypes.wintypes.DWORD
        self._kernel32.GetExitCodeProcess.argtypes = (
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        )
        self._kernel32.GetExitCodeProcess.restype = ctypes.wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = (ctypes.wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
        self._advapi32.OpenProcessToken.argtypes = (
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.wintypes.HANDLE),
        )
        self._advapi32.OpenProcessToken.restype = ctypes.wintypes.BOOL
        self._advapi32.GetTokenInformation.argtypes = (
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        )
        self._advapi32.GetTokenInformation.restype = ctypes.wintypes.BOOL
        self._shell32.ShellExecuteExW.argtypes = (ctypes.POINTER(_ShellExecuteInfoW),)
        self._shell32.ShellExecuteExW.restype = ctypes.wintypes.BOOL

    def is_process_elevated(self) -> bool:
        token = ctypes.wintypes.HANDLE()
        if (
            self._advapi32.OpenProcessToken(
                self._kernel32.GetCurrentProcess(), ctypes.wintypes.DWORD(TOKEN_QUERY), ctypes.byref(token)
            )
            == 0
        ):
            raise OSError(ctypes.get_last_error(), "OpenProcessToken 失败")
        try:
            elevation = _TokenElevation()
            returned = ctypes.wintypes.DWORD()
            if (
                self._advapi32.GetTokenInformation(
                    token,
                    ctypes.wintypes.DWORD(TOKEN_ELEVATION_CLASS),
                    ctypes.byref(elevation),
                    ctypes.wintypes.DWORD(ctypes.sizeof(elevation)),
                    ctypes.byref(returned),
                )
                == 0
            ):
                raise OSError(ctypes.get_last_error(), "GetTokenInformation 失败")
            return bool(elevation.TokenIsElevated)
        finally:
            if token.value is not None:
                self.close_handle(int(token.value))

    def launch_elevated(self, executable: str, parameters: str, working_directory: str) -> int:
        info = _ShellExecuteInfoW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = SEE_MASK_NOCLOSEPROCESS
        info.lpVerb = "runas"
        info.lpFile = executable
        info.lpParameters = parameters
        info.lpDirectory = working_directory
        info.nShow = SW_SHOWNORMAL
        if self._shell32.ShellExecuteExW(ctypes.byref(info)) == 0:
            raise ElevationLaunchError(ctypes.get_last_error())
        if not info.hProcess:
            raise ElevationLaunchError(0)
        return int(info.hProcess)

    def wait_for_exit(self, handle: int) -> int:
        result = self._kernel32.WaitForSingleObject(ctypes.wintypes.HANDLE(handle), ctypes.wintypes.DWORD(INFINITE))
        if result != WAIT_OBJECT_0:
            raise OSError(ctypes.get_last_error(), "WaitForSingleObject 失败")
        exit_code = ctypes.wintypes.DWORD()
        if self._kernel32.GetExitCodeProcess(ctypes.wintypes.HANDLE(handle), ctypes.byref(exit_code)) == 0:
            raise OSError(ctypes.get_last_error(), "GetExitCodeProcess 失败")
        return int(exit_code.value)

    def close_handle(self, handle: int) -> None:
        if self._kernel32.CloseHandle(ctypes.wintypes.HANDLE(handle)) == 0:
            raise OSError(ctypes.get_last_error(), "CloseHandle 失败")


_api = _WindowsElevationApi()


def quote_windows_arguments(arguments: Sequence[str]) -> str:
    """按 Windows CreateProcess 规则引用参数。"""

    return subprocess.list2cmdline(list(arguments))


def is_process_elevated() -> bool:
    """通过当前进程 Token 判断是否已提升。"""

    return _api.is_process_elevated()


def relaunch_current_process_elevated(spec: ElevationLaunchSpec) -> ElevationResult:
    """Launch the explicit entry specification and forward its exit code."""

    handle: int | None = None
    try:
        launched_handle = _api.launch_elevated(
            str(spec.executable),
            quote_windows_arguments(spec.arguments),
            str(spec.working_directory),
        )
        if not launched_handle:
            raise ElevationLaunchError(0)
        handle = launched_handle
        return ElevationResult(ElevationErrorCode.OK, _api.wait_for_exit(handle))
    except ElevationLaunchError as exc:
        if exc.win32_code == ERROR_CANCELLED:
            return ElevationResult(ElevationErrorCode.ELEVATION_CANCELLED, None)
        return ElevationResult(ElevationErrorCode.ELEVATION_FAILED, None)
    except OSError:
        return ElevationResult(ElevationErrorCode.ELEVATION_FAILED, None)
    finally:
        if handle is not None:
            try:
                _api.close_handle(handle)
            except OSError:
                pass
