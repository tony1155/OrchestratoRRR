# Phase 7C real install update and installed-artifact audit

This record covers the separately authorized real install update at baseline
`d710aef333e18c80f68d45959ec865fc74a6c5ff`. The committed updater was invoked
exactly once through a foreground `System.Diagnostics.Process` wrapper. The
wrapper separated stdout and stderr, waited for the child to exit, and used
the child exit code directly. No retry was performed.

## Update inputs and result

The source was the previously audited repository-relative onedir
`dist/OrchestratoRRR`. Its EXE SHA-256 was
`3080F16D772449AD4C455D9A8CFA37FFE238D4C4DEEA77AEC309C2EF2F07B22D`; its
schema SHA-256 was
`1994EB5915DA0079FD270412D48EA4562FA5EB4172F8BA7E8E98B9A17791F2CD`; and
its complete manifest contained 106 files and 28,633,496 bytes with
fingerprint
`D240028EE8920159890ABE27AFA68A640118D49CA420416A460208E4B0480D6E`.

The mandatory product-data backup was the verified `LOCALAPPDATA_SIBLING`
bundle. Its manifest SHA-256 was
`7C7D4BEA0EFA3E177ED175CEFDF54FAE691C54F413C37F3D8F2E72138B19ED98`, with
three files and 11,238 bytes. The canonical product-data states were
`config=true`, `runtime=false`, `logs=true`, and `run-results=true`.

The updater returned exit code `0`, a single success JSON object, and empty
stderr. The result reported `true_backup_rollback=false`, 106 installed
files, and the approved source EXE hash. The non-sensitive wrapper audit is
confined to the repository-relative category
`build/audit/phase-7c-install-update-20260803T034809Z-b462600704d24cf0b7dc3efa5ddb1407`.

The update used same-parent staging and transaction-backup directory renames.
The old install was replaced successfully, and the real transaction backup
was removed only after all post-checks passed. No staging, backup, failed, or
unknown transaction residue remained.

## Installed artifact audit

The canonical installed artifact is a regular, non-reparse onedir. Its EXE
SHA-256 is
`3080F16D772449AD4C455D9A8CFA37FFE238D4C4DEEA77AEC309C2EF2F07B22D`; its
bundled schema SHA-256 is
`1994EB5915DA0079FD270412D48EA4562FA5EB4172F8BA7E8E98B9A17791F2CD`.
The complete installed manifest matches the source manifest exactly: 106
files, 28,633,496 bytes, and fingerprint
`D240028EE8920159890ABE27AFA68A640118D49CA420416A460208E4B0480D6E`.
The new EXE differs from the old installed EXE
`4CBDD3DAE50C631D6459713D9B68D3D6808503DADB83AFF7EFA071BC4C9DA9C`.

The installed privacy and project-resource audits passed. The installed tree
contains the expected bundled RunReport schema and no canonical config,
recovered JSONL or RunReport, backup manifest or bundle, project scripts,
PowerShell maintenance files, documentation, tests, repository configuration,
business data, or machine-specific configuration.

## Preservation and execution boundaries

The source onedir remained unchanged. Canonical product data remained three
files and 11,238 bytes with manifest fingerprint
`FCCF94FFB321E933EBFBEAB520B6ADAD9EBCF8F912ACB08C487CD7E07538D796`; the
configuration, recovered JSONL, and recovered RunReport hashes were
unchanged. The runtime directory remains absent and was not created.

The formal backup bundle remained unchanged, including its manifest and file
hashes. The Start Menu shortcut remained byte-for-byte unchanged while still
targeting the canonical installed EXE with `start`, the canonical runtime
working directory, and description `OrchestratoRRR`.

Neither source nor installed EXE was executed. The first-install script,
build, PyInstaller, another backup, UAC, ADB, TCP, business programs, and the
real workflow were not executed. The legacy PowerShell entry remains
retained. A real workflow retry requires separate explicit authorization.

## Phase status

`phase_7c_reinstall_completed=true` and
`phase_7c_installed_artifact_audit_completed=true`. The real workflow retry,
Phase 7C, Phase 7E, and Phase 7 remain incomplete. The next phase is
`PHASE_7C_INSTALL_UPDATE_AUDIT_COMMIT`; the audit documentation must be
reviewed and committed before a separately authorized workflow retry.
