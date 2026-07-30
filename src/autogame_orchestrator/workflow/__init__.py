"""Phase 6A 工作流契约与 Fake 编排内核。"""

from autogame_orchestrator.workflow.contracts import (
    ElevationGateway,
    ReportSink,
    StageExecutionContext,
    StageExecutor,
    StageExecutorFactory,
)
from autogame_orchestrator.workflow.coordinator import WorkflowCoordinationResult, WorkflowCoordinator
from autogame_orchestrator.workflow.plan import ExecutionPlan, build_execution_plan
from autogame_orchestrator.workflow.runner import WorkflowRunner

__all__ = [
    "ElevationGateway",
    "ExecutionPlan",
    "ReportSink",
    "StageExecutionContext",
    "StageExecutor",
    "StageExecutorFactory",
    "WorkflowCoordinationResult",
    "WorkflowCoordinator",
    "WorkflowRunner",
    "build_execution_plan",
]
