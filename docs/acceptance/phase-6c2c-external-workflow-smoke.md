# Phase 6C2C——external 完整真实工作流验收

## 基线与执行范围

- 分支：`phase/6-complete-workflow`
- 批准基线提交：`3a63f949ccc7effc42e09252633e4a39c4a94f2c`
- 模式：`workflow_external`
- 完整 workflow 执行次数：`1`
- 运行退出码：`0`
- 脱敏耗时：`1655` 秒

本次使用仓库外已批准的 external smoke 配置，通过公开 `run` CLI 进入生产工作流。
没有修改仓库、配置或文档，没有自动重试，也没有执行第二次 workflow。

## 执行计划与 RunReport

执行计划精确包含 11 个阶段，顺序保持不变：

1. `VALIDATE_CONFIG`
2. `SYNC_MAA_CONFIG`
3. `UPDATE_MAA`
4. `ENSURE_MUMU_RUNNING`
5. `WAIT_MUMU_ADB_READY`
6. `RUN_STARRAIL`
7. `STOP_STARRAIL`
8. `VERIFY_STARRAIL_STOPPED`
9. `RUN_MAA`
10. `RUN_AALC`
11. `WRITE_RUN_REPORT`

RunReport 脱敏结果：

```text
report_found=true
report_schema_version=1
report_mode=workflow_external
report_status=success
report_error_code=OK
report_stage_count=11
report_stage_order_matches=true
```

全部阶段均为 `success/OK`：

```text
VALIDATE_CONFIG=success/OK
SYNC_MAA_CONFIG=success/OK
UPDATE_MAA=success/OK
ENSURE_MUMU_RUNNING=success/OK
WAIT_MUMU_ADB_READY=success/OK
RUN_STARRAIL=success/OK
STOP_STARRAIL=success/OK
VERIFY_STARRAIL_STOPPED=success/OK
RUN_MAA=success/OK
RUN_AALC=success/OK
WRITE_RUN_REPORT=success/OK
```

MAA Sync 和 Update 均安全关闭：

```text
maa_sync_executed=false
maa_sync_changed=false
maa_update_executed=false
```

## MuMu readiness 与业务阶段

Phase 6C2B4C 建立的连接在本次 workflow 开始时仍为 ready，因此 ENSURE 没有再次
connect：

```text
ensure_adb_connect_attempted=false
ensure_adb_connect_status=not_attempted
ensure_readiness_rechecked_after_connect=false
wait_probe_status=ready
wait_probe_error=OK
wait_adb_connect_attempted=false
```

WAIT 是独立的只读 readiness 阶段。external 模式没有执行 MuMu start、stop、restart，
没有执行 disconnect、ADB server 重启、端口扫描、实例扫描或 emulator transport 自动
选择。

StarRail 真实执行并完成 owned-process cleanup。MAA 真实执行一次，exit code 为 0，
owned-process cleanup 成功。AALC 执行一次，操作者从 AALC 自身界面正常关闭，exit code
为 0，owned-process cleanup 成功：

```text
starrail_executed=true
starrail_owned_process_cleaned=true
maa_executed=true
maa_exit_code=0
maa_owned_process_cleaned=true
aalc_executed=true
aalc_attempt_count=1
aalc_exit_code=0
aalc_operator_graceful_close=true
aalc_owned_process_cleaned=true
```

## AALC 网络限制

AALC 进程生命周期和 Adapter 合约均已通过：

```text
aalc_process_lifecycle_validation=PASS
aalc_adapter_contract_validation=PASS
aalc_online_business_ui_validation=NOT_VERIFIED
aalc_business_task_completion_claimed=false
aalc_network_issue_blocking_phase_6=false
```

由于网络原因，AALC 在线业务界面未能正常打开。该限制不应写成 AALC 在线流程已
通过，也不应写成 AALC 业务任务自然完成；它不改变本次 workflow/lifecycle acceptance
的结果。

## 结论

```text
workflow_lifecycle_acceptance=PASS
phase_6c2c_completed=true
result=PASS
```

工作树在运行前后保持干净，RunReport 已完整写入并通过脱敏读取。该结果仅覆盖批准的
external-only 工作流，不覆盖 managed MuMu 生命周期或 AALC 在线业务 UI。
