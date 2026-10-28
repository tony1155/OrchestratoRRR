# MaaFgo BBC-free paths and process isolation

> **状态更新（2026-10-29）**：本文是当时 revision（d7f3a474）的只读调查记录，
> 保留原始结论与证据边界。其中"下一步/阻塞"类陈述已在 MaaFgo Phase 2 落地时
> 处理：上游无安全机制（见 `maafgo-upstream-inventory-2026-10-29.md`），最终
> 采用 ORR 私有 BBC-free 分发 transform（`docs/decisions/ADR-0003`），完成证据
> 契约与生产接入见 `docs/maafgo-full-workflow.md`。历史结论不因此改写。

Revision: `d7f3a474f50b9a0631ee9acd6df67998c1933f2b`.
Read-only source investigation; no FGO/BBC/ADB/controller/task execution.
Source names below are relative to that snapshot. The matrix describes task
reachability on base + CN resources; it is not a certification of every server,
every option combination or stop/cancellation behavior.

## Task dependency matrix

Task definitions were traced through `next`/`on_error` nodes, task overrides,
`options/战斗方式.json`, and relevant custom action call sites. Every ordinary
matrix graph traversed without missing node names. Dynamic native repeat calls
were then inspected separately; a graph scan alone is not proof of safety.

| Top-level task | BBC in selected task path | Evidence / exact condition |
| --- | --- | --- |
| 登录 | NONE | `tasks/登录.json` → `登录识别`; CN `pipeline/login.json`, 24 reachable ordinary nodes, no custom BBC action; `包名=B服` is the concrete candidate |
| 种树 | NONE | Entry `种树`, 20 ordinary reachable nodes, no custom actions |
| 免费友情10连 | NONE | `tasks/每日免费友情.json` → `每日免费友情开始`, 25 ordinary reachable nodes, no custom actions |
| 每日1石 / 常驻每日1抽 | NONE | Summon pipelines (27/26 nodes); consume in-game resources, so excluded from the minimal candidate |
| 技能升级 / 被动升级 | NONE | Skill pipelines (23/41 nodes), no BBC actions; business resource spending remains real |
| 整理礼物盒 | NONE on inspected action path | `execute_boxtask`; method `run_task` targets gift-box/filter/sell/navigation nodes, no BBC manager import/call; destructive in-game options are not selected for candidate |
| 强化从者 | NONE on inspected action path | `execute_servant_up` uses strengthen/navigation nodes and box helper; no BBC call found |
| Chaldea 自动编队 / 羁绊补齐 / 构建个人从者礼装库 | NONE on inspected action paths | Formation/bond/inventory actions, not BBC process actions; some fetch Chaldea data or write local state; no general no-side-effect claim |
| 日常战斗 / 冠位戴冠战 / 大活动 / 小活动 / 直接bbc战斗 | CONDITIONAL | Explicit `battle_mode=native` replaces the shared dispatch BBC branch with `原生自动战斗_多次入口`; default is `bbc` |
| 迦勒底之门 | CONDITIONAL | `chaldea_gate_quest_type` cases 种火/修炼场/QP expose nested `battle_mode`; select native there, not merely a nonexistent top-level task option |
| 芥雏子学姐在线代打 | NONE on native branch | `tasks/原生自动战斗.json` → `原生自动战斗调度` → `auto_battle` |
| 芥雏子学姐连续代打 | NONE on inspected repeat branch | Entry `原生自动战斗_多次入口` → `auto_battle_repeat`; method dispatches first/next/last native battle entries |
| 启动bbc | REQUIRED | Entry `启动bbc` → custom action `start_bbc` |
| 关闭游戏 | REQUIRED kill effect | CN and JP `pipeline/关闭游戏.json`: `StopApp` → `关闭bbc` → `stop_bbc`, even if BBC was never started by this profile |

There is also a source task file defining `Chaldea 一键战斗` → `bbc战斗` →
`execute_bbc_task` (BBC-required). It is not imported by the pinned root interface,
so its presence on disk alone must not be advertised as a selectable CLI task.

For native combat, `options/战斗方式.json` explicitly removes
`[JumpBack]执行bbc战斗` from `通用战斗调度`. It does not first call `start_bbc`.
`auto_battle_action.py` imports the native battle runtime, not a BBC manager.
`auto_battle_repeat_action.py:99–123` selects native first/next/last entries;
its `bbc弹窗信息输出` overrides only reuse a display node name, not a BBC process.
This is evidence for an alternative combat backend, not evidence that the
experimental native backend has equivalent gameplay reliability to BBC.
Arbitrary Chaldea input, arbitrary overrides and other server layers are not
part of a confirmed runnable profile.

## Candidate and qualification

Task-only candidate, expressed as design (no profile file created):

- Resource: `B服(小米/应用宝服)` using `resource/base` + `resource/cn`.
- Controller: declared non-elevating `安卓设备` ADB controller; future explicit
  manual endpoint binding must still be validated by the existing ORR contract.
- Ordered tasks: `登录` with `包名=B服`, `种树`, `免费友情10连`.
- Exclude `启动bbc`, `关闭游戏`, all paid summons and all combat tasks.

This is useful daily automation with no BBC task action on the inspected normal
or ordinary error branches. It is still real FGO business and was not run.
**BBC_FREE_PROFILE_PARTIAL**, rather than a fully isolated profile:
`agent/main.py` always imports `bbc_stop_listener`, whose `MaaTaskerPostStop`
callback kills matching external BBC processes without checking whether this
profile used BBC. Cancellation/stop safety remains unresolved. Native mode does
not disable that listener. Task selection alone does not satisfy the complete
process ownership invariant.

## Executable identity and endpoint isolation

| Invariant without changing MaaFgo | Result | Evidence |
| --- | --- | --- |
| Separate filesystem root | YES | Distribution can be copied into a private root |
| Configurable unique executable basename | NO | `bbc_connection_manager.py:26–29` constructs `BBchannel/dist/BBchannel64/BBchannel.exe`; no public option override |
| Unique control TCP/callback ports | NO | Same module defines 127.0.0.1:25001 and callback 25002 at lines 21–23 |
| Process lookup scoped to executable full path/run | NO | `bbc_process_utils.py` matches four hardcoded basenames using process name OR argv[0] |
| Kill scoped after renaming | NO | Renaming breaks the hardcoded launch path and does not change the kill predicate; original externally owned basenames remain targets |
| Fixed emulator ADB endpoint expressible | YES, unvalidated live | `connect_method=manual` uses `manual_port` for `connect_adb` IP; unrelated to the two BBC control ports |
| Arbitrary port occupant protected | NO | Manager construction runs netstat and `taskkill` against a PID listening on 25002 without executable identity/ownership validation |

BBC executable-internal rename behavior is **UNVERIFIED** because no BBC executable
was acquired/executed here. Even if the executable tolerated renaming, the
MaaFgo-side hardcoded path, global predicate and fixed ports already prevent the
proposed no-source-change isolation. No unique basename, shim, symlink, global
kill workaround or source patch was introduced.

Conclusion remains **BBC_EXTERNAL_PROCESS_KILL_RISK**;
**BBC_ISOLATED_INSTANCE_POSSIBLE is not established**. The ownership matrix from
[Phase 2A](maafgo-bbc-ownership.md) remains unchanged: existing BBC is external;
new descendants are ORR-owned only with actual Job membership; emulator and
Android game ownership do not transfer through a BBC connection.

Next step is one direction only: obtain an upstream-owned cleanup contract that
does not register/use global BBC cleanup for the proposed BBC-free run. A future
real smoke can be planned only after that ownership issue is resolved.
