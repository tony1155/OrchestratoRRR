"""Phase 6A 的静态架构和 CLI 边界测试。"""

from pathlib import Path

from autogame_orchestrator.cli import app

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "src" / "autogame_orchestrator" / "workflow"


def workflow_source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in WORKFLOW.glob("*.py"))


def test_workflow_core_does_not_import_runtime_adapters() -> None:
    source = workflow_source()
    for name in ("StarRailAdapter", "MAAAdapter", "AALCAdapter", "MumuAdapter", "AdbClient"):
        assert name not in source


def test_workflow_core_does_not_import_process_supervisor() -> None:
    assert "ProcessSupervisor" not in workflow_source()


def test_workflow_core_has_no_process_launch_primitives() -> None:
    source = workflow_source()
    for name in ("subprocess", "os.system", "shell=True", "taskkill", "psutil", "Win32_Process"):
        assert name not in source


def test_public_cli_command_set_includes_controlled_run() -> None:
    names = {command.name or command.callback.__name__ for command in app.registered_commands}
    assert names == {"version", "validate", "plan", "run"}


def test_no_other_execution_cli_is_added() -> None:
    names = {command.name or command.callback.__name__ for command in app.registered_commands}
    assert names.isdisjoint({"all", "execute", "workflow", "start"})


def test_plan_module_has_no_external_execution_dependency() -> None:
    source = (WORKFLOW / "plan.py").read_text(encoding="utf-8")
    assert "runtime" not in source
    assert "platform" not in source
