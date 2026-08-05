# Phase 6B2B1——安全 MAA 配置同步验收

## 范围

本阶段只实现默认关闭的 `SYNC_MAA_CONFIG`。它包含冻结配置、GUI JSON 白名单转换、有界读取、双输出预验证、同目录临时文件、flush/fsync、单文件原子替换、原子备份和第二个目标失败时的首目标回滚。

未实现 MAA 更新、MuMu start/stop/restart 或实例选择，也未增加公开 run CLI。本阶段没有读取真实源配置、写入真实目标、执行旧脚本、真实程序、网络或 UAC。

## 配置与转换边界

`[maa_sync]` 默认 `enabled=false`，因此现有配置保持兼容，路径可为空，且生产 Stage 不构造同步器。启用时要求四个非空且互不冲突的规范化路径、严格布尔值和拒绝 bool 的正整数大小上限。

转换器是纯函数，只支持旧静态契约确认的 `StartUp`、`Recruit`、`Infrast`、`Mall`、`Fight`、`Award` 字段。未知字段不会透传；禁用的未知任务跳过，启用的未知任务失败。测试数据全部人工构造，不含调查机器配置。

## 写入与恢复

同步器先完成两个源的有界读取、解析、转换、确定化 JSON 编码和两个目标原始快照，随后才创建目标父目录与临时文件。临时文件位于各自目标目录，使用不可预测名称，写入后 flush/fsync，最终通过 `os.replace()` 提交。

目标原有内容按大小上限读入内存。启用备份且目标存在时，固定 `.bak` 也通过临时文件、flush/fsync 和原子替换写入。若两个目标都已与期望 bytes 一致，则 `changed=false`，不重写、不备份。

第二个目标替换失败、取消或父 Deadline 到期时，已替换的首目标通过新临时文件原子恢复；首目标原本不存在时删除新文件。回滚失败使用独立 `ROLLBACK_FAILED`，不会声称同步成功。临时文件始终在 finally 清理，工作流外层不重试。

## 工作流与隐私

`SYNC_MAA_CONFIG` 关闭时直接返回 `SUCCESS/OK`；启用时惰性构造同步器，并原样传递父 Deadline 与 CancellationToken。StageReport 只投影稳定错误码和布尔状态，不包含源/目标路径、配置值、异常文本、临时文件名或备份路径。

默认完整生产计划现在安全通过关闭的同步阶段，并在 `UPDATE_MAA` 返回 `WORKFLOW_STAGE_BLOCKED`。阻断前不会构造 StarRail、MAA、AALC 或 MuMu Runtime，也不访问网络。

## 自动验证

- MAA Sync 专项：92 项；
- Phase 6A 核心：75 项；
- production workflow：119 项。

最终完整回归、静态检查与隐私扫描以本阶段执行回执记录为准。

## 结论

Phase 6B2B1 安全 MAA 配置同步完成。MAA Sync 默认关闭；本阶段未执行真实配置同步。

MAA 更新仍在 6B2B2 阻断，MuMu start/stop/实例控制仍在 6B2B3 阻断。公开 run CLI 和真实完整工作流尚未实现；Phase 6B2 与 Phase 6 整体均未完成。
