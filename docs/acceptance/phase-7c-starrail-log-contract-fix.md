# Phase 7C StarRail dynamic log contract fix

Baseline: `76d618997e309d20fbde867c34f4f46bb4ef9202`

The first correctly confirmed packaged external workflow reached the real run
executor and completed the five stages through `wait_mumu_adb_ready`.
`run_starrail` then failed closed with
`PROCESS_EXIT_BEFORE_SUCCESS`. That result does not establish that the
external StarRail task succeeded.

The failure review identified a log-path/cursor mismatch. The configured
date-rendered file did not exist, while StarRailCopilot created a
same-directory file with an additional time component. The configured success
marker already had support from two historical normal sessions, so no keyword
was changed.

The runtime now derives a bounded filename contract from a single `{date}`
token in the final filename component. It snapshots matching regular,
non-reparse files in the configured parent directory before process launch,
without recursion or mtime-based selection. Pre-existing candidates begin at
their snapshot EOF; newly created or replaced candidates begin at offset zero.
One changed candidate becomes the fixed active cursor. Multiple changed
candidates fail closed as `LOG_READ_FAILED` with the finite diagnostic
`LOG_CANDIDATE_AMBIGUOUS`.

Existing behavior remains intact: exact fixed paths still work, failure
markers precede success markers, matching remains case-sensitive, reads and
rolling text remain bounded, and an exit code of zero without a current-run
success marker remains `PROCESS_EXIT_BEFORE_SUCCESS`. No post-exit drain or
launcher/child ownership change was introduced.

The focused StarRail suite now covers dynamic-file success, stale historical
content, append-after-snapshot behavior, a new dynamic file without a marker,
ambiguous candidates, nonmatching siblings, exact paths, rotation,
read-limit failure, failure priority, and process-tree cleanup. All 39 focused
tests passed; file-scoped Ruff and mypy checks also passed.

This phase changed source, tests, and documentation only. It did not rebuild,
reinstall, modify machine-local configuration, execute a packaged executable,
or rerun the real workflow. Phase 7C remains incomplete. The next boundary is
`PHASE_7C_REBUILD_REINSTALL_FOR_RETRY`, with both an updated artifact and
separate real-workflow retry authorization still required. The legacy
PowerShell entry remains available and is not ready for replacement.
