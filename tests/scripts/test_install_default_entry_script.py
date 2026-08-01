from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install-default-entry.ps1"


def test_install_script_parses_without_execution() -> None:
    command = (
        "& { param([string]$Path) $tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "$env:PHASE7D1_SCRIPT,[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count -ne 0) { exit 1 } }"
    )
    environment = os.environ.copy()
    environment["PHASE7D1_SCRIPT"] = str(SCRIPT)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        shell=False,
        creationflags=0,
        env=environment,
    )
    assert result.returncode == 0


def test_install_script_has_canonical_fail_closed_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "[string]$SourceOnedir" in text
    assert '"Programs\\OrchestratoRRR"' in text
    assert '"OrchestratoRRR\\config"' not in text
    assert '"runtime"' in text
    assert '"logs"' in text
    assert '"run-results"' in text
    assert '"Microsoft\\Windows\\Start Menu\\Programs\\OrchestratoRRR"' in text
    assert "$shortcut.TargetPath = $installedExe" in text
    assert '$shortcut.Arguments = "start"' in text
    assert "$shortcut.WorkingDirectory = $runtimeDirectory" in text
    assert "DEFAULT_ENTRY_INSTALL_TARGET_NOT_EMPTY" in text
    assert "IsPathRooted($env:LOCALAPPDATA)" in text
    assert "IsPathRooted($env:APPDATA)" in text
    assert "[System.IO.FileAttributes]::ReparsePoint" in text
    assert "orchestrator.toml" not in text


def test_install_script_never_embeds_confirmation_or_executes_product() -> None:
    folded = SCRIPT.read_text(encoding="utf-8").casefold()
    for forbidden in (
        "i_understand_this_runs_real_programs",
        "--confirm-real-execution",
        "--config",
        "--deadline-seconds",
        "--_elevation-child",
        "start-process",
        "invoke-expression",
        "-verb runas",
        "cmd.exe",
    ):
        assert forbidden not in folded
    assert "& $installedexe" not in folded
