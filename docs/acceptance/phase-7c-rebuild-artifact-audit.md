# Phase 7C rebuild and static artifact audit

The authorized retry used baseline commit `99bb13fe930587eaa8eb033a360aecb5a6cb6d7a`.
The first formal build attempt was complete-looking but unproven because its
outer PowerShell wrapper promoted native stderr to a terminating error before
capturing the child exit code and completion marker. This was the one separate
retry authorized for this phase; the total formal build-attempt count is two,
with no automatic retry in the second attempt.

The retry invoked the committed build script exactly once through
`System.Diagnostics.Process`. Standard output and standard error were captured
through separate asynchronous streams, the child was awaited to completion,
and `Process.ExitCode` was read directly. The retry returned exit code `0` and
standard output contained `OrchestratoRRR onedir build completed.`. Native
stderr was non-empty and was retained as ordinary audit text; it was not used
as a failure signal. The audit files are confined to the repository-relative
`build/audit/phase-7c-rebuild-retry-<timestamp>-<guid>` category and contain
only captured streams and non-sensitive hashes.

The resulting onedir passed static validation. Its EXE SHA-256 is
`3080F16D772449AD4C455D9A8CFA37FFE238D4C4DEEA77AEC309C2EF2F07B22D`; its
bundled RunReport schema SHA-256 is
`1994EB5915DA0079FD270412D48EA4562FA5EB4172F8BA7E8E98B9A17791F2CD`.
The artifact contains 106 files and 28633496 total bytes, with full-manifest
fingerprint `D240028EE8920159890ABE27AFA68A640118D49CA420416A460208E4B0480D6E`.
The EXE differs from both the old installed artifact and the pre-retry
diagnostic candidate. `Analysis-00.toc`, `PYZ-00.toc`, `EXE-00.toc`, and
`COLLECT-00.toc` were produced during the retry. Both StarRail runtime modules
were present in Analysis and PYZ, and the project-owned missing-module warning
count was zero.

The schema is valid JSON and byte-identical to the committed source schema.
The artifact tree contains no canonical config, recovered log or report,
product-data backup, PowerShell maintenance file, project documentation,
tests, or other business data. The privacy and project-resource audits passed.
The packaged EXE was not executed.

The canonical product-data manifest remained unchanged at three files and
11238 bytes. The canonical runtime directory remains absent. The independent
product-data backup bundle, installed 106-file artifact, shortcut, and install
transaction residue state were unchanged. No installer, updater, UAC, ADB,
TCP probe, business program, or real workflow was executed.

`phase_7c_rebuild_retry_completed=true`,
`phase_7c_rebuild_completed=true`,
`phase_7c_dist_artifact_audit_completed=true`, and
`phase_7c_updated_artifact_ready=true`. Reinstall, installed-artifact audit,
real workflow retry, Phase 7C, Phase 7E, and Phase 7 remain incomplete. The
next phase is `PHASE_7C_REBUILD_ARTIFACT_AUDIT_COMMIT`. Install update and the
real workflow retry still require separate explicit authorization. The legacy
PowerShell entry remains retained.
