# Phase 7B2B: packaged isolated workflow

Baseline: `b14d29dce2c21dcf446c7520e09a7943334de483`.

This acceptance reused the single onedir rebuild produced by Phase 7B2A. No
PyInstaller command or build script was run. The packaged EXE was started
exactly once, using only the hidden `_isolated-workflow-smoke` command with a
30-second deadline and the isolated synthetic-execution confirmation.

## Isolation boundary

The harness created a unique system-temporary parent containing separate,
initially empty `runner` and `workspace` directories. The packaged process used
`runner` as its working directory and received `workspace` through the hidden
command option. Neither directory was inside the repository, build output, or
dist output, and the workspace was not a symlink or reparse point.

The generated workspace contained exactly:

- `synthetic-config.toml`;
- `synthetic-bin/`;
- `synthetic-work/`;
- `logs/`;
- `run-results/`.

The synthetic configuration used external MuMu lifecycle mode, disabled MAA
sync/update and network update, required one AALC attempt, and required no
administrator permission. Every configured executable was an inert ordinary
placeholder file inside the workspace, with no PE header or script shebang.
The expected workspace-local paths in the synthetic config were not exposed in
stdout, stderr, logs, or the RunReport.

## Packaged result

The single packaged invocation exited with code 0, wrote 110 stdout bytes and
zero stderr bytes, and did not time out. Its stable summary reported:

`status=success error_code=OK mode=workflow_isolated stages=11 forbidden_calls=0`

The unique JSONL log parsed successfully and contained exactly one
`workflow.start` event followed by 11 `workflow.stage.finished` events. The
stages were, in order:

1. `validate_config`
2. `sync_maa_config`
3. `update_maa`
4. `ensure_mumu_running`
5. `wait_mumu_adb_ready`
6. `run_starrail`
7. `stop_starrail`
8. `verify_starrail_stopped`
9. `run_maa`
10. `run_aalc`
11. `write_run_report`

Every event reported synthetic success/OK. The unique RunReport used schema
version 1, mode `workflow_isolated`, status `success`, error code `OK`, and the
same 11 successful stages. Disabled sync/update diagnostics, ready MuMu source
status, and StarRail cleanup postconditions matched the isolated contract. The
report passed independent offline validation using only the schema bundled in
the onedir artifact; the bundled and canonical schema hashes matched.

## Safety and cleanup

The command reported `forbidden_calls=0`. It accepted no real configuration or
business executable input, and no public `run`, UAC, ADB, TCP probe, MuMu,
StarRail, MAA, or AALC program was executed. These synthetic successes are not
claims of real business success or frozen UAC validation.

The EXE hash, bundled-schema hash, and dist file count were unchanged after the
invocation. The temporary runner, workspace, config, logs, reports, and the
Git-ignored harness were removed. The onedir artifact remains preserved.

Phase 7B2 is complete. Phase 7C remains a separately authorized real packaged
external validation scope and was not started. Phase 7D still owns the default
entry and final working-directory policy. The legacy PowerShell entry remains
retained, and Phase 7 is not complete.
