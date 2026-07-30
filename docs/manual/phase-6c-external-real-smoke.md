# Phase 6C2——external 真实工作流 smoke 手册

本手册只供操作者在 Phase 6C2 明确批准后执行。实施代理不得在 Phase 6C1 运行真实程序、ADB、网络或 UAC。

## 前置门禁

执行前必须人工确认：

- 工作树干净，并记录当前分支和提交 SHA；
- 真实配置位于 Git 仓库外；
- `mumu.lifecycle_mode = "external"`；
- `maa_sync.enabled = false`；
- `maa_update.enabled = false`；
- `aalc.attempts = 1`；
- 正确的 MuMu 实例已由用户或外部工具启动；
- 目标 ADB device 已 ready；
- 选择有限且不超过 86400 秒的 Deadline；
- 使用精确确认值 `I_UNDERSTAND_THIS_RUNS_REAL_PROGRAMS`。

不要把真实配置、路径、设备地址、端口、PID、完整命令、输出、原始 JSONL 或原始 RunReport 提交到仓库。

## 受控调用形状

从仓库的受控 Python 环境调用：

```text
autogame-orch run
  --config <REPOSITORY_EXTERNAL_TOML>
  --deadline-seconds <FINITE_POSITIVE_SECONDS>
  --confirm-real-execution I_UNDERSTAND_THIS_RUNS_REAL_PROGRAMS
```

不得添加阶段选择、跳过、强制运行或忽略错误参数。run v1 不接受这些参数。

若完整计划需要管理员权限，普通父入口会在 Runner 和任何 Adapter 构造前请求一次入口级提升。UAC 等待时间不计入提升子入口重新建立的业务 Deadline；当前不承诺在普通父入口等待 UAC 时跨进程转发 Ctrl+C。

## 预期阶段顺序

```text
配置验证
MAA 配置同步安全跳过
MAA 更新安全跳过
MuMu readiness
StarRail
StarRail 清理验证
MAA
AALC
报告写入
```

external 模式不会停止、启动或重启 MuMu，也不会尝试修复未 ready 状态。MuMu 必须在业务阶段开始前由外部正确管理。

## AALC 终止语义

AALC 可能使用无限工作负载，不存在自然业务完成终点。验收时应先观察 AALC 正常运行，再由操作者从 AALC 自身界面优雅关闭。AALC 进程 exit 0 表示进程生命周期正常结束和清理成功，不表示无限业务自然完成。

必须区分：

- `operator_graceful_close`：操作者确认运行正常后从 AALC 界面优雅关闭；
- `cancellation`：通过 Ctrl+C 请求取消，不属于正常业务完成；
- `deadline_timeout`：父 Deadline 到期；
- `process_failure`：进程或 Stage 失败。

## 脱敏证据

只记录 Adapter/Stage 名称、稳定状态、稳定错误码、耗时、退出码以及清理、提升、取消等布尔结果。不得记录真实路径、ADB serial 或端口、PID、配置内容、完整命令、stdout/stderr、原始 JSONL 或原始 RunReport。

真实 smoke 只有在操作者完成执行、核验脱敏证据并单独批准后才能关闭 Phase 6C2。Phase 6C1 的 Fake 结果不能替代该证据。
