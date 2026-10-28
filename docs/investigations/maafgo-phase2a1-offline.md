# Phase 2A.1 — offline distribution and bounded Python smoke

> **状态更新（2026-10-29）**：本文是当时 revision（d7f3a474）的只读调查记录，
> 保留原始结论与证据边界。其中"下一步/阻塞"类陈述已在 MaaFgo Phase 2 落地时
> 处理：上游无安全机制（见 `maafgo-upstream-inventory-2026-10-29.md`），最终
> 采用 ORR 私有 BBC-free 分发 transform（`docs/decisions/ADR-0003`），完成证据
> 契约与生产接入见 `docs/maafgo-full-workflow.md`。历史结论不因此改写。

Date: 2026-09-09. Branch: `feat/maafgo-integration`.
Recovered the latest project-specific pi session (last user continuation at
19:59 local time). Its latest substantive instruction was Phase 2A.1, which
explicitly resumes offline work beyond the older Phase 2A stop conditions.

Phase 1 checkpoint: `7fbb547a7793752df31a63cd52e3e3065c46c877`.
Phase 2A documentation checkpoint: `63eceff089c64f9e96f75e609b7568ab94b72de7`.
Both already existed at takeover; the working tree was clean. The older
Phase 2A document's statement that its documents were uncommitted is historical.
No commits or pushes were made during this continuation.

## Outcome and gate boundaries

| Gate | Result | What was actually verified |
| --- | --- | --- |
| A | PASS for offline filesystem/inventory contract | 12,423 files; all manifest hashes read back; imports and resource directories resolve; 104 Windows PE files are AMD64/PE32+; explicit embedded Python and matching binding/native material |
| B | PARTIAL_PASS | Python 3.12.10; MaaFramework reports v5.13.0; five core native DLLs load; dependency metadata checks pass; all 61 Agent sources compile; six pure modules import |
| C | BLOCKED | `PROJECT_LOAD_ONLY_NOT_SUPPORTED` in the pinned CLI; not launched |
| D | NOT RUN | Real tasks are outside this phase's authorization |

Gate A is not a full Windows loader, ProjectInterface schema, resource semantic,
or business certification. The immutable assembly manifest explicitly reports
`FILESYSTEM_PASS_RUNTIME_PENDING` and
`RUNTIME_DLL_RESOLUTION_REQUIRES_GATE_B`. Gate B subsequently resolves the five
tested native entry libraries on this host, not every optional/delay-loaded
dependency or every third-party extension on a clean Windows machine. No PE
import-table dependency resolver was added. Full Agent imports remain untested.
Neither Gate A nor B enables the Phase 1 adapter to report business success.

No MaaPiCli, AgentServer, ADB, MuMu, FGO, BBC or MXU was started or connected to.
The only acquired executable run was isolated Python for the bounded Gate B.
No synthetic/production device profile was created or read. No production
workflow, TOML, installer, upstream source, or existing process was changed.

## Fixed inventory

| Material | Identity |
| --- | --- |
| MaaFramework SDK / MaaPiCli | v5.13.0, release commit `2bcfa85c66a2eac6ca3e5937f175495275ee0643` |
| SDK ZIP SHA256 | `179b51b6211fc74317c8dc06f10fae4724aca370df7d1bf694cd00d06ff38efe` |
| MaaFgo | `d7f3a474f50b9a0631ee9acd6df67998c1933f2b` |
| MaaFgo snapshot SHA256 | `d21e0ec90e4aecce87d950c0ac04b72f46cce1bfd55e4a0488d29a86163f247b` |
| Python | python.org embedded CPython 3.12.10 amd64 |
| Python ZIP SHA256 | `4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3` |
| Binding | `maafw-5.13.0-py3-none-win_amd64.whl` |
| Binding SHA256 | `105c22431183446d350864b946fb9448f47fd9d73a20e4b46e276ea2a22067e5` |
| Output manifest SHA256 | `f069055e063cea0f112c0b89ef1a025ddd600dfd75f0a56df05ea0ed1ff05423` |

The SDK ZIP contains no Python wheel. The separately published matching
[official maafw 5.13.0 wheel](https://pypi.org/project/maafw/5.13.0/) was selected
instead of a floating binding. Every file under its `maa/bin/`, including
the plugin subdirectory, is compared byte-for-byte against the corresponding
SDK `bin/` file before writing. This proves the native parity of these actual
artifacts rather than assuming equal version strings imply equal DLLs.

The pinned MaaFgo `tools/setup_embed_python.py` chooses Python 3.12.10 amd64.
Its CI otherwise downloads latest Framework and installs unpinned requirements;
that upstream process is not reproduced. Seven top-level packages were explicitly
selected here: maafw 5.13.0, opencv-python-headless 4.11.0.86, numpy 2.2.6,
psutil 7.0.0, highspy 1.10.0, onnxruntime 1.22.0 and Pillow 11.2.1.
The outer acquisition resolved transitive dependencies once. All 17 exact
filenames/versions/SHA256 values are frozen in
[`scripts/maafgo-smoke-wheels.lock.json`](../../scripts/maafgo-smoke-wheels.lock.json).
Downloads used the configured pip mirror, then every wheel hash was independently
checked against official PyPI metadata for that exact version before use.
This is an experimental dependency lock, not a claim of upstream runtime support.
The assembler performs no dependency resolution, downloads, pip installs or execution.

## Reproducible assembly

[`scripts/prepare_maafgo_cli_smoke.py`](../../scripts/prepare_maafgo_cli_smoke.py)
consumes three explicit archives and the reviewed wheel directory. Run with
explicit local paths (angle-bracket values below are placeholders):

```powershell
.venv\Scripts\python.exe scripts\prepare_maafgo_cli_smoke.py `
  --framework '<materials>/framework.zip' `
  --maafgo '<materials>/maafgo.zip' `
  --python '<materials>/python-3.12.10-embed-amd64.zip' `
  --wheels '<materials>/wheels' `
  --output '<new-private-external-directory>'
```

The output must be absent/empty, outside the repository, and in a private parent
without concurrent writers. Reparse-point ancestors, archive symlinks, traversal,
Windows alternate streams/reserved names and case collisions are rejected.
Every archive is hashed before consumption; all validation precedes output
creation. Writes use exclusive creation. Partial output is retained on failure,
with no success manifest; the tool never deletes or cleans any directory.
The private-parent assumption does not claim protection from an adversary racing
filesystem junction changes during writes.

Actual layout (589,068,068 payload bytes):

```text
<distribution>/
  MaaPiCli.exe, MaaFramework.dll, MaaToolkit.dll, ...  # SDK bin, preserved
  plugins/                                          # SDK bin/plugins
  MaaAgentBinary/                                    # SDK share payload
  interface.json, resource/, tasks/, options/, i18n/   # source assets
  agent/                                            # unchanged source
  python/                                           # fixed embedded CPython
    Lib/site-packages/                               # locked wheel material
      maa/bin/                                      # SDK-identical native files
  licenses/, LICENSE, README.md, requirements.txt
  distribution-manifest.json
```

No upstream `config/` is copied. `requirements.txt` is provenance only, not an
installation instruction. No BBC executable is in the snapshot or this bundle;
BBC executable architecture is therefore NOT AVAILABLE, not claimed verified.
The snapshot's `bbcdll` contains a BBC server and replacement `_ctypes` modules;
they are deliberately excluded from this no-business bundle, not inserted into
CPython. MaaAgentBinary is an Android helper payload (ELF/scripts for multiple
Android architectures), not a Windows Agent executable; it must not be subjected
to an erroneous Windows-x64-only PE check. All 104 actual Windows executable,
DLL, PYD and NODE files passed the PE architecture check.

Only two deterministic transformations occur:

1. Source `python ../agent/main.py` becomes
   `./python/python.exe -u ./agent/main.py`, matching the pinned Windows MXU
   Agent launch layout. Controller, resources, tasks and options are unchanged.
2. `python312._pth` explicitly contains `python312.zip`, `.`, `Lib/site-packages`
   and `../agent`. `import site` is disabled. No user site/PYTHONPATH discovery,
   get-pip or executable `.pth` processing is enabled. `coloredlogs.pth` remains
   inert; the one SymPy man page is mapped from wheel `.data/data` to Python's
   `share/man/man1`. Unknown wheel `.data`/`.pth` layouts fail closed.

Pinned MaaPiCli `Configurator.cpp:239` selects `<project>/MaaAgentBinary`.
Lines 424–428 set Agent executable/arguments and project cwd. `Parser.cpp:29–48`
resolves interface imports relative to the interface root. Agent `main()` would
also chdir to project root and initialize Toolkit at `./`; it was not called.
Future launch must explicitly control `MAAFW_BINARY_PATH`, which the official
binding honors, rather than inheriting a user override. Gate B set it to the
verified private binding's `maa/bin` and used a restricted child environment.

The local ignored locators are `tmp/phase2a-root.txt` (materials) and
`tmp/phase2a1-distribution-root.txt` (assembled directory). Paths are deliberately
absent from the public manifest and this report. Gate B JSON is beside the
materials under `evidence/gate-b-result.json`. After Gate B, all payload hashes
were verified again and there were zero unexpected files in the distribution.

## BBC and completion conclusions

See [Agent import safety](maafgo-agent-import-safety.md) and
[BBC-free path investigation](maafgo-bbc-free-paths.md).
Result: **BBC_FREE_PROFILE_PARTIAL**. Useful task-only paths exist, including
login, planting and free friendship summon, and explicit native combat options.
However global stop callbacks remain enabled even on those paths. Renaming BBC
and moving it cannot fix the hardcoded executable predicate and ports.

Completion remains `exit 0 => COMPLETION_UNCONFIRMED`. A future reporter should
use `AgentServer.tasker_sink()` and observe every selected task's start and
terminal status, with caller-generated unpredictable run ID, plan digest and
per-task identities. The pinned Configurator generates a fixed set of `PI_*`
variables; it does not establish an arbitrary ProjectInterface environment map
for ORR. `Runner.cpp` shows normal child environment inheritance, so a dedicated
ORR environment contract is a plausible transport, pending upstream reporter
agreement and end-to-end validation. No reporter was implemented.
Write a bounded versioned artifact atomically in a fresh private run directory;
reject absent, stale, malformed, duplicate, unknown or missing task evidence.
Failure/cancellation dominates later success. Hard termination cannot guarantee
an artifact; timestamps or final-task success alone cannot certify completion.

Next direction: resolve the upstream Agent's BBC cleanup ownership contract
for the candidate BBC-free profile, before proposing a real smoke. Do not
proceed to production integration or real game execution from this checkpoint.

## Changes and verification

Added the dev assembler, wheel lock, focused tests, and three investigation
documents. No production modules changed. Focused tests: **25 passed**.
Ruff: passed. Strict mypy: passed (81 source files).
Full regression: **1713 passed, 1 skipped**, 120.80 seconds, using the existing
Windows venv and fresh TEMP/TMP/cache/base directories. The initial restricted
run had six existing installer/shortcut failures (1707 passed, 1 skipped);
all passed when rerun outside the sandbox against fresh synthetic fixtures.
No installer or shortcut implementation was changed to accommodate the sandbox.
`git diff --check` and no-index whitespace checks on all new files passed.

`git diff --stat` is empty because all six additions remain untracked, as
requested; a no-index comparison against empty files shows 6 files / 920 added
lines (assembler 297, lock 107, tests 158, import audit 79, BBC paths 92,
this report 187). Nothing was staged, committed or pushed.
