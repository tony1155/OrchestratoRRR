# MaaFgo / MaaPiCli Windows compatibility investigation

> **状态更新（2026-10-29）**：本文是当时 revision（d7f3a474）的只读调查记录，
> 保留原始结论与证据边界。其中"下一步/阻塞"类陈述已在 MaaFgo Phase 2 落地时
> 处理：上游无安全机制（见 `maafgo-upstream-inventory-2026-10-29.md`），最终
> 采用 ORR 私有 BBC-free 分发 transform（`docs/decisions/ADR-0003`），完成证据
> 契约与生产接入见 `docs/maafgo-full-workflow.md`。历史结论不因此改写。

Date: 2026-09-09. Scope: source inspection, invocation skeleton and synthetic
Windows processes only. No MaaPiCli, MaaFgo, MXU, BBC, MuMu or FGO business run
was performed. No production TOML or MaaFgo-owned configuration was changed.

## Repository baseline

Requested commands were run before edits:

```text
git status
git branch --show-current
git log -5 --oneline
```

`status` and `log` initially encountered Git's different-owner safety check.
They were repeated with a command-local
`-c safe.directory=E:/Program Files/Games/Autogame/orchestrator-src` override;
no global Git configuration was changed. Results:

```text
On branch feat/bettergi-integration
Your branch is up to date with 'origin/feat/bettergi-integration'.
nothing to commit, working tree clean

5ae17d5 fix: include Conda native dependencies during packaging
e7361b9 fix: start local workflow without a confirmation prompt by default
e49f55f feat: add source launcher with separate local run data
9537b45 feat: integrate optional BetterGI one-dragon workflow stage
19a24db docs: record real MaaResource merge validation
```

Created `feat/maafgo-integration` from `5ae17d5`. Creating the ref needed a
sandbox escalation because `.git` was read-only. No reset, deletion, commit,
checkout of old documents, or fetch/rebase of the baseline was performed.
"Up to date" above is Git's local remote-tracking state, not a new network fetch.

## Evidence and version boundary

The investigation uses upstream source, not an installed binary's reported
version. GitHub API resolved these `main` commits during this investigation:

| Component | Source revision |
| --- | --- |
| MaaFramework / MaaPiCli | `7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7` |
| MaaFgo | `d7f3a474f50b9a0631ee9acd6df67998c1933f2b` |

Links below are pinned to those revisions. Sources were fetched read-only;
no upstream repository was edited, built, installed or executed. A future
installed package must be version/hash inventoried independently. This is
not a claim that every historical or future MaaPiCli release has this contract.

## Confirmed from upstream

### 1. Invocation and file locations

The CLI scans for the literal `-d`; this selects direct execution of the saved
configuration. Without it, the CLI is interactive. Do not assume flags from
proposed CLI redesigns are supported. The invocation for this adapter is
exactly `MaaPiCli.exe -d`. `main` derives both user and resource paths from
`library_dir()`, not a configurable CLI profile argument.
[CLI entry point](https://github.com/MaaXYZ/MaaFramework/blob/7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7/source/MaaPiCli/CLI/main.cpp)

Official instructions require the working directory to be the project root,
containing `interface.json` and the CLI executable. The fixed relative user
profile is `config/maa_pi_config.json`. The adapter requires the executable's
directory and working directory to agree; changing CWD cannot redirect a CLI
located elsewhere to another profile.
[CLI README](https://github.com/MaaXYZ/MaaFramework/blob/7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7/source/MaaPiCli/README.md),
[filename constants](https://github.com/MaaXYZ/MaaFramework/blob/7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7/source/include/ProjectInterface/Configurator.h)

MaaFgo source uses `assets/interface.json`, PI interface version 2, project
name `MaaFgo`, and an `Adb` controller. Its task/option definitions are imported
from separate files; the empty top-level task array does not mean the project
has no tasks. Source-tree Agent invocation is `python ../agent/main.py`.
[MaaFgo interface](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/assets/interface.json)

### 2. Windows distribution is not a ready-made CLI distribution

The current workflow builds a Windows x86-64 MXU artifact and downloads the
latest MaaFramework rather than pinning its version. `tools/install-MXU.py`
copies the interface to the installation root, imports/resources alongside
it, and native dependencies into `maafw/`. It explicitly excludes
`*MaaPiCli*`. The Agent command is changed to `./python/python.exe` with
`-u ./agent/main.py`. `tools/install.py` also excludes MaaPiCli in its
non-Android layout. `MaaFgo.exe` in the MXU artifact is the renamed GUI, not
the required CLI.
[build workflow](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/.github/workflows/install.yml),
[MXU packaging](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/tools/install-MXU.py),
[other packaging](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/tools/install.py)

Consequently, a separate, user-approved CLI-compatible installation with
matching DLLs, Python binding, Agent, resources/imports and MaaAgentBinary
must be prepared before smoke. This phase neither assembles that installation
nor edits the upstream interface. Python dependency `maafw` is also unpinned
in the project requirements.
[Python requirements](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/requirements.txt)

### 3. Saved configuration shape and identity

The upstream serialized `Configuration` envelope has required `controller`,
`resource`, `task`; the controller contains a `name`, not the ADB connection.
ADB parameters are in the top-level `adb` object: `name`, `adb_path`, `address`.
Task entries contain a name and optional option list. Options can carry
`value`, `values` or `inputs`; optional global/resource/controller option
lists also exist. They remain opaque to this integration.
[Configuration and AdbConfig types](https://github.com/MaaXYZ/MaaFramework/blob/7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7/source/include/ProjectInterface/Types.h)

Illustrative structural example only, not a ready-to-run FGO profile:

```json
{
  "controller": {"name": "<name declared in interface.controller>"},
  "adb": {
    "name": "127.0.0.1:16384-C:\\Example\\adb.exe",
    "adb_path": "C:\\Example\\adb.exe",
    "address": "127.0.0.1:16384"
  },
  "resource": "<resource name owned by MaaFgo>",
  "task": [{"name": "<task name owned by MaaFgo>", "option": []}]
}
```

The controller type is resolved from the selected interface controller.
The parser supports imported task definitions and may remove incompatible
configuration entries in memory. This integration does not reproduce its
task/option parser. It intentionally accepts a stricter JSON subset:
UTF-8/BOM allowed, at most 1 MiB per inspected file, object root, no duplicate
keys, NaN/Infinity, comments, malformed types, or empty task selection.
[upstream parser](https://github.com/MaaXYZ/MaaFramework/blob/7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7/source/MaaPiCli/Impl/Parser.cpp)

### 4. Agent launch and task completion

The configurator passes the Agent command/arguments from the interface,
sets its CWD to the interface directory and supplies PI environment metadata.
Resource paths are relative to that directory. It takes the ADB identity
from the top-level saved `adb` object.
[runtime generation](https://github.com/MaaXYZ/MaaFramework/blob/7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7/source/MaaPiCli/Impl/Configurator.cpp)

The Runner launches each Agent as a `boost::process::child`, appending the
generated socket identifier, then connects the Agent client. It posts tasks
and waits on the last task ID. Critically, it ignores that wait's status and
returns `true` after disconnecting Agents. Controller/resource/Agent setup
failures have explicit `false` returns, but task failures are not universally
mapped to failure. It also calls `reconfig_adb`: a discovered device matching
saved name and ADB path can replace the saved address.
[Runner implementation](https://github.com/MaaXYZ/MaaFramework/blob/7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7/source/MaaPiCli/Impl/Runner.cpp)

MaaFgo's Agent reads the last argument as socket ID, changes CWD to the parent
of `agent/`, initializes Toolkit, starts the Agent server, joins, and shuts
down. OrchestratoRRR must not spawn that Python Agent separately.
[Agent entry](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/agent/main.py)

### 5. Exit, signals and process ownership

In direct mode, `main` returns zero for a true Runner result and `-1` for
false. Its signal handler calls `exit(0)` for SIGINT, SIGTERM, SIGABRT and
SIGSEGV; a zero code therefore cannot certify business completion even
apart from unchecked task status. Windows termination is not equivalent to
invoking that signal handler. No whole-descendant cleanup guarantee follows
from this code.
[CLI entry point](https://github.com/MaaXYZ/MaaFramework/blob/7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7/source/MaaPiCli/CLI/main.cpp)

The interactor can call `ShellExecuteW(..., "runas", ...)` when the selected
controller requires elevation. It saves configuration and returns success
when a replacement elevated instance starts. The same interactor prints a
completion sentence solely from Runner's boolean, so that sentence is not
independent task evidence. Manual ADB input produces the device name
`<address>-<adb_path>`.
[interactor](https://github.com/MaaXYZ/MaaFramework/blob/7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7/source/MaaPiCli/CLI/interactor.cpp)

MaaFgo's BBC connection manager uses `subprocess.Popen` to launch BBC;
its shown creation flags are zero or `CREATE_NEW_CONSOLE`, not Job breakaway.
However, its start action also searches for existing BBC processes, may
reuse one, or kills matching BBC processes globally before restarting.
That behavior is outside the new adapter's ownership policy and makes
coexistence with an independently running BBC unsafe to assume.
[BBC launch](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/agent/custom/bbc_connection_manager.py),
[BBC start action](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/agent/custom/bbc_start.py)

The stop listener listens for `MaaTaskerPostStop` and kills matching BBC
processes. Killing the Agent or CLI is not proof this task event was emitted.
The adapter does not send that event or add global name-based process kills.
[BBC stop listener](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/agent/custom/bbc_stop_listener.py)

### 6. Logs and side effects

Toolkit configures a `debug/` log directory relative to its user path and
uses `config/maa_option.json`. If the options file is absent, Toolkit creates
it. Logging can be disabled. MaaPiCli's inspected path provides no stable,
per-invocation machine-readable all-task result artifact. Framework debug
logs are a possible future evidence source, not a frozen success contract.
[Toolkit options implementation](https://github.com/MaaXYZ/MaaFramework/blob/7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7/source/MaaToolkit/Config/GlobalOptionConfig.cpp),
[option filenames/defaults](https://github.com/MaaXYZ/MaaFramework/blob/7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7/source/MaaToolkit/Config/GlobalOptionConfig.h)

MaaFgo's `mfaalog` writes human-facing stdout prefixes; BBC launch redirects
its own output to `bbc_stdout.log` and `bbc_stderr.log`. These are not a
versioned, run-scoped task-result protocol.
[Agent logging](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/agent/custom/mfaalog.py),
[BBC output files](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/agent/custom/bbc_connection_manager.py)

"Read-only" in this phase means the adapter's checks never write user files.
It does not promise upstream processes cannot write their own logs/state.
Those side effects require an explicitly approved, isolated smoke later.

## Phase-one implementation contract

- `MaaFgoConfig` has only enabled, executable, working directory and two
  strictly positive integer budgets. Arguments are always `("-d",)`.
- Disabled configuration needs no paths; directly running a disabled adapter
  is rejected. Enabled use is Windows-only. Paths must be absolute, files
  must exist, executable basename must be MaaPiCli.exe, and executable/CWD
  must describe the same CLI project root. The interface must identify
  MaaFgo PI v2 and exactly one matching, non-elevating Adb controller.
- The constructor's required `expected_adb_serial` must later be supplied
  directly from `config.mumu.adb_serial`, not a second TOML setting.
  Read-only preflight compares it with **top-level `adb.address`**, not a
  guessed controller.address field. Only canonical `127.0.0.1:<1-65535>` is
  accepted. No DNS, localhost alias, whitespace, alternate loopback IP,
  leading-zero port, USB serial or automatic repair is performed.
- Preflight also requires an existing absolute adb.exe and the upstream
  manual-input name `<address>-<adb_path>`; detected emulator names fail as
  `ADB_AUTODETECT_UNSUPPORTED`. The generic device finder includes the serial
  in its fallback name, so a matching manual-style name binds that discovery
  to the same endpoint. This is a source-based restriction for the inspected
  implementation, not verification of arbitrary installed binaries.
  [device discovery](https://github.com/MaaXYZ/MaaFramework/blob/7ee7bd3d2e04d901f0b66d1907c2456639fb6ee7/source/MaaToolkit/AdbDevice/AdbDeviceFinder.cpp)
- This check does not probe ADB, certify readiness, or prove BBC's separate
  connection settings select the same emulator. BBC can use its own auto/
  MuMu/manual connection strategy. That is an explicit second-phase gate;
  do not mirror or rewrite those business options in OrchestratoRRR.
- The Adapter reuses ProcessSpec, ProcessSupervisor, Deadline and
  CancellationToken. The default supervisor gets stop_timeout_seconds as
  its kill-confirmation budget. The existing suspended launch / Job assign /
  resume sequence and KILL_ON_JOB_CLOSE remain unchanged. No breakaway,
  descendants-survive-close, process attachment or global kill is enabled.
- The effective deadline is the smaller of configured and caller budgets;
  expired/cancelled preflight does not launch. Cleanup runs in finally,
  including KeyboardInterrupt (which propagates). Stop uses existing hard
  Job termination, not a newly invented Ctrl+C protocol. Existing supervisor
  cleanup bounds apply; no external filesystem operation is made magically
  interruptible by the deadline.
- Exit nonzero means PROCESS_EXIT_NONZERO. Exit zero with normal termination
  and cleanup means **FAILED / COMPLETION_UNCONFIRMED**. The initial result
  model intentionally has no OK or business-success status. It always
  reports completion_confirmed=false. A successful smoke alone cannot fix
  the demonstrated upstream status-propagation gap.
- Timeout/cancellation preserve their status if cleanup fails; cleanup
  failure overrides the error code and never claims owned_process_cleaned.
  WAIT_FAILED/unknown stopped paths are also conservative about cleanup.
- stdout/stderr go to DEVNULL: zero raw bytes retained and no unbounded
  capture file. Stable diagnostics are generated from an allowlist of
  enums, flags and exit code, never exceptions, paths, PID, serial or raw
  ProcessResult diagnostics. No log-text completion parser is added.
- No AppConfig/TOML loader, provider registry, production stage, report
  schema or default workflow order is changed. Future projection can consume
  the result's sanitized diagnostics; it must not promote unconfirmed to OK.

## Unknowns and required later smoke

These are not validated by the Fake:

1. An actual installed MaaPiCli/DLL/Python/Agent version combination, CLI
   directory layout, relative dependency resolution, imported resources,
   and compatible user-created CLI profile (MXU state is not assumed to be
   interchangeable).
2. Correct same-endpoint selection by both MaaFramework and BBC, including
   multiple MuMu instances, unavailable expected instance, and attempted
   rediscovery. Configuration matching is necessary, not runtime evidence.
3. Real successful/failed/partially failed task status and a robust evidence
   protocol. Investigate per-run task callbacks/log boundaries and rotation
   before any success promotion. Do not trust the printed completion line.
4. Agent/BBC descendant membership and cleanup under real timeout, cancel,
   crash and parent exit; console vs service/elevated environments; any
   further BBC child or pre-existing service. Job protection only owns its
   descendants, not pre-existing processes or Android applications.
5. Real Ctrl+C behavior and safe interruption points. First-phase automated
   tests exercise CancellationToken/TerminateJobObject, not signal delivery
   to a real MaaPiCli.
6. Upstream state/log writes and interference with an already running
   MXU/Agent/BBC. Run approved smoke only with isolated copies/configuration
   and no unrelated BBC process at risk. Do not automate MXU or patch BBC to
   bypass the risk.

## Verification

Focused suite: 94 passed. Real Windows Fake subprocesses cover exit 0/nonzero,
large private stdout/stderr, hang, cancellation, deadline/config timeout,
living-child cleanup on parent exit/failure/timeout/cancel, launch failure,
cleanup failure, wait failure, interrupts and path-free diagnostics.
Configuration cases cover disabled/invalid paths and integers, malformed or
oversized JSON, duplicate keys/controllers, identity mismatch, autodetection,
elevation rejection and byte/mtime-preserving read-only checks.

The first focused invocation hit PermissionError on the existing
`E:/Temp/pytest-of-shiki` cache root (33 passed, 62 setup errors). Repeating
with fresh workspace-local TEMP/TMP passed; no original temp files were
removed. One existing `.pytest_cache` permission warning remained on that
repeat. Full-suite verification uses a fresh cache directory as well.

Final results:

| Check | Result |
| --- | --- |
| Focused pytest, fresh temp/cache | 94 passed in 6.91s, no warnings |
| Full pytest, outside sandbox | 1688 passed, 1 skipped in 118.47s |
| Ruff | All checks passed |
| strict mypy | No issues in 81 source files |
| git diff --check | Passed |

The first full run inside the sandbox returned 1682 passed, 1 skipped and
6 failures in existing packaging tests (access denied / UPDATE_POSTCHECK_FAILED).
Those tests redirect APPDATA/LOCALAPPDATA to synthetic installations. All
36 packaging tests passed outside the sandbox in 47.47s, followed by the
successful complete run above. No installer code was changed to obtain a pass.

Commands used the existing repository environment:

```powershell
# Each pytest invocation used its own newly created directory; no existing
# pytest basetemp or user files were deleted. TEMP/TMP affect this shell only.
$env:TEMP = Join-Path (Get-Location) ('tmp/maafgo-validation-' + [guid]::NewGuid().ToString('N'))
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP | Out-Null
& .venv/Scripts/python.exe -m pytest tests/config/test_maafgo_config.py tests/runtime/test_maafgo_runtime.py -q --tb=short -o cache_dir="$env:TEMP/pytest-cache"
& .venv/Scripts/python.exe -m pytest -q --tb=short -o cache_dir="$env:TEMP/pytest-cache"
& .venv/Scripts/python.exe -m ruff check .
& .venv/Scripts/python.exe -m mypy src
git -c safe.directory='E:/Program Files/Games/Autogame/orchestrator-src' diff --check
```

Only the eight new files have intent-to-add entries so ordinary Git diff
includes them; no file content is staged and no commit was made.

## Second phase proposal, not installed

Managed lifecycle position:

```text
RUN_MAA
WAIT_MUMU_ADB_READY_BEFORE_MAAFGO
RUN_MAAFGO
SHUTDOWN_MUMU
RUN_BETTERGI (if enabled)
WRITE_RUN_REPORT
```

For external MuMu, recheck the existing external instance's ADB readiness
without acquiring start/stop ownership. Add independent opt-in provider,
stable stage projection and failure cleanup only in phase two, after the
identity/ownership gates and completion evidence contract above are settled.
Keep MaaFgo entirely separate from MAA resource merging and updates.
