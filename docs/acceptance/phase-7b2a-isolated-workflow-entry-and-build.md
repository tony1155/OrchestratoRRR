# Phase 7B2A: isolated workflow entry and onedir rebuild

Baseline: `913f3f10876d1fa9ce1697dc5a3cc2e810d6cc69`.

Phase 7B1 was already complete for packaged `version`, root help,
fixture-only `validate`, and fixture-only `plan`. This phase adds only the
implementation needed for the next isolated packaged smoke; it does not claim
that the packaged isolated command has been executed.

## Hidden entry

The formal Typer app now contains the hidden `_isolated-workflow-smoke`
command. The public root command set remains `version`, `validate`, `plan`, and
`run`; the hidden command and the elevation marker remain absent from public
help.

The hidden command requires an existing absolute empty workspace, a finite
deadline no greater than 120 seconds, and the exact confirmation
`I_UNDERSTAND_THIS_RUNS_ONLY_SYNTHETIC_IN_PROCESS_FAKES`. It generates a
workspace-local synthetic configuration and inert placeholder files. It does
not accept a configuration path, executable path, ADB serial, or network
address from the user.

## Isolated execution contract

The command reuses `execute_run_request` and the existing
`ProductionApplicationDependencies`/`RuntimeFactories` injection seams. All
Runtime implementations are process-local synthetic objects. The default
Runtime factory, concrete business adapters, ProcessSupervisor, TCP/ADB probes,
Windows elevation gateway, and child-process launchers are not used.

The report mode is `workflow_isolated`, while the unchanged default production
mode is `workflow_external`. The synthetic plan has the exact external
11-stage order:

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

Source tests and one source-only hidden smoke passed. The source report was
`workflow_isolated`, successful, `OK`, and contained 11 successful stages. The
workspace contained one report and one JSONL log, with no absolute workspace
path, user identity, confirmation string, or business output in the evidence.

## Build and static audit

The implementation was checked with the isolated tests, the existing CLI and
production regression suites, two complete pytest passes, Ruff, mypy, and
`git diff --check`. The only product rebuild in this phase used the controlled
PyInstaller 6.21.0 onedir console script. It completed successfully once.

Static inspection confirmed:

- `dist/OrchestratoRRR/OrchestratoRRR.exe` exists;
- the internal directory and canonical bundled RunReport schema exist;
- PyInstaller analysis contains `autogame_orchestrator.diagnostics.packaged_isolated_workflow`;
- no required production module was missing from the warnings;
- no project docs, tests, config, logs, reports, fixture, harness, legacy
  PowerShell, or business executable was included;
- the bundled schema remains the only project data resource.

The generated EXE was not executed in Phase 7B2A. There was no packaged
isolated smoke, packaged `run`, real UAC, ADB, MuMu, StarRail, MAA, AALC, or
production workflow execution. Phase 7B2B owns the packaged isolated smoke.

Phase 7D still owns the default entry and final working-directory policy. The
legacy PowerShell entry remains retained. Phase 7 is not complete.
