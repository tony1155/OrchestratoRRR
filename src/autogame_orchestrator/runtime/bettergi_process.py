"""Read-only Windows process snapshot; never attach to or kill existing instances."""

import ctypes
import time
from ctypes import wintypes

from autogame_orchestrator.process import Deadline, ManagedProcess


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("user", ctypes.c_int64),
        ("kernel", ctypes.c_int64),
        ("period_user", ctypes.c_int64),
        ("period_kernel", ctypes.c_int64),
        ("faults", wintypes.DWORD),
        ("total", wintypes.DWORD),
        ("active", wintypes.DWORD),
        ("terminated", wintypes.DWORD),
    ]


def stop_owned_job(process: ManagedProcess, deadline: Deadline) -> bool:
    """Confirm the whole owned job is empty before its handle is closed."""
    if process.job_handle is None:
        return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel.QueryInformationJobObject
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    query.restype = wintypes.BOOL
    process.terminate_job()
    while True:
        accounting = _Accounting()
        if not query(process.job_handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if accounting.active == 0:
            return True
        if deadline.expired:
            return False
        time.sleep(min(0.05, deadline.remaining_seconds))


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("usage", wintypes.DWORD),
        ("pid", wintypes.DWORD),
        ("heap", ctypes.c_size_t),
        ("module", wintypes.DWORD),
        ("threads", wintypes.DWORD),
        ("parent", wintypes.DWORD),
        ("priority", wintypes.LONG),
        ("flags", wintypes.DWORD),
        ("name", wintypes.WCHAR * 260),
    ]


def bettergi_is_running() -> bool:
    """Fail closed on enumeration errors, including an unavailable platform API."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel.CreateToolhelp32Snapshot
    snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    snapshot.restype = wintypes.HANDLE
    first, next_entry = kernel.Process32FirstW, kernel.Process32NextW
    for method in (first, next_entry):
        method.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
        method.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _ProcessEntry()
        entry.size = ctypes.sizeof(entry)
        present = first(handle, ctypes.byref(entry))
        while present:
            if entry.name.casefold() == "bettergi.exe":
                return True
            present = next_entry(handle, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
        return False
    finally:
        kernel.CloseHandle(handle)
