# Phase 6A 验收记录

## 验收范围

本阶段只验收工作流计划模型、执行契约、Fake Stage 编排、失败/取消/父 Deadline 传播、RunReport v1 聚合与写入边界，以及入口自提权的前置决策契约。没有绑定或执行任何真实 Adapter、MuMu、ADB、业务程序或 UAC。

## 已完成契约

- 默认十五阶段顺序与既有 `planning.build_plan()` 完全一致；冻结计划拒绝空计划、重复阶段、错误首尾和非严格 bool。
- 所有 Stage 共享同一 `run_id`、`CancellationToken` 和父 `Deadline`，预算不会被重置或延长。
- StageExecutor 通过工厂惰性构造；失败后的执行器、普通父入口请求重启时的 Runner 和执行器均不会构造。
- 首次失败、超时、取消、非法报告、缺失绑定或异常触发 fail-fast，剩余业务阶段统一记录 `SKIPPED`。
- `WRITE_RUN_REPORT` 由 Runner 内部最终化，不请求 Stage 工厂；报告 sink 在所有结果路径上只尝试一次。
- 写入失败时内存结果使用 `RUN_REPORT_WRITE_ERROR`，并仅通过稳定 `source_error_code` 保留先前业务错误。
- elevation 计划判定先于 Runner；测试使用 Fake gateway，覆盖无需提升、已提升、请求重启、取消、失败、退出码转发和 marker 防递归。
- WorkflowRunner 没有全工作流重试；AALCAdapter 已有的有限 attempts 未修改。

## 自动验证

Phase 6A 工作流专项：`75 passed`。

完整回归连续两次通过：第一次 `598 passed`，第二次 `598 passed`。

## 隐私与架构

递归测试覆盖 RunReport JSON 投影、Stage diagnostics、顶层 diagnostics、事件字段和异常投影。工作流核心不导入具体 Adapter、`ProcessSupervisor`、ADB 客户端或 Win32 API，也不包含进程启动原语。

## 未完成边界

- Phase 6B 生产 Stage 投影和真实组件绑定尚未完成；
- MuMu 真实停启门禁仍存在；
- MAA 配置同步和更新尚未实现；
- Phase 6C 公开 run CLI、完整 Fake 验收和受控真实工作流 smoke 尚未实现；
- 未执行任何真实完整工作流，旧 PowerShell 尚不可替换；
- Phase 6 整体尚未完成。

## 建议结论

Phase 6A 工作流契约与 Fake 编排内核完成，可在保持上述门禁的前提下进入 Phase 6B。不得据此声明完整工作流可用于生产。
