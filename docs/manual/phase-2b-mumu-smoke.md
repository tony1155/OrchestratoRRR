# 阶段 2B 手工验收说明

> **状态:** 待用户手工执行。实施代理不得执行以下任何命令。

## 前提

1. 已安装 MuMu 模拟器（MuMu Player 12）。
2. 已知 MuMu 管理程序（如 `MuMuNxDevice.exe`）的完整路径。
3. 已知该程序的 start/stop 命令行参数形式。
4. 已知实例 ID（如有）。
5. ADB 已可用（`adb.exe` 路径已知）。

## 步骤

### 1. 确认配置

编辑 `config/orchestrator.local.toml` 中的 `[mumu]` 节：

```toml
[mumu]
executable = "C:\\full\\path\\to\\MuMuNxDevice.exe"
adb_executable = "C:\\full\\path\\to\\adb.exe"
adb_serial = "127.0.0.1:16384"
start_arguments = []
stop_arguments = []
```

**注意:** `start_arguments` 和 `stop_arguments` 必须填写为实际命令行参数列表（不含可执行文件名本身）。

### 2. 执行 status

```powershell
python -m autogame_orchestrator.status
```

观察输出：
- `READY`：模拟器已运行且 ADB 可达。
- `STOPPED`：端口关闭或设备不可见。
- `NOT_READY`：设备存在但未完全启动。

### 3. 执行 start（仅在用户手工批准后）

```powershell
python -m autogame_orchestrator.start
```

观察：
- 管理程序是否正常执行。
- 模拟器窗口是否出现。
- status 是否最终变为 `READY`。

### 4. 观察 readiness

多次执行 `status`，确认 READY 状态稳定。

### 5. 执行 stop

```powershell
python -m autogame_orchestrator.stop
```

观察：
- 管理程序是否正常执行。
- 模拟器窗口是否关闭。
- status 是否最终变为 `STOPPED`。

### 6. 失败恢复

如果 start 或 stop 失败：
1. 通过 Windows 任务管理器手动关闭 MuMu 进程。
2. 检查管理程序路径是否正确。
3. 检查 start_arguments 和 stop_arguments 是否正确。

### 7. 确认没有启动游戏

- version/validate/plan/status/start/stop/restart 都不应启动任何游戏进程。
- 如果 status 报告 READY，停止后应看到模拟器桌面（而非游戏画面）。

### 8. 确认管理命令没有被 Job 误杀

- start 执行后，管理程序应退出（短暂进程）。
- 实际模拟器进程应继续运行（不受 Job Object 约束）。
- 如果模拟器在 start 后数秒内消失，则管理程序可能与模拟器有父子进程关系，不应通过 `ProcessSupervisor.run()` 直接启动。

## 风险

- 如果管理程序与模拟器主进程是父子关系，`ProcessSupervisor.run()` 会在管理程序退出后通过 `KILL_ON_JOB_CLOSE` 终止模拟器。这种情况下必须使用不同的启动方式（如直接调用 GUI 或使用其他管理器）。
- 本适配器假定管理命令是短生命周期 CLI，不持有模拟器进程作为子进程。
