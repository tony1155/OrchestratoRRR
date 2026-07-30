# Adapter 真实 smoke 最终验收

## 1. 验收范围

本记录固化 StarRail、MAA、AALC 三个 Runtime Adapter 的受控真实 smoke 脱敏证据。验收覆盖真实启动、状态判定、退出语义、进程所有权与清理；AALC 还覆盖普通权限入口自提权、单次 UAC、提升后运行及退出码转发。本记录不包含 Phase 6 完整工作流实现。

## 2. 执行信息

- 执行日期：2026-07-30
- 执行分支：`validation/adapter-real-smoke`
- 验收基线：`32f041d526549e466d5628ff5079336c16f2dda4`

## 3. StarRail 脱敏结果

```text
adapter=starrail
status=completed
error_code=OK
completion_mode=log_success
duration_seconds=358.344
matched_keyword=No task pending
log_path_present=true
owned_process_cleaned=true
cancel_requested=false
diagnostics_exit=0
stdout_truncated=true
```

成功条件来自增量日志关键词。输出摘要发生截断不影响本次验收。

## 4. MAA 脱敏结果

```text
adapter=maa
status=completed
error_code=OK
completion_mode=normal_exit
duration_seconds=934.407
exit_code=0
owned_process_cleaned=true
cancel_requested=false
diagnostics_exit=0
```

MAA 仅以进程正常退出且退出码为 0 判定成功，不解析输出关键词。

## 5. AALC 脱敏结果

```text
adapter=aalc
status=completed
error_code=OK
completion_mode=normal_exit
duration_seconds=134.218
configured_attempts=1
attempts_started=1
successful_attempt_number=1
exit_code=0
elevation_required=true
process_elevated=true
owned_process_cleaned=true
cancel_requested=false
diagnostics_exit=0
```

### 无限工作负载与人工关闭语义

AALC 配置的是无限刷本，不存在自然的业务完成终点。操作者确认无限工作负载实际运行正常后，对 AALC 执行优雅关闭。本次结果中的 `completed` 表示进程正常退出、退出码转发和生命周期管理成功，不表示 AALC 自动完成了无限任务，也不作任何业务完成声明。

人工观察事实：初始入口没有管理员权限；普通权限入口只请求一次 UAC；未观察到递归 UAC；无限工作负载运行行为正常；终止触发为操作者优雅关闭；业务自然完成不适用于本场景。

### 自提权验证

修复前，普通权限且未声明管理员要求时得到 `PROCESS_START_FAILED`；管理员权限直接运行时 AALC 可以启动。配置管理员要求并完成入口 bootstrap 后，普通权限入口自动请求一次 UAC，提升整个 OrchestratoRRR，再由既有 ProcessSupervisor 和 Job Object 链路运行 AALC。本次验收覆盖自提权、真实运行、提升后退出码转发和进程清理。

## 6. 进程所有权与清理

三个 Adapter 的 `owned_process_cleaned` 均为 `true`。未发现需要写入验收记录的残留受管进程证据。AALC 的普通父入口不直接启动业务进程，提升后的入口负责完整 Adapter 生命周期。

## 7. 已知限制

- 本验收是三个单 Adapter 的真实 smoke，不是 Phase 6 多阶段完整工作流；
- AALC 使用无限工作负载，终止条件是人工确认运行正常后的优雅关闭；
- StarRail 输出摘要发生截断，但成功判定来自增量日志关键词；
- 本记录只固化脱敏摘要，原始结果和本机配置不进入版本库。

## 8. 隐私说明

本文不记录真实绝对路径、用户名、PID、设备序列、设备身份信息、配置内容、完整命令行、stdout/stderr 原文、本机环境变量或原始 JSON。仅保留 Adapter 名称、耗时、状态、错误码、允许的退出码与关键词，以及清理和提权布尔证据。

## 9. 最终放行结论

StarRail、MAA、AALC 的受控真实 Adapter smoke 均已通过。

AALC 使用无限工作负载，因此验收的终止条件是：操作者确认实际运行正常后执行优雅关闭，而不是等待业务自然完成。

Adapter 真实 smoke 门禁关闭。允许进入 Phase 6 完整工作流实施。Phase 6 尚未在本提交中实现。
