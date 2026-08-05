# Phase 7C product-data backup

This record covers the separately authorized real product-data backup at
baseline `b73e0bdf04be9ecfb171a521ee4b74d2337c5eec`. It does not authorize a
build, install update, packaged execution, or workflow retry.

## Backup result

- `scripts/backup-product-data.ps1` was invoked exactly once and returned exit
  code 0 with a single success JSON object and no stderr.
- The destination was the `LOCALAPPDATA_SIBLING` backup root with leaf name
  `OrchestratoRRR-Backups`, outside both canonical product data and the
  installed program.
- One formal bundle was finalized through same-directory staging and an
  atomic rename. Its leaf-name fingerprint is `A602DEC34452`.
- The bundle manifest is format version 1 with SHA-256
  `7C7D4BEA0EFA3E177ED175CEFDF54FAE691C54F413C37F3D8F2E72138B19ED98`,
  three files, and 11,238 total bytes.

The manifest records `config=true`, `runtime=false`, `logs=true`, and
`run-results=true`. It contains the canonical configuration and the recovered
first-failure JSONL and RunReport. Their approved hashes and JSON/schema
structure were independently revalidated inside the bundle. The manifest
contains only relative paths, sizes, and SHA-256 values; no absolute paths or
configuration contents.

## Preservation and boundaries

The source product-data manifest contained three files and remained identical
before and after backup, with fingerprint
`FCCF94FFB321E933EBFBEAB520B6ADAD9EBCF8F912ACB08C487CD7E07538D796`.
The canonical configuration, recovered log and report, old installed EXE and
schema, 106-file installed tree, and Start Menu shortcut were unchanged.
The canonical runtime directory remained absent and was not created. The
backup root contains one finalized bundle, no staging residue, and no unknown
entries; the bundle and source files remain preserved for the later updater
gate.

No build, PyInstaller run, install update, updater execution, packaged EXE,
shortcut launch, confirmation, UAC, ADB, TCP probe, business program, or real
workflow was performed. The legacy PowerShell entry remains in parallel.

## Phase status

`phase_7c_product_data_backup_completed=true` and
`phase_7c_product_data_backup_bundle_ready=true`. Phase 7C, Phase 7E, and
Phase 7 remain incomplete. A real rebuild, artifact audit, install update,
installed audit, and workflow retry each require their own authorization; the
next phase is `PHASE_7C_PRODUCT_DATA_BACKUP_COMMIT`.
