# Phase 7C safe backup and install-update implementation

Baseline: `46d618626b40796ded0923a7acad757e082891d0`

The product-data loss incident has been forensically reviewed. The exact
JSONL and RunReport from the first failed external run were recovered without
changing the canonical configuration or installed artifact. The canonical
runtime directory remains absent and this implementation phase did not create
it.

Packaging maintenance is now split into three independent boundaries. The
existing build script remains the sole build entry and was not run. The new
`backup-product-data.ps1` creates a separately located recovery bundle, and
`update-default-entry.ps1` consumes only an already completed immutable
onedir plus an independently verified backup. Neither script calls the build
or first-install script.

The backup bundle is completed in a unique staging directory and atomically
finalized only after verification. Its version-one manifest records directory
presence plus sorted relative paths, sizes, and SHA-256 values. It contains no
absolute source path, username, configuration content, business argument, or
confirmation value. A separate `manifest.sha256` protects the manifest. A
missing runtime directory is represented as absent and is never created.

The updater requires explicit current/source EXE hashes, source schema hash,
source file count, backup path, and backup-manifest hash. It validates complete
file manifests for source, current install, and staging, and rejects a source
whose EXE hash is unchanged. Canonical product data is a read-only consistency
gate: its directory states and complete file manifest must still equal the
backup manifest before staging, immediately before swap, and after activation.
The updater neither restores nor writes product data.

Installation staging, true rollback backup, and failed-install isolation are
unique GUID siblings of the canonical install directory. Activation uses
directory renames, never per-file overwrite. Post-check failure restores only
the actual transaction backup; reconstructing from dist is not an accepted
rollback. Cleanup is restricted to exact script-owned GUID paths. Existing
transaction residue fails closed and is not guessed at or automatically
removed after an outer interruption.

The focused suite uses only temporary synthetic LOCALAPPDATA/APPDATA trees,
fake onedirs, inert files, and synthetic shortcuts. Its 36 tests cover backup
success and source preservation, unsafe destinations, reparse rejection,
manifest privacy, update success, argument/artifact/backup/product-data/source
and shortcut rejection, stale-code rejection, transaction residue, rollback
before and after activation, rollback failure evidence preservation, public
bool/array parameter binding, source revalidation, and test-hook export
isolation.
PowerShell parser checks, file-scoped Ruff, and file-scoped mypy also pass.

This phase did not build a real artifact, update the real installation, modify
real product data or shortcuts, execute a packaged program, or run a real
workflow. The implementation review and focused revalidation are complete; the
changes must be committed before separately authorized product-data backup,
rebuild, artifact audit, install update, installed-artifact audit, and
real-workflow retry. Phase 7C remains incomplete. The legacy PowerShell entry
remains retained and is not ready for replacement.
