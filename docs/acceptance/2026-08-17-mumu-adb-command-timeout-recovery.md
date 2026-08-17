# 2026-08-17 MuMu ADB 子命令超时恢复

> 本文是 commit <code>80e0835</code> 的历史验收记录。后续 offline recovery、
> failure cleanup 与精确 endpoint recycle 的当前状态统一维护在
> [累积维护与修复日志](../maintenance-log.md)；本文保留为 ADB child deadline
> 的详细证据。

## 事故现场

- 基线：`22d9fd0 refactor(workflow): retire AALC from production pipeline`
- 失败运行：`7883dd4e-feae-41f2-8bb7-48d61a6e9f26`
- 最终状态：`failure / WORKFLOW_STAGE_TIMEOUT`
- 失败阶段：`ensure_mumu_running`
- 阶段耗时：`120000 ms`
- source error：`START_TIMEOUT`
- 最后安全 probe：`timeout / ADB_TIMEOUT / adb_devices`
- controlled connect：未尝试
- 后续阶段：`run_starrail` 及以后均未进入

失败后只读现场显示 MuMu 宿主进程存在、TCP 端口监听，但
`is_android_started=false`；随后一条有 5 秒外部上限的
`adb devices -l` 返回设备为 offline。没有 Windows 应用崩溃事件或
minidump，因此证据只支持「MuMu Android/ADB readiness 未成立」，不支持
把现场描述为已证实的 MuMu native crash。

## 根因分层

环境触发与代码缺陷是两个不同问题：

1. 本次触发条件是 MuMu manager 接受 launch 后，Android/ADB 没有进入 ready。
2. `AdbClient._run_adb_command()` 把完整的 MuMu start operation deadline
   直接交给单个 `ProcessSupervisor.run()`。因此一次异常阻塞的
   `adb devices -l` 可以独占全部 120 秒，readiness loop 没有机会再次
   probe，也无法把最后状态推进到更准确的 offline/boot-not-completed。

7200 秒 workflow deadline 和 120 秒 MuMu start timeout 均不是缺陷；缺陷是
ADB 子命令没有自己的有限预算。

## 修复

`AdbClientConfig` 增加内部默认值为 5 秒的
`command_timeout_seconds`。每条 `adb version/devices/connect/get-state/getprop`
命令只获得一个在创建时固定的 child deadline：

```text
adb command deadline <= 5 seconds
adb command deadline <= parent operation remaining
```

child deadline 只限制当前进程，不重置也不延长 start/stop operation deadline。
命令超时后 `ProcessSupervisor` 仍按原契约终止其拥有的进程树并返回
`ADB_TIMEOUT`。

managed start 的初始 status 若因该 child deadline 超时：

- 不再次调用 MuMu manager launch；
- 在原有、单调递减的 start operation deadline 内进入 readiness polling；
- 下一轮可重新执行只读 probe，并在原严格条件成立时使用既有 controlled
  local connect recovery。

managed stop 的初始 status 若仅因 child deadline 超时，不再把 5 秒误当成
完整 stop timeout；它继续执行原有幂等 MuMu manager shutdown，再在同一 stop
operation deadline 内确认端口关闭。

## 安全边界

- 未增加 `adb kill-server`、`adb start-server` 或任意地址扫描。
- controlled connect 仍只允许精确的 localhost endpoint，并且只在
  `DEVICE_NOT_FOUND / select_device` 时成立。
- `ADB_TIMEOUT`、`DEVICE_OFFLINE`、`ANDROID_NOT_BOOTED` 不会触发 connect。
- 没有自动重启 MuMu，也没有增加新的 120 秒预算。
- 本次没有运行真实 workflow、MuMu、StarRail、MAA、AALC 或 Limbus。

## 回归测试

新增或收紧的核心用例：

- `test_command_timeout_is_shorter_than_long_parent_deadline`：单条阻塞命令
  返回后父预算仍有余量。
- `test_short_parent_deadline_clamps_command_timeout`：父预算更短时父预算优先。
- `test_start_recovers_after_one_adb_devices_command_timeout`：第一次
  `adb devices` 永久阻塞并被 child deadline 终止，下一轮恢复正常；
  同一个 `start()` 返回 `STARTED`，manager launch 只调用一次。
- `test_blocked_adb_command_is_bounded_by_start_deadline`：持续阻塞仍严格止于
  start operation deadline。
- `test_initial_adb_command_timeout_waits_without_relaunching_manager`：初始
  ADB timeout 不会重复 launch。
- `test_initial_adb_command_timeout_does_not_skip_shutdown`：初始 ADB timeout
  不会阻止原有 shutdown 命令。

验证结果：

```text
ADB/MuMu focused                73 passed
probes/runtime/workflow        578 passed
full pytest                    1425 passed, 1 skipped
ruff check .                   passed
mypy src                       passed (68 source files)
changed-file format check      passed
```

全仓 format check 仍仅列出四个基线已存在、与本修复无关的文件；本次未修改：

```text
src/autogame_orchestrator/runtime/starrail_log.py
tests/packaging/test_install_update_scripts.py
tests/runtime/test_starrail_port.py
tests/runtime/test_starrail_runtime.py
```

## 打包结果

使用 `scripts/build-package.ps1` 与受版本控制的 PyInstaller spec 重建桌面
快捷方式引用的 onedir：

```text
exe_sha256_before=CEBA40DE19A9558228273E704ED64B0E1796DE1AA7375B016201F52AF5595FDC
exe_sha256_after=AB63BDE14D3E2C728DF9DC9C9AEC5D0888E987D7AA4E91B0B9255A5C3419C9F0
internal_exists=true
schema_exists=true
```

桌面快捷方式未修改，仍直接指向
`dist/OrchestratoRRR/OrchestratoRRR.exe`。

## 剩余边界

若 MuMu Android engine 在整个 120 秒 operation deadline 内始终没有启动，
workflow 仍会按设计 fail closed，StarRail 不会启动。本修复保证单条 ADB
进程不能吞掉全部预算，并允许瞬时阻塞恢复；它不伪造 readiness，也不以
无限等待掩盖 MuMu 自身故障。

上游阶段失败时 `SHUTDOWN_MUMU` 仍可能被普通 pipeline skip，这是已有的
always-run/finally 独立缺口，不属于本次 ADB timeout 修复。
