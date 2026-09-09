# Phase 2A — acquisition checkpoint, stopped at BBC ownership gate

This is a blocked investigation checkpoint, NOT a completed distribution or a
passing smoke. No production files or upstream source files were modified.

## Phase 1 checkpoint

Audited all eight actual new-file diffs, including configuration, adapter and
result model against `maafgo-maapicli-windows.md`. No contract discrepancy
requiring a change was found. In particular `confirmed` in the adapter refers
to configuration confirmation, not business completion; result
`completion_confirmed` remains unconditionally false. Existing supervisor and
workflow were not modified. Branch: `feat/maafgo-integration`; baseline
`5ae17d5` remains an ancestor.

After renewed successful verification, committed only the eight requested
files as `7fbb547a7793752df31a63cd52e3e3065c46c877`:
`feat(maafgo): add guarded MaaPiCli runtime skeleton`. No push.

## Acquired inventory (not an installed runtime inventory)

GitHub API re-resolved main to the same Phase 1 source SHAs. Release discovery
was followed by pinned URLs; no floating DLL installation was used.

| Item | Exact identity |
| --- | --- |
| MaaFramework release | v5.13.0 |
| Release commit, resolved via commits/v5.13.0 | 2bcfa85c66a2eac6ca3e5937f175495275ee0643 |
| Framework main, reference only, not binary provenance | 7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7 |
| MaaPiCli binary source | bin/MaaPiCli.exe from the same official v5.13.0 archive |
| MaaFgo source | d7f3a474f50b9a0631ee9acd6df67998c1933f2b |
| Observed MaaFgo release, NOT used | v1.31.4 MXU |
| Target architecture | win-x86_64 per official asset name; PE validation NOT RUN |
| Smoke Python | NOT SELECTED / NOT INSTALLED |
| Smoke maafw binding | NOT SELECTED / NOT INSTALLED |

Acquired archives:

- `https://github.com/MaaXYZ/MaaFramework/releases/download/v5.13.0/MAA-win-x86_64-v5.13.0.zip`
  SHA256 `179b51b6211fc74317c8dc06f10fae4724aca370df7d1bf694cd00d06ff38efe`
- `https://api.github.com/repos/xlxyvergil/MaaFgo/zipball/d7f3a474f50b9a0631ee9acd6df67998c1933f2b`
  SHA256 `d21e0ec90e4aecce87d950c0ac04b72f46cce1bfd55e4a0488d29a86163f247b`
  This is the hash of the actual downloaded snapshot, not a guarantee GitHub
  will forever regenerate identical ZIP bytes for that commit.

Created a UUID-named root under the user-authorized external temporary smoke
parent. Public documentation deliberately omits its absolute machine path.
Local locator: ignored `tmp/phase2a-root.txt`. No existing directory was reused
or deleted. Downloads and extracted source remain for inspection. Archive
entries were checked for absolute POSIX paths and `..` before extraction;
this one-off acquisition is NOT a hardened reusable assembly tool.

Current layout under `<smoke-root>`:

```text
framework.zip
framework/              # original official archive layout
  bin/MaaPiCli.exe
  bin/MaaFramework.dll
  bin/MaaAgentClient.dll
  bin/MaaAgentServer.dll
  bin/MaaToolkit.dll
  bin/...                # other official dependencies retained together
  share/MaaAgentBinary/  # Android helper payload, not the Python Agent server
maafgo.zip
maafgo/<snapshot>/       # original MaaFgo source; no MXU/user profile
  assets/interface.json
  assets/tasks/, assets/options/, assets/resource/
  agent/main.py
  tools/install-MXU.py
evidence/main.cpp        # fetched at Framework release commit above
evidence/Runner.cpp
```

This is source/material acquisition, not a CLI-compatible project root.
No binary was copied from PATH, MXU, a production installation or another
Framework release. No Python environment or synthetic profile was created.

## Distribution analysis and deferred assembly

The official SDK archive contains MaaPiCli and native DLLs together; unlike
MaaFgo MXU, it does not exclude MaaPiCli. This removes the need to steal a CLI
from an unrelated installation, but does not yet prove Python/native parity.

MaaFgo source interface uses `python ../agent/main.py` relative to assets.
`tools/install-MXU.py` copies assets to root and transforms the Windows agent
command to `./python/python.exe`, arguments `-u ./agent/main.py`; its native
layout is `maafw/`, with `maafw/MaaAgentBinary`. A future CLI assembly needs
its own explicit transformation based on pinned source, not a blindly reused
MXU interface or unrecorded manual edit. Assets imports and resources must
remain relative to the root interface. Agent `main()` changes CWD to the
parent of `agent/`, then calls `Toolkit.init_option("./")`: that makes user
options/log paths local to that distribution (`config/maa_option.json`,
`debug/` per Phase 1 source investigation). It is NOT import-only execution.
Exact CLI/native helper search layout and binding native selection still need
release-specific validation; the SDK's share layout alone is not proof.

No deterministic transformer or prepare script was added because the confirmed
ownership stop condition was reached first. On resumption, use explicit
source-to-destination mappings, an absent/empty external target, reject
reparse points/path escapes, validate all recursive imports/resources and PE
architecture, pin Python plus binding/native versions, record relative-path
hash inventory and transformation manifest, and never copy source `config/`
or user profiles. No automatic cleanup is preferable to unsafe cleanup.

A synthetic profile must be generated ONLY after reading the expected ORR
endpoint through its established configuration contract (never duplicate it
as a new setting), using explicit absolute adb.exe and manual device name.
No production profile was read during this checkpoint. Empty tasks must never
be fed to the Phase 1 adapter, which correctly rejects them. No safe task was
certified here: **NO_SAFE_TASK_AVAILABLE for authorization purposes**, not an
exhaustive proof that no possible upstream pipeline can be harmless.

## Gates and stop reason

| Gate | Result | Evidence / limitation |
| --- | --- | --- |
| A filesystem/inventory | BLOCKED | CLI and official companion files acquired; final assembly, imports, PE dependencies and Python import not validated |
| B Agent import-only | NOT RUN | No environment selected; complete transitive import-side-effect audit not performed |
| C official project-load-only | BLOCKED | PROJECT_LOAD_ONLY_NOT_SUPPORTED in inspected release CLI entry |
| D direct mode | NOT RUN | No certified safe task; confirmed BBC external-process kill risk; no endpoint/profile validation |

The release-pinned `source/MaaPiCli/CLI/main.cpp` only scans `-d`. It always
initializes Toolkit and loads the project, then either runs direct mode or
enters the interactor. There is no official parse-and-exit flag in this entry;
unknown flags (including a guessed --help/--validate) are not a safe substitute.
No interactive CLI was launched to approximate load-only mode.

`maafgo-bbc-ownership.md` records the confirmed stop condition:
**BBC_EXTERNAL_PROCESS_KILL_RISK**. Per the user's stop-on-any-condition rule,
work stopped before executable assembly/gates rather than experimenting around
it. No MaaPiCli of any version was executed; no agent/main.py or Agent imports
were executed; no MuMu/FGO/BBC was launched or connected to. Framework DLLs were
not loaded. No ADB probe, MXU automation or process cleanup was performed.

## Completion evidence

Release-pinned Runner.cpp still waits on the last task ID without examining the
returned status, disconnects Agents, and returns true. main.cpp still maps
that boolean to exit 0 and has signal handlers that call exit(0).
**exit 0 != business success** remains mandatory.

The existing MaaFgo stop listener demonstrates an actual extension point:
`@AgentServer.tasker_sink()` / `TaskerEventSink.on_tasker_task` receives task
notifications inside the Agent. This does not mean an unrelated ORR process
can subscribe to a running MaaPiCli's callbacks. The callback forwarding is a
candidate for a future MaaFgo-side reporter, without patching MaaFramework.
No external result subscription or versioned result file was established.
No log analysis was executed; run ID, final-status coverage and clear run
boundaries in debug logs remain UNVERIFIED, not inferred from keywords.

Future reporter proposal, NOT implemented:

```json
{
  "schema_version": 1,
  "run_id": "caller-generated-unpredictable-id",
  "status": "success|failure|cancelled",
  "last_task": "stable-task-identity",
  "completed_at": "UTC timestamp"
}
```

The minimal example needs an expected task plan digest and per-task IDs/final
statuses before it can certify all-task completion. The caller must create a
fresh private run directory and convey identity by an explicitly supported
channel; current MaaPiCli propagation has not been established. Reporter must
observe start plus terminal status of EVERY selected task, reject duplicate,
unknown or missing task identities, and never infer success from Agent shutdown
or last-task completion alone. Publish once using temporary file + flush +
atomic replace within the same run directory; validate schema, bounded size,
run ID and plan digest when consuming. Timestamp alone is not freshness proof.
Failure/cancellation must not be overwritten by later success. A killed Agent
cannot promise to emit cancellation: absent, partial, stale or malformed
artifacts remain COMPLETION_UNCONFIRMED (with supervisor timeout/cancel taking
precedence). A task-reported success still needs agreed MaaFgo business semantics.

## Verification and remaining work

Renewed checks before the Phase 1 commit, using the existing Windows venv and
a fresh TEMP/TMP plus pytest cache:

- focused config/runtime: **94 passed**, 6.72s;
- full suite: **1688 passed, 1 skipped**, 116.69s;
- ruff check .: passed;
- mypy src: passed, 81 files;
- staged diff check: passed; eight files, 1369 insertions.

Phase 2A changes are investigation documentation only; no assembly/validation
code or new tests were added. Required assembly negative tests therefore remain
DEFERRED, not claimed passing. Existing production TOML, installer, default
stage order, MAA/resource merge, BetterGI and MuMu ownership are untouched.
Phase 2A documents are intentionally uncommitted.

Next phase should first resolve BBC ownership with the upstream contract and
approve whether isolated Gate A/B work should resume despite the known business
blocker. Then finish binding/runtime parity, deterministic assembly and its
negative tests, dependency side-effect audit, and a versioned completion reporter
design review. Do not connect the production workflow based on this checkpoint.
