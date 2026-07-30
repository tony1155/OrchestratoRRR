"""external 生产工作流的安全 composition root。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self

from autogame_orchestrator.config_model import AppConfig
from autogame_orchestrator.log_writer import JsonlLogWriter
from autogame_orchestrator.models import JsonValue, RunReport
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.workflow.contracts import ElevationGateway, ReportSink
from autogame_orchestrator.workflow.coordinator import WorkflowCoordinationResult, WorkflowCoordinator
from autogame_orchestrator.workflow.plan import ExecutionPlan
from autogame_orchestrator.workflow.production.elevation import WindowsElevationGateway
from autogame_orchestrator.workflow.production.factory import build_production_executor_factory
from autogame_orchestrator.workflow.production.ports import RuntimeFactories
from autogame_orchestrator.workflow.production.report_sink import ProductionReportSink
from autogame_orchestrator.workflow.runner import WorkflowRunner


class WorkflowLog(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> object: ...

    def info(self, event: str, message: str, details: dict[str, object] | None = None) -> None: ...


LogFactory = Callable[[Path, str], WorkflowLog]
ReportSinkFactory = Callable[[AppConfig], ReportSink]


def _production_report_sink(config: AppConfig) -> ReportSink:
    return ProductionReportSink(config.orchestrator.report_dir)


@dataclass(frozen=True)
class ProductionApplicationDependencies:
    """可注入的生产边界；默认值才绑定真实平台和 Runtime factory。"""

    elevation_gateway: ElevationGateway
    runtime_factories: RuntimeFactories | None = None
    report_sink_factory: ReportSinkFactory = _production_report_sink
    log_factory: LogFactory = JsonlLogWriter


def default_production_dependencies() -> ProductionApplicationDependencies:
    """构造无副作用的默认依赖，不检查权限、不打开文件、不构造 Adapter。"""

    return ProductionApplicationDependencies(WindowsElevationGateway())


class _LoggedProductionRunner:
    """权限满足后才打开日志并构造生产 Stage factory。"""

    def __init__(
        self,
        config: AppConfig,
        plan: ExecutionPlan,
        dependencies: ProductionApplicationDependencies,
    ) -> None:
        self._config = config
        self._plan = plan
        self._dependencies = dependencies

    def run(
        self,
        *,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
        run_id: str | None = None,
    ) -> RunReport:
        if deadline is None or run_id is None:
            raise ValueError("生产工作流要求父 Deadline 和 run_id")
        log_path = Path(self._config.orchestrator.log_dir) / f"run-{run_id}.jsonl"
        with self._dependencies.log_factory(log_path, run_id) as log:
            log.info(
                "workflow.start",
                "External workflow started",
                {"mode": "workflow_external", "stage_count": len(self._plan.stages)},
            )
            executor_factory = build_production_executor_factory(
                self._config,
                runtime_factories=self._dependencies.runtime_factories,
            )
            report_sink = self._dependencies.report_sink_factory(self._config)

            def emit(event: Mapping[str, JsonValue]) -> None:
                log.info("workflow.stage.finished", "Workflow stage finished", dict(event))

            runner = WorkflowRunner(
                self._plan,
                executor_factory,
                report_sink,
                event_sink=emit,
                mode="workflow_external",
            )
            return runner.run(deadline=deadline, cancel=cancel, run_id=run_id)


def execute_production_workflow(
    config: AppConfig,
    *,
    deadline: Deadline,
    cancel: CancellationToken,
    run_id: str,
    relaunch_arguments: Sequence[str],
    elevation_marker_present: bool,
    dependencies: ProductionApplicationDependencies | None = None,
) -> WorkflowCoordinationResult:
    """前置协调 elevation，权限满足后才构造生产 Runner。"""

    selected = default_production_dependencies() if dependencies is None else dependencies

    def runner_factory(plan: ExecutionPlan) -> _LoggedProductionRunner:
        return _LoggedProductionRunner(config, plan, selected)

    return WorkflowCoordinator(selected.elevation_gateway, runner_factory).execute(
        config,
        relaunch_arguments=relaunch_arguments,
        elevation_marker_present=elevation_marker_present,
        deadline=deadline,
        cancel=cancel,
        run_id=run_id,
    )
