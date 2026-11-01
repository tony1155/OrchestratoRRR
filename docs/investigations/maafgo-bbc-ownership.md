# MaaFgo BBC ownership gate

> **状态更新（2026-10-29）**：本文是当时 revision（d7f3a474）的只读调查记录，
> 保留原始结论与证据边界。其中"下一步/阻塞"类陈述已在 MaaFgo Phase 2 落地时
> 处理：上游无安全机制（见 `maafgo-upstream-inventory-2026-10-29.md`），最终
> 采用 ORR 私有 BBC-free 分发 transform（`docs/decisions/ADR-0003`），完成证据
> 契约与生产接入见 `docs/maafgo-full-workflow.md`。历史结论不因此改写。

## Evidence boundary
Read-only inspection of MaaFgo commit
`d7f3a474f50b9a0631ee9acd6df67998c1933f2b`, downloaded independently from
GitHub. No BBC binary was downloaded or executed by this investigation.
Source links below use that exact revision:

- [start action](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/agent/custom/bbc_start.py)
- [connection manager](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/agent/custom/bbc_connection_manager.py)
- [process predicate](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/agent/custom/bbc_process_utils.py)
- [stop listener](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/agent/custom/bbc_stop_listener.py)
- [connection options](https://github.com/xlxyvergil/MaaFgo/blob/d7f3a474f50b9a0631ee9acd6df67998c1933f2b/assets/options/connect_method.json)

## Findings

1. The interface imports `tasks/启动bbc.json`. Custom action `start_bbc`
   implements launch/reuse/restart. This is a confirmed entry, not an exhaustive
   transitive inventory of all battle pipelines that can reach it.
2. `StartBbc.run` reads `context.get_node_data("启动bbc").attach`, not the
   MaaPiCli profile's top-level `adb.address`. PI options override that pipeline
   node. `options/connect_method.json` selects auto/mumu/ldplayer/manual;
   `options/manual_port.json` is the separately imported manual input definition.
3. `auto` maps to `auto` with `{mode: auto}`. MuMu maps to `connect_mumu`
   with path/index/pkg/app_index. Manual maps to `connect_adb` with
   `{ip: manual_port}`. BBC control TCP ports are separately fixed to loopback
   25001 and callback 25002; these are NOT the emulator ADB port.
4. Without a source patch, the exposed manual option can express the same
   endpoint as ORR's `config.mumu.adb_serial`. This is only configuration
   expressibility: exact profile serialization, live binding and fail-closed
   behavior have NOT been validated. No production configuration was read or
   copied to assert a match. MuMu mode is not an ADB-serial equality guarantee.
5. Existing BBC is searched globally. Reuse requires manager connectivity,
   `get_connection`, connected/available state, nonempty emulator parameters,
   and matching parameters. Manual compares IP exactly; auto accepts any
   nonempty parameter object. Otherwise start calls `_kill_all_bbc_processes`
   BEFORE restart and before its subsequent stopping check.
6. There is a conditional reuse path, NOT a fail-closed connect-existing-only
   mode in the inspected start action. A connection failure falls into restart.
7. The listener reacts to entry `MaaTaskerPostStop`, not ordinary successful
   completion. Normal completion therefore does not guarantee listener cleanup;
   hard termination also cannot guarantee delivery or execution of this event.
8. New BBC uses subprocess creation without a demonstrated breakaway flag.
   This makes Job inheritance plausible, not measured. CLI/Agent/BBC membership
   under a real ORR Job remains unverified. A reused external process never
   becomes a descendant merely because the Agent connects to it.
9. Both start cleanup and stop listener call `psutil.process_iter` and kill
   matching processes without checking Job, parent, run ID, executable full
   path, endpoint or ownership. Predicate matches basename (process name OR
   argv[0]): bbchannel.exe, bbchannel64.exe, bbchannel_debug.exe,
   bbchannel64_debug.exe. Precise basename matching avoids some unrelated
   processes but does NOT protect an external user's BBC.

## Ownership matrix

| Process/entity | Owner |
| --- | --- |
| MaaPiCli launched by ORR | OrchestratoRRR |
| Python Agent descendant | OrchestratoRRR if actually in its Job |
| Newly spawned BBC descendant | OrchestratoRRR only if actually in its Job |
| Pre-existing BBC | External / not owned |
| MuMu | Existing MuMu lifecycle contract; no new ownership |
| Android FGO | MaaFgo business effect, not a Win32 Job child |

**BBC_EXTERNAL_PROCESS_KILL_RISK — confirmed smoke blocker.** An isolated
filesystem does not isolate the Windows process namespace or fixed TCP ports.
Per the Phase 2A stop rule, no further executable assembly/import/run gates
were attempted after confirming this condition. No global kill workaround,
source patch, BBC experiment or workflow integration was added.

Future work requires an explicit upstream-owned design for connect-only / scoped
spawn-and-cleanup with positive identity and ownership, or separately approved
OS-level isolation. Merely checking that no BBC is currently running is racy
and does not resolve this contract.
