# Phase 6B2B3B——外部管理 MuMu 生命周期模式

## 验收范围

本阶段提供 `external` 生命周期模式：用户或外部工具必须提前启动正确的 MuMu 实例，OrchestratoRRR 只通过既有只读 `status()` Port 验证 ADB readiness。本阶段没有实现或执行 MuMu start、stop、restart、实例创建、实例选择、NemuShell RPC 或 `.nemu` 文件读取。

`managed` 仍是默认模式，因此既有配置、静态 `planning.build_plan()` 和公开 `plan` 命令继续保留完整 15 阶段。managed 生产 start/stop 仍未授权。

## 配置契约

`mumu.lifecycle_mode` 只接受严格小写枚举 `managed` 或 `external`。默认值为 `managed`。

external 模式允许 `executable` 为空，但仍要求 `adb_executable` 和 `adb_serial`；`start_arguments` 与 `stop_arguments` 必须为空，防止借 external 模式夹带生命周期控制命令。路径检查只检查 ADB executable，不检查 MuMu GUI 或管理程序。

示例：

```toml
[mumu]
lifecycle_mode = "external"
executable = ""
adb_executable = "<ADB_EXECUTABLE>"
adb_serial = "127.0.0.1:<PORT>"
start_timeout_seconds = 120
stop_timeout_seconds = 20
start_arguments = []
stop_arguments = []
```

## 执行计划

external 默认执行计划包含 11 个阶段：

```text
VALIDATE_CONFIG
SYNC_MAA_CONFIG
UPDATE_MAA
ENSURE_MUMU_RUNNING
WAIT_MUMU_ADB_READY
RUN_STARRAIL
STOP_STARRAIL
VERIFY_STARRAIL_STOPPED
RUN_MAA
RUN_AALC
WRITE_RUN_REPORT
```

只移除 `STOP_MUMU`、`VERIFY_MUMU_STOPPED`、`START_MUMU` 和 `WAIT_MUMU_ADB_READY_AFTER_RESTART`。初始 `ENSURE_MUMU_RUNNING` 与 `WAIT_MUMU_ADB_READY` 必须保留。调用方显式提供 stages 时不做静默删减，仍由 ExecutionPlan 执行结构校验。

## readiness 与失败语义

external 的 `ENSURE_MUMU_RUNNING` 只调用一次 `status()`。READY 成功；STOPPED 以 `WORKFLOW_STAGE_BLOCKED` 和固定 blocker `mumu_external_not_ready` 停止，OrchestratoRRR 不尝试修复；NOT_READY、TIMEOUT、CANCELLED 与 FAILED 保持既有安全映射并触发 fail-fast。

`WAIT_MUMU_ADB_READY` 继续只调用一次 `status()`，原样传递同一个父 Deadline 和 CancellationToken，不新增 sleep 循环、ADB reconnect 或设备选择回退。

## 完整 Fake 验收

完整生产绑定 Fake 流程覆盖：配置验证成功、MAA Sync/Update 默认关闭、MuMu READY、StarRail 完成且受管进程已清理、MAA 完成、AALC 完成以及 RunReport 写入成功。结果为 `SUCCESS/OK`，11 个 StageReport 顺序与 external ExecutionPlan 完全一致，MAA 和 AALC 均可到达。

Fake 证据确认 MuMu status 被调用，start、stop、restart 调用数均为 0；没有进程扫描、实例号、RPC instance、设备地址或 `.nemu` 内容进入 StageReport/RunReport。工作流没有外层重试，AALC Adapter 自身 attempts 语义不变。

## 权限与生产边界

external readiness 不新增 MuMu 管理员权限要求。入口权限规划仍只综合 AALC、启用的 MAA Sync 与启用的 MAA Update，并继续在 Runner 和 Stage factory 前完成。

NemuShell 的只读帮助证据只证明 RPC/Shell 调用形状，不是生命周期管理入口。external 是当前唯一安全支持的 MuMu 工作流路径，但不等价于旧 PowerShell 的完整生命周期行为。

## 结论

Phase 6B2B3B 的 external 支持路径已准备完成；未执行真实 MuMu、ADB 或完整工作流。Phase 6B2B3C managed 实例化生命周期控制继续阻断且未获授权。公开 run CLI 尚未实现，Phase 6 整体尚未完成。
