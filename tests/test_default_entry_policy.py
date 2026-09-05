from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from autogame_orchestrator.config_loader import load_config
from autogame_orchestrator.config_model import MumuLifecycleMode
from autogame_orchestrator.default_entry import (
    CONFIG_TOKEN,
    REPORT_TOKEN,
    DefaultEntryDependencies,
    DefaultEntryErrorCode,
    execute_default_entry,
    resolve_default_entry_paths,
    validate_start_deadline,
)
from autogame_orchestrator.run_application import RUN_CONFIRMATION, RunCommandResult
from autogame_orchestrator.workflow.plan import build_execution_plan
from tests.run_application.helpers import write_run_config


class FakeIO:
    def __init__(self, inputs: list[str] | None = None, *, stdin_tty: bool = True, stdout_tty: bool = True) -> None:
        self.inputs = list(inputs or [])
        self.stdin_tty = stdin_tty
        self.stdout_tty = stdout_tty
        self.messages: list[str] = []
        self.prompts: list[str] = []

    def stdin_isatty(self) -> bool:
        return self.stdin_tty

    def stdout_isatty(self) -> bool:
        return self.stdout_tty

    def write(self, message: str) -> None:
        self.messages.append(message)

    def read(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.inputs.pop(0)


def _canonical_fixture(tmp_path: Path) -> tuple[Mapping[str, str], object]:
    local = tmp_path / "LocalAppData"
    environment = {"LOCALAPPDATA": str(local)}
    paths = resolve_default_entry_paths(environment)
    assert paths is not None
    generated = write_run_config(tmp_path / "fixture")
    text = generated.read_text(encoding="utf-8")
    text = text.replace(
        f'log_dir = "{(tmp_path / "fixture" / "logs").as_posix()}"',
        f'log_dir = "{paths.log_directory.as_posix()}"',
    )
    text = text.replace(
        f'report_dir = "{(tmp_path / "fixture" / "reports").as_posix()}"',
        f'report_dir = "{paths.report_directory.as_posix()}"',
    )
    text = text.replace(
        'log_path_template = "logs/{date}.log"',
        f'log_path_template = "{(tmp_path / "fixture" / "work" / "{date}.log").as_posix()}"',
    )
    paths.config_directory.mkdir(parents=True)
    paths.config_path.write_text(text, encoding="utf-8")
    return environment, paths


def _canonical_managed_fixture(tmp_path: Path) -> tuple[Mapping[str, str], object]:
    """与 `_canonical_fixture` 相同，但 MuMu 为 managed 且配齐启停命令。"""
    local = tmp_path / "LocalAppData"
    environment = {"LOCALAPPDATA": str(local)}
    paths = resolve_default_entry_paths(environment)
    assert paths is not None
    generated = write_run_config(tmp_path / "fixture", lifecycle_mode="managed")
    text = generated.read_text(encoding="utf-8")
    text = text.replace(
        f'log_dir = "{(tmp_path / "fixture" / "logs").as_posix()}"',
        f'log_dir = "{paths.log_directory.as_posix()}"',
    )
    text = text.replace(
        f'report_dir = "{(tmp_path / "fixture" / "reports").as_posix()}"',
        f'report_dir = "{paths.report_directory.as_posix()}"',
    )
    text = text.replace(
        'log_path_template = "logs/{date}.log"',
        f'log_path_template = "{(tmp_path / "fixture" / "work" / "{date}.log").as_posix()}"',
    )
    paths.config_directory.mkdir(parents=True)
    paths.config_path.write_text(text, encoding="utf-8")
    return environment, paths


def _dependencies(environment, io: FakeIO, run_executor) -> DefaultEntryDependencies:
    return DefaultEntryDependencies(
        environment=environment,
        io=io,
        config_loader=lambda path: load_config(path, check_paths=False),
        plan_builder=build_execution_plan,
        run_executor=run_executor,
    )


@pytest.mark.parametrize("value", [True, False, 0, -1, math.nan, math.inf, -math.inf, 86401])
def test_deadline_rejects_unsafe_values(value: object) -> None:
    assert validate_start_deadline(value) is False


def test_deadline_accepts_finite_numbers() -> None:
    assert validate_start_deadline(1)
    assert validate_start_deadline(21600.0)
    assert validate_start_deadline(86400)


@pytest.mark.parametrize(("stdin_tty", "stdout_tty"), [(False, True), (True, False)])
def test_noninteractive_fails_before_path_resolution(tmp_path: Path, stdin_tty: bool, stdout_tty: bool) -> None:
    io = FakeIO(stdin_tty=stdin_tty, stdout_tty=stdout_tty)
    local = tmp_path / "must-not-exist"
    result = execute_default_entry(
        dependencies=_dependencies(
            {"LOCALAPPDATA": str(local)},
            io,
            lambda request: pytest.fail("workflow must not run"),
        )
    )
    assert result.error_code == DefaultEntryErrorCode.INTERACTIVE_CONSOLE_REQUIRED
    assert not local.exists()
    assert io.prompts == []


@pytest.mark.parametrize("environment", [{}, {"LOCALAPPDATA": ""}, {"LOCALAPPDATA": "relative"}])
def test_localappdata_fail_closed(environment: Mapping[str, str]) -> None:
    io = FakeIO([""])
    result = execute_default_entry(
        dependencies=_dependencies(environment, io, lambda request: pytest.fail("workflow must not run"))
    )
    assert result.error_code == DefaultEntryErrorCode.LOCALAPPDATA_UNAVAILABLE


def test_missing_config_is_tokenized_and_creates_no_runtime_dirs(tmp_path: Path) -> None:
    environment = {"LOCALAPPDATA": str(tmp_path / "LocalAppData")}
    paths = resolve_default_entry_paths(environment)
    assert paths is not None
    io = FakeIO([""])
    result = execute_default_entry(
        dependencies=_dependencies(environment, io, lambda request: pytest.fail("workflow must not run"))
    )
    assert result.error_code == DefaultEntryErrorCode.CONFIG_NOT_FOUND
    assert CONFIG_TOKEN in "\n".join(io.messages)
    assert str(tmp_path) not in "\n".join(io.messages)
    assert not paths.runtime_directory.exists()
    assert not paths.log_directory.exists()
    assert not paths.report_directory.exists()


def test_default_entry_path_policy_is_field_only_and_does_not_change_load_config(tmp_path: Path) -> None:
    environment, paths = _canonical_fixture(tmp_path)
    config, errors = load_config(paths.config_path, check_paths=False)
    assert config is not None and errors == []
    assert (
        config.check_default_entry_paths(
            canonical_log_directory=paths.log_directory,
            canonical_report_directory=paths.report_directory,
        )
        == ()
    )
    relative = replace(config, starrail=replace(config.starrail, executable="relative.exe"))
    issues = relative.check_default_entry_paths(
        canonical_log_directory=paths.log_directory,
        canonical_report_directory=paths.report_directory,
    )
    assert [issue.field for issue in issues] == ["starrail.executable"]
    public_config, public_errors = load_config(paths.config_path, check_paths=False)
    assert public_config is not None and public_errors == []
    assert environment["LOCALAPPDATA"]


def test_external_mumu_empty_executable_and_disabled_empty_sync_are_allowed(tmp_path: Path) -> None:
    _, paths = _canonical_fixture(tmp_path)
    config, errors = load_config(paths.config_path, check_paths=False)
    assert config is not None and errors == []
    config = replace(
        config,
        maa_sync=replace(
            config.maa_sync,
            gui_settings_source="",
            gui_tasks_source="",
            cli_profile_destination="",
            cli_tasks_destination="",
        ),
    )
    assert (
        config.check_default_entry_paths(
            canonical_log_directory=paths.log_directory,
            canonical_report_directory=paths.report_directory,
        )
        == ()
    )


def test_managed_mumu_requires_absolute_executable(tmp_path: Path) -> None:
    _, paths = _canonical_fixture(tmp_path)
    config, errors = load_config(paths.config_path, check_paths=False)
    assert config is not None and errors == []
    config = replace(config, mumu=replace(config.mumu, lifecycle_mode=MumuLifecycleMode.MANAGED))
    issues = config.check_default_entry_paths(
        canonical_log_directory=paths.log_directory,
        canonical_report_directory=paths.report_directory,
    )
    assert "mumu.executable" in {issue.field for issue in issues}


def test_enabled_sync_requires_all_absolute_paths(tmp_path: Path) -> None:
    _, paths = _canonical_fixture(tmp_path)
    config, errors = load_config(paths.config_path, check_paths=False)
    assert config is not None and errors == []
    config = replace(
        config,
        maa_sync=replace(config.maa_sync, enabled=True, gui_settings_source="relative.json"),
    )
    issues = config.check_default_entry_paths(
        canonical_log_directory=paths.log_directory,
        canonical_report_directory=paths.report_directory,
    )
    assert "maa_sync.gui_settings_source" in {issue.field for issue in issues}


@pytest.mark.parametrize(
    ("field", "mutator"),
    [
        ("orchestrator.log_dir", lambda c: replace(c, orchestrator=replace(c.orchestrator, log_dir="logs"))),
        ("orchestrator.report_dir", lambda c: replace(c, orchestrator=replace(c.orchestrator, report_dir="reports"))),
        ("mumu.adb_executable", lambda c: replace(c, mumu=replace(c.mumu, adb_executable="adb.exe"))),
        ("starrail.working_directory", lambda c: replace(c, starrail=replace(c.starrail, working_directory="work"))),
        (
            "starrail.log_path_template",
            lambda c: replace(c, starrail=replace(c.starrail, log_path_template="logs/{date}.log")),
        ),
        ("maa.executable", lambda c: replace(c, maa=replace(c.maa, executable="maa.exe"))),
    ],
)
def test_default_entry_rejects_relative_paths(tmp_path: Path, field: str, mutator) -> None:
    _, paths = _canonical_fixture(tmp_path)
    config, errors = load_config(paths.config_path, check_paths=False)
    assert config is not None and errors == []
    issues = mutator(config).check_default_entry_paths(
        canonical_log_directory=paths.log_directory,
        canonical_report_directory=paths.report_directory,
    )
    assert field in {issue.field for issue in issues}


def test_wrong_confirmation_never_executes_and_leaves_no_probe(tmp_path: Path) -> None:
    environment, paths = _canonical_fixture(tmp_path)
    io = FakeIO(["wrong", ""])
    result = execute_default_entry(
        dependencies=_dependencies(environment, io, lambda request: pytest.fail("workflow must not run"))
    )
    assert result.error_code == DefaultEntryErrorCode.CONFIRMATION_REJECTED
    assert len([line for line in io.messages if line[:1].isdigit()]) == 11
    assert list(paths.log_directory.glob(".orchestrator-write-probe-*")) == []
    assert list(paths.report_directory.glob(".orchestrator-write-probe-*")) == []
    assert list(paths.log_directory.iterdir()) == []
    assert list(paths.report_directory.iterdir()) == []
    assert io.prompts[-1] == "Press Enter to close."


def test_success_calls_formal_run_once_with_canonical_request_and_runtime_cwd(tmp_path: Path) -> None:
    environment, paths = _canonical_fixture(tmp_path)
    io = FakeIO([RUN_CONFIRMATION, ""])
    calls = []
    original = Path.cwd()

    def fake_run(request):
        calls.append((request, Path.cwd()))
        return RunCommandResult(0, "success", "OK", "synthetic-test-run")

    result = execute_default_entry(dependencies=_dependencies(environment, io, fake_run))
    assert result == result.__class__(0, "success", "OK")
    assert len(calls) == 1
    request, call_cwd = calls[0]
    assert request.config_path == paths.config_path
    assert request.config_path.is_absolute()
    assert request.deadline_seconds == 21600.0
    assert request.confirmation == RUN_CONFIRMATION
    assert request.elevation_child is False
    assert call_cwd == paths.runtime_directory
    assert Path.cwd() == original
    assert any(REPORT_TOKEN in message for message in io.messages)


def test_runtime_cwd_is_restored_when_executor_raises(tmp_path: Path) -> None:
    environment, _ = _canonical_fixture(tmp_path)
    io = FakeIO([RUN_CONFIRMATION, ""])
    original = Path.cwd()

    def fail(_request):
        raise RuntimeError("sensitive")

    result = execute_default_entry(dependencies=_dependencies(environment, io, fail))
    assert result.error_code == DefaultEntryErrorCode.INTERNAL_ERROR
    assert Path.cwd() == original
    assert "sensitive" not in "\n".join(io.messages)


def test_invalid_deadline_precedes_filesystem_and_config(tmp_path: Path) -> None:
    local = tmp_path / "must-not-exist"
    io = FakeIO([""])
    result = execute_default_entry(
        math.nan,
        dependencies=_dependencies(
            {"LOCALAPPDATA": str(local)},
            io,
            lambda request: pytest.fail("workflow must not run"),
        ),
    )
    assert result.error_code == DefaultEntryErrorCode.DEADLINE_INVALID
    assert not local.exists()


def test_managed_plan_is_accepted_and_stage_count_is_not_hardcoded(tmp_path: Path) -> None:
    """`start` 命令须接受 managed 的 16 阶段计划，并按实际阶段数输出。

    回归保护：入口曾额外硬校验 `plan.stages != EXTERNAL_RUN_STAGES`，使 managed
    配置一律以 PLAN_INVALID 拒绝；警告文案也写死为「11 external stages」。
    """
    environment, paths = _canonical_managed_fixture(tmp_path)
    io = FakeIO([RUN_CONFIRMATION, ""])
    calls = []

    def fake_run(request):
        calls.append(request)
        return RunCommandResult(0, "success", "OK", "synthetic-managed-run")

    result = execute_default_entry(dependencies=_dependencies(environment, io, fake_run))

    assert result.error_code == "OK"
    assert len(calls) == 1
    assert len([line for line in io.messages if line[:1].isdigit()]) == 16
    assert any("16 stages" in message for message in io.messages)
    assert not any("11 external stages" in message for message in io.messages)


def test_managed_plan_without_arguments_is_rejected_before_execution(tmp_path: Path) -> None:
    """managed 未配齐时入口必须在执行前拒绝。

    本修固的 managed 配置 executable 为空，会先被默认入口的路径策略检查拦下
    （managed 要求给出绝对路径），早于 run v1 闸门；两者均属预期的安全拦截点。
    关键断言是“不得执行工作流”。
    """
    local = tmp_path / "LocalAppData"
    environment = {"LOCALAPPDATA": str(local)}
    paths = resolve_default_entry_paths(environment)
    assert paths is not None
    generated = write_run_config(tmp_path / "fixture", lifecycle_mode="managed", mumu_arguments=False)
    text = generated.read_text(encoding="utf-8")
    text = text.replace(
        f'log_dir = "{(tmp_path / "fixture" / "logs").as_posix()}"',
        f'log_dir = "{paths.log_directory.as_posix()}"',
    )
    text = text.replace(
        f'report_dir = "{(tmp_path / "fixture" / "reports").as_posix()}"',
        f'report_dir = "{paths.report_directory.as_posix()}"',
    )
    paths.config_directory.mkdir(parents=True)
    paths.config_path.write_text(text, encoding="utf-8")
    io = FakeIO([""])
    result = execute_default_entry(
        dependencies=_dependencies(environment, io, lambda request: pytest.fail("workflow must not run"))
    )
    assert result.error_code in {
        DefaultEntryErrorCode.PATH_POLICY_INVALID,
        DefaultEntryErrorCode.RUN_V1_GATE_FAILED,
    }
    assert result.exit_code != 0
