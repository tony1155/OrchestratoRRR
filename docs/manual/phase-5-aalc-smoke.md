# Phase 5 AALC smoke 手册

执行前必须先遵循 [Adapter 真实 smoke 统一门禁](adapter-real-smoke-gate.md)。首次 AALC smoke 强制使用 `attempts=1`，不得启用重试。

若 AALC 需要管理员权限，在本地 `[aalc]` 设置 `requires_administrator = true`。普通权限入口会在 AALCAdapter 构造前提升整个 OrchestratoRRR；用户取消 UAC 时任务安全停止。禁止绕过入口而用 `runas` 单独启动 AALC，因为那会破坏现有 Job Object、输出捕获、超时、取消和清理契约。

真实 AALC smoke 必须等待用户批准。批准后使用正式 `load_config()` 和 `AALCAdapter`，以父 Deadline 执行单次受控验证；实施代理不得执行真实 AALC。

成功只依据进程正常退出且 exit code 为 0，不解析 stdout、stderr 或日志关键词。最多三次尝试，只有非零退出和单次尝试超时允许重试；cleanup failure、取消、路径、配置和启动失败不重试。

本阶段未实现完整工作流或公开 run CLI，未替换旧 PowerShell，也未执行真实 MAA、StarRailCopilot、MuMu 或 ADB。
当前没有最终成功 JSON，本文不声明真实 AALC smoke 已通过。
