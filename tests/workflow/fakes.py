"""不启动外部程序的工作流 Fake。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from autogame_orchestrator.models import ErrorCode, OutcomeKind, RunReport, StageName, StageReport
from autogame_orchestrator.workflow.contracts import StageExecutionContext


def make_stage_report(
    stage: StageName,
    outcome: OutcomeKind = OutcomeKind.SUCCESS,
    error_code: ErrorCode = ErrorCode.OK,
    *,
    diagnostics: dict[str, object] | None = None,
) -> StageReport:
    now = datetime.now(UTC)
    return StageReport(
        stage=stage,
        outcome=outcome,
        error_code=error_code,
        started_at=now,
        finished_at=now,
        duration_ms=0,
        diagnostics={} if diagnostics is None else diagnostics,
    )


class FakeExecutor:
    def __init__(self, action: Callable[[StageExecutionContext], object]) -> None:
        self.action = action
        self.contexts: list[StageExecutionContext] = []
        self.calls = 0

    def execute(self, context: StageExecutionContext) -> StageReport:
        self.calls += 1
        self.contexts.append(context)
        result = self.action(context)
        return result  # type: ignore[return-value]


class RecordingFactory:
    def __init__(self) -> None:
        self.calls: list[StageName] = []
        self.executors: dict[StageName, FakeExecutor] = {}
        self.missing: set[StageName] = set()
        self.factory_error: set[StageName] = set()

    def __call__(self, stage: StageName) -> FakeExecutor:
        self.calls.append(stage)
        if stage in self.missing:
            raise KeyError(stage)
        if stage in self.factory_error:
            raise RuntimeError("敏感异常不得进入结果")
        if stage not in self.executors:
            self.executors[stage] = FakeExecutor(lambda context: make_stage_report(context.stage))
        return self.executors[stage]


class MemorySink:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.reports: list[RunReport] = []

    def write(self, report: RunReport) -> None:
        self.reports.append(report)
        if self.fail:
            raise OSError("本机路径不得进入结果")


class ElevationCode(StrEnum):
    OK = "OK"
    CANCELLED = "ELEVATION_CANCELLED"
    FAILED = "ELEVATION_FAILED"


@dataclass(frozen=True)
class FakeElevationResult:
    error_code: ElevationCode
    exit_code: int


class FakeElevationGateway:
    def __init__(self, *, elevated: bool, result: FakeElevationResult | None = None) -> None:
        self.elevated = elevated
        self.result = result or FakeElevationResult(ElevationCode.OK, 0)
        self.check_calls = 0
        self.relaunch_calls = 0
        self.arguments: tuple[str, ...] = ()

    def is_elevated(self) -> bool:
        self.check_calls += 1
        return self.elevated

    def relaunch(self, arguments: tuple[str, ...]) -> FakeElevationResult:
        self.relaunch_calls += 1
        self.arguments = arguments
        return self.result
