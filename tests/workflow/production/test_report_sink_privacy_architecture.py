"""生产 ReportSink、隐私白名单与静态架构边界。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autogame_orchestrator.cli import app
from autogame_orchestrator.models import ErrorCode, StageName
from autogame_orchestrator.reporter import validate_run_report_json
from autogame_orchestrator.runtime.models import MumuRuntimeStatus
from autogame_orchestrator.workflow.plan import build_execution_plan
from autogame_orchestrator.workflow.production.factory import build_production_executor_factory
from autogame_orchestrator.workflow.production.projection import (
    project_aalc,
    project_maa,
    project_mumu,
    project_starrail,
)
from autogame_orchestrator.workflow.production.report_sink import ProductionReportSink
from autogame_orchestrator.workflow.runner import WorkflowRunner
from tests.workflow.fakes import MemorySink
from tests.workflow.production.fakes import aalc_result, maa_result, mumu_result, starrail_result, valid_config
from tests.workflow.production.test_executors_and_factory import factories
from tests.workflow.test_workflow_runner import make_runner

ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = ROOT / "src" / "autogame_orchestrator" / "workflow" / "production"
CORE = ROOT / "src" / "autogame_orchestrator" / "workflow"


def test_production_sink_writes_with_existing_reporter(tmp_path: Path) -> None:
    report = make_runner()[0].run()
    ProductionReportSink(str(tmp_path)).write(report)
    written = list(tmp_path.glob("run-report-*.json"))
    assert len(written) == 1
    assert json.loads(written[0].read_text(encoding="utf-8"))["run_id"] == report.run_id


def test_production_sink_failure_has_no_path(tmp_path: Path) -> None:
    target = tmp_path / "not-a-directory"
    target.write_text("occupied", encoding="utf-8")
    with pytest.raises(OSError) as captured:
        ProductionReportSink(str(target)).write(make_runner()[0].run())
    assert str(tmp_path) not in str(captured.value)


def test_sink_failure_is_mapped_by_workflow_runner(tmp_path: Path) -> None:
    target = tmp_path / "not-a-directory"
    target.write_text("occupied", encoding="utf-8")
    runner, _factory, _sink = make_runner(sink=ProductionReportSink(str(target)))
    assert runner.run().error_code == ErrorCode.RUN_REPORT_WRITE_ERROR


def test_blocked_stage_report_uses_existing_run_report_schema(tmp_path: Path) -> None:
    config = valid_config(tmp_path)
    runtime_factories, _counts = factories()
    report = WorkflowRunner(
        build_execution_plan(config),
        build_production_executor_factory(config, runtime_factories=runtime_factories),
        MemorySink(),
    ).run()
    valid, message = validate_run_report_json(report.to_json_encodable())
    assert valid, message


@pytest.mark.parametrize(
    "projection",
    [
        lambda: project_starrail(StageName.RUN_STARRAIL, starrail_result()),
        lambda: project_maa(StageName.RUN_MAA, maa_result()),
        lambda: project_aalc(StageName.RUN_AALC, aalc_result()),
        lambda: project_mumu(StageName.WAIT_MUMU_ADB_READY, mumu_result(MumuRuntimeStatus.NOT_READY)),
    ],
)
@pytest.mark.parametrize(
    "secret",
    [
        "123456",
        "654321",
        "777777",
        "E:\\private",
        "stdout secret",
        "stderr secret",
        "TOKEN_VALUE",
        "secret keyword",
    ],
)
def test_projected_result_does_not_expose_raw_runtime_values(projection, secret: str) -> None:
    text = json.dumps(projection().to_json_encodable(), ensure_ascii=False)
    assert secret not in text


def test_public_cli_commands_include_controlled_run() -> None:
    names = {command.name or command.callback.__name__ for command in app.registered_commands if not command.hidden}
    assert names == {"version", "validate", "plan", "run", "start"}


def test_core_files_have_no_concrete_runtime_imports() -> None:
    names = ("contracts.py", "plan.py", "runner.py", "coordinator.py")
    source = "\n".join((CORE / name).read_text(encoding="utf-8") for name in names)
    for symbol in ("StarRailAdapter", "MAAAdapter", "AALCAdapter", "MumuAdapter", "ProcessSupervisor", "AdbClient"):
        assert symbol not in source


def test_production_package_has_no_process_launch_or_scan_primitives() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in PRODUCTION.glob("*.py"))
    for symbol in ("subprocess", "os.system", "shell=True", "taskkill", "psutil", "Win32_Process"):
        assert symbol not in source


def test_concrete_adapters_appear_only_in_runtime_bindings() -> None:
    for path in PRODUCTION.glob("*.py"):
        if path.name == "runtime_bindings.py":
            continue
        source = path.read_text(encoding="utf-8")
        for symbol in ("StarRailAdapter", "MAAAdapter", "AALCAdapter", "MumuAdapter"):
            assert symbol not in source
