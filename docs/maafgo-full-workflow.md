# MaaFgo 完整 FGO 工作流（Phase 2）

状态：**REAL DEVICE ACCEPTANCE: PENDING USER**（开发阶段：实现完成、合成/离线验证通过）
基线：MaaFgo `d7f3a474` / MaaFramework v5.13.0 / MaaPiCli（SDK 内）/ CPython 3.12.10
关联：`docs/decisions/ADR-0003-maafgo-bbc-free-private-distribution.md`、
`docs/investigations/maafgo-upstream-inventory-2026-10-29.md`、
`docs/manual/maafgo-real-acceptance.md`

## 目标与边界

从 OrchestratoRRR 统一入口启动一次 FGO workflow，在 managed MuMu 模式下从
「MuMu 未启动、FGO 未启动」开始，由 MaaFgo 自己完成 登录 → 导航关卡 → 助战/编队
→ native 自动战斗 → 结算，OrchestratoRRR 负责生命周期、设备身份、进程所有权、
完成证据与收尾。OrchestratoRRR 不实现任何 FGO 业务逻辑（地图、识别、助战、
编队、战斗状态机都由 MaaFgo own）。

## Workload 选择

顶层 `game = "starrail" | "fgo"`（缺省 = starrail，旧配置行为逐字节不变）：

- `game = "starrail"`：既有 16 阶段 managed / 11 阶段 external 计划；`[maafgo]`
  即使配置了也不参与校验与执行。
- `game = "fgo"`：要求 `[fgo]`（provider=maafgo、package_name、
  stop_game_on_exit）与启用状态的 `[maafgo]`；starrail/maa/maa_sync/maa_update/
  maa_resource_merge/aalc/bettergi 段**整段缺省合法**（不参与校验，也不执行），
  但段一旦存在仍须可解析——存在却解析失败会阻断整个加载（fail closed）。
  ADB 设备真值只在
  `[mumu] adb_serial`，`[fgo]`/`[maafgo]` 不提供第二份端点。

## FGO 执行计划

managed（8 阶段）：

```text
VALIDATE_CONFIG → ENSURE_MUMU_RUNNING → WAIT_MUMU_ADB_READY
→ PREPARE_MAAFGO_RUN → RUN_MAAFGO → STOP_FGO → SHUTDOWN_MUMU → WRITE_RUN_REPORT
```

external（7 阶段）：同上但无 `SHUTDOWN_MUMU`（不启动、不停止外部 MuMu，
只确认 readiness，不获取生命周期所有权）。

`PREPARE_MAAFGO_RUN` 与 `RUN_MAAFGO` 分离，使 RunReport 能区分：

| 失败类别 | 阶段 | 稳定诊断 |
| --- | --- | --- |
| 配置/profile/distribution 准备失败 | `PREPARE_MAAFGO_RUN` | `source_error_code = MAAFGO_PROFILE_POLICY_REJECTED / MAAFGO_DISTRIBUTION_UNVERIFIED / ADB_…` |
| 进程启动/运行失败 | `RUN_MAAFGO` | `PROCESS_START_FAILED / PROCESS_EXIT_NONZERO` |
| 业务完成失败 | `RUN_MAAFGO` | `MAAFGO_TASK_FAILED / MAAFGO_RESULT_* / COMPLETION_UNCONFIRMED` |

## 完成证据契约（ORR ↔ MaaFgo reporter）

exit code 不证明业务成功（MaaPiCli Runner 忽略任务状态、信号处理可 exit 0；
`exit 0 => COMPLETION_UNCONFIRMED` 是刻意的安全设计）。生产 run 的唯一成功
路径是**逐任务、run-scoped、机器可验证**的证据：

### 1. Run 契约（OrchestratoRRR 侧，PREPARE 阶段）

- 每次运行创建全新私有目录 `<report_dir>/maafgo/<uuid4>/`，不复用旧 artifact；
  陈旧结果靠「全新目录 + run id + digest」三重绑定拒绝，而不是删除-覆盖同一
  全局文件。
- 解析 profile 任务名 + interface import 链得到 `(name, entry)` 对
  （PI 以 interface entry 投递任务，如 `登录 -> 登录识别`）。
- 原子写出 `expected-tasks.json`；`plan_digest = sha256(该文件字节)`。
- 通过 `ProcessSpec.environment_overrides` 向子进程注入
  （MaaPiCli Runner 正常继承子进程环境）：

```text
ORR_MAAFGO_RUN_ID                 # uuid4，调用方生成、不可预测
ORR_MAAFGO_PLAN_DIGEST
ORR_MAAFGO_RESULT_PATH
ORR_MAAFGO_EXPECTED_TASKS_PATH
ORR_MAAFGO_RESULT_SCHEMA_VERSION  # "1"
```

### 2. Reporter（ORR 私有分发内 `agent/orr_reporter.py`）

- 经官方 `AgentServer.tasker_sink()` 注册 `TaskerEventSink`，消费
  `Tasker.Task.{Starting,Succeeded,Failed}`（v5.13.0 源码核实的语义）。
- `entry=MaaTaskerPostStop` 是 post_stop 内部任务：只记录
  `stop_signal_observed`，绝不计为业务任务；其余未在期望集合内的 entry 记入
  `unexpected_entries`（ORR 视为契约漂移，fail closed）。
- 失败占优：任务一旦 `failed` 不再翻转为 success。
- 每次终态变化即原子持久化（临时文件 + fsync + `os.replace`）；atexit 兜底。
- reporter 不枚举进程、不访问网络、不使用 BBC 端口；所有异常吞掉绝不崩溃
  Agent（写不进 artifact => ORR 侧 RESULT_MISSING => fail closed）。

### 3. Artifact（schema v1，≤64KiB，UTF-8，机器可读）

```json
{
  "schema_version": 1,
  "run_id": "<ORR_MAAFGO_RUN_ID>",
  "plan_digest": "<sha256>",
  "outcome": "success | failed | incomplete",
  "tasks": [{"name": "登录", "entry": "登录识别", "terminal": "success"}],
  "unexpected_entries": [],
  "stop_signal_observed": false
}
```

### 4. OrchestratoRRR 严格校验（child 退出后）

`exit 0` + 正常终止 + owned tree 清理 + 配置确认之后，还必须全部成立：

```text
artifact 存在（否则 MAAFGO_RESULT_MISSING）
schema_version 已知；≤64KiB；严格 JSON（无重复键、无 NaN/Infinity）
run_id 精确匹配；plan_digest 精确匹配（否则 MAAFGO_RESULT_ID_MISMATCH）
任务集合与期望完全一致：不多、不少、不重、顺序一致（否则 MAAFGO_RESULT_INVALID）
unexpected_entries 为空（否则 MAAFGO_RESULT_INVALID）
每个任务 terminal == success（failed → MAAFGO_TASK_FAILED；
pending → COMPLETION_UNCONFIRMED）
```

全部成立才产生 `MaaFgoRunStatus.SUCCESS / completion_confirmed=true`。
timeout/cancel 是控制面结果，**优先于任何晚到的 success artifact**。

## BBC 安全

见 ADR-0003。要点：生产运行只允许 ORR 私有分发（PREPARE 阶段
`check_distribution()` fail closed）；BBC 不启动；bbc_stop_listener 不注册；
六个 bbc_* 模块被移除；无全局 taskkill 路径；不选择 MaaFgo 的 `关闭游戏`。

## Profile policy（只读）

`MaaFgoConfig.check_profile_policy()` 在 PREPARE 阶段执行，绝不改写用户
profile：任务列表非空；首个任务必须是 `登录`（完整流程入口，从游戏未运行
状态开始）；拒绝 `启动bbc`/`关闭游戏`/`直接bbc战斗`/`Chaldea 一键战斗`；
拒绝只含 `原生自动战斗`/`直接战斗` 一类需要人工预置页面的组合；所有
`日常战斗/冠位戴冠战/迦勒底之门/通用大活动/通用小活动` 必须显式
`battle_mode=native`（默认是 bbc，缺失选项即拒绝）。policy 与 pinned
revision 的任务语义绑定（分发校验先于 policy）。

## STOP_FGO（游戏退出职责在 OrchestratoRRR）

等价 `adb.exe -s <expected serial> shell am force-stop <exact package>`：
serial 只来自 `[mumu] adb_serial`（仅 127.0.0.1:port）；package 来自
`[fgo] package_name`（Android 包名白名单正则）；argument array、无 shell
拼接；deadline 有界、cancellation 感知；成功后有界 `pidof` 验证（一次重试，
不确定不判失败）。不通过 Windows 进程名、不做任何全局操作。

## 失败 / 超时 / 取消的 teardown

Runner 支持有序、逐阶段门控的 failure-cleanup 列表（公共内核的最小扩展，
StarRail 语义不变）：

| 场景 | STOP_FGO | SHUTDOWN_MUMU |
| --- | --- | --- |
| managed 成功 | 执行（业务阶段） | 执行（业务阶段） |
| managed 失败/超时（RUN 已到达） | cleanup 执行 | cleanup 执行 |
| managed 失败（PREPARE 失败，FGO 未运行） | 跳过 | cleanup 执行（MuMu 已被启动，必须关闭） |
| 用户 Ctrl+C（取消） | 跳过（保留现场） | 跳过（保留现场） |
| external 失败 | cleanup 执行 | 不存在该阶段 |

取消语义沿用项目既有产品约定：**取消不主动破坏用户环境**（MuMu 保留运行、
FGO 现场保留），但 MaaPiCli + Python Agent 的 owned 进程树仍由
ProcessSupervisor/Job Object 立即终止——「是否杀本次 owned 进程」与「是否关
闭 MuMu/游戏」是两个独立问题。

## RunReport / projection

`RUN_MAAFGO` / `STOP_FGO` 的 StageReport 诊断只输出白名单字段
（`source_error_code`、`provider`、`termination_reason`、`exit_code`、
`owned_process_cleaned`、`configuration_confirmed`、`completion_confirmed`、
`expected/confirmed_task_count`、`completion_evidence_schema_version`、
`plan_digest_match`、`artifact_validation_state`、STOP_FGO 的 `verification`）。
不输出：绝对路径、用户名、
adb 路径、完整 serial、PID、原始 stdout/stderr、异常 repr、上游 JSON 全量。
公共 ErrorCode 词表保持稳定（`WORKFLOW_STAGE_FAILED/TIMEOUT/CANCELLED` +
`source_error_code` 承载 MaaFgo 专属细节）。

## Fake 与测试

`tests/fakes/fake_maafgo.py` 支持 artifact 故障注入
（ok / missing / malformed / wrong-run-id / wrong-digest / missing-task /
duplicate-task / unknown-task / entry-drift / task-failed / incomplete /
unexpected-entry / ok-then-hang），success 模式生成与生产 reporter 相同
schema 的 artifact，并由测试证明其能通过生产 verifier。工作流测试以 Fake
Port 走完整 managed/external 链路（MuMu 启动 → ADB ready → PREPARE → RUN →
STOP_FGO → SHUTDOWN → report），不 mock `MaaFgoAdapter = success` 的短路。

## 已知限制

- 真机（真实 MuMu/FGO 账号/目标关卡/真实 MaaFgo 安装）未验收。
- native 自动战斗的玩法可靠性是 MaaFgo 上游的实验性能力，本项目不做背书。
- pin 升级（MaaFgo main 新增的任务/模块）未评估。
- `pidof` 验证依赖设备侧 toybox 行为；不确定结果不会失败整个 run。

REAL DEVICE ACCEPTANCE: PENDING USER
