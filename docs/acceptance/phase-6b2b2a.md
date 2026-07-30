# Phase 6B2B2A——安全 MaaCore/资源更新验收

## 范围

本阶段只实现 `maa update` 对应的 MaaCore/资源更新生产 Stage。它默认关闭，并要求 `enabled=true` 与 `allow_network=true` 双重显式授权。实现未运行真实 MAA、真实网络、旧脚本或 UAC。

不支持 `maa self update`、`hot-update`、安装命令或任务命令。`maa self update` 属于 CLI 安装生命周期；由包管理器安装的 CLI 应继续由包管理器负责，OrchestratoRRR 当前不接管自替换。旧流程中的 hot-update 没有当前正式上游命令证据，因此继续阻断。

## 配置与命令边界

`[maa_update]` 默认 `enabled=false`、`allow_network=false`、`requires_administrator=false`，参数固定以严格小写 `update` 开头。参数数量、单项长度、空值、控制字符和禁止命令均有界校验。配置不允许独立 executable 或 working directory，也不提供自更新或 hot-update 开关。

启用更新时，通过冻结配置投影复用现有 `[maa]` 的 executable、working directory、环境覆盖和 stop timeout，只替换 update 参数与更新 timeout。生产 composition root 惰性构造既有 `MAAAdapter`；仍由原有 ProcessSupervisor、Job Object、退出码、父 Deadline、取消和清理契约负责生命周期，Stage 外层没有重试。

## Stage 投影与隐私

关闭时 `UPDATE_MAA` 返回 `SUCCESS/OK` 与 `executed=false`，不构造更新 Port，也不访问网络。启用时原样传递同一个 Deadline 和 CancellationToken，并按既有 `MAARunStatus` 映射成功、失败、超时与取消。

StageReport 只保留 enabled/executed、稳定源错误码、终止原因、退出码、清理结果和输出截断布尔值。PID、输出原文、完整参数、路径、环境值、下载地址和原始 Runtime diagnostics 均不透传。

## 权限与工作流

完整计划在 Runner 和所有 Stage factory 构造前综合 AALC、启用的 MAA Sync 和启用的 MAA Update 管理员要求；任一阶段声明需要管理员权限时，入口先执行统一提升决策。Stage 执行过程中不会临时提权。

默认关闭的更新阶段现在安全跳过。下一门禁取决于 MuMu 只读状态：STOPPED 时 `ENSURE_MUMU_RUNNING` 使用 `mumu_start_not_approved` 阻断；READY 时流程继续，但 `STOP_MUMU` 仍是无条件禁止的控制 Stage。

## 自动验证

- MAA Update 专项：95 项；
- MAA Sync 专项：92 项；
- Phase 6A 核心：75 项；
- production workflow：131 项。

完整回归、静态边界和隐私扫描以本阶段执行回执为准。

## 结论

Phase 6B2B2A 安全 MaaCore/资源更新完成。真实更新与真实网络均未执行。

6B2B2B 的 maa-cli 自更新决策继续阻断；6B2B3 的 MuMu start/stop/实例控制继续阻断。公开 run CLI 与真实完整工作流尚未实现，Phase 6B2、Phase 6B 和 Phase 6 整体均未完成。
