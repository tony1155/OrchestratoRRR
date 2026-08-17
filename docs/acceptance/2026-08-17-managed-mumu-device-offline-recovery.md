# 2026-08-17 Managed MuMu DEVICE_OFFLINE recovery

## Incident evidence

This change follows the individual ADB command timeout fix recorded in
`2026-08-17-mumu-adb-command-timeout-recovery.md`; that five-second child
deadline remains in force.

The later real run failed before StarRail:

- failed stage: `ensure_mumu_running`
- stage duration: `120000 ms`
- stage/source error: `WORKFLOW_STAGE_TIMEOUT / START_TIMEOUT`
- last safe readiness classification:
  `DEVICE_OFFLINE / select_device`
- controlled connect was not eligible

At the same time, the MuMu UI and Android applications remained usable.
`MuMuManager info` reported `is_android_started=false` while the player
state was `start_finished`, and the host ADB view classified only the exact
configured MuMu transport as offline. This evidence does not establish that
the whole emulator or Android guest was frozen. It establishes a persistent
host-to-guest ADB control-plane failure which the production workflow had no
managed recovery policy for.

## Recovery policy

`MumuAdapter.start()` now treats persistent `DEVICE_OFFLINE` as a
managed-lifecycle recovery case only when all of these conditions remain true:

- the probe step is `select_device`;
- the configured host is the exact local host;
- the configured serial exactly matches that configured local endpoint;
- the offline state persists for a three-second grace period;
- this `start()` call has not already attempted offline recovery.

One transient offline sample therefore does not restart MuMu. A persistent
offline state permits at most one stop/start recovery. Probe, stop confirmation,
manager start, subsequent polling, and cancellation all share the original
single start-operation `Deadline`; recovery never creates or refreshes a
120-second budget.

If readiness is still offline after the restart, polling continues only until
the original deadline and then returns `START_TIMEOUT`. The recovery attempt
sets `changed=true`, including failure and timeout paths, so production
workflow state records that managed lifecycle ownership was exercised.

The existing controlled-connect contract was not widened. In particular,
`DEVICE_OFFLINE` was not added to `_connect_is_allowed()`. ADB connect
continues to require `DEVICE_NOT_FOUND / select_device` and the exact local
endpoint. The implementation does not kill or restart the global ADB server,
disconnect other devices, scan endpoints, or operate on non-target transports.
External lifecycle mode remains report-only and performs zero start, stop, or
restart operations.

## Managed failure cleanup

The production runner now tracks whether managed MuMu ownership was acquired
or changed. After a primary failure or timeout, an owned managed instance gets
one `SHUTDOWN_MUMU` cleanup attempt before `WRITE_RUN_REPORT`.

Cleanup uses a fresh, bounded deadline limited by the configured MuMu stop
timeout. This lets cleanup run even when the primary workflow deadline is
already exhausted, without becoming unbounded. Cleanup receives a fresh
cancellation token so a cancellation that caused the primary path to stop
cannot silently suppress the bounded shutdown attempt.

The primary failure remains authoritative. A cleanup timeout or failure is
recorded only as:

- `failure_cleanup_attempted`
- `failure_cleanup_outcome`
- `failure_cleanup_error_code`

It cannot replace the original failed stage, top-level status, or top-level
error code. A normal successful workflow still executes its existing final
`SHUTDOWN_MUMU` exactly once and does not run duplicate cleanup. External
mode has no cleanup stage and no lifecycle ownership.

## Interactive failure notification

After a failed production request has written its RunReport, the packaged
Windows interactive CLI shows one modal failure dialog before returning the
original nonzero exit code. The dialog contains only:

- original failed stage;
- stable error code;
- MuMu cleanup result;
- notice that detailed diagnostics are in the RunReport.

It excludes confirmation material, device serials, PIDs, raw ADB output, and
command lines. The dialog is disabled unless the process is a frozen Windows
build with interactive stdin and stdout, so pytest, CI, redirected subprocesses,
and source-tree calls cannot block on a MessageBox. Dialog failure is swallowed
without changing the original result.

## Regression coverage

The focused suite covers:

- transient offline recovery without restart;
- persistent offline, one managed restart, then ready;
- persistent offline after restart, exactly one restart, bounded timeout;
- original operation deadline identity across probe/stop/start;
- external offline with zero recovery and lifecycle operations;
- unchanged `DEVICE_NOT_FOUND` controlled-connect behavior;
- retained five-second ADB child deadline;
- partial-start and upstream failures performing one cleanup;
- cleanup failure remaining secondary;
- normal success avoiding duplicate cleanup;
- report-before-dialog ordering and original exit-code preservation;
- no dialog in noninteractive or non-packaged environments;
- safe allowlisted offline recovery diagnostics.

Validation:

```text
focused pytest                  198 passed
full pytest                     1442 passed, 1 skipped
ruff check .                    passed
mypy src                        passed (69 source files)
changed-file format check       passed (17 files)
git diff --check                passed
```

The full format check still identifies only the four pre-existing unrelated
files listed in the earlier ADB timeout record. They were not modified.

## Package

The version-controlled `scripts/build-package.ps1` and PyInstaller onedir spec
rebuilt the artifact used by the Desktop shortcut:

```text
exe_sha256_before=AB63BDE14D3E2C728DF9DC9C9AEC5D0888E987D7AA4E91B0B9255A5C3419C9F0
exe_sha256_after=1AB5DDDB2D15745882BECCEBA811410105E5D25DBAAE698B9B285A09B7C38A82
internal_exists=true
schema_exists=true
```

The Desktop shortcut was not modified and still points to the rebuilt onedir
executable. No real workflow, MuMu, StarRail, MAA, AALC, Limbus, or real ADB
operation was started for validation.
