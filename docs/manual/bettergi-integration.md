# BetterGI 一条龙接入

适配官方 `babalae/better-genshin-impact` **0.64.0**，不是 aquawius/BGI 分支。
实现基线为 OrchestratoRRR `19a24dba5d6ef974b0ce531e489f469c74fb092a`。

## 配置

1. 在 BetterGI GUI 中创建 `Orchestrator-Daily` 一条龙，选择至少一个任务。
2. 完成后操作设为 **关闭软件**。清除“从指定任务开始”的标记，保存后关闭 BetterGI。
3. 将示例配置中的 `[bettergi]` 段复制到实际使用的 TOML，再设 `enabled = true`。

```toml
[bettergi]
enabled = true
executable = 'E:\Program Files\Games\Autogame\BetterGI\BetterGI.exe'
working_directory = 'E:\Program Files\Games\Autogame\BetterGI'
mode = "one_dragon"
config_name = "Orchestrator-Daily"
timeout_seconds = 7200
stop_timeout_seconds = 15
```

省略该段或 `enabled = false` 时，旧流程与路径要求保持不变，不创建 BetterGI Runtime。
目前仅支持 `one_dragon`，参数由 Adapter 生成，不接受任意 arguments。
业务 JSON 仍由 BetterGI GUI 管理；编排器只读检查
`User/OneDragon/Orchestrator-Daily.json`，不复制、转换或覆盖它。

启用后 managed 模式顺序为 `RUN_MAA → SHUTDOWN_MUMU → RUN_BETTERGI → WRITE_RUN_REPORT`。
external 模式在 MAA 后执行 BetterGI，不操作外部 MuMu 生命周期。
该阶段要求管理员权限，复用现有工作流提升机制。
总 Deadline 应覆盖原流程和 BetterGI 的累计耗时；阶段超时不会重置总预算。

## 完成与清理契约

- 启动前用 Windows 进程快照拒绝已有 `BetterGI.exe`，枚举失败也拒绝启动，不接管已有实例。
- 直接受管启动 `BetterGI.exe startOneDragon Orchestrator-Daily`。
- 启动前记录日志文件偏移，只读取后续增量；支持跨日新文件和分块 UTF-8。
- 只接受本次 PID、近期启动时间和一致 Primary 实例标识的日志。
- `OneDragonFlowViewModel` 必须确认指定配置，随后输出整体完成事件。
- 错误级别、已知配置组异常或任务中断都会阻止成功；取消有独立结果。
- 必须正常退出且退出码为 0。提前退出或实例转发后退出，没有执行证据时返回
  `COMPLETION_UNCONFIRMED`。日志截断、替换、超限等返回 `LOG_CONTRACT_FAILED`。
- 所有已启动路径都清理本次 Job，并在关闭句柄前查询其活动进程数，确认归零。
  清理拥有独立的有限预算，不使用已取消的 token。失败时保留原始错误，另报
  `owned_process_cleaned = false`；原本成功但清理失败会改为 `CLEANUP_FAILED`。
- 标准输出和标准错误不作为业务证据，不保存在 RunReport；报告只投影错误码、
  退出码、配置/完成证据与清理状态，不写原始日志、PID 或配置名称。

这里的成功是 **0.64.0 日志契约下的执行完成**，不是游戏奖励到账的证明。
普通 `NormalEndException` 也可能表示可接受的结束；v1 对其“任务中断”日志保守判失败。
其他版本、其他界面语言和未知异常路径需重新核对契约，不能仅靠退出码兼容。
本轮没有真实启动 BetterGI 或原神，也没有修改本机生产 TOML 或更新已安装的编排器。

原神可能经独立启动器启动，或在任务开始前已存在；**只有进入本次 Job 的进程才属于清理范围**。
不会按名字结束游戏、启动器或其他已有进程。真实 smoke 必须检查游戏归属与残留，
不能把 `owned_process_cleaned` 理解成整台电脑上没有原神进程。

## 无业务副作用验证

```powershell
.\.venv\Scripts\python.exe -m autogame_orchestrator validate --config config\orchestrator.local.toml --check-paths
.\.venv\Scripts\python.exe -m autogame_orchestrator plan --config config\orchestrator.local.toml
.\.venv\Scripts\python.exe -m pytest tests/runtime/test_bettergi_runtime.py tests/config/test_bettergi_config.py tests/workflow/production/test_bettergi_stage.py -q
```

Fake 程序由 Python 启动，只写合成日志。测试覆盖提前退出、其他实例、旧日志、跨日、
错误配置、内部异常后正常退出、取消、超时、清理失败、子进程回收和工作流报告 schema。

真实验收另行进行：先单独验证一条龙自动执行和退出，再检查配置名错误、内部失败、
取消与超时后的 BetterGI/游戏残留，最后跑完整流程。正式 run 仍使用既有真实执行确认入口。

## 上游证据

2026-09-07 本地验证：定向测试 56 passed；完整 pytest 1568 passed、1 skipped；
Ruff lint、strict mypy（77 个源文件）和本次修改的 Python 文件格式检查通过。
Windows 实例探针已作只读验证；没有执行真实游戏 smoke。

- [命令行解析](https://github.com/babalae/better-genshin-impact/blob/0.64.0/BetterGenshinImpact/Helpers/CommandLineOptions.cs)
- [一条龙选择、运行与完成动作](https://github.com/babalae/better-genshin-impact/blob/0.64.0/BetterGenshinImpact/ViewModel/Pages/OneDragonFlowViewModel.cs)
- [实例日志格式](https://github.com/babalae/better-genshin-impact/blob/0.64.0/BetterGenshinImpact/App.xaml.cs)
- [异常与取消处理](https://github.com/babalae/better-genshin-impact/blob/0.64.0/BetterGenshinImpact/GameTask/TaskRunner.cs)
