# Phase 7D1 native default entry

Phase 7D1 implements the policy selected by Phase 7D0:
OrchestratoRRR.lnk launches OrchestratoRRR.exe start. The public start command
accepts only an optional bounded --deadline-seconds value, defaulting to 21600
seconds. It does not accept a configuration path or a real-execution
confirmation option.

The entry requires an interactive stdin and stdout before it resolves any
paths. It discovers exactly
%LOCALAPPDATA%\OrchestratoRRR\config\orchestrator.toml, enforces the
canonical runtime, log, and report directories, and applies a start-only
absolute-path policy to business paths. General load_config, validate, plan,
and run behavior is unchanged.

Preflight is in-process and report-free: config load, start-only path policy,
run-v1 validation, path existence checks, execution-plan construction, and
the exact external 11-stage gate all complete before runtime/log/report
directories are prepared. The entry previews those 11 stages, warns that real
programs and UAC may be involved, and requires the existing exact
RUN_CONFIRMATION value to be typed every time. It never stores that value in
configuration, the shortcut, or an environment variable.

After confirmation, start changes the process working directory to the
canonical runtime directory, calls execute_run_request exactly once with
default production dependencies, and restores the original working directory
even on an exception. Existing source and frozen UAC re-entry therefore capture
the canonical runtime directory without changes to the elevation boundary.
All terminal outcomes pause with Press Enter to close.; non-interactive
rejection does not pause.

scripts/install-default-entry.ps1 defines a fail-closed first installation to
%LOCALAPPDATA%\Programs\OrchestratoRRR and creates a Start Menu shortcut
whose only argument is start and whose working directory is the canonical
runtime directory. It does not create a real configuration, overwrite a
nonempty installation, execute the product, request elevation, or alter the
legacy PowerShell entry.

Source tests use injected RunCommandResult values and do not execute a real
workflow. The installer was parsed and inspected but not executed. No real
shortcut was created, no packaged EXE was run, and no onedir was rebuilt.
Phase 7D1 is complete; Phase 7D2 owns rebuilding and packaged non-business
entry tests. Phase 7C remains separately authorized real packaged execution,
and Phase 7E owns any future legacy-entry replacement decision. The legacy
PowerShell entry remains in place and Phase 7 is not complete.
