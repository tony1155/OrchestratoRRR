"""入口级 elevation 前置决策测试。"""

from __future__ import annotations

from typing import cast

from autogame_orchestrator.config_model import AALCConfig, AppConfig
from autogame_orchestrator.models import RunReport
from autogame_orchestrator.workflow.coordinator import WorkflowCoordinator
from tests.workflow.fakes import ElevationCode, FakeElevationGateway, FakeElevationResult


class FakeRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, **kwargs) -> RunReport:
        self.calls += 1
        return cast("RunReport", kwargs.get("report"))


class RecordingRunnerFactory:
    def __init__(self) -> None:
        self.calls = 0
        self.runner = FakeRunner()

    def __call__(self, plan):
        self.calls += 1
        return self.runner


def config(requires_administrator: bool) -> AppConfig:
    return AppConfig(aalc=AALCConfig(requires_administrator=requires_administrator))


def test_non_admin_relaunches_before_runner_construction() -> None:
    gateway = FakeElevationGateway(elevated=False)
    factory = RecordingRunnerFactory()
    result = WorkflowCoordinator(gateway, factory).execute(config(True))
    assert result.relaunched is True
    assert gateway.relaunch_calls == 1
    assert factory.calls == 0


def test_non_admin_relaunches_before_executor_factory() -> None:
    gateway = FakeElevationGateway(elevated=False)
    factory = RecordingRunnerFactory()
    WorkflowCoordinator(gateway, factory).execute(config(True))
    assert factory.runner.calls == 0


def test_elevated_entry_does_not_relaunch() -> None:
    gateway = FakeElevationGateway(elevated=True)
    factory = RecordingRunnerFactory()
    WorkflowCoordinator(gateway, factory).execute(config(True))
    assert gateway.relaunch_calls == 0
    assert factory.calls == 1


def test_requirement_false_never_checks_elevation() -> None:
    gateway = FakeElevationGateway(elevated=False)
    factory = RecordingRunnerFactory()
    WorkflowCoordinator(gateway, factory).execute(config(False))
    assert gateway.check_calls == 0
    assert gateway.relaunch_calls == 0


def test_elevation_cancelled_is_propagated() -> None:
    gateway = FakeElevationGateway(
        elevated=False,
        result=FakeElevationResult(ElevationCode.CANCELLED, 9),
    )
    result = WorkflowCoordinator(gateway, RecordingRunnerFactory()).execute(config(True))
    assert result.elevation_error_code == "ELEVATION_CANCELLED"
    assert result.exit_code == 9


def test_elevation_failure_is_propagated() -> None:
    gateway = FakeElevationGateway(
        elevated=False,
        result=FakeElevationResult(ElevationCode.FAILED, 10),
    )
    result = WorkflowCoordinator(gateway, RecordingRunnerFactory()).execute(config(True))
    assert result.elevation_error_code == "ELEVATION_FAILED"
    assert result.exit_code == 10


def test_elevated_child_exit_code_is_forwarded() -> None:
    gateway = FakeElevationGateway(
        elevated=False,
        result=FakeElevationResult(ElevationCode.OK, 37),
    )
    result = WorkflowCoordinator(gateway, RecordingRunnerFactory()).execute(config(True))
    assert result.exit_code == 37


def test_elevation_marker_prevents_recursive_relaunch() -> None:
    gateway = FakeElevationGateway(elevated=False)
    factory = RecordingRunnerFactory()
    result = WorkflowCoordinator(gateway, factory).execute(
        config(True),
        elevation_marker_present=True,
    )
    assert result.elevation_error_code == "ELEVATION_FAILED"
    assert gateway.relaunch_calls == 0
    assert factory.calls == 0


def test_relaunch_arguments_are_forwarded_without_config_contents() -> None:
    gateway = FakeElevationGateway(elevated=False)
    arguments = ("--config", "safe-reference", "--internal-elevated")
    WorkflowCoordinator(gateway, RecordingRunnerFactory()).execute(
        config(True),
        relaunch_arguments=arguments,
    )
    assert gateway.arguments == arguments


def test_plan_is_built_before_permission_decision() -> None:
    gateway = FakeElevationGateway(elevated=False)
    WorkflowCoordinator(gateway, RecordingRunnerFactory()).execute(config(True))
    assert gateway.check_calls == 1
