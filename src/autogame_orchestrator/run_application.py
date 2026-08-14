"""公开 run 命令的纯门禁、应用协调和稳定退出码。"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from pathlib import Path

from autogame_orchestrator.config_loader import load_config
from autogame_orchestrator.config_model import AppConfig, MumuLifecycleMode
from autogame_orchestrator.entry_runtime import (
    ElevationLaunchSpec,
    EntryRuntime,
    EntryRuntimeKind,
    detect_entry_runtime,
)
from autogame_orchestrator.models import ErrorCode, RunReport, RunStatus, StageName
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.workflow.coordinator import WorkflowCoordinationResult
from autogame_orchestrator.workflow.plan import ExecutionPlan, build_execution_plan
from autogame_orchestrator.workflow.production.application import (
    ProductionApplicationDependencies,
    execute_production_workflow,
)

RUN_CONFIRMATION = "I_UNDERSTAND_THIS_RUNS_REAL_PROGRAMS"
MAX_RUN_DEADLINE_SECONDS = 86400.0
ELEVATION_MARKER = "--_elevation-child"

EXTERNAL_RUN_STAGES = (
    StageName.VALIDATE_CONFIG,
    StageName.SYNC_MAA_CONFIG,
    StageName.UPDATE_MAA,
    StageName.ENSURE_MUMU_RUNNING,
    StageName.WAIT_MUMU_ADB_READY,
    StageName.RUN_STARRAIL,
    StageName.STOP_STARRAIL,
    StageName.VERIFY_STARRAIL_STOPPED,
    StageName.RUN_MAA,
    StageName.WRITE_RUN_REPORT,
)


MANAGED_RUN_STAGES = (
    StageName.VALIDATE_CONFIG,
    StageName.SYNC_MAA_CONFIG,
    StageName.UPDATE_MAA,
    StageName.ENSURE_MUMU_RUNNING,
    StageName.WAIT_MUMU_ADB_READY,
    StageName.RUN_STARRAIL,
    StageName.STOP_STARRAIL,
    StageName.VERIFY_STARRAIL_STOPPED,
    StageName.STOP_MUMU,
    StageName.VERIFY_MUMU_STOPPED,
    StageName.START_MUMU,
    StageName.WAIT_MUMU_ADB_READY_AFTER_RESTART,
    StageName.RUN_MAA,
    StageName.SHUTDOWN_MUMU,
    StageName.WRITE_RUN_REPORT,
)


@dataclass(frozen=True)
class RunRequest:
    config_path: Path
    deadline_seconds: float
    confirmation: str
    elevation_child: bool = False


@dataclass(frozen=True)
class RunCommandResult:
    exit_code: int
    status: str
    error_code: str
    run_id: str | None
    report: RunReport | None = None


def validate_run_request(request: RunRequest) -> str | None:
    """只校验确认值和有限父预算，不读取配置或构造运行时。"""

    if request.confirmation != RUN_CONFIRMATION:
        return "real_execution_confirmation_required"
    value = request.deadline_seconds
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "invalid_deadline"
    if not math.isfinite(value) or value <= 0 or value > MAX_RUN_DEADLINE_SECONDS:
        return "invalid_deadline"
    return None


def validate_run_v1_config(config: AppConfig) -> str | None:
    """生产运行的配置闸门：managed 模式仍需显式启停命令。

    managed 模式已获批准，但要求显式配置启停管理命令，避免解闸后静默降级。
    MAA 配置同步已获批准：其路径约束由 ``MAASyncConfig`` 校验（四路径非空、
    源与目标不得重叠），写入为原子替换并具备备份与双目标回滚。
    AALC 重试已获批准：`AALCConfig` 将 attempts 限制在 1–3，且适配器仅对非零
    退出与单次尝试超时重试；正常完成、取消、父 Deadline 到期与清理失败均不重试。

    MAA 自更新已解闸：``MAAUpdateConfig`` 仍禁止 self/hot-update/install/run/task
    子命令、要求 ``arguments[0] == "update"``，并要求 ``allow_network``。上游
    ``maa update`` 的解压环节非事务性（先 ``ensure_clean()`` 清空目标目录再逐
    文件解压，无暂存目录、无完成标记、无回滚），但官方 Windows 发布包将
    ``MaaCore.dll`` 排在所有资源条目之后，中断时动态库通常尚未落盘，下一次
    ``maa update`` 会因读不到版本而重装；MAA GUI 覆盖安装为第二道兜底。
    """

    if config.mumu.lifecycle_mode == MumuLifecycleMode.MANAGED and not (
        config.mumu.start_arguments and config.mumu.stop_arguments
    ):
        return "managed_mumu_arguments_required"
    return None


def validate_external_plan(plan: ExecutionPlan) -> str | None:
    """要求与生命周期模式匹配的精确默认计划（external 11 阶段 / managed 15 阶段）。"""

    if plan.stages not in (EXTERNAL_RUN_STAGES, MANAGED_RUN_STAGES):
        return "external_plan_invalid"
    return None


def build_relaunch_spec(request: RunRequest, runtime: EntryRuntime) -> ElevationLaunchSpec:
    """Build the source or frozen elevated-child entry specification."""

    common_arguments: tuple[str, ...] = (
        "run",
        "--config",
        str(request.config_path.resolve()),
        "--deadline-seconds",
        format(request.deadline_seconds, ".17g"),
        "--confirm-real-execution",
        RUN_CONFIRMATION,
    )
    if runtime.kind is EntryRuntimeKind.SOURCE:
        arguments = ("-m", "autogame_orchestrator", *common_arguments)
    else:
        arguments = common_arguments
    return ElevationLaunchSpec(
        executable=runtime.executable,
        arguments=arguments + (() if request.elevation_child else (ELEVATION_MARKER,)),
        working_directory=runtime.working_directory,
    )


def map_run_exit_code(report: RunReport) -> int:
    """按稳定枚举映射工作流退出码。"""

    if report.error_code == ErrorCode.RUN_REPORT_WRITE_ERROR:
        return 7
    if report.status == RunStatus.SUCCESS and report.error_code == ErrorCode.OK:
        return 0
    if report.status == RunStatus.CANCELLED:
        return 5
    if report.error_code == ErrorCode.WORKFLOW_STAGE_TIMEOUT:
        return 4
    if report.status == RunStatus.FAILURE:
        return 3
    return 8


def _coordination_result(result: WorkflowCoordinationResult, run_id: str) -> RunCommandResult:
    if result.report is not None:
        report = result.report
        return RunCommandResult(
            map_run_exit_code(report),
            report.status.value,
            report.error_code.value,
            report.run_id,
            report,
        )
    if result.elevation_error_code == "ELEVATION_CANCELLED":
        return RunCommandResult(9, "elevation_cancelled", "ELEVATION_CANCELLED", None)
    if result.elevation_error_code == "OK" and result.exit_code is not None:
        return RunCommandResult(result.exit_code, "relaunched", "OK", None)
    return RunCommandResult(10, "elevation_failed", "ELEVATION_FAILED", None)


def execute_run_request(
    request: RunRequest,
    *,
    cancel: CancellationToken | None = None,
    dependencies: ProductionApplicationDependencies | None = None,
    entry_runtime: EntryRuntime | None = None,
) -> RunCommandResult:
    """按固定顺序执行 run v1 preflight，并进入生产协调边界。"""

    request_error = validate_run_request(request)
    if request_error is not None:
        return RunCommandResult(2, "rejected", request_error, None)
    config, errors = load_config(request.config_path, check_paths=False)
    if config is None or errors:
        code = errors[0].value if errors else ErrorCode.CONFIG_SCHEMA_ERROR.value
        return RunCommandResult(2, "rejected", code, None)
    gate_error = validate_run_v1_config(config)
    if gate_error is not None:
        return RunCommandResult(2, "rejected", gate_error, None)
    plan = build_execution_plan(config)
    plan_error = validate_external_plan(plan)
    if plan_error is not None:
        return RunCommandResult(2, "rejected", plan_error, None)

    parent_deadline = Deadline.after(float(request.deadline_seconds))
    token = CancellationToken() if cancel is None else cancel
    run_id = str(uuid.uuid4())
    runtime = detect_entry_runtime() if entry_runtime is None else entry_runtime
    try:
        coordination = execute_production_workflow(
            config,
            deadline=parent_deadline,
            cancel=token,
            run_id=run_id,
            relaunch_spec=build_relaunch_spec(request, runtime),
            elevation_marker_present=request.elevation_child,
            dependencies=dependencies,
        )
    except Exception:
        return RunCommandResult(8, "failure", ErrorCode.INTERNAL_ERROR.value, run_id)
    return _coordination_result(coordination, run_id)
