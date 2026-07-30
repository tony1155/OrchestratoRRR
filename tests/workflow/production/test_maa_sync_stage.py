from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import pytest

from autogame_orchestrator.config_model import AppConfig, MAASyncConfig
from autogame_orchestrator.maa_sync.models import MAASyncErrorCode, MAASyncResult, MAASyncStatus
from autogame_orchestrator.models import ErrorCode, OutcomeKind, StageName
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.workflow.contracts import StageExecutionContext
from autogame_orchestrator.workflow.production.factory import build_production_executor_factory
from tests.workflow.production.test_executors_and_factory import factories

NOW = datetime(2026, 7, 30, tzinfo=UTC)


class FakeSync:
    def __init__(self, status: MAASyncStatus) -> None:
        code = {
            MAASyncStatus.COMPLETED: MAASyncErrorCode.OK,
            MAASyncStatus.FAILED: MAASyncErrorCode.TRANSFORM_FAILED,
            MAASyncStatus.TIMEOUT: MAASyncErrorCode.PARENT_DEADLINE,
            MAASyncStatus.CANCELLED: MAASyncErrorCode.CANCELLED,
        }[status]
        self.result = MAASyncResult(status, code, NOW, NOW, 0, True, True, True, True, False, False, False, False)
        self.deadline = None
        self.cancel = None

    def run(self, deadline=None, cancel=None):
        self.deadline = deadline
        self.cancel = cancel
        return self.result


def context(deadline=None, cancel=None):
    return StageExecutionContext(
        "00000000-0000-0000-0000-000000000001", StageName.SYNC_MAA_CONFIG, deadline, cancel or CancellationToken()
    )


def test_disabled_sync_constructs_no_service() -> None:
    runtime_factories, counts = factories()
    factory = build_production_executor_factory(AppConfig(), runtime_factories=runtime_factories)
    report = factory(StageName.SYNC_MAA_CONFIG).execute(context())
    assert (report.outcome, report.error_code) == (OutcomeKind.SUCCESS, ErrorCode.OK)
    assert counts == Counter()


@pytest.mark.parametrize(
    "status,outcome,code",
    [
        (MAASyncStatus.COMPLETED, OutcomeKind.SUCCESS, ErrorCode.OK),
        (MAASyncStatus.FAILED, OutcomeKind.FAILURE, ErrorCode.WORKFLOW_STAGE_FAILED),
        (MAASyncStatus.TIMEOUT, OutcomeKind.TIMEOUT, ErrorCode.WORKFLOW_STAGE_TIMEOUT),
        (MAASyncStatus.CANCELLED, OutcomeKind.CANCELLED, ErrorCode.WORKFLOW_CANCELLED),
    ],
)
def test_sync_status_mapping(status: MAASyncStatus, outcome: OutcomeKind, code: ErrorCode) -> None:
    service = FakeSync(status)
    runtime_factories, counts = factories()
    runtime_factories = type(runtime_factories)(
        runtime_factories.starrail,
        runtime_factories.maa,
        runtime_factories.aalc,
        runtime_factories.mumu,
        lambda: counts.update(["maa_sync"]) or service,
    )
    config = AppConfig(
        maa_sync=MAASyncConfig(
            enabled=True,
            gui_settings_source="a",
            gui_tasks_source="b",
            cli_profile_destination="c",
            cli_tasks_destination="d",
        )
    )
    report = build_production_executor_factory(config, runtime_factories=runtime_factories)(
        StageName.SYNC_MAA_CONFIG
    ).execute(context())
    assert (report.outcome, report.error_code) == (outcome, code)
    assert counts["maa_sync"] == 1


def test_stage_forwards_same_deadline_and_token() -> None:
    service = FakeSync(MAASyncStatus.COMPLETED)
    runtime_factories, _ = factories()
    runtime_factories = type(runtime_factories)(
        runtime_factories.starrail,
        runtime_factories.maa,
        runtime_factories.aalc,
        runtime_factories.mumu,
        lambda: service,
    )
    config = AppConfig(maa_sync=MAASyncConfig(True, "a", "b", "c", "d"))
    deadline = Deadline.after(30)
    token = CancellationToken()
    build_production_executor_factory(config, runtime_factories=runtime_factories)(StageName.SYNC_MAA_CONFIG).execute(
        context(deadline, token)
    )
    assert service.deadline is deadline
    assert service.cancel is token


def test_stage_diagnostics_are_allowlisted() -> None:
    service = FakeSync(MAASyncStatus.COMPLETED)
    runtime_factories, _ = factories()
    runtime_factories = type(runtime_factories)(
        runtime_factories.starrail,
        runtime_factories.maa,
        runtime_factories.aalc,
        runtime_factories.mumu,
        lambda: service,
    )
    config = AppConfig(maa_sync=MAASyncConfig(True, "sensitive-source", "b", "c", "d"))
    report = build_production_executor_factory(config, runtime_factories=runtime_factories)(
        StageName.SYNC_MAA_CONFIG
    ).execute(context())
    assert set(report.diagnostics) == {
        "source_error_code",
        "enabled",
        "changed",
        "profile_written",
        "tasks_written",
        "profile_backup_written",
        "tasks_backup_written",
        "rollback_attempted",
        "rollback_succeeded",
    }
    assert "sensitive-source" not in repr(report)


def test_update_maa_remains_blocked() -> None:
    runtime_factories, counts = factories()
    report = build_production_executor_factory(AppConfig(), runtime_factories=runtime_factories)(
        StageName.UPDATE_MAA
    ).execute(
        StageExecutionContext("00000000-0000-0000-0000-000000000001", StageName.UPDATE_MAA, None, CancellationToken())
    )
    assert report.error_code == ErrorCode.WORKFLOW_STAGE_BLOCKED
    assert counts == Counter()
