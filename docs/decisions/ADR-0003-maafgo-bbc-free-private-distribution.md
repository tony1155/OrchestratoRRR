# ADR-0003: MaaFgo BBC-free 私有分发（方案 B：确定性私有 transform）

日期：2026-10-29
状态：已采纳（实现完成，真机验收待用户）

## 背景

OrchestratoRRR 的 MaaFgo 集成要求 `battle_mode = native` 的 BBC-free 运行。
Phase 2A/2A.1 调查（`docs/investigations/maafgo-bbc-ownership.md`、
`maafgo-agent-import-safety.md`、`maafgo-bbc-free-paths.md`）确认：

1. `agent/main.py` 无条件导入并注册 `bbc_stop_listener`；其
   `MaaTaskerPostStop` sink 用 `psutil.process_iter` 全局枚举并强杀四个硬编码
   BBC basename 的进程，不检查本 run 是否启动过 BBC。
2. `bbc_connection_manager` 固定占用 127.0.0.1:25001/25002，构造时对占用
   25002 端口的 PID 直接 `taskkill /F /PID`，无属主校验。
3. 选择 `battle_mode=native` 的战斗路径不经过 BBC，但上述全局清理路径仍然
   注册 —— 这就是 `BBC_EXTERNAL_PROCESS_KILL_RISK`，是 Phase 2A 确认的
   production smoke blocker。

## 决策

按目标给定的优先级先做方案 A（upstream 安全机制），结论是**不存在**：

- 截至 2026-10-29，upstream main（`194bb78`）的 `IS_ANDROID` 分支只对
  Android 运行时（MaaFwApp）跳过 BBC 导入；Windows CLI 运行仍注册
  bbc_stop_listener（`docs/investigations/maafgo-upstream-inventory-2026-10-29.md`）。
- 没有禁用 BBC listener、native-only、per-run BBC ownership 或 Agent 注册
  feature flag 的任何正式机制。

因此采用**方案 B：OrchestratoRRR 私有分发装配上的最小、可审计、版本绑定的
deterministic transform**（不修改用户安装、不运行时 monkeypatch 未知版本）：

```
pinned MaaFgo d7f3a474 快照（SHA256 锁定）
        ↓ scripts/prepare_maafgo_cli_smoke.py（ORR 私有 assembler）
1. agent-main.pinned.py 哈希守卫（f25b3a3c…），源不匹配 => ASSEMBLY fail closed
2. agent/main.py 整文件替换为 agent-main.orr.py：
   删除 4 行 BBC import；插入 import orr_reporter（逐字节确定）
3. 删除 agent/custom/bbc_*.py 六个模块（误 import 直接失败）
4. 注入 agent/orr_reporter.py（完成证据 reporter）
5. distribution-manifest.json 记录 orr_transform 身份
        ↓
MaaFgoConfig.check_distribution() 在每次生产 PREPARE 阶段 fail-closed 校验
```

## 约束与保证

- patch 只针对 pinned revision；源 hash 不匹配即 `AGENT_MAIN_SOURCE_MISMATCH`，
  绝不 fuzzy-patch 未知版本。
- manifest 记录 `transform_id=orr-bbc-free-native-reporter`、`transform_version=1`、
  前后 sha256、被移除模块清单；`MaaFgoConfig.check_distribution()` 校验
  `maafgo_commit`、`transform_id/version`、`bbc_listener_registered=false`、
  `reporter_registered=true`。
- 指向未验证安装（无 manifest、错误 commit、错误 transform）一律
  `MAAFGO_DISTRIBUTION_UNVERIFIED` fail closed；不存在绕过开关。
- 测试覆盖：transform 逐字节可重建、BBC 模块确实不存在、native Agent import
  面（`import orr_reporter` + 全部非 BBC 注册）保持、assembler 不覆盖已有目录。
- reporter 使用与 BBC listener 相同的官方 `AgentServer.tasker_sink()` API，
  只读观察任务通知并原子写出有界 result artifact；不枚举进程、不触碰网络、
  不使用 25001/25002。

## 不做的事

- 不启动 BBC；不选择任何 BBC task；不使用 MaaFgo `关闭游戏`（游戏退出由
  OrchestratoRRR 的 STOP_FGO 以精确 ADB force-stop 完成）。
- 不因 upstream main 更新而升级 pin；升级需单独 compatibility investigation。
- 本 ADR 不宣称真机已完成验收。

REAL DEVICE ACCEPTANCE: PENDING USER
