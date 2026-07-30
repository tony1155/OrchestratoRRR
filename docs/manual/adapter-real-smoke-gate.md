# Adapter 真实 smoke 统一门禁

本手册只能由用户在明确批准后手工执行。实施代理不得执行任何真实 StarRailCopilot、MAA、AALC、MuMu 或 ADB。

## AALC 管理员权限门禁

当本地 `[aalc]` 配置设置 `requires_administrator = true` 时，普通权限入口会在构造 `AALCAdapter` 前请求一次 UAC。用户拒绝 UAC 时安全停止并返回 `ELEVATION_CANCELLED`，不会创建成功 JSON。工具提升的是整个 OrchestratoRRR/Python 入口，不会使用 `runas` 单独启动 AALC；提升后的入口仍通过现有 ProcessSupervisor、CreateProcessW 和 Job Object 管理 AALC。

首次真实 smoke 前应确认本地配置已按实际权限要求设置该字段。当前没有可接受的真实 AALC 成功 JSON，因此不得把管理员窗口能够打开程序视作 smoke 已通过。

## 强制顺序

1. 单独执行 StarRailCopilot smoke；
2. 单独执行 MAA smoke；
3. 单独执行 AALC 单次尝试 smoke，首次不得使用 `--allow-aalc-retries`；
4. 人工审查三个 JSON 结果和任务管理器中的进程清理情况；
5. 只有三个结果均获人工接受后，才允许进入 Phase 6。

每次执行前，用户必须关闭同类旧实例、核对不提交的 `config/orchestrator.local.toml`、确认即将启动真实程序、设置有限正数 deadline，并准备使用 Ctrl+C 请求取消。执行后须通过任务管理器确认无残留受管进程，检查 JSON 中 `owned_process_cleaned`，且不得提交本地配置或 `smoke-results/`。

## 命令模板

```powershell
$Confirm = 'I_UNDERSTAND_THIS_LAUNCHES_A_REAL_PROGRAM'

python -m autogame_orchestrator.diagnostics.adapter_smoke `
  --adapter starrail `
  --config config/orchestrator.local.toml `
  --deadline-seconds 600 `
  --output smoke-results/starrail.json `
  --confirm-real-execution $Confirm
```

将 `--adapter` 和输出文件依次替换为 `maa`、`aalc`。首次 AALC smoke 强制使用配置副本 `attempts=1`，不得添加重试许可参数。该工具一次只构造一个 Adapter，不会启动、停止或重启 MuMu，也不会执行 ADB。

判定保持 Adapter 原有语义：StarRailCopilot 依据增量日志关键词；MAA 仅以 exit 0 成功；AALC 仅以 exit 0 成功且首次仅一次尝试。JSON 不记录配置路径、可执行文件路径、工作目录、环境值、stdout/stderr 原文或 PID 数值。

当前仅完成门禁工具和 Fake/替身自动测试，尚无三个 Adapter 均通过的最终验收证据，也未批准 Phase 6。
当前仍未批准 Phase 6；管理员权限 bootstrap 不等于完整工作流。
