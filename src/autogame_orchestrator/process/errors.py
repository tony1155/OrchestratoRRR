"""进程启动与生命周期错误码。"""

from __future__ import annotations

from enum import StrEnum


class ProcessLaunchErrorCode(StrEnum):
    """进程启动阶段可能遇到的错误码。"""

    EXECUTABLE_NOT_FOUND = "EXECUTABLE_NOT_FOUND"
    WORKING_DIRECTORY_NOT_FOUND = "WORKING_DIRECTORY_NOT_FOUND"
    OUTPUT_OPEN_FAILED = "OUTPUT_OPEN_FAILED"
    CREATE_PROCESS_FAILED = "CREATE_PROCESS_FAILED"
    JOB_CREATE_FAILED = "JOB_CREATE_FAILED"
    JOB_CONFIGURE_FAILED = "JOB_CONFIGURE_FAILED"
    JOB_ASSIGN_FAILED = "JOB_ASSIGN_FAILED"
    RESUME_THREAD_FAILED = "RESUME_THREAD_FAILED"
    HANDLE_CLOSE_FAILED = "HANDLE_CLOSE_FAILED"


class TerminationReason(StrEnum):
    """进程终止原因。"""

    NORMAL_EXIT = "normal_exit"  # 进程自行退出，退出码为 0
    NONZERO_EXIT = "nonzero_exit"  # 进程自行退出，退出码非 0
    TIMEOUT = "timeout"  # deadline 到期，由 supervisor 终止
    CANCELLED = "cancelled"  # CancellationToken 触发，由 supervisor 终止
    STOPPED = "stopped"  # 用户主动调用 stop
    START_FAILED = "start_failed"  # 进程未成功进入运行状态
    WAIT_FAILED = "wait_failed"  # 等待 Win32 状态失败
    TERMINATION_FAILED = "termination_failed"  # 终止后未能在硬期限内确认退出


class ProcessExecutionErrorCode(StrEnum):
    """进程执行错误码。"""

    OK = "OK"
    START_FAILED = "START_FAILED"
    EXIT_NONZERO = "EXIT_NONZERO"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    STOPPED = "STOPPED"
    WAIT_FAILED = "WAIT_FAILED"
    TERMINATION_FAILED = "TERMINATION_FAILED"
