"""公开 run 命令的解析、控制台、signal 与日志隐私测试。"""

from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import autogame_orchestrator.cli as cli
from autogame_orchestrator.run_application import RUN_CONFIRMATION, RunCommandResult
from tests.run_application.helpers import write_run_config

runner = CliRunner()


def test_root_help_lists_run() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.stdout


def test_run_help_has_required_options() -> None:
    result = runner.invoke(cli.app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--config" in result.stdout
    assert "--deadline-seconds" in result.stdout
    assert "--confirm-real-execution" in result.stdout


def test_run_help_hides_elevation_marker() -> None:
    result = runner.invoke(cli.app, ["run", "--help"])
    assert "--_elevation-child" not in result.stdout


@pytest.mark.parametrize(
    "forbidden",
    [
        "--stage",
        "--skip-stage",
        "--from-stage",
        "--to-stage",
        "--mode",
        "--force",
        "--unsafe",
        "--ignore-errors",
        "--no-cleanup",
    ],
)
def test_run_help_has_no_plan_override(forbidden: str) -> None:
    assert forbidden not in runner.invoke(cli.app, ["run", "--help"]).stdout


def test_run_missing_confirmation_is_cli_error(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        ["run", "--config", str(tmp_path / "missing.toml"), "--deadline-seconds", "30"],
    )
    assert result.exit_code == 2


def test_wrong_confirmation_is_safe_error(tmp_path: Path) -> None:
    path = tmp_path / "secret-config.toml"
    result = runner.invoke(
        cli.app,
        [
            "run",
            "--config",
            str(path),
            "--deadline-seconds",
            "30",
            "--confirm-real-execution",
            "wrong-secret-value",
        ],
    )
    assert result.exit_code == 2
    assert "real_execution_confirmation_required" in result.stdout
    assert str(path) not in result.stdout
    assert "wrong-secret-value" not in result.stdout


@pytest.mark.parametrize("deadline", ["0", "-1", "nan", "inf", "86401"])
def test_invalid_deadline_is_safe_cli_error(tmp_path: Path, deadline: str) -> None:
    result = runner.invoke(
        cli.app,
        [
            "run",
            "--config",
            str(tmp_path / "missing.toml"),
            "--deadline-seconds",
            deadline,
            "--confirm-real-execution",
            RUN_CONFIRMATION,
        ],
    )
    assert result.exit_code == 2
    assert "invalid_deadline" in result.stdout
    assert str(tmp_path) not in result.stdout


def test_managed_mode_is_safe_cli_error(tmp_path: Path) -> None:
    path = write_run_config(tmp_path, lifecycle_mode="managed")
    result = runner.invoke(
        cli.app,
        [
            "run",
            "--config",
            str(path),
            "--deadline-seconds",
            "30",
            "--confirm-real-execution",
            RUN_CONFIRMATION,
        ],
    )
    assert result.exit_code == 2
    assert "managed_mumu_not_supported" in result.stdout
    assert str(path) not in result.stdout
    assert "127.0.0.1:" + "16384" not in result.stdout


def test_internal_elevation_marker_is_accepted_but_not_echoed(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [
            "run",
            "--config",
            str(tmp_path / "missing.toml"),
            "--deadline-seconds",
            "30",
            "--confirm-real-execution",
            "wrong",
            "--_elevation-child",
        ],
    )
    assert result.exit_code == 2
    assert "_elevation-child" not in result.stdout


def test_signal_handler_is_restored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    installed: list[object] = []
    original = object()
    monkeypatch.setattr(cli.signal, "getsignal", lambda sig: original)
    monkeypatch.setattr(cli.signal, "signal", lambda sig, handler: installed.append(handler))
    runner.invoke(
        cli.app,
        [
            "run",
            "--config",
            str(tmp_path / "missing.toml"),
            "--deadline-seconds",
            "30",
            "--confirm-real-execution",
            "wrong",
        ],
    )
    assert len(installed) == 2
    assert installed[-1] is original


def test_sigint_handler_requests_same_token(monkeypatch: pytest.MonkeyPatch) -> None:
    installed: list[object] = []
    observed: list[bool] = []
    monkeypatch.setattr(cli.signal, "getsignal", lambda sig: signal.SIG_DFL)
    monkeypatch.setattr(cli.signal, "signal", lambda sig, handler: installed.append(handler))

    def fake_execute(request, *, cancel):
        handler = installed[-1]
        handler(signal.SIGINT, None)
        observed.append(cancel.is_cancelled)
        return RunCommandResult(5, "cancelled", "WORKFLOW_CANCELLED", "safe-run-id")

    monkeypatch.setattr(cli, "execute_run_request", fake_execute)
    result = runner.invoke(
        cli.app,
        [
            "run",
            "--config",
            "safe-reference.toml",
            "--deadline-seconds",
            "30",
            "--confirm-real-execution",
            RUN_CONFIRMATION,
        ],
    )
    assert result.exit_code == 5
    assert observed == [True]


def test_success_console_is_fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "execute_run_request",
        lambda request, *, cancel: RunCommandResult(0, "success", "OK", "safe-run-id"),
    )
    result = runner.invoke(
        cli.app,
        [
            "run",
            "--config",
            "safe-reference.toml",
            "--deadline-seconds",
            "30",
            "--confirm-real-execution",
            RUN_CONFIRMATION,
        ],
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == "Workflow completed: status=success error_code=OK"


def test_failure_console_does_not_print_sensitive_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "execute_run_request",
        lambda request, *, cancel: RunCommandResult(3, "failure", "WORKFLOW_STAGE_FAILED", "safe-run-id"),
    )
    result = runner.invoke(
        cli.app,
        [
            "run",
            "--config",
            "sensitive-config.toml",
            "--deadline-seconds",
            "30",
            "--confirm-real-execution",
            RUN_CONFIRMATION,
        ],
    )
    assert result.exit_code == 3
    assert result.stdout.strip() == "Workflow finished: status=failure error_code=WORKFLOW_STAGE_FAILED"
    for secret in ("sensitive-config", "stdout", "stderr", "123456"):
        assert secret not in result.stdout


def test_validate_log_does_not_record_config_path(tmp_path: Path) -> None:
    path = write_run_config(tmp_path)
    result = runner.invoke(cli.app, ["validate", "--config", str(path)])
    assert result.exit_code == 0
    content = "\n".join(item.read_text(encoding="utf-8") for item in (tmp_path / "logs").glob("*.jsonl"))
    assert str(path) not in content
    assert '"config_provided": true' in content


def test_plan_log_does_not_record_config_path(tmp_path: Path) -> None:
    path = write_run_config(tmp_path)
    result = runner.invoke(cli.app, ["plan", "--config", str(path)])
    assert result.exit_code == 0
    content = "\n".join(item.read_text(encoding="utf-8") for item in (tmp_path / "logs").glob("*.jsonl"))
    assert str(path) not in content
    assert '"config_provided": true' in content


@pytest.mark.parametrize("arguments", [["--help"], ["run", "--help"]])
def test_python_module_help_is_safe_subprocess(arguments: list[str]) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "autogame_orchestrator", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "Traceback" not in completed.stdout
    assert "Traceback" not in completed.stderr
