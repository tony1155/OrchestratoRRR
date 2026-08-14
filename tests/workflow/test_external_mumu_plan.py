"""external MuMu 动态执行计划测试。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from autogame_orchestrator.config_model import (
    AALCConfig,
    AppConfig,
    MAASyncConfig,
    MAAUpdateConfig,
    MuMuConfig,
    MumuLifecycleMode,
)
from autogame_orchestrator.models import StageName
from autogame_orchestrator.planning import build_plan
from autogame_orchestrator.workflow.plan import build_execution_plan

EXTERNAL_STAGES = (
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

REMOVED_STAGES = (
    StageName.STOP_MUMU,
    StageName.VERIFY_MUMU_STOPPED,
    StageName.START_MUMU,
    StageName.WAIT_MUMU_ADB_READY_AFTER_RESTART,
)

# SHUTDOWN_MUMU 也只属于 managed：它是 AALC 之后的收尾关闭，external 模式下
# 编排器不拥有模拟器生命周期，故同样被移除。它不在 REMOVED_STAGES 里是因为
# 后者断言的是静态计划中连续的 [8:12] 区段，而 SHUTDOWN_MUMU 位于索引 14。
MANAGED_ONLY_TEARDOWN = StageName.SHUTDOWN_MUMU


def _external_config(**changes: object) -> AppConfig:
    config = AppConfig(mumu=MuMuConfig(lifecycle_mode=MumuLifecycleMode.EXTERNAL))
    return replace(config, **changes)


def test_static_build_plan_has_fifteen_managed_stages() -> None:
    assert len(build_plan()) == 15


def test_static_build_plan_order_is_unchanged() -> None:
    assert build_plan()[8:12] == REMOVED_STAGES


def test_managed_execution_plan_uses_static_plan() -> None:
    assert build_execution_plan(AppConfig()).stages == build_plan()


def test_managed_execution_plan_has_fifteen_stages() -> None:
    assert len(build_execution_plan(AppConfig()).stages) == 15


def test_managed_plan_ends_with_shutdown_before_report() -> None:
    """收尾关闭必须紧邻报告之前：跑完不留模拟器，但报告仍是最后一步。"""
    stages = build_execution_plan(AppConfig()).stages
    assert stages[-2:] == (MANAGED_ONLY_TEARDOWN, StageName.WRITE_RUN_REPORT)


def test_external_plan_omits_shutdown_stage() -> None:
    """external 模式不拥有模拟器生命周期，不得出现收尾关闭阶段。"""
    assert MANAGED_ONLY_TEARDOWN not in build_execution_plan(_external_config()).stages


def test_external_execution_plan_has_exact_order() -> None:
    assert build_execution_plan(_external_config()).stages == EXTERNAL_STAGES


def test_external_execution_plan_has_ten_stages() -> None:
    stages = build_execution_plan(_external_config()).stages
    assert len(stages) == 10
    assert StageName.RUN_AALC not in stages


@pytest.mark.parametrize("stage", REMOVED_STAGES)
def test_external_default_plan_removes_only_lifecycle_stage(stage: StageName) -> None:
    assert stage not in build_execution_plan(_external_config()).stages


@pytest.mark.parametrize(
    "stage",
    [StageName.ENSURE_MUMU_RUNNING, StageName.WAIT_MUMU_ADB_READY],
)
def test_external_plan_preserves_initial_readiness(stage: StageName) -> None:
    assert stage in build_execution_plan(_external_config()).stages


@pytest.mark.parametrize("stage", REMOVED_STAGES)
def test_explicit_stages_are_not_filtered_by_external_mode(stage: StageName) -> None:
    plan = build_execution_plan(_external_config(), stages=build_plan())
    assert stage in plan.stages


def test_explicit_custom_stages_are_preserved_exactly() -> None:
    stages = (StageName.VALIDATE_CONFIG, StageName.RUN_MAA, StageName.WRITE_RUN_REPORT)
    assert build_execution_plan(_external_config(), stages=stages).stages is stages


def test_external_mode_does_not_require_administrator() -> None:
    assert build_execution_plan(_external_config()).requires_administrator is False


def test_external_mode_ignores_legacy_aalc_elevation_rule() -> None:
    config = _external_config(aalc=AALCConfig(requires_administrator=True))
    assert build_execution_plan(config).requires_administrator is False


def test_external_mode_preserves_sync_elevation_rule() -> None:
    config = _external_config(maa_sync=MAASyncConfig(enabled=True, requires_administrator=True))
    assert build_execution_plan(config).requires_administrator is True


def test_external_mode_preserves_update_elevation_rule() -> None:
    config = _external_config(maa_update=MAAUpdateConfig(enabled=True, allow_network=True, requires_administrator=True))
    assert build_execution_plan(config).requires_administrator is True
