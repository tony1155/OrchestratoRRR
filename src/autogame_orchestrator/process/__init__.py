"""进程管理子包。

阶段 1B：Deadline、CancellationToken、进程模型、Win32 句柄、
Job Object、进程启动器、ProcessResult、ProcessSupervisor。
"""

from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.process.errors import (
    ProcessExecutionErrorCode,
    ProcessLaunchErrorCode,
    TerminationReason,
)
from autogame_orchestrator.process.models import ManagedProcess, ProcessSpec
from autogame_orchestrator.process.result import ProcessResult
from autogame_orchestrator.process.supervisor import ProcessSupervisor, ProcessSupervisorCloseError

__all__ = [
    "Deadline",
    "CancellationToken",
    "ProcessSpec",
    "ManagedProcess",
    "ProcessResult",
    "ProcessSupervisor",
    "ProcessSupervisorCloseError",
    "ProcessExecutionErrorCode",
    "ProcessLaunchErrorCode",
    "TerminationReason",
]
