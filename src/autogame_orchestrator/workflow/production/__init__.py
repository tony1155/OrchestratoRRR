"""Phase 6B1 生产 Stage 投影与安全绑定骨架。"""

from autogame_orchestrator.workflow.production.factory import (
    ProductionExecutorFactory,
    build_production_executor_factory,
)
from autogame_orchestrator.workflow.production.ports import RuntimeFactories
from autogame_orchestrator.workflow.production.report_sink import ProductionReportSink
from autogame_orchestrator.workflow.production.state import ProductionWorkflowState

__all__ = [
    "ProductionExecutorFactory",
    "ProductionReportSink",
    "ProductionWorkflowState",
    "RuntimeFactories",
    "build_production_executor_factory",
]
