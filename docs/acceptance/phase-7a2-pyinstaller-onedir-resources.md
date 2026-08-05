# Phase 7A2 - PyInstaller onedir and RunReport Resources

## Baseline and scope

This acceptance record is based on commit
5ec6833c19f5f4f8fb167e9b6ff25d92b82d25f9. Phase 7A2 adds a controlled
PyInstaller 6.21.0 onedir console definition and closes deterministic
RunReport schema lookup for source and frozen layouts.

The project version remains 0.1.0 and the canonical schema remains the
single file `schemas/run-report-v1.schema.json`. The schema content and
schema version were not changed.

## Runtime resource contract

`resource_paths.resolve_run_report_schema_path()` is the only resource
lookup boundary used by `reporter.py`.

- Source mode resolves the repository-root `schemas/run-report-v1.schema.json`.
- Frozen mode resolves
  `autogame_orchestrator/_resources/run-report-v1.schema.json` beside the
  bundled package.
- The locator does not use the current working directory, parent-directory
  search, `sys._MEIPASS`, a user configuration directory, or the network.
- Missing or invalid schema data raises the stable
  `RunReportSchemaResourceError`; report writes map that condition to the
  existing `RUN_REPORT_VALIDATION_ERROR` contract.

The PyInstaller spec copies the canonical schema once into the frozen
package resource directory. It does not create a second schema in Git.

## Packaging definition

The controlled first packaging form is PyInstaller onedir with a console
window:

- `packaging/OrchestratoRRR.spec` uses `packaging/entrypoint.py`, which only
  delegates to `autogame_orchestrator.cli:app`.
- `console=True`, `upx=False`, `strip=False`, and `debug=False` are explicit.
- The only project data item is the RunReport schema.
- `docs`, `tests`, `config`, logs, run-results, Git metadata, real
  configuration, and business executables are excluded from project inputs.
- `scripts/build-package.ps1` derives all paths from its own location, uses
  the project virtual-environment Python and `python -m PyInstaller`, and
  verifies only the expected EXE, internal bundle directory, and schema.
- The script never executes the generated EXE, requests UAC, reads real
  configuration, or runs a workflow.

The first three historical build attempts did not produce a runnable onedir:

1. `FAIL_INVALID_SPEC_OPTION` because a spec input was combined with
   `--specpath`.
2. `FAIL_SPECPATH_PROJECT_ROOT` because the spec root calculation went one
   directory too high.
3. `FAIL_ANALYSIS_SPLASH_ATTRIBUTE_MISSING` because `COLLECT` referenced the
   nonexistent `Analysis.splash` attribute. This attempt produced only a
   partial root-level EXE; that EXE was never executed.

Phase 7A2C removes all splash references and uses the standard onedir
`EXE(exclude_binaries=True)` plus `COLLECT(exe, a.binaries, a.datas)` shape.
No splash screen, image, Tk, Pillow, or splash resource is part of this
project. The independent Phase 7A2C build completed successfully as
historical build attempt 4. It produced the onedir executable and internal
directory, and the bundled schema hash matches the canonical schema.

## Validation boundary and remaining work

PyInstaller 6.21.0 is installed only in the project virtual environment.
Automatic tests cover source lookup, simulated frozen lookup, closed failure
on missing resources, reporter regression, and the static spec contract.
The build warnings are reviewed for required production imports; no broad
hidden-import or `collect_all` rule is used without build evidence.

The generated EXE was not executed. The artifact audit found no project docs,
tests, config, logs, reports, real TOML, business executables, or legacy
PowerShell, and the bounded privacy scan passed. Phase 7A2 is complete within
its packaging/resource scope. Phase 7B1 still owns the
packaged `version`, `--help`, fixture-only validate, and fixture-only plan
smoke. Phase 7D still owns the default user entry and final working-directory
policy. The legacy PowerShell entry remains in place and must not be removed.
Phase 7 is not complete.
