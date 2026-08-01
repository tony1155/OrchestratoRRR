from __future__ import annotations

from typer.testing import CliRunner

from autogame_orchestrator import cli
from autogame_orchestrator.default_entry import DefaultEntryResult

runner = CliRunner()


def test_root_help_exposes_start_but_not_internal_markers() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for command in ("version", "validate", "plan", "run", "start"):
        assert command in result.stdout
    assert "_isolated-workflow-smoke" not in result.stdout
    assert "--_elevation-child" not in result.stdout


def test_start_help_only_exposes_deadline_option() -> None:
    result = runner.invoke(cli.app, ["start", "--help"])
    assert result.exit_code == 0
    assert "--deadline-seconds" in result.stdout
    for forbidden in ("--config", "--confirm-real-execution", "--workspace", "--executable", "--adb-serial"):
        assert forbidden not in result.stdout


def test_start_uses_default_and_explicit_deadline(monkeypatch) -> None:
    captured: list[float] = []

    def fake_start(value: float) -> DefaultEntryResult:
        captured.append(value)
        return DefaultEntryResult(0, "success", "OK")

    monkeypatch.setattr(cli, "execute_default_entry", fake_start)
    assert runner.invoke(cli.app, ["start"]).exit_code == 0
    assert runner.invoke(cli.app, ["start", "--deadline-seconds", "3600"]).exit_code == 0
    assert captured == [21600.0, 3600.0]


def test_public_command_set_includes_start() -> None:
    public = {item.name or item.callback.__name__ for item in cli.app.registered_commands if not item.hidden}
    hidden = {item.name or item.callback.__name__ for item in cli.app.registered_commands if item.hidden}
    assert public == {"version", "validate", "plan", "run", "start"}
    assert hidden == {"_isolated-workflow-smoke"}
