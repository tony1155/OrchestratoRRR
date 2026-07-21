# ADR-0002：Windows 进程隔离——使用 Job Object 实现可靠进程树管理

**日期:** 2026-07-21
**状态:** 已接受

## 背景

编排器需要管理多个外部 Windows 进程的生命周期（StarRailCopilot、MAA、AALC、MuMu）。
这些程序可能创建子进程。编排器崩溃或异常退出时，必须保证所有被管理的进程树被操作系统自动清理。

## 决策

使用 Windows Job Object 的 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` 作为进程隔离原语。

## 为什么使用 Windows Job Object

1. **内核级保证。** `KILL_ON_JOB_CLOSE` 是内核行为——当 Job 句柄关闭时，操作系统自动终止 Job 内所有进程。即使编排器 Python 进程崩溃，内核仍然执行清理。不存在 "PID 重用" 或 "原子性窗口" 问题。

2. **进程树覆盖。** `AssignProcessToJobObject` 后，该进程及其所有后续子进程（无论多深）都自动属于该 Job，无需递归枚举。

3. **零运行时依赖。** 通过标准库 `ctypes` 调用 `kernel32.dll`，不需要 `pywin32` 或 `psutil`。

## 为什么不用 psutil 作为进程隔离

- `psutil` 没有 Job Object API。
- `psutil.Process(pid).kill()` 需要知道 PID，而 PID 可能在扫描和终止之间被系统回收重用。
- `psutil.Process(pid).children()` 采用进程快照扫描，不是原子操作——子进程可能在两次扫描之间生成。
- 编排器崩溃后，`psutil` 无法执行任何清理。

`psutil` 可以作为可选的诊断补充（CPU/内存统计），但绝不能作为进程隔离原语。

## 为什么不用 `Popen + CREATE_SUSPENDED + ResumeThread`

`subprocess.Popen(creationflags=CREATE_SUSPENDED)` 返回的对象不暴露进程句柄和线程句柄，只暴露 `pid` 和高级操作。`ResumeThread` 需要 `HANDLE`，而 `Popen` 在 Windows 上关闭了这些句柄。

必须直接调用 `CreateProcessW` 以保留完整的 `PROCESS_INFORMATION.hProcess` 和 `PROCESS_INFORMATION.hThread`。

## 为什么使用 `CreateProcessW`

1. 返回进程句柄和线程句柄，两者在 Job 分配前都需要持有。
2. 支持 `CREATE_SUSPENDED`——进程在 Job 分配前不执行任何代码，消除逃逸窗口。
3. 直接控制 `bInheritHandles`，用于 stdout/stderr 文件重定向。

## 句柄所有权

| 句柄 | 所有者 | 关闭时机 |
|---|---|---|
| `hProcess` | `ManagedProcess` | `close_handles()` |
| `hThread` | 启动器 | `CreateProcessW` 后立即关闭 |
| Job handle | `ManagedProcess` | `close_handles()` |
| stdout fd | `ManagedProcess` | `close_handles()` |
| stderr fd | `ManagedProcess` | `close_handles()` |

## stdout/stderr 二进制直写

- 文件以二进制模式打开（`os.O_BINARY`），避免换行符转换。
- 父进程不设置或假设子进程编码。编码解释属于后续日志读取层的职责。
- 不使用 `subprocess.PIPE`——避免死锁和后台 reader 线程。

## 阶段 1A / 1B 拆分原因

阶段 1 设计规模较大。拆分为两个子阶段：

- **1A**：基础设施——`Deadline`、`CancellationToken`、`ProcessSpec`、`ManagedProcess`、Job Object、`CreateProcessW` 启动器、Fake Program。可以独立测试所有 Win32 和 Job 行为。
- **1B**：编排——`ProcessSupervisor`（完整 `run`/`wait`/`stop`/`close` 生命周期）、超时升级、优雅停止、幂等关闭。

## 已知 Windows 风险

1. **CTRL_BREAK_EVENT 需要控制台。** 即使设置了 `CREATE_NEW_PROCESS_GROUP`，如果父进程本身没有控制台（例如在 PyInstaller 打包的可执行文件中），`GenerateConsoleCtrlEvent` 可能失败。阶段 1B 需要评估是否使用 `AttachConsole` + `FreeConsole`。

2. **嵌套 Job Object。** 如果调用进程已处于另一个 Job 中（例如某些安全软件），`CreateJobObjectW` 仍然可以成功，但 `AssignProcessToJobObject` 可能失败。此时返回清晰错误，不无限等待。

3. **32 位 vs 64 位。** 所有 ctypes 结构体使用默认对齐。在 64 位 Windows 上测试验证（目标平台），32 位兼容性不保证。

## PyInstaller 影响

`ctypes` 方案不引入任何额外 DLL。`kernel32.dll` 在 Windows 上始终可用。PyInstaller 打包后的可执行文件无需额外配置即可使用 Job Object。

## 后续 ADR

阶段 1B 将补充优雅停止策略 ADR（`CTRL_BREAK_EVENT` vs `WM_CLOSE` vs 文件信号）。
