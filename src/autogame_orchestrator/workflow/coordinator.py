"""在构造 Runner 前完成入口级权限决策。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from autogame_orchestrator.config_model import AppConfig
from autogame_orchestrator.models import RunReport
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.workflow.contracts import ElevationGateway, WorkflowRunnerContract
from autogame_orchestrator.workflow.plan import ExecutionPlan, build_execution_plan


@dataclass(frozen=True)
class WorkflowCoordinationResult:
    """本入口运行或提升后子入口运行的结果投影。"""

    report: RunReport | None
    elevation_error_code: str | None
    exit_code: int | None
    relaunched: bool


RunnerFactory = Callable[[ExecutionPlan], WorkflowRunnerContract]


def _stable_error_code(value: object) -> str:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) else "ELEVATION_FAILED"


class WorkflowCoordinator:
    """保证 elevation 决策先于 Runner 和任何 Stage 工厂。"""

    def __init__(self, elevation_gateway: ElevationGateway, runner_factory: RunnerFactory) -> None:
        self._elevation_gateway = elevation_gateway
        self._runner_factory = runner_factory

    def execute(
        self,
        config: AppConfig,
        *,
        relaunch_arguments: Sequence[str] = (),
        elevation_marker_present: bool = False,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
        run_id: str | None = None,
    ) -> WorkflowCoordinationResult:
        """构建完整计划、前置决定权限，再惰性构造 Runner。"""
        plan = build_execution_plan(config)
        if plan.requires_administrator and not self._elevation_gateway.is_elevated():
            if elevation_marker_present:
                return WorkflowCoordinationResult(None, "ELEVATION_FAILED", 10, False)
            elevation = self._elevation_gateway.relaunch(tuple(relaunch_arguments))
            return WorkflowCoordinationResult(
                None,
                _stable_error_code(elevation.error_code),
                elevation.exit_code,
                True,
            )

        runner = self._runner_factory(plan)
        report = runner.run(deadline=deadline, cancel=cancel, run_id=run_id)
        return WorkflowCoordinationResult(report, None, None, False)
