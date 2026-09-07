# Local Source Entry

Use `scripts/run-local.ps1` for everyday runs on a machine with this checkout.
It invokes the repository's `.venv/Scripts/python.exe` and the existing
`autogame_orchestrator run --config` command. Changes to Python source take
effect on the next launch; an EXE rebuild is not required. Dependency changes
still require updating the virtual environment.

## Setup

From the repository root, install the package in editable mode once:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

An existing working editable environment does not need reinstalling on every
launch. The launcher never installs dependencies or builds a package. It
rejects an interpreter or imported package belonging to another checkout.

Use `config/orchestrator.local.toml` as the single local production config.
All business paths must be absolute. By default the data directory is
`orchestrator-data` beside the repository, not inside it. For this installation:

```toml
[orchestrator]
log_dir = 'E:\Program Files\Games\Autogame\orchestrator-data\logs'
report_dir = 'E:\Program Files\Games\Autogame\orchestrator-data\run-results'
```

The launcher's working directory is `orchestrator-data/runtime`. JSONL logs
and RunReports remain separate from repository test output. BetterGI,
StarRailCopilot and MAA keep their own existing log settings; these are not
redirected by the orchestrator log setting.

## Launch

```powershell
# Read-only configuration, source, schema, path and plan checks. No game/UAC.
.\scripts\run-local.ps1 -CheckOnly

# Interactive execution, followed by a pause so the result stays visible.
.\scripts\run-local.ps1

# Optional alternate absolute locations; TOML destinations must match.
.\scripts\run-local.ps1 -Config 'E:\other\orchestrator.local.toml' `
    -DataDirectory 'E:\other\orchestrator-data' -DeadlineSeconds 14400
```

The launcher displays the Python, source, config, log, report and runtime
paths and the complete plan. A real run requires an interactive console and
the exact confirmation requested on screen. `-NoPause` only suppresses the
final pause; it does not bypass confirmation or permit noninteractive runs.
The default total deadline remains 7200 seconds (maximum 86400). Cancellation,
elevation, process ownership and cleanup remain governed by the existing run
command. Failed interactive source runs now use the same bounded-information
Windows dialog as packaged runs, after the report has been written.

For a desktop shortcut, target Windows PowerShell with arguments:

```text
-NoProfile -ExecutionPolicy Bypass -File "E:\Program Files\Games\Autogame\orchestrator-src\scripts\run-local.ps1"
```

This execution-policy override applies to that process only. The launcher
does not change UAC or system execution-policy settings. An existing shortcut
that runs as administrator may keep that setting; otherwise the run command
requests elevation when required. The shortcut must not target the old EXE
or carry an embedded execution confirmation.

`-CheckOnly` reads but does not create data directories, write logs/reports,
request elevation, start business programs or perform network updates. Real
runs create data directories only after confirmation. The directory write
permissions still need to allow the user running the launcher to create them.

## Compatibility

The installed `start` command still uses its canonical `%LOCALAPPDATA%`
config and data directories. This policy is unchanged; do not use `start`
for the local source workflow. Packaged release/install scripts are retained
but are no longer prerequisites for local use.

Switching the local TOML only redirects future runs. Historical C-drive data
is neither moved nor deleted. Back up the local config and old shortcut
before changing them. The local TOML, desktop shortcut and machine-specific
wrapper outside the repository are not committed to Git. The tracked
launcher and this document are the reproducible entry definition.
