"""Windows 进程创建（CreateProcessW）的 ctypes 封装。

使用 ``CREATE_SUSPENDED`` 创建挂起进程，返回进程和线程句柄。
调用方负责在恢复执行前加入 Job Object。

关键安全设计：
    - 命令行使用 ``create_unicode_buffer``（CreateProcessW 可能修改 lpCommandLine）。
    - 句柄继承策略：仅将 stdout/stderr 设为可继承，创建后立即恢复不可继承。
    - ``poll()`` 使用 ``WaitForSingleObject`` 判定进程存活，避免退出码 259 误判。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import subprocess

CREATE_SUSPENDED = 0x00000004
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
STILL_ACTIVE = 259
HANDLE_FLAG_INHERIT = 0x00000001
STARTF_USESTDHANDLES = 0x00000100


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("lpReserved", ctypes.wintypes.LPWSTR),
        ("lpDesktop", ctypes.wintypes.LPWSTR),
        ("lpTitle", ctypes.wintypes.LPWSTR),
        ("dwX", ctypes.wintypes.DWORD),
        ("dwY", ctypes.wintypes.DWORD),
        ("dwXSize", ctypes.wintypes.DWORD),
        ("dwYSize", ctypes.wintypes.DWORD),
        ("dwXCountChars", ctypes.wintypes.DWORD),
        ("dwYCountChars", ctypes.wintypes.DWORD),
        ("dwFillAttribute", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("wShowWindow", ctypes.wintypes.WORD),
        ("cbReserved2", ctypes.wintypes.WORD),
        ("lpReserved2", ctypes.wintypes.LPBYTE),
        ("hStdInput", ctypes.wintypes.HANDLE),
        ("hStdOutput", ctypes.wintypes.HANDLE),
        ("hStdError", ctypes.wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.wintypes.HANDLE),
        ("hThread", ctypes.wintypes.HANDLE),
        ("dwProcessId", ctypes.wintypes.DWORD),
        ("dwThreadId", ctypes.wintypes.DWORD),
    ]


_kernel32 = ctypes.windll.kernel32

_kernel32.CreateProcessW.argtypes = (
    ctypes.wintypes.LPCWSTR,
    ctypes.wintypes.LPWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.wintypes.BOOL,
    ctypes.wintypes.DWORD,
    ctypes.c_void_p,
    ctypes.wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION),
)
_kernel32.CreateProcessW.restype = ctypes.wintypes.BOOL

_kernel32.ResumeThread.argtypes = (ctypes.wintypes.HANDLE,)
_kernel32.ResumeThread.restype = ctypes.wintypes.DWORD

_kernel32.WaitForSingleObject.argtypes = (ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD)
_kernel32.WaitForSingleObject.restype = ctypes.wintypes.DWORD

_kernel32.GetExitCodeProcess.argtypes = (ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.DWORD))
_kernel32.GetExitCodeProcess.restype = ctypes.wintypes.BOOL

_kernel32.SetHandleInformation.argtypes = (ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD)
_kernel32.SetHandleInformation.restype = ctypes.wintypes.BOOL


class ProcessCreationError(RuntimeError):
    """CreateProcessW 失败。"""

    def __init__(self, message: str, win32_code: int | None = None) -> None:
        detail = f" (Win32 错误码: {win32_code})" if win32_code else ""
        super().__init__(f"{message}{detail}")
        self.win32_code = win32_code


def _build_command_line(executable: str, arguments: tuple[str, ...]) -> str:
    return subprocess.list2cmdline([executable, *arguments])


def create_suspended_process(
    executable: str,
    arguments: tuple[str, ...],
    working_directory: str | None,
    environment_block: str | None,
    stdout_handle: int | None,
    stderr_handle: int | None,
    create_new_process_group: bool,
    inherit_handles: bool,
) -> PROCESS_INFORMATION:
    """使用 ``CREATE_SUSPENDED`` 创建进程。"""
    command_line = _build_command_line(executable, arguments)
    cmd_buf = ctypes.create_unicode_buffer(command_line)

    startup_info = STARTUPINFOW()
    startup_info.cb = ctypes.sizeof(startup_info)

    if stdout_handle is not None or stderr_handle is not None:
        startup_info.dwFlags = STARTF_USESTDHANDLES
        startup_info.hStdInput = ctypes.wintypes.HANDLE(_get_stdin_handle())
        if stdout_handle is not None:
            startup_info.hStdOutput = ctypes.wintypes.HANDLE(stdout_handle)
        if stderr_handle is not None:
            startup_info.hStdError = ctypes.wintypes.HANDLE(stderr_handle)

    creation_flags = CREATE_SUSPENDED
    if create_new_process_group:
        creation_flags |= CREATE_NEW_PROCESS_GROUP
    if environment_block is not None:
        creation_flags |= CREATE_UNICODE_ENVIRONMENT

    proc_info = PROCESS_INFORMATION()

    if environment_block:
        env_buf = ctypes.create_unicode_buffer(environment_block)
        env_ptr = ctypes.cast(env_buf, ctypes.c_void_p)
    else:
        env_ptr = None

    result = _kernel32.CreateProcessW(
        None,
        ctypes.cast(cmd_buf, ctypes.wintypes.LPWSTR),
        None,
        None,
        ctypes.wintypes.BOOL(inherit_handles),
        ctypes.wintypes.DWORD(creation_flags),
        env_ptr,
        ctypes.wintypes.LPCWSTR(working_directory) if working_directory else None,
        ctypes.byref(startup_info),
        ctypes.byref(proc_info),
    )

    if result == 0:
        code = ctypes.get_last_error()
        msg = f"CreateProcessW 失败: {executable}"
        raise ProcessCreationError(msg, code)

    return proc_info


def resume_thread(thread_handle: int) -> None:
    result = _kernel32.ResumeThread(ctypes.wintypes.HANDLE(thread_handle))
    if result == 0xFFFFFFFF:
        code = ctypes.get_last_error()
        msg = "ResumeThread 失败"
        raise ProcessCreationError(msg, code)


def is_process_alive(process_handle: int) -> bool:
    result = _kernel32.WaitForSingleObject(ctypes.wintypes.HANDLE(process_handle), ctypes.wintypes.DWORD(0))
    return bool(result == WAIT_TIMEOUT)


def get_exit_code(process_handle: int) -> int | None:
    if is_process_alive(process_handle):
        return None
    code = ctypes.wintypes.DWORD()
    r = _kernel32.GetExitCodeProcess(ctypes.wintypes.HANDLE(process_handle), ctypes.byref(code))
    if r == 0:
        return None
    return code.value


def set_handle_inheritable(handle: int, inheritable: bool) -> None:
    flag = HANDLE_FLAG_INHERIT if inheritable else 0
    r = _kernel32.SetHandleInformation(
        ctypes.wintypes.HANDLE(handle),
        ctypes.wintypes.DWORD(HANDLE_FLAG_INHERIT),
        ctypes.wintypes.DWORD(flag),
    )
    if r == 0:
        code = ctypes.get_last_error()
        msg = "SetHandleInformation 失败"
        raise ProcessCreationError(msg, code)


def _get_stdin_handle() -> int:
    import msvcrt

    return msvcrt.get_osfhandle(0)
