# Phase 5 AALC smoke 手册

执行前必须先遵循 [Adapter 真实 smoke 统一门禁](adapter-real-smoke-gate.md)。首次 AALC smoke 强制使用 `attempts=1`，不得启用重试。

若 AALC 需要管理员权限，在本地 `[aalc]` 设置 `requires_administrator = true`。普通权限入口会在 AALCAdapter 构造前提升整个 OrchestratoRRR；用户取消 UAC 时任务安全停止。禁止绕过入口而用 `runas` 单独启动 AALC，因为那会破坏现有 Job Object、输出捕获、超时、取消和清理契约。

真实 AALC smoke 的首次验收已于 2026-07-30 完成；后续复验仍必须由用户明确批准，并使用正式 `load_config()` 和 `AALCAdapter`，以父 Deadline 执行单次受控验证。实施代理不得自行执行真实 AALC。

成功只依据进程正常退出且 exit code 为 0，不解析 stdout、stderr 或日志关键词。最多三次尝试，只有非零退出和单次尝试超时允许重试；cleanup failure、取消、路径、配置和启动失败不重试。

本阶段未实现完整工作流或公开 run CLI，未替换旧 PowerShell，也未执行真实 MAA、StarRailCopilot、MuMu 或 ADB。
最终脱敏证据见 [Adapter 真实 smoke 最终验收](../acceptance/adapter-real-smoke.md)。AALC 使用无限工作负载，验收中的 `completed` 表示操作者确认运行正常后优雅关闭、进程正常退出和生命周期管理成功，不表示无限业务自动完成。
