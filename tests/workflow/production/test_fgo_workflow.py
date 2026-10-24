"""FGO（Mash）链路的计划、执行器投影与配置门测试。"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autogame_orchestrator.config_model import (
    AppConfig,
    GameSelection,
    MashConfig,
    MashRepeatMode,
    MashServer,
    MuMuConfig,
    MumuLifecycleMode,
)
from autogame_orchestrator.models import ErrorCode, OutcomeKind, StageName
from autogame_orchestrator.planning import build_fgo_plan, build_plan
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.process.errors import TerminationReason
from autogame_orchestrator.run_application import (
    FGO_EXTERNAL_RUN_STAGES,
    FGO_MANAGED_RUN_STAGES,
    validate_external_plan,
)
from autogame_orchestrator.runtime.mash_models import MashErrorCode, MashRunResult, MashRunStatus
from autogame_orchestrator.workflow.contracts import StageExecutionContext
from autogame_orchestrator.workflow.plan import ExecutionPlan, build_execution_plan
from autogame_orchestrator.workflow.production.factory import build_production_executor_factory
from autogame_orchestrator.workflow.production.ports import RuntimeFactories

NOW = datetime(2026, 10, 24, tzinfo=UTC)
LATER = datetime(2026, 10, 24, 0, 0, 10, tzinfo=UTC)


def mash_result(
    status: MashRunStatus = MashRunStatus.COMPLETED,
    *,
    diagnostics: dict[str, object] | None = None,
) -> MashRunResult:
    values = {
        MashRunStatus.COMPLETED: (MashErrorCode.OK, TerminationReason.NORMAL_EXIT, 0),
        MashRunStatus.FAILED: (MashErrorCode.PROCESS_EXIT_NONZERO, TerminationReason.NONZERO_EXIT, 1),
        MashRunStatus.TIMEOUT: (MashErrorCode.PROCESS_TIMEOUT, TerminationReason.STOPPED, None),
        MashRunStatus.CANCELLED: (MashErrorCode.GRACEFUL_STOP_FAILED, TerminationReason.STOPPED, None),
    }
    code, reason, exit_code = values[status]
    base: dict[str, object] = {
        "graceful_stop_requested": status in {MashRunStatus.TIMEOUT, MashRunStatus.CANCELLED},
        "outcome": "finished" if status is MashRunStatus.COMPLETED else status.value,
        "completedRuns": 3,
    }
    if diagnostics:
        base.update(diagnostics)
    return MashRunResult(
        status,
        code,
        NOW,
        LATER,
        10_000,
        4321,
        exit_code,
        reason,
        True,
        '{"type":"run-started"}',
        "",
        False,
        False,
        base,
    )


class FakeMashRun:
    def __init__(self, result: MashRunResult) -> None:
        self.result = result
        self.deadline = None
        self.cancel = None

    def run(self, deadline=None, cancel=None):
        self.deadline = deadline
        self.cancel = cancel
        return self.result


def fgo_config(tmp_path: Path) -> AppConfig:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    executables: dict[str, str] = {}
    for name in ("mash-cli.exe", "mumu.exe", "adb.exe"):
        path = tmp_path / name
        path.write_text("fake", encoding="utf-8")
        executables[name] = str(path)
    return AppConfig(
        mumu=MuMuConfig(
            executable=executables["mumu.exe"],
            adb_executable=executables["adb.exe"],
        ),
        game=GameSelection.FGO,
        mash=MashConfig(
            executable=executables["mash-cli.exe"],
            working_directory=str(work),
            project_id="p-fgo-1",
            server=MashServer.CN,
            result_file=str(tmp_path / "mash-result.json"),
            repeat_mode=MashRepeatMode.COUNT,
            repeat_count=3,
        ),
    )


def context() -> StageExecutionContext:
    return StageExecutionContext(
        "00000000-0000-0000-0000-000000000001",
        StageName.RUN_MASH,
        Deadline.after(60.0),
        CancellationToken(),
    )


def factories(mash: object | None) -> tuple[RuntimeFactories, Counter[str]]:
    counts: Counter[str] = Counter()

    def counting(name: str, value: object):
        def factory():
            counts[name] += 1
            return value

        return factory

    runtime_factories = RuntimeFactories(
        counting("starrail", object()),
        counting("maa", object()),
        counting("aalc", object()),
        counting("mumu", object()),
        None,
        None,
        None,
        counting("mash", mash) if mash is not None else None,
    )
    return runtime_factories, counts


def test_fgo_plan_shape_is_frozen() -> None:
    plan = build_fgo_plan()
    assert plan[0] is StageName.VALIDATE_CONFIG
    assert plan[-1] is StageName.WRITE_RUN_REPORT
    assert StageName.RUN_MASH in plan
    assert StageName.RUN_STARRAIL not in plan
    assert StageName.RUN_MAA not in plan
    assert len(set(plan)) == len(plan)
    assert build_plan() is not build_fgo_plan() or build_plan() != build_fgo_plan()


def test_build_execution_plan_selects_fgo_managed(tmp_path: Path) -> None:
    config = fgo_config(tmp_path)
    plan = build_execution_plan(config)
    assert plan.stages == FGO_MANAGED_RUN_STAGES


def test_build_execution_plan_selects_fgo_external(tmp_path: Path) -> None:
    config = fgo_config(tmp_path)
    config = _with_external_mumu(config)
    plan = build_execution_plan(config)
    assert plan.stages == FGO_EXTERNAL_RUN_STAGES
    assert StageName.SHUTDOWN_MUMU not in plan.stages


def _with_external_mumu(config: AppConfig) -> AppConfig:
    from dataclasses import replace

    return replace(
        config,
        mumu=MuMuConfig(
            lifecycle_mode=MumuLifecycleMode.EXTERNAL,
            executable="",
            adb_executable=config.mumu.adb_executable,
        ),
    )


def test_validate_external_plan_accepts_fgo_variants() -> None:
    assert validate_external_plan(ExecutionPlan(FGO_MANAGED_RUN_STAGES, False)) is None
    assert validate_external_plan(ExecutionPlan(FGO_EXTERNAL_RUN_STAGES, False)) is None
    tampered = FGO_MANAGED_RUN_STAGES[:4] + (StageName.STOP_MUMU,) + FGO_MANAGED_RUN_STAGES[4:]
    assert validate_external_plan(ExecutionPlan(tampered, False)) == "external_plan_invalid"


@pytest.mark.parametrize(
    "status,outcome,code",
    [
        (MashRunStatus.COMPLETED, OutcomeKind.SUCCESS, ErrorCode.OK),
        (MashRunStatus.FAILED, OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED),
        (MashRunStatus.TIMEOUT, OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT),
        (MashRunStatus.CANCELLED, OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED),
    ],
)
def test_run_mash_stage_projection(
    tmp_path: Path, status: MashRunStatus, outcome: OutcomeKind, code: ErrorCode
) -> None:
    fake = FakeMashRun(mash_result(status))
    runtime_factories, counts = factories(fake)
    report = build_production_executor_factory(fgo_config(tmp_path), runtime_factories=runtime_factories)(
        StageName.RUN_MASH
    ).execute(context())
    assert (report.outcome, report.error_code) == (outcome, code)
    assert counts == Counter({"mash": 1})
    assert report.diagnostics["source_error_code"] is not None
    if status is MashRunStatus.COMPLETED:
        assert report.diagnostics["mash_completed_runs"] == 3
        assert report.diagnostics["mash_outcome"] == "finished"
    if status in {MashRunStatus.TIMEOUT, MashRunStatus.CANCELLED}:
        assert report.diagnostics["graceful_stop_requested"] is True


def test_run_mash_without_binding_maps_config_schema_error(tmp_path: Path) -> None:
    runtime_factories, _ = factories(None)
    report = build_production_executor_factory(fgo_config(tmp_path), runtime_factories=runtime_factories)(
        StageName.RUN_MASH
    ).execute(context())
    assert report.outcome is OutcomeKind.FAILURE
    assert report.error_code is ErrorCode.CONFIG_SCHEMA_ERROR


def test_fgo_config_validates_without_starrail_maa_sections(tmp_path: Path) -> None:
    config = fgo_config(tmp_path)
    assert config.validate() == []
    assert config.check_paths() == []


def test_fgo_config_rejects_incomplete_mash(tmp_path: Path) -> None:
    config = fgo_config(tmp_path)
    from dataclasses import replace

    broken = replace(config.mash, project_id="")
    assert replace(config, mash=broken).validate() != []


def test_starrail_game_ignores_mash_section(tmp_path: Path) -> None:
    config = fgo_config(tmp_path)
    from dataclasses import replace

    starrail = replace(config, game=GameSelection.STARRAIL)
    # starrail 段未配置（缺可执行文件等），但 mash 段的错误不应出现在 starrail 模式。
    errors = starrail.validate()
    assert all("mash" not in str(e) for e in errors)
