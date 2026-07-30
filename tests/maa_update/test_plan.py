from __future__ import annotations

import pytest

from autogame_orchestrator.config_model import AALCConfig, AppConfig, MAASyncConfig, MAAUpdateConfig
from autogame_orchestrator.models import StageName
from autogame_orchestrator.workflow.coordinator import WorkflowCoordinator
from autogame_orchestrator.workflow.plan import build_execution_plan
from tests.workflow.fakes import FakeElevationGateway
from tests.workflow.test_workflow_coordinator import RecordingRunnerFactory


def test_sync_administrator_requirement_enters_plan() -> None:
    config = AppConfig(maa_sync=MAASyncConfig(enabled=True, requires_administrator=True))
    assert build_execution_plan(config).requires_administrator is True


def test_disabled_sync_does_not_require_administrator() -> None:
    config = AppConfig(maa_sync=MAASyncConfig(requires_administrator=True))
    assert build_execution_plan(config).requires_administrator is False


def test_update_administrator_requirement_enters_plan() -> None:
    config = AppConfig(maa_update=MAAUpdateConfig(True, True, True))
    assert build_execution_plan(config).requires_administrator is True


def test_disabled_update_does_not_require_administrator() -> None:
    config = AppConfig(maa_update=MAAUpdateConfig(requires_administrator=True))
    assert build_execution_plan(config).requires_administrator is False


def test_aalc_administrator_rule_is_preserved() -> None:
    assert build_execution_plan(AppConfig(aalc=AALCConfig(requires_administrator=True))).requires_administrator is True


def test_no_requirement_does_not_require_administrator() -> None:
    assert build_execution_plan(AppConfig()).requires_administrator is False


@pytest.mark.parametrize(
    "config,stages",
    [
        (
            AppConfig(maa_sync=MAASyncConfig(enabled=True, requires_administrator=True)),
            (StageName.VALIDATE_CONFIG, StageName.UPDATE_MAA, StageName.WRITE_RUN_REPORT),
        ),
        (
            AppConfig(maa_update=MAAUpdateConfig(True, True, True)),
            (StageName.VALIDATE_CONFIG, StageName.SYNC_MAA_CONFIG, StageName.WRITE_RUN_REPORT),
        ),
    ],
)
def test_requirement_only_applies_when_stage_is_present(config: AppConfig, stages: tuple[StageName, ...]) -> None:
    assert build_execution_plan(config, stages=stages).requires_administrator is False


@pytest.mark.parametrize(
    "config",
    [
        AppConfig(maa_sync=MAASyncConfig(enabled=True, requires_administrator=True)),
        AppConfig(maa_update=MAAUpdateConfig(True, True, True)),
    ],
)
def test_new_requirements_relaunch_before_runner(config: AppConfig) -> None:
    gateway = FakeElevationGateway(elevated=False)
    factory = RecordingRunnerFactory()
    result = WorkflowCoordinator(gateway, factory).execute(config)
    assert result.relaunched is True
    assert factory.calls == 0
