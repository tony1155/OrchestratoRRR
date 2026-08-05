# Phase 6C1——受控 external run CLI 与完整 Fake 验收

## 验收范围

本阶段新增公开 `autogame-orch run`，但首版入口只接受固定 external MuMu 计划。入口要求精确真实执行确认和不超过 86400 秒的有限父 Deadline；用户不能选择、跳过或重排阶段。

run v1 在构造 Runner、Stage factory 或 Adapter 前强制要求：

- `mumu.lifecycle_mode = "external"`；
- `maa_sync.enabled = false`；
- `maa_update.enabled = false`；
- `aalc.attempts = 1`；
- 动态执行计划精确包含 11 个 external 阶段。

任一门禁失败均以稳定输入错误安全停止，不请求 UAC、不创建业务报告、不访问网络，也不构造 Runtime。

## 入口与权限契约

生产 composition root 复用 `WorkflowCoordinator` 和既有 Windows elevation API。计划需要管理员权限时，普通父入口在 Runner、Stage factory、日志和 Adapter 构造前请求提升；父入口等待并原样转发提升子入口退出码，不写第二份 RunReport。内部 marker 防止递归提升，UAC 取消和提升失败分别映射为退出码 9 和 10。

提升子入口根据同一原始秒数建立业务 Deadline；等待 UAC 的时间不计入子入口业务执行 Deadline。父入口与提升子入口不共享同一个内存 Deadline 对象。

## 执行与报告

生产工作流报告 mode 为 `workflow_external`，Fake Runner 默认 `workflow_fake` 保持兼容。到达的 Runtime Stage 共享同一个父 Deadline 和 CancellationToken；Runner 不增加全工作流重试，AALC Adapter 自身 attempts 契约不变。

日志只在权限满足并进入 Runner 后打开。生产 executor factory、ProductionReportSink 和安全事件 sink 均在该受控生命周期内接线；日志初始化失败时，在任何 Adapter 构造前停止。Runner 对成功、失败、超时和取消都只尝试一次 RunReport 写入。

退出码固定为：成功 0，输入/配置/门禁 2，工作流失败 3，超时 4，取消 5，报告写入失败 7，内部失败 8，UAC 取消 9，提升失败 10。

## Fake 验收

完整 Fake CLI 应用路径覆盖配置加载、external 计划、MuMu readiness、StarRail、清理后置条件、MAA、AALC 和报告写入，得到 `SUCCESS/OK`、`workflow_external` 与 11 个有序 StageReport。MuMu start、stop、restart 调用数均为零；没有执行真实程序、ADB、网络或 UAC。

专项测试还覆盖精确确认、Deadline 边界、四项 run v1 门禁、elevation 前置与递归保护、稳定退出码、SIGINT 取消与 handler 恢复、日志初始化失败、各 Runtime 失败投影、报告写入失败以及控制台、JSONL、RunReport 的递归隐私边界。

最终自动验收数字：

- Phase 6C1 `tests/run_application`：86 项；
- CLI：43 项；
- workflow：248 项，其中 production workflow 152 项；
- external MuMu 专项：90 项；
- 完整 pytest 连续两次均为 1132 项通过；
- Ruff check、Ruff format check、mypy 均通过。

## 结论

Phase 6C1 完成公开 external run v1、生产 composition root 和完整 Fake 验收。Phase 6B 的 external 支持路径已经具备受控入口；managed MuMu 生命周期控制仍延期，且不属于 external 发布路径。

本阶段没有执行真实完整工作流。Phase 6C2 必须由操作者依照手册受控执行真实 external smoke；Phase 6C3 尚未开始。Phase 6 整体尚未完成，旧 PowerShell 尚不可替换。
