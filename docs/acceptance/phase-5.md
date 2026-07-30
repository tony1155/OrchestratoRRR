# Phase 5——AALC Runtime Adapter 验收

> 后续状态（2026-07-30）：本文保留 Phase 5 当时的验收记录；真实 AALC smoke 已在 [最终验收记录](adapter-real-smoke.md) 中完成脱敏验收。AALC 无限工作负载由操作者确认运行正常后优雅关闭，不声明业务自然完成。

建议状态：附注接受——Fake 环境完成，
真实 AALC smoke 待用户批准。

## 自动验证记录

- AALC 配置专项：28 项通过。
- AALC runtime 专项：38 项通过。
- 完整 pytest 第一次：440 项通过。
- 完整 pytest 第二次：440 项通过。
- cancellation 压力：10/10 通过。
- retry success 压力：10/10 通过。
- child cleanup 压力：15/15 通过。

## 行为证据

- 单次成功只启动一次尝试；首次失败后第二次成功保留两次结果。
- 非零退出与单次尝试超时允许有界重试；parent deadline、取消、启动失败与 cleanup failure 不重试。
- 每次重试使用独立 PID、临时目录、ProcessSupervisor 和 Job Object 生命周期。
- 成功、重试前清理、超时和取消场景均确认受管父进程与 child 已退出。
- 结果序列化不包含临时路径、配置路径、状态/PID 文件路径或环境敏感值。

本阶段未执行真实 AALC、MAA、StarRailCopilot、MuMu 或 ADB，未实现完整工作流或公开 run CLI，未替换旧 PowerShell。
