"""冻结执行计划的契约测试。"""

from dataclasses import FrozenInstanceError

import pytest

from autogame_orchestrator.config_model import AALCConfig, AppConfig
from autogame_orchestrator.models import StageName
from autogame_orchestrator.planning import build_plan
from autogame_orchestrator.workflow.plan import ExecutionPlan, build_execution_plan


def test_default_plan_preserves_existing_order() -> None:
    assert build_execution_plan(AppConfig()).stages == build_plan()


def test_default_plan_has_fifteen_stages() -> None:
    assert len(build_execution_plan(AppConfig()).stages) == 15


def test_default_plan_ends_with_maa_shutdown_and_report() -> None:
    stages = build_execution_plan(AppConfig()).stages
    assert StageName.RUN_AALC not in stages
    assert stages[-3:] == (
        StageName.RUN_MAA,
        StageName.SHUTDOWN_MUMU,
        StageName.WRITE_RUN_REPORT,
    )


def test_execution_plan_is_frozen() -> None:
    plan = build_execution_plan(AppConfig())
    with pytest.raises(FrozenInstanceError):
        plan.requires_administrator = True  # type: ignore[misc]


def test_empty_plan_is_rejected() -> None:
    with pytest.raises(ValueError):
        ExecutionPlan((), False)


def test_non_tuple_stages_are_rejected() -> None:
    with pytest.raises(ValueError):
        ExecutionPlan([StageName.VALIDATE_CONFIG], False)  # type: ignore[arg-type]


def test_duplicate_stage_is_rejected() -> None:
    stages = (StageName.VALIDATE_CONFIG, StageName.RUN_MAA, StageName.RUN_MAA, StageName.WRITE_RUN_REPORT)
    with pytest.raises(ValueError):
        ExecutionPlan(stages, False)


def test_validate_config_must_be_first() -> None:
    with pytest.raises(ValueError):
        ExecutionPlan((StageName.RUN_MAA, StageName.WRITE_RUN_REPORT), False)


def test_write_report_is_required() -> None:
    with pytest.raises(ValueError):
        ExecutionPlan((StageName.VALIDATE_CONFIG, StageName.RUN_MAA), False)


def test_write_report_must_be_last() -> None:
    stages = (StageName.VALIDATE_CONFIG, StageName.WRITE_RUN_REPORT, StageName.RUN_MAA)
    with pytest.raises(ValueError):
        ExecutionPlan(stages, False)


@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_requires_administrator_is_strict_bool(value: object) -> None:
    with pytest.raises(ValueError):
        ExecutionPlan((StageName.VALIDATE_CONFIG, StageName.WRITE_RUN_REPORT), value)  # type: ignore[arg-type]


def test_legacy_aalc_requirement_is_ignored() -> None:
    config = AppConfig(aalc=AALCConfig(requires_administrator=True))
    assert build_execution_plan(config).requires_administrator is False


def test_aalc_without_requirement_does_not_require_administrator() -> None:
    assert build_execution_plan(AppConfig()).requires_administrator is False


def test_plan_without_aalc_never_requires_administrator() -> None:
    config = AppConfig(aalc=AALCConfig(requires_administrator=True))
    stages = (StageName.VALIDATE_CONFIG, StageName.RUN_MAA, StageName.WRITE_RUN_REPORT)
    assert build_execution_plan(config, stages=stages).requires_administrator is False
