# MaaFgo upstream inventory — 2026-10-29

Read-only inventory performed before Phase 2 integration coding. Nothing
upstream was modified; sources were fetched into a throw-away directory outside
the repository history.

## Revisions

| Component | Current main / release | ORR pinned revision |
| --- | --- | --- |
| xlxyvergil/MaaFgo | `194bb78394d5ce48d1f357649cecab4107eb6ebe` (merge PR #295) | `d7f3a474f50b9a0631ee9acd6df67998c1933f2b` |
| MaaXYZ/MaaPiCli (now a standalone repo) | `65c75ab8fb4b2a526008ec3ff5dbb2600be6fa5c` | MaaPiCli ships inside the MaaFramework v5.13.0 SDK (`2bcfa85c66a2eac6ca3e5937f175495275ee0643`) |
| MaaXYZ/MaaFramework | `0fc6025c2fc224a171b57d89505e8d47acd2a8b1` | tag `v5.13.0` = `2bcfa85c66a2eac6ca3e5937f175495275ee0643` |

## Findings against the pinned baseline

1. **BBC stop listener is still unconditionally registered on Windows.**
   Current `agent/main.py` gained an `IS_ANDROID` guard
   (`sys.platform == "android"` or `MAAFGO_PLATFORM == "android"`) that skips
   the BBC imports only for the MaaFwApp Android runtime. On Windows the
   `import bbc_action / bbc_start / bbc_stop / bbc_stop_listener` block still
   executes. `agent/custom/bbc_stop_listener.py` is byte-identical to the
   pinned revision: the `MaaTaskerPostStop` sink globally enumerates and kills
   processes matching the four hardcoded BBC basenames. There is **no**
   upstream opt-out, native-only mode, per-run BBC ownership flag, or
   Agent registration feature gate. → Plan B (ORR private transform) was
   selected; see `docs/decisions/ADR-0003-maafgo-bbc-free-private-distribution.md`.
2. **Completion reporting is still absent upstream.** MaaPiCli's Runner
   (v5.13.0 baseline, confirmed again at the pinned tag) ignores the task
   wait status and returns `true` after disconnecting Agents, and the CLI's
   signal handler can `exit(0)`. The ORR reporter contract
   (`MaaFgoRunContract` + schema v1 artifact) remains necessary.
3. **Notification semantics verified at source.** `Tasker::run_task`
   (`source/MaaFramework/Tasker/Tasker.cpp:351,362`, tag `v5.13.0`) emits
   `Tasker.Task.Starting` / `Tasker.Task.Succeeded` / `Tasker.Task.Failed`
   per posted task; `post_stop()` posts an internal `EmptyTask` with entry
   `MaaTaskerPostStop` (`Tasker.cpp:182`). The Python binding
   (`maa/agent/agent_server.py`, `maa/tasker.py::TaskerEventSink`) delivers
   these through `AgentServer.tasker_sink()` with
   `NotificationType.{Starting,Succeeded,Failed}`. The ORR reporter is built
   on this exact API.
4. **PI entry names.** `Configurator::generate_runtime_task` posts each saved
   task by its interface `entry` (default = task name); `Runner.cpp` posts all
   tasks then waits on the last id. This is why the ORR expected-task contract
   binds `(profile task name, interface entry)` pairs.
5. **No pin upgrade performed.** The offline bundle remains
   MaaFramework v5.13.0 + MaaFgo `d7f3a474` + embedded CPython 3.12.10 + the
   locked wheel set. The current MaaFgo main adds Android-runtime tasks
   (`battle_editor`, `main_story`, `expball`, `bbc_to_chaldea`) that are not
   covered by the Phase 2A/2A.1 investigations; upgrading would require a new
   compatibility investigation, re-run of the offline gates, and its own
   commit. Existing pinned revision takes precedence over unverified latest.

## Impact on the Phase 2 design

- Production FGO runs require the ORR-private assembly
  (`scripts/prepare_maafgo_cli_smoke.py` output with
  `orr_transform.transform_id == "orr-bbc-free-native-reporter"`), verified by
  `MaaFgoConfig.check_distribution()` before every run.
- The completion artifact contract documented in
  `docs/maafgo-full-workflow.md` is implemented against the v5.13.0 binding
  API verified above.

REAL DEVICE ACCEPTANCE: PENDING USER
