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

# Start immediately after preflight; pause at the end to keep the result visible.
.\scripts\run-local.ps1

# Optional typed confirmation before starting.
.\scripts\run-local.ps1 -ConfirmBeforeRun

# Optional alternate absolute locations; TOML destinations must match.
.\scripts\run-local.ps1 -Config 'E:\other\orchestrator.local.toml' `
    -DataDirectory 'E:\other\orchestrator-data' -DeadlineSeconds 14400
```

The launcher displays the Python, source, config, log, report and runtime
paths and the complete plan. A real run requires an interactive console but
starts immediately after preflight by default, including from the desktop
shortcut. The local launcher supplies the existing run command's confirmation
value automatically. Use `-ConfirmBeforeRun` to opt into a typed confirmation
prompt. `-NoPause` only suppresses the final pause; it does not bypass an
explicit `-ConfirmBeforeRun` or permit noninteractive runs.
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
runs create data directories after preflight and any requested confirmation.
The directory write permissions still need to allow the user running the
launcher to create them.

## Compatibility

### Keep the MAA CLI installation separate from the GUI

MAA GUI repair can remove directories that are not part of its distribution,
including an embedded `maa-cli` and `MaaResource`. A missing CLI executable
then stops the local launcher with `LOCAL_CONFIG_INVALID: CONFIG_PATH_NOT_FOUND`.
Do not install orchestrator dependencies inside the GUI installation directory.

Use a dedicated tree such as `orchestrator-data/maa`:

- `cli/v0.7.4/maa.exe`: the pinned CLI executable.
- `lib`: MaaCore and its native dependencies.
- `resource`: the CLI's own base resources.
- `MaaResource`: the CLI's incremental resource repository.
- `config`, `cache`, `state`: separate CLI configuration and runtime data.

Point `maa.executable` and `maa.working_directory` at the CLI above, and set
`MAA_DATA_DIR` to this dedicated tree. Set `MAA_CONFIG_DIR`, `MAA_CACHE_DIR`,
and `MAA_STATE_DIR` to its corresponding subdirectories. Keep the GUI settings
and task sources in the GUI directory, but write synchronized profiles/tasks
into the dedicated CLI config. The resource merge source and destination must
both be inside the dedicated tree; merging into the GUI's resources can also
conflict with its integrity checks.

Back up the local TOML before migrating. Restore a verified CLI release and
a matching core/resource set, initialize the incremental resource repository,
then validate configuration sync, update, resource merge, and
`maa run orchestrator --profile orchestrator --batch --dry-run` using the same
environment as the workflow. Finally run `run-local.ps1 -CheckOnly`.
These checks do not constitute a complete game workflow run.

The installed `start` command still uses its canonical `%LOCALAPPDATA%`
config and data directories. This policy is unchanged; do not use `start`
for the local source workflow. Packaged release/install scripts are retained
but are no longer prerequisites for local use.

Switching the local TOML only redirects future runs. Historical C-drive data
is neither moved nor deleted. Back up the local config and old shortcut
before changing them. The local TOML, desktop shortcut and machine-specific
wrapper outside the repository are not committed to Git. The tracked
launcher and this document are the reproducible entry definition.
