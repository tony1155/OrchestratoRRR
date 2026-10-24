# FGO（Mash）链路设计

> 状态：已实现，Fake 级测试验收（2026-10-24）。真实设备联调未做——验收步骤见 [docs/fgo-acceptance-guide.md](fgo-acceptance-guide.md)。
> 前置阅读：集成仓库 `mash-integration/docs/02-mash-cli-spec.md`（mash-cli 契约）。

## 定位

Mash（[ZaiZheTingDun/mash-app](https://github.com/ZaiZheTingDun/mash-app)，MIT，FGO 自动化）
通过与 MAA / AALC 平级的第四个外部 Runtime 接入：`MashAdapter` 实现 `MashRunPort`。
它不是 MAA Adapter 的一种，也不拥有 MuMu 生命周期。

生命周期分工（延续既有边界）：

| 职责 | 归属 |
|---|---|
| MuMu 启停 / ADB reconnect / readiness | OrchestratoRRR（managed 或 external，不变） |
| ADB 设备身份 | OrchestratoRRR 验证后经 `--device` 传入（`mash.adb_serial`；留空则用 Mash GUI 持久化选择） |
| FGO 战斗执行 | mash-cli（headless 子进程） |
| 结果裁决 | OrchestratoRRR（退出码 + run-result JSON 投影进 StageReport） |

## 生产计划

`game = "fgo"` 时 `build_execution_plan` 选用 FGO 计划；external 过滤照常生效
（移除 SHUTDOWN_MUMU）。

```
managed（6 阶段）                      external（5 阶段）
VALIDATE_CONFIG                        VALIDATE_CONFIG
ENSURE_MUMU_RUNNING                    ENSURE_MUMU_RUNNING
WAIT_MUMU_ADB_READY                    WAIT_MUMU_ADB_READY
RUN_MASH                               RUN_MASH
SHUTDOWN_MUMU                          WRITE_RUN_REPORT
WRITE_RUN_REPORT
```

`validate_external_plan` 的白名单相应扩展为四个计划元组。StarRail 链路
（16/11 阶段）完全不动；`game` 缺省即 `"starrail"`，旧配置零影响。

## RUN_MASH 阶段语义

`MashAdapter`（`runtime/mash.py`）驱动一次 `mash-cli run`：

- 参数由 `MashConfig` 构造（project/server/result-file/events/device/repeat/extra）；
  `resource_dir` 注入 `MASH_RESOURCE_DIR`（显式 environment 覆盖优先）。
- 退出码契约映射：`0→COMPLETED`，`1→FAILED`，`2→CANCELLED`，`3→TIMEOUT`。
- **取消/超时先优雅后硬终止**：触发 `mash-cli cancel --wait <stop_timeout_seconds>`
  （文件信号，目标进程自行按契约退出码 2 结束），宽限耗尽才由
  `ProcessSupervisor.stop` 终止 Job，并标记 `GRACEFUL_STOP_FAILED`。
- run-result JSON 的稳定字段（`outcome/message/completedRuns/runId`）进入
  StageReport 诊断（投影层改名 `mash_*`，不透传本机路径）。

## 配置

见 `config/orchestrator.example.toml` 的 `game` 键与 `[mash]` 段。要点：

- `game = "fgo"` 时 `[mash]` 必填；`starrail/maa/maa_sync/maa_resource_merge`
  段不参与 validate/check_paths（反之 `game = "starrail"` 忽略 `[mash]`）。
- `launcher_arguments`：前置解释器参数，标准部署（executable 直接指向
  mash-cli.exe）留空；包装/测试部署使用。

## 前置条件（真实部署）

1. 安装 Mash GUI 并至少运行一次：下载 CV runtime、配置 FGO 项目
   （数据位于 `%APPDATA%/com.xiaotongx.mash`，CLI 与 GUI 共享）。
2. `mash-cli validate --project <id> --json` 全绿。
3. mash-cli.exe 可与 Mash GUI 同目录部署（资源解析自动生效），
   异地部署时设置 `mash.resource_dir`。

## 边界与不做

- FGO 与 StarRail 不并发（共享 MuMu；由调用侧串行编排）。
- 不在 OrchestratoRRR 内解析 Mash 内部 RunnerState——只认 mash-cli 的
  退出码与 result JSON 契约。
- AALC 兼容段保留原样，不借本次改动恢复。
