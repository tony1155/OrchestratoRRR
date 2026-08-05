# Phase 6C2B4C——真实冷连接自动恢复验收

## 基线与范围

- 分支：`phase/6-complete-workflow`
- 批准基线提交：`3a63f949ccc7effc42e09252633e4a39c4a94f2c`
- 模式：`external`
- 本记录只覆盖一次真实冷连接准备和一次生产 `ENSURE_MUMU_RUNNING`。
- 未运行完整 workflow、WAIT 阶段或任何业务程序。

本验收验证：配置目标的 TCP transport 在设备列表中缺失时，生产 external ensure
是否能在严格条件下自动执行一次本地 TCP connect，并通过一次 readiness 复验恢复为
ready。

## 冷状态准备

操作者已确认 MuMu 实例和 Android 桌面处于可用状态，并同意对配置目标执行测试准备。
初始只读检查发现精确目标为 ready，因此仅对该精确目标执行了一次目标明确的
disconnect；没有执行无目标 disconnect、其他设备 disconnect、ADB server 重启或实例
生命周期命令。准备后的只读检查确认：

```text
initial_exact_target_state=absent_or_disconnected
test_setup_disconnect_called=true
test_setup_disconnect_attempts=1
test_setup_disconnect_exact_target_only=true
exact_target_absent_before_ensure=true
other_transports_present=true
```

原始设备身份、地址、端口、命令输出和进程信息未进入本记录。

## 生产 ensure 结果

生产调用链为正式配置加载、production runtime binding、`ProductionStageExecutor`、
`ENSURE_MUMU_RUNNING`、`MumuAdapter.ensure_external_ready`、
`MumuReadinessProbe.ensure_ready` 和 `AdbClient`。Stage 只执行一次：

```text
stage=ENSURE_MUMU_RUNNING
stage_outcome=success
stage_error_code=OK
runtime_status=ready
runtime_error_code=OK
action=status
changed=false
probe_status=ready
probe_error=OK
probe_step=none
adb_connect_attempted=true
adb_connect_status=connected
adb_connect_error=OK
readiness_rechecked_after_connect=true
production_connect_triggered=true
exact_expected_device_ready_after_ensure=true
multiple_devices_present=true
emulator_transport_selected=false
automatic_device_selection=false
automatic_retry=false
connection_preserved_after_success=true
```

生产路径没有选择 emulator transport，没有根据设备列表第一项作 fallback，也没有
执行 `adb start-server`、`adb kill-server`、额外 disconnect、端口扫描或 MuMu
start/stop/restart。ADB server 的生命周期仍属于 ADB 客户端和外部环境；普通 ADB
命令可能按 ADB 自身行为使用或拉起默认 server，OrchestratoRRR 不拥有该生命周期。

## 结论

```text
phase_6c2b4c_completed=true
result=PASS
```

本证据证明了已批准 external 路径的真实冷连接自动恢复能力，不证明 managed MuMu
生命周期、实例自动选择或任何未批准的 ADB 操作。
