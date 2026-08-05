# Phase 7C PROGRAM_PORT install update and installed-artifact audit

This record covers the separately authorized real install update that promoted
the rebuilt PROGRAM_PORT-fix onedir into the canonical installed location at
baseline `c8ea36103f8015dac194de1a334906df9386efc6`. It is a distinct install
event from the earlier install-update audit; this one replaces the previously
installed EXE `3080F16D772449AD4C455D9A8CFA37FFE238D4C4DEEA77AEC309C2EF2F07B22D`
with the approved new dist below.

## Read-only precheck

Before consuming the single authorized updater invocation, an independent
read-only gate confirmed: HEAD equalled remote at the baseline; the tracked
worktree was clean; the new dist matched every approved value exactly; the new
product-data backup bundle was uniquely located by its manifest SHA-256; the
new backup matched the current five-file product data file-by-file and by
directory state; the old backup bundle still existed unchanged; the installed
EXE was still the old `3080F16D…`; the shortcut was byte-stable; install
transaction residue was zero; and no OrchestratoRRR, StarRail, MAA, AALC,
build, or updater processes were running. No asset was modified during the
precheck.

## Pre-invocation wrapper deviation

The first foreground wrapper attempt failed during construction, before any
child process was created, because Windows PowerShell 5.1 does not expose the
`System.Diagnostics.ProcessStartInfo.ArgumentList` property. Classification:
`PRE_INVOCATION_WRAPPER_ERROR`. This attempt did not invoke the updater,
produced no filesystem change, and is not an updater retry. The wrapper was
corrected to build a properly quoted argument string, and the formal updater
invocation then occurred exactly once.

## Update inputs and result

The source was the repository-relative onedir `dist/OrchestratoRRR`. Its EXE
SHA-256 was
`9EEDF9FC4720BA6209439EA96F39BBE21C2E765A7386403D829707DA091A9C7C`; its
schema SHA-256 was
`1994EB5915DA0079FD270412D48EA4562FA5EB4172F8BA7E8E98B9A17791F2CD`; and its
complete manifest contained 106 files and 28,636,334 bytes with fingerprint
`D00498B3E01938AD55DF01F89BC32EF6F5911B2B0C17825CF6D46D373E805A78`.

The mandatory product-data backup was the verified sibling bundle whose
manifest SHA-256 was
`1CA6ECFEE44B3EC3D180E58A6C7DF3228E8802A9920E52D7EB9F3AB06B847CA8`, with five
files and 20,144 bytes and directory states `config=true`, `runtime=true`,
`logs=true`, and `run-results=true`. This backup matched the current product
data file-by-file.

The committed updater was invoked exactly once through a foreground
`System.Diagnostics.Process` wrapper. The wrapper separated stdout and stderr,
waited for the child to exit with no timeout, and used the child exit code
directly; native stderr was not promoted to an outer terminating error. The
updater returned exit code `0`, a single success JSON object, and empty
stderr. The result reported `true_backup_rollback=false`, 106 installed files,
and the approved source EXE hash. No rollback occurred and no retry was
performed. The update used same-parent staging and transaction-backup renames;
the real transaction backup was removed only after all post-checks passed. No
staging, backup, failed, or unknown transaction residue remained.

## Installed artifact audit

The canonical installed artifact is a regular, non-reparse onedir. Its EXE
SHA-256 is
`9EEDF9FC4720BA6209439EA96F39BBE21C2E765A7386403D829707DA091A9C7C`; its
bundled schema SHA-256 is
`1994EB5915DA0079FD270412D48EA4562FA5EB4172F8BA7E8E98B9A17791F2CD`. The
complete installed manifest matches the source manifest exactly: 106 files,
28,636,334 bytes, and fingerprint
`D00498B3E01938AD55DF01F89BC32EF6F5911B2B0C17825CF6D46D373E805A78`. The new
installed EXE differs from the replaced old EXE `3080F16D…`.

The PROGRAM_PORT launch-argument fix code is present in the installed
artifact: the installed EXE contains the `starrail_port` module marker that
the replaced old EXE did not. Presence in the packaged artifact is confirmed;
the real runtime effect of the fix remains unverified because no packaged EXE
or workflow was executed.

## Preservation and execution boundaries

The source onedir remained unchanged. Current product data remained five files
and 20,144 bytes with the runtime directory present; there were no added,
modified, or deleted product-data files across the update.

Two backup bundles exist, and each remained individually unchanged before and
after the update. The old bundle (manifest SHA-256 `7C7D4BEA…`, three files,
11,238 bytes, runtime state false) and the new bundle (manifest SHA-256
`1CA6ECFE…`, five files, 20,144 bytes, runtime state true) are distinct
bundles; their unchanged status is asserted per bundle and does not imply the
two bundles are equal to each other.

The Start Menu shortcut remained byte-for-byte unchanged while still targeting
the canonical installed EXE with argument `start`, the canonical runtime
working directory, and description `OrchestratoRRR`. All install transaction
residue and unknown-entry counts were zero.

Neither source nor installed EXE was executed. The updater ran exactly once
and was not re-invoked. No build, PyInstaller, additional backup, first-install
script, legacy PowerShell orchestrator, UAC, ADB, TCP probe, business program,
or real workflow was executed. The legacy PowerShell entry remains retained.

## Phase status

`phase_7c_program_port_reinstall_completed=true` and
`phase_7c_program_port_installed_artifact_audit_completed=true`. The real
workflow retry, Phase 7C, Phase 7E, and Phase 7 remain incomplete;
`phase_7c_completed=false`. The next gate is the independent real packaged
workflow retry authorization (`PHASE_7C_REAL_WORKFLOW_RETRY_AUTHORIZATION`),
which must not begin without separate explicit authorization.
