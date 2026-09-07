"""Source-entry checks only read configuration and never construct a workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from autogame_orchestrator import local_preflight
from autogame_orchestrator.local_preflight import LocalPreflightError, inspect_local_launch
from autogame_orchestrator.process import ProcessSupervisor
from autogame_orchestrator.run_application import RUN_CONFIRMATION
from tests.run_application.helpers import write_run_config

SOURCE_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def local_config(tmp_path: Path) -> tuple[Path, Path]:
    fixture = tmp_path / "fixture"
    data = tmp_path / "local data [test]"
    config = write_run_config(fixture, lifecycle_mode="managed")
    content = config.read_text(encoding="utf-8")
    content = content.replace((fixture / "logs").as_posix(), (data / "logs").as_posix())
    content = content.replace((fixture / "reports").as_posix(), (data / "run-results").as_posix())
    content = content.replace('"logs/{date}.log"', f'"{fixture.as_posix()}/work/{{date}}.log"')
    config.write_text(content, encoding="utf-8")
    return config, data


def test_preflight_checks_real_paths_without_starting_or_writing(local_config, monkeypatch, tmp_path: Path) -> None:
    config, data = local_config
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "unused-c-drive"))
    monkeypatch.setattr(ProcessSupervisor, "launch", lambda *args, **kwargs: pytest.fail("must not launch"))
    metadata = inspect_local_launch(config, SOURCE_ROOT, data)
    assert metadata["python"] == str(SOURCE_ROOT / ".venv" / "Scripts" / "python.exe")
    assert metadata["config_path"] == str(config)
    assert metadata["log_directory"] == str(data / "logs")
    assert metadata["report_directory"] == str(data / "run-results")
    assert metadata["runtime_directory"] == str(data / "runtime")
    assert metadata["confirmation"] == RUN_CONFIRMATION
    assert len(metadata["stages"]) == 16
    assert not data.exists()
    assert not (tmp_path / "unused-c-drive").exists()
    assert Path.cwd() == tmp_path


@pytest.mark.parametrize("which", ["config", "source", "data"])
def test_relative_paths_are_rejected(local_config, which: str) -> None:
    config, data = local_config
    paths = {"config": config, "source": SOURCE_ROOT, "data": data}
    paths[which] = Path("relative")
    with pytest.raises(LocalPreflightError, match="LOCAL_ABSOLUTE_PATHS_REQUIRED"):
        inspect_local_launch(paths["config"], paths["source"], paths["data"])
    assert not data.exists()


def test_other_checkout_is_rejected(local_config, tmp_path: Path) -> None:
    config, data = local_config
    with pytest.raises(LocalPreflightError, match="LOCAL_SOURCE_MISMATCH"):
        inspect_local_launch(config, tmp_path, data)


def test_global_python_is_rejected(local_config, monkeypatch, tmp_path: Path) -> None:
    config, data = local_config
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    with pytest.raises(LocalPreflightError, match="LOCAL_VENV_REQUIRED"):
        inspect_local_launch(config, SOURCE_ROOT, data)


def test_frozen_entry_is_rejected(local_config, monkeypatch) -> None:
    config, data = local_config
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(LocalPreflightError, match="LOCAL_SOURCE_MISMATCH"):
        inspect_local_launch(config, SOURCE_ROOT, data)


@pytest.mark.parametrize("field", ["logs", "run-results"])
def test_old_log_or_report_destination_is_rejected(local_config, field: str) -> None:
    config, data = local_config
    config.write_text(
        config.read_text(encoding="utf-8").replace((data / field).as_posix(), (data.parent / "old" / field).as_posix()),
        encoding="utf-8",
    )
    with pytest.raises(LocalPreflightError, match="LOCAL_PATH_POLICY_INVALID: orchestrator"):
        inspect_local_launch(config, SOURCE_ROOT, data)
    assert not data.exists()


def test_missing_business_executable_is_rejected(local_config) -> None:
    config, data = local_config
    (config.parent / "maa-placeholder.exe").unlink()
    with pytest.raises(LocalPreflightError, match="LOCAL_CONFIG_INVALID: CONFIG_PATH_NOT_FOUND"):
        inspect_local_launch(config, SOURCE_ROOT, data)


def test_file_in_place_of_runtime_directory_is_rejected(local_config) -> None:
    config, data = local_config
    data.mkdir()
    (data / "runtime").write_text("keep", encoding="ascii")
    with pytest.raises(LocalPreflightError, match="LOCAL_DATA_DIRECTORY_INVALID"):
        inspect_local_launch(config, SOURCE_ROOT, data)
    assert (data / "runtime").read_text() == "keep"


def test_preflight_cli_returns_structured_metadata(local_config, tmp_path: Path) -> None:
    config, data = local_config
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "autogame_orchestrator.local_preflight",
            "--config",
            str(config),
            "--source-root",
            str(SOURCE_ROOT),
            "--data-directory",
            str(data),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["source_root"] == str(SOURCE_ROOT)
    assert not data.exists()


def test_preflight_cli_error_is_bounded(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "preflight",
            "--config",
            str(tmp_path / "missing"),
            "--source-root",
            str(SOURCE_ROOT),
            "--data-directory",
            str(tmp_path),
        ],
    )
    assert local_preflight.main() == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "LOCAL_PREFLIGHT_FAILED\n"


def _run_script(config: Path, data: Path, *options: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SOURCE_ROOT / "scripts" / "run-local.ps1"),
            "-Config",
            str(config),
            "-DataDirectory",
            str(data),
            *options,
        ],
        cwd=config.parent,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize("extra", [(), ("-ConfirmBeforeRun",)])
def test_script_check_only_is_read_only_and_works_from_another_cwd(local_config, extra: tuple[str, ...]) -> None:
    config, data = local_config
    result = _run_script(config, data, "-CheckOnly", *extra)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "source entry" in result.stdout
    assert str(data / "run-results") in result.stdout
    assert "16. write_run_report" in result.stdout
    assert "Preflight passed" in result.stdout
    assert not data.exists()


def test_script_never_runs_without_an_interactive_console(local_config) -> None:
    config, data = local_config
    result = _run_script(config, data, "-NoPause")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "An interactive console is required" in result.stdout
    assert not data.exists()


def test_script_missing_config_does_not_fall_back_to_installed_config(local_config) -> None:
    config, data = local_config
    result = _run_script(config.with_name("missing.toml"), data, "-CheckOnly")
    assert result.returncode == 2
    assert "No workflow was started" in result.stdout
    assert not data.exists()


@pytest.mark.parametrize("deadline", ["0", "86401"])
def test_script_rejects_out_of_range_deadlines(local_config, deadline: str) -> None:
    config, data = local_config
    result = _run_script(config, data, "-DeadlineSeconds", deadline, "-CheckOnly")
    assert result.returncode != 0
    assert "source entry" not in result.stdout
    assert not data.exists()


@pytest.mark.parametrize(
    ("confirm_before_run", "answer", "accepted"),
    [
        (False, "", True),
        (True, RUN_CONFIRMATION, True),
        (True, RUN_CONFIRMATION + " to continue", False),
        (True, RUN_CONFIRMATION.lower(), False),
        (True, "", False),
    ],
)
def test_script_confirmation_is_opt_in(confirm_before_run: bool, answer: str, accepted: bool) -> None:
    # Execute the actual confirmation branch in isolation, never the launch command.
    command = r"""$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:ORCH_LAUNCHER, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw 'Script parse failed' }
$branch = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Clauses[0].Item1.Extent.Text -eq '$ConfirmBeforeRun'
}, $true)
if ($null -eq $branch) { throw 'Confirmation branch missing' }
$ConfirmBeforeRun = $env:ORCH_CONFIRM -eq '1'
$launch = [pscustomobject]@{ confirmation = $env:ORCH_EXPECTED }
$script:promptCount = 0
function Read-Host([string]$Prompt) {
    $script:promptCount++
    return $env:ORCH_ANSWER
}
$failure = $null
$confirmation = $null
try { . ([scriptblock]::Create($branch.Extent.Text)) } catch { $failure = $_.Exception.Message }
@{ confirmation = $confirmation; prompts = $script:promptCount; error = $failure } | ConvertTo-Json -Compress
"""
    environment = os.environ.copy()
    environment.update(
        ORCH_LAUNCHER=str(SOURCE_ROOT / "scripts" / "run-local.ps1"),
        ORCH_CONFIRM="1" if confirm_before_run else "0",
        ORCH_EXPECTED=RUN_CONFIRMATION,
        ORCH_ANSWER=answer,
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    metadata = json.loads(result.stdout)
    assert metadata["prompts"] == int(confirm_before_run)
    if accepted:
        assert metadata["error"] is None
        assert metadata["confirmation"] == RUN_CONFIRMATION
    else:
        assert metadata["error"] == "Confirmation rejected. No workflow was started."
