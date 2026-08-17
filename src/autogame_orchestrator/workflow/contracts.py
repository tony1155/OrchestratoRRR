"""Phase 6A 工作流的纯契约。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from autogame_orchestrator.entry_runtime import ElevationLaunchSpec
from autogame_orchestrator.models import JsonValue, RunReport, StageName, StageReport
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline


@dataclass(frozen=True)
class StageExecutionContext:
    """传给单个 Stage 的不可变父级执行预算。"""

    run_id: str
    stage: StageName
    deadline: Deadline | None
    cancel: CancellationToken
    failure_cleanup: bool = False


class StageExecutor(Protocol):
    """单个工作流 Stage 的执行边界。"""

    def execute(self, context: StageExecutionContext) -> StageReport: ...


StageExecutorFactory = Callable[[StageName], StageExecutor]


class ReportSink(Protocol):
    """RunReport 持久化边界；失败时应抛出异常。"""

    def write(self, report: RunReport) -> None: ...


WorkflowEvent = Mapping[str, JsonValue]
WorkflowEventSink = Callable[[WorkflowEvent], None]


class ElevationGatewayResult(Protocol):
    """与 Windows elevation 结果等价的最小只读投影。"""

    @property
    def error_code(self) -> str: ...

    @property
    def exit_code(self) -> int: ...


class ElevationGateway(Protocol):
    """入口权限检查与重启边界；核心包不接触 Win32 API。"""

    def is_elevated(self) -> bool: ...

    def relaunch(self, spec: ElevationLaunchSpec) -> ElevationGatewayResult: ...


class WorkflowRunnerContract(Protocol):
    """供入口协调器惰性构造的 Runner 最小接口。"""

    def run(
        self,
        *,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
        run_id: str | None = None,
    ) -> RunReport: ...
