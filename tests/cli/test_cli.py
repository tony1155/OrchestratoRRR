"""CLI integration tests using Typer's CliRunner."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from autogame_orchestrator import __version__
from autogame_orchestrator.cli import app

runner = CliRunner()


def test_version_output() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
    assert "autogame-orchestrator" in result.stdout


def test_validate_valid_config(valid_config: Path) -> None:
    result = runner.invoke(app, ["validate", "--config", str(valid_config)])
    assert result.exit_code == 0
    assert "Validation OK" in result.stdout


def test_validate_invalid_toml(invalid_toml: Path) -> None:
    result = runner.invoke(app, ["validate", "--config", str(invalid_toml)])
    assert result.exit_code == 1
    assert "CONFIG_PARSE_ERROR" in result.stderr


def test_validate_nonexistent_file() -> None:
    result = runner.invoke(app, ["validate", "--config", "Z:\\does_not_exist.toml"])
    assert result.exit_code == 1
    assert "CONFIG_FILE_NOT_FOUND" in result.stderr


def test_validate_with_check_paths(valid_config: Path) -> None:
    result = runner.invoke(app, ["validate", "--config", str(valid_config), "--check-paths"])
    assert result.exit_code == 1
    assert "CONFIG_PATH_NOT_FOUND" in result.stderr


def test_validate_missing_fields(missing_fields_config: Path) -> None:
    result = runner.invoke(app, ["validate", "--config", str(missing_fields_config)])
    assert result.exit_code == 1
    assert "CONFIG_SCHEMA_ERROR" in result.stderr


def test_validate_invalid_values(invalid_values_config: Path) -> None:
    result = runner.invoke(app, ["validate", "--config", str(invalid_values_config)])
    assert result.exit_code == 1
    assert "CONFIG_SCHEMA_ERROR" in result.stderr


def test_plan_valid_config(valid_config: Path) -> None:
    result = runner.invoke(app, ["plan", "--config", str(valid_config)])
    assert result.exit_code == 0
    assert "DRY PLAN" in result.stdout
    assert "run_starrail" in result.stdout
    assert "stop_starrail" in result.stdout
    assert "stop_mumu" in result.stdout
    assert "start_mumu" in result.stdout
    assert "run_maa" in result.stdout
    assert "run_aalc" in result.stdout


def test_plan_correct_order(valid_config: Path) -> None:
    result = runner.invoke(app, ["plan", "--config", str(valid_config)])
    lines = result.stdout.split("\n")
    stage_lines = [line.strip() for line in lines if line.strip() and line.strip()[0].isdigit()]

    idx_run_srp = -1
    idx_stop_srp = -1
    idx_stop_mumu = -1
    idx_start_mumu = -1

    for line in stage_lines:
        if "run_starrail" in line:
            idx_run_srp = stage_lines.index(line)
        if "stop_starrail" in line:
            idx_stop_srp = stage_lines.index(line)
        if "stop_mumu" in line:
            idx_stop_mumu = stage_lines.index(line)
        if "start_mumu" in line:
            idx_start_mumu = stage_lines.index(line)

    assert idx_run_srp >= 0
    assert idx_stop_srp >= 0
    assert idx_stop_mumu >= 0
    assert idx_start_mumu >= 0
    assert idx_stop_srp > idx_run_srp
    assert idx_stop_mumu > idx_stop_srp
    assert idx_start_mumu > idx_stop_mumu


def test_plan_invalid_config(invalid_toml: Path) -> None:
    result = runner.invoke(app, ["plan", "--config", str(invalid_toml)])
    assert result.exit_code == 1
    assert "CONFIG_PARSE_ERROR" in result.stdout or "CONFIG_PARSE_ERROR" in result.stderr


def test_cli_has_no_run_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert "run" not in result.stdout.lower() or result.stdout.lower().count("run") <= 3


def test_cli_has_no_all_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert " all " not in result.stdout
