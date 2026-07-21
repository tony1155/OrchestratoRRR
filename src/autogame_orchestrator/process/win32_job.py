"""Windows Job Object 的 ctypes 封装。

提供 Job 的创建、配置（KILL_ON_JOB_CLOSE）、进程分配和终止功能。

核心设计：
    - 每个 ManagedProcess 对应一个 Job Object。
    - JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE 确保 Job 句柄关闭时 OS 自动终止所有加入的进程。
    - ``terminate()`` 显式终止 Job 内所有进程。
    - ``close()`` 关闭 Job 句柄（幂等）。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_INVALID_HANDLE_VALUE = ctypes.wintypes.HANDLE(-1).value

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9

# ---------------------------------------------------------------------------
# 结构体定义
# ---------------------------------------------------------------------------


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.wintypes.DWORD),
        ("Affinity", ctypes.c_ulonglong),
        ("PriorityClass", ctypes.wintypes.DWORD),
        ("SchedulingClass", ctypes.wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


# ---------------------------------------------------------------------------
# kernel32 API 声明
# ---------------------------------------------------------------------------

_kernel32 = ctypes.windll.kernel32

_kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.wintypes.LPCWSTR)
_kernel32.CreateJobObjectW.restype = ctypes.wintypes.HANDLE

_kernel32.SetInformationJobObject.argtypes = (
    ctypes.wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.wintypes.DWORD,
)
_kernel32.SetInformationJobObject.restype = ctypes.wintypes.BOOL

_kernel32.AssignProcessToJobObject.argtypes = (ctypes.wintypes.HANDLE, ctypes.wintypes.HANDLE)
_kernel32.AssignProcessToJobObject.restype = ctypes.wintypes.BOOL

_kernel32.TerminateJobObject.argtypes = (ctypes.wintypes.HANDLE, ctypes.wintypes.UINT)
_kernel32.TerminateJobObject.restype = ctypes.wintypes.BOOL


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


class JobObjectError(RuntimeError):
    """Job Object 操作失败。"""

    def __init__(self, message: str, win32_code: int | None = None) -> None:
        detail = f" (Win32 错误码: {win32_code})" if win32_code else ""
        super().__init__(f"{message}{detail}")
        self.win32_code = win32_code


def create_job_object(name: str | None = None) -> int:
    """创建 Job Object。

    Args:
        name: Job 名称。``None`` 创建匿名 Job。

    Returns:
        Job 句柄。

    Raises:
        JobObjectError: 创建失败。
    """
    handle = _kernel32.CreateJobObjectW(None, name)
    handle_int: int = handle
    if handle_int == 0 or handle_int == _INVALID_HANDLE_VALUE:
        code = ctypes.get_last_error()
        msg = "CreateJobObjectW 失败"
        raise JobObjectError(msg, code)
    return handle_int


def configure_job_kill_on_close(job_handle: int) -> None:
    """配置 Job Object：句柄关闭时自动终止所有加入的进程。

    Args:
        job_handle: Job 句柄。

    Raises:
        JobObjectError: 配置失败。
    """
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

    result = _kernel32.SetInformationJobObject(
        ctypes.wintypes.HANDLE(job_handle),
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if result == 0:
        code = ctypes.get_last_error()
        msg = "SetInformationJobObject (KILL_ON_JOB_CLOSE) 失败"
        raise JobObjectError(msg, code)


def assign_process_to_job(job_handle: int, process_handle: int) -> None:
    """将进程加入 Job Object。

    Args:
        job_handle: Job 句柄。
        process_handle: 进程句柄。

    Raises:
        JobObjectError: 分配失败。
    """
    result = _kernel32.AssignProcessToJobObject(
        ctypes.wintypes.HANDLE(job_handle),
        ctypes.wintypes.HANDLE(process_handle),
    )
    if result == 0:
        code = ctypes.get_last_error()
        msg = "AssignProcessToJobObject 失败"
        raise JobObjectError(msg, code)


def terminate_job(job_handle: int, exit_code: int = 1) -> None:
    """终止 Job Object 中的所有进程。

    Args:
        job_handle: Job 句柄。
        exit_code: 终止时设置的退出码。

    Raises:
        JobObjectError: 终止失败。
    """
    result = _kernel32.TerminateJobObject(
        ctypes.wintypes.HANDLE(job_handle),
        ctypes.wintypes.UINT(exit_code),
    )
    if result == 0:
        code = ctypes.get_last_error()
        msg = "TerminateJobObject 失败"
        raise JobObjectError(msg, code)
