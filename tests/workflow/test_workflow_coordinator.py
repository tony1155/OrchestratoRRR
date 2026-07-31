"""入口级 elevation 前置决策测试。"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from autogame_orchestrator.config_model import AALCConfig, AppConfig
from autogame_orchestrator.entry_runtime import ElevationLaunchSpec
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


def launch_spec() -> ElevationLaunchSpec:
    return ElevationLaunchSpec(Path("python.exe"), ("run", "--config", "safe-reference"), Path.cwd())


def execute(coordinator: WorkflowCoordinator, app_config: AppConfig, **kwargs):
    return coordinator.execute(app_config, relaunch_spec=launch_spec(), **kwargs)


def test_non_admin_relaunches_before_runner_construction() -> None:
    gateway = FakeElevationGateway(elevated=False)
    factory = RecordingRunnerFactory()
    result = execute(WorkflowCoordinator(gateway, factory), config(True))
    assert result.relaunched is True
    assert gateway.relaunch_calls == 1
    assert factory.calls == 0


def test_non_admin_relaunches_before_executor_factory() -> None:
    gateway = FakeElevationGateway(elevated=False)
    factory = RecordingRunnerFactory()
    execute(WorkflowCoordinator(gateway, factory), config(True))
    assert factory.runner.calls == 0


def test_elevated_entry_does_not_relaunch() -> None:
    gateway = FakeElevationGateway(elevated=True)
    factory = RecordingRunnerFactory()
    execute(WorkflowCoordinator(gateway, factory), config(True))
    assert gateway.relaunch_calls == 0
    assert factory.calls == 1


def test_requirement_false_never_checks_elevation() -> None:
    gateway = FakeElevationGateway(elevated=False)
    factory = RecordingRunnerFactory()
    execute(WorkflowCoordinator(gateway, factory), config(False))
    assert gateway.check_calls == 0
    assert gateway.relaunch_calls == 0


def test_elevation_cancelled_is_propagated() -> None:
    gateway = FakeElevationGateway(
        elevated=False,
        result=FakeElevationResult(ElevationCode.CANCELLED, 9),
    )
    result = execute(WorkflowCoordinator(gateway, RecordingRunnerFactory()), config(True))
    assert result.elevation_error_code == "ELEVATION_CANCELLED"
    assert result.exit_code == 9


def test_elevation_failure_is_propagated() -> None:
    gateway = FakeElevationGateway(
        elevated=False,
        result=FakeElevationResult(ElevationCode.FAILED, 10),
    )
    result = execute(WorkflowCoordinator(gateway, RecordingRunnerFactory()), config(True))
    assert result.elevation_error_code == "ELEVATION_FAILED"
    assert result.exit_code == 10


def test_elevated_child_exit_code_is_forwarded() -> None:
    gateway = FakeElevationGateway(
        elevated=False,
        result=FakeElevationResult(ElevationCode.OK, 37),
    )
    result = execute(WorkflowCoordinator(gateway, RecordingRunnerFactory()), config(True))
    assert result.exit_code == 37


def test_elevation_marker_prevents_recursive_relaunch() -> None:
    gateway = FakeElevationGateway(elevated=False)
    factory = RecordingRunnerFactory()
    result = execute(
        WorkflowCoordinator(gateway, factory),
        config(True),
        elevation_marker_present=True,
    )
    assert result.elevation_error_code == "ELEVATION_FAILED"
    assert gateway.relaunch_calls == 0
    assert factory.calls == 0


def test_relaunch_spec_is_forwarded_without_config_contents() -> None:
    gateway = FakeElevationGateway(elevated=False)
    spec = ElevationLaunchSpec(Path("python.exe"), ("--config", "safe-reference", "--internal-elevated"), Path.cwd())
    WorkflowCoordinator(gateway, RecordingRunnerFactory()).execute(
        config(True),
        relaunch_spec=spec,
    )
    assert gateway.spec == spec


def test_plan_is_built_before_permission_decision() -> None:
    gateway = FakeElevationGateway(elevated=False)
    execute(WorkflowCoordinator(gateway, RecordingRunnerFactory()), config(True))
    assert gateway.check_calls == 1
