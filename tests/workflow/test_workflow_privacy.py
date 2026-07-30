"""工作流报告、事件和异常投影的递归隐私测试。"""

import json

import pytest

from autogame_orchestrator.models import StageName
from tests.workflow.fakes import MemorySink, RecordingFactory
from tests.workflow.test_workflow_runner import make_runner

SECRETS = (
    "E:\\private\\program.exe",
    "private-config.toml",
    "stdout secret",
    "stderr secret",
    "adb-serial-secret",
    "TOKEN_VALUE",
    "123456",
    "orchestratorrr-maa-",
)


@pytest.mark.parametrize("secret", SECRETS)
def test_report_and_events_do_not_expose_sensitive_values(secret: str) -> None:
    events = []
    factory = RecordingFactory()
    factory.factory_error.add(StageName.VALIDATE_CONFIG)
    report = make_runner(factory, MemorySink(), event_sink=events.append)[0].run()
    projection = json.dumps(
        {"report": report.to_json_encodable(), "events": events},
        ensure_ascii=False,
    )
    assert secret not in projection


def test_all_stage_diagnostics_are_json_serializable() -> None:
    report = make_runner()[0].run()
    for stage in report.stages:
        json.dumps(dict(stage.diagnostics))


def test_top_level_diagnostics_use_allowlisted_fields() -> None:
    report = make_runner()[0].run()
    assert set(report.diagnostics) <= {
        "requires_administrator",
        "stage_count",
        "source_error_code",
    }
