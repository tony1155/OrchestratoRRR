"""按冻结计划执行 Fake Stage 的 Phase 6A 编排内核。"""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from autogame_orchestrator import __version__
from autogame_orchestrator.models import (
    ErrorCode,
    OutcomeKind,
    RunReport,
    RunStatus,
    StageName,
    StageReport,
    is_json_serializable,
)
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.workflow.contracts import (
    ReportSink,
    StageExecutionContext,
    StageExecutorFactory,
    WorkflowEventSink,
)
from autogame_orchestrator.workflow.plan import ExecutionPlan


def _instant_report(
    stage: StageName,
    outcome: OutcomeKind,
    error_code: ErrorCode,
    *,
    diagnostics: dict[str, str | int | bool] | None = None,
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


def _validate_stage_report(value: object, expected: StageName) -> bool:
    if not isinstance(value, StageReport):
        return False
    try:
        if value.stage != expected:
            return False
        if value.outcome == OutcomeKind.SUCCESS and value.error_code != ErrorCode.OK:
            return False
        if value.outcome != OutcomeKind.SUCCESS and value.error_code == ErrorCode.OK:
            return False
        return is_json_serializable(dict(value.diagnostics))
    except (AttributeError, TypeError, ValueError):
        return False


class WorkflowRunner:
    """惰性构造 StageExecutor，并且无全工作流重试。"""

    def __init__(
        self,
        plan: ExecutionPlan,
        executor_factory: StageExecutorFactory,
        report_sink: ReportSink,
        *,
        event_sink: WorkflowEventSink | None = None,
    ) -> None:
        self._plan = plan
        self._executor_factory = executor_factory
        self._report_sink = report_sink
        self._event_sink = event_sink

    def _emit(self, report: StageReport, index: int) -> None:
        if self._event_sink is None:
            return
        event = {
            "event": "workflow_stage_finished",
            "stage": report.stage.value,
            "outcome": report.outcome.value,
            "error_code": report.error_code.value,
            "stage_index": index,
            "stage_count": len(self._plan.stages),
        }
        try:
            self._event_sink(event)
        except Exception:
            return

    def run(
        self,
        *,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
        run_id: str | None = None,
    ) -> RunReport:
        """按顺序执行一次计划，并始终进入报告最终化。"""
        started_at = datetime.now(UTC)
        started_monotonic = time.monotonic()
        workflow_run_id = str(uuid.uuid4()) if run_id is None else run_id
        token = CancellationToken() if cancel is None else cancel
        business_stages = self._plan.stages[:-1]
        reports: list[StageReport] = []
        top_status = RunStatus.SUCCESS
        top_error = ErrorCode.OK
        stopped = False

        for index, stage in enumerate(business_stages):
            if stopped:
                report = _instant_report(stage, OutcomeKind.SKIPPED, ErrorCode.SKIPPED)
            elif token.is_cancelled:
                top_status = RunStatus.CANCELLED
                top_error = ErrorCode.WORKFLOW_CANCELLED
                stopped = True
                report = _instant_report(stage, OutcomeKind.SKIPPED, ErrorCode.SKIPPED)
            elif deadline is not None and deadline.expired:
                top_status = RunStatus.FAILURE
                top_error = ErrorCode.WORKFLOW_STAGE_TIMEOUT
                stopped = True
                report = _instant_report(
                    stage,
                    OutcomeKind.TIMEOUT,
                    ErrorCode.WORKFLOW_STAGE_TIMEOUT,
                    diagnostics={"stage_index": index, "stage_count": len(self._plan.stages)},
                )
            else:
                try:
                    executor = self._executor_factory(stage)
                except KeyError:
                    report = _instant_report(
                        stage,
                        OutcomeKind.FAILURE,
                        ErrorCode.WORKFLOW_EXECUTOR_NOT_REGISTERED,
                    )
                    top_status = RunStatus.FAILURE
                    top_error = ErrorCode.WORKFLOW_EXECUTOR_NOT_REGISTERED
                    stopped = True
                except Exception:
                    report = _instant_report(stage, OutcomeKind.FAILURE, ErrorCode.INTERNAL_ERROR)
                    top_status = RunStatus.FAILURE
                    top_error = ErrorCode.INTERNAL_ERROR
                    stopped = True
                else:
                    context = StageExecutionContext(
                        run_id=workflow_run_id,
                        stage=stage,
                        deadline=deadline,
                        cancel=token,
                    )
                    try:
                        candidate = executor.execute(context)
                    except Exception:
                        candidate = _instant_report(stage, OutcomeKind.FAILURE, ErrorCode.INTERNAL_ERROR)
                    if not _validate_stage_report(candidate, stage):
                        report = _instant_report(
                            stage,
                            OutcomeKind.FAILURE,
                            ErrorCode.WORKFLOW_STAGE_RESULT_INVALID,
                        )
                    else:
                        report = candidate

                    if report.outcome != OutcomeKind.SUCCESS:
                        stopped = True
                        if report.outcome == OutcomeKind.CANCELLED:
                            top_status = RunStatus.CANCELLED
                            top_error = ErrorCode.WORKFLOW_CANCELLED
                        elif report.outcome == OutcomeKind.TIMEOUT:
                            top_status = RunStatus.FAILURE
                            top_error = ErrorCode.WORKFLOW_STAGE_TIMEOUT
                        elif report.error_code == ErrorCode.WORKFLOW_STAGE_RESULT_INVALID:
                            top_status = RunStatus.FAILURE
                            top_error = ErrorCode.WORKFLOW_STAGE_RESULT_INVALID
                        elif report.error_code == ErrorCode.INTERNAL_ERROR:
                            top_status = RunStatus.FAILURE
                            top_error = ErrorCode.INTERNAL_ERROR
                        else:
                            top_status = RunStatus.FAILURE
                            top_error = ErrorCode.WORKFLOW_STAGE_FAILED

            reports.append(report)
            self._emit(report, index)

        write_report = _instant_report(StageName.WRITE_RUN_REPORT, OutcomeKind.SUCCESS, ErrorCode.OK)
        reports.append(write_report)
        finished_at = datetime.now(UTC)
        candidate_report = RunReport(
            schema_version=1,
            run_id=workflow_run_id,
            orchestrator_version=__version__,
            mode="workflow_fake",
            status=top_status,
            error_code=top_error,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(0, int((time.monotonic() - started_monotonic) * 1000)),
            stages=tuple(reports),
            diagnostics={
                "requires_administrator": self._plan.requires_administrator,
                "stage_count": len(self._plan.stages),
            },
        )

        try:
            self._report_sink.write(candidate_report)
        except Exception:
            failed_write = replace(
                write_report,
                outcome=OutcomeKind.FAILURE,
                error_code=ErrorCode.RUN_REPORT_WRITE_ERROR,
            )
            reports[-1] = failed_write
            diagnostics: dict[str, str | int | bool] = {
                "requires_administrator": self._plan.requires_administrator,
                "stage_count": len(self._plan.stages),
            }
            if top_error != ErrorCode.OK:
                diagnostics["source_error_code"] = top_error.value
            final_report = replace(
                candidate_report,
                status=RunStatus.FAILURE,
                error_code=ErrorCode.RUN_REPORT_WRITE_ERROR,
                finished_at=datetime.now(UTC),
                duration_ms=max(0, int((time.monotonic() - started_monotonic) * 1000)),
                stages=tuple(reports),
                diagnostics=diagnostics,
            )
            self._emit(failed_write, len(self._plan.stages) - 1)
            return final_report

        self._emit(write_report, len(self._plan.stages) - 1)
        return candidate_report
