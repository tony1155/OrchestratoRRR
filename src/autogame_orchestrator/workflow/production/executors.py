"""生产 StageExecutor；只调用既有 Runtime Port，不复制生命周期逻辑。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from autogame_orchestrator.config_model import AppConfig, MumuLifecycleMode
from autogame_orchestrator.maa_resource.models import MAAResourceMergeStatus
from autogame_orchestrator.maa_sync.models import MAASyncStatus
from autogame_orchestrator.models import ErrorCode, OutcomeKind, StageName, StageReport
from autogame_orchestrator.runtime.models import MumuRuntimeStatus
from autogame_orchestrator.workflow.contracts import StageExecutionContext
from autogame_orchestrator.workflow.production.ports import (
    MAAResourceMergePort,
    MAARunPort,
    MAASyncPort,
    MAAUpdatePort,
    ManagedMumuRuntimePort,
    MumuRuntimePort,
    StarRailRunPort,
)
from autogame_orchestrator.workflow.production.projection import (
    maa_output_diagnostics,
    project_maa,
    project_mumu,
    project_starrail,
)
from autogame_orchestrator.workflow.production.runtime_bindings import RuntimeBindingError
from autogame_orchestrator.workflow.production.state import ProductionWorkflowState


def _instant(
    stage: StageName,
    outcome: OutcomeKind,
    code: ErrorCode,
    diagnostics: dict[str, str | int | bool] | None = None,
) -> StageReport:
    now = datetime.now(UTC)
    return StageReport(
        stage,
        outcome,
        code,
        now,
        now,
        0,
        diagnostics={} if diagnostics is None else diagnostics,
    )


class ProductionStageExecutor:
    """单个 Stage 的安全生产投影。"""

    def __init__(
        self,
        stage: StageName,
        config: AppConfig,
        state: ProductionWorkflowState,
        *,
        starrail: Callable[[], StarRailRunPort],
        maa: Callable[[], MAARunPort],
        mumu: Callable[[], MumuRuntimePort],
        maa_sync: Callable[[], MAASyncPort],
        maa_update: Callable[[], MAAUpdatePort],
        maa_resource_merge: Callable[[], MAAResourceMergePort],
    ) -> None:
        self._stage = stage
        self._config = config
        self._state = state
        self._starrail = starrail
        self._maa = maa
        self._mumu = mumu
        self._maa_sync = maa_sync
        self._maa_update = maa_update
        self._maa_resource_merge = maa_resource_merge

    def execute(self, context: StageExecutionContext) -> StageReport:
        if context.stage != self._stage:
            return _instant(self._stage, OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_RESULT_INVALID)
        try:
            return self._execute(context)
        except RuntimeBindingError:
            return _instant(self._stage, OutcomeKind.FAILURE, ErrorCode.CONFIG_SCHEMA_ERROR)
        except Exception:
            return _instant(self._stage, OutcomeKind.FAILURE, ErrorCode.INTERNAL_ERROR)

    def _execute(self, context: StageExecutionContext) -> StageReport:
        stage = self._stage
        if stage == StageName.VALIDATE_CONFIG:
            return self._validate()
        if stage == StageName.SYNC_MAA_CONFIG:
            return self._run_maa_sync(context)
        if stage == StageName.UPDATE_MAA:
            return self._run_maa_update(context)
        if stage == StageName.MERGE_MAA_RESOURCE:
            return self._run_maa_resource_merge(context)
        if self._config.mumu.lifecycle_mode == MumuLifecycleMode.EXTERNAL and stage in {
            StageName.STOP_MUMU,
            StageName.START_MUMU,
            StageName.SHUTDOWN_MUMU,
        }:
            blockers = {
                StageName.STOP_MUMU: "mumu_stop_not_approved",
                StageName.START_MUMU: "mumu_start_not_approved",
                StageName.SHUTDOWN_MUMU: "mumu_shutdown_not_approved",
            }
            return _instant(
                stage,
                OutcomeKind.FAILURE,
                ErrorCode.WORKFLOW_STAGE_BLOCKED,
                {"blocker": blockers[stage]},
            )
        if stage in {
            StageName.ENSURE_MUMU_RUNNING,
            StageName.WAIT_MUMU_ADB_READY,
            StageName.VERIFY_MUMU_STOPPED,
            StageName.WAIT_MUMU_ADB_READY_AFTER_RESTART,
            StageName.STOP_MUMU,
            StageName.START_MUMU,
            StageName.SHUTDOWN_MUMU,
        }:
            return self._run_mumu(context)
        if stage == StageName.RUN_STARRAIL:
            result = self._starrail().run(context.deadline, context.cancel)
            self._state.starrail_run_reached = True
            self._state.starrail_completed = result.status.value == "completed"
            self._state.starrail_owned_process_cleaned = result.owned_process_cleaned
            return project_starrail(stage, result)
        if stage in {StageName.STOP_STARRAIL, StageName.VERIFY_STARRAIL_STOPPED}:
            return self._verify_starrail_postcondition()
        if stage == StageName.RUN_MAA:
            return project_maa(stage, self._maa().run(context.deadline, context.cancel))
        return _instant(stage, OutcomeKind.FAILURE, ErrorCode.WORKFLOW_EXECUTOR_NOT_REGISTERED)

    def _run_maa_sync(self, context: StageExecutionContext) -> StageReport:
        if not self._config.maa_sync.enabled:
            return _instant(
                self._stage,
                OutcomeKind.SUCCESS,
                ErrorCode.OK,
                {"enabled": False, "changed": False},
            )
        sync_result = self._maa_sync().run(context.deadline, context.cancel)
        mapping = {
            MAASyncStatus.COMPLETED: (OutcomeKind.SUCCESS, ErrorCode.OK),
            MAASyncStatus.FAILED: (OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED),
            MAASyncStatus.TIMEOUT: (OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT),
            MAASyncStatus.CANCELLED: (OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED),
        }
        outcome, code = mapping[sync_result.status]
        return StageReport(
            self._stage,
            outcome,
            code,
            sync_result.started_at,
            sync_result.finished_at,
            sync_result.duration_ms,
            diagnostics={
                "source_error_code": sync_result.error_code.value,
                "enabled": sync_result.enabled,
                "changed": sync_result.changed,
                "profile_written": sync_result.profile_written,
                "tasks_written": sync_result.tasks_written,
                "profile_backup_written": sync_result.profile_backup_written,
                "tasks_backup_written": sync_result.tasks_backup_written,
                "rollback_attempted": sync_result.rollback_attempted,
                "rollback_succeeded": sync_result.rollback_succeeded,
            },
        )

    def _run_maa_update(self, context: StageExecutionContext) -> StageReport:
        if not self._config.maa_update.enabled:
            return _instant(
                self._stage,
                OutcomeKind.SUCCESS,
                ErrorCode.OK,
                {"enabled": False, "executed": False},
            )
        if not self._config.maa_update.allow_network or self._config.maa_update.validate():
            return _instant(self._stage, OutcomeKind.FAILURE, ErrorCode.CONFIG_SCHEMA_ERROR)
        update_result = self._maa_update().run(context.deadline, context.cancel)
        mapping = {
            "completed": (OutcomeKind.SUCCESS, ErrorCode.OK),
            "failed": (OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED),
            "timeout": (OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT),
            "cancelled": (OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED),
        }
        outcome, code = mapping[update_result.status.value]
        return StageReport(
            self._stage,
            outcome,
            code,
            update_result.started_at,
            update_result.finished_at,
            update_result.duration_ms,
            diagnostics={
                "enabled": True,
                "executed": True,
                "source_error_code": update_result.error_code.value,
                "termination_reason": (
                    update_result.termination_reason.value if update_result.termination_reason is not None else ""
                ),
                "exit_code": update_result.exit_code,
                "owned_process_cleaned": update_result.owned_process_cleaned,
                "stdout_truncated": update_result.stdout_truncated,
                "stderr_truncated": update_result.stderr_truncated,
                **maa_output_diagnostics(update_result),
            },
        )

    def _run_maa_resource_merge(self, context: StageExecutionContext) -> StageReport:
        """把 MaaResource 增量资源合并进 MaaCore 共用资源目录。

        必须紧跟在 ``UPDATE_MAA`` 之后：``maa update`` 刚把仓库 pull 到最新，而
        MaaCore 本身升级会把 ``resource`` 重刷回该版本自带的内容，因此合并必须
        在两者之后才能得到正确结果。
        """
        if not self._config.maa_resource_merge.enabled:
            return _instant(
                self._stage,
                OutcomeKind.SUCCESS,
                ErrorCode.OK,
                {"enabled": False, "executed": False},
            )
        if self._config.maa_resource_merge.validate():
            return _instant(self._stage, OutcomeKind.FAILURE, ErrorCode.CONFIG_SCHEMA_ERROR)
        merge_result = self._maa_resource_merge().run(context.deadline, context.cancel)
        mapping = {
            MAAResourceMergeStatus.COMPLETED: (OutcomeKind.SUCCESS, ErrorCode.OK),
            MAAResourceMergeStatus.FAILED: (OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED),
            MAAResourceMergeStatus.TIMEOUT: (OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT),
            MAAResourceMergeStatus.CANCELLED: (OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED),
        }
        outcome, code = mapping[merge_result.status]
        return StageReport(
            self._stage,
            outcome,
            code,
            merge_result.started_at,
            merge_result.finished_at,
            merge_result.duration_ms,
            diagnostics={
                "enabled": True,
                "executed": True,
                "source_error_code": merge_result.error_code.value,
                "changed": merge_result.changed,
                "files_scanned": merge_result.files_scanned,
                "files_copied": merge_result.files_copied,
                "files_identical": merge_result.files_identical,
                "bytes_copied": merge_result.bytes_copied,
                "directories_created": merge_result.directories_created,
            },
        )

    def _validate(self) -> StageReport:
        errors = self._config.validate()
        if not errors:
            errors = self._config.check_paths()
        if not errors:
            return _instant(self._stage, OutcomeKind.SUCCESS, ErrorCode.OK)
        return _instant(
            self._stage,
            OutcomeKind.FAILURE,
            errors[0],
            {"error_count": len(errors), "first_error_code": errors[0].value},
        )

    def _run_mumu(self, context: StageExecutionContext) -> StageReport:
        if context.deadline is None:
            return _instant(
                self._stage,
                OutcomeKind.FAILURE,
                ErrorCode.WORKFLOW_DEADLINE_REQUIRED,
            )
        mumu = self._mumu()
        managed = self._config.mumu.lifecycle_mode == MumuLifecycleMode.MANAGED
        stop_stages = {StageName.STOP_MUMU, StageName.SHUTDOWN_MUMU}
        lifecycle_stages = {
            StageName.ENSURE_MUMU_RUNNING,
            StageName.START_MUMU,
            StageName.STOP_MUMU,
            StageName.SHUTDOWN_MUMU,
        }
        if managed and self._stage in lifecycle_stages:
            if not isinstance(mumu, ManagedMumuRuntimePort):
                return _instant(
                    self._stage,
                    OutcomeKind.FAILURE,
                    ErrorCode.WORKFLOW_STAGE_BLOCKED,
                    {"blocker": "mumu_lifecycle_port_unavailable"},
                )
            if self._stage in stop_stages:
                result = mumu.stop(context.deadline, context.cancel)
            else:
                result = mumu.start(context.deadline, context.cancel)
        elif self._stage == StageName.ENSURE_MUMU_RUNNING:
            result = mumu.ensure_external_ready(context.deadline, context.cancel)
        else:
            result = mumu.status(context.deadline, context.cancel)
        if managed:
            if self._stage in {StageName.ENSURE_MUMU_RUNNING, StageName.START_MUMU} and (
                result.changed
                or result.status
                in {
                    MumuRuntimeStatus.STARTED,
                    MumuRuntimeStatus.RESTARTED,
                }
            ):
                self._state.mumu_managed_owned = True
            if self._stage in {StageName.STOP_MUMU, StageName.SHUTDOWN_MUMU} and (
                result.status == MumuRuntimeStatus.STOPPED
            ):
                self._state.mumu_managed_owned = False

        report = project_mumu(
            self._stage,
            result,
            lifecycle_mode=self._config.mumu.lifecycle_mode,
            ensure_running=self._stage == StageName.ENSURE_MUMU_RUNNING,
            expect_stopped=self._stage
            in {
                StageName.STOP_MUMU,
                StageName.VERIFY_MUMU_STOPPED,
                StageName.SHUTDOWN_MUMU,
            },
        )
        if context.failure_cleanup:
            report = replace(
                report,
                diagnostics={**dict(report.diagnostics), "failure_cleanup": True},
            )
        return report

    def _verify_starrail_postcondition(self) -> StageReport:
        cleaned = self._state.starrail_owned_process_cleaned
        success = self._state.starrail_run_reached and cleaned
        return _instant(
            self._stage,
            OutcomeKind.SUCCESS if success else OutcomeKind.FAILURE,
            ErrorCode.OK if success else ErrorCode.WORKFLOW_STAGE_FAILED,
            {
                "postcondition": "owned_process_cleaned",
                "owned_process_cleaned": cleaned,
            },
        )
