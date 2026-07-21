# 阶段 1A 验收记录

## 一、基线信息

* 项目：Autogame Orchestrator
* 阶段：阶段 1A——进程基础契约与 Windows Job Object 底座
* 工作目录：`E:\Program Files\Games\Autogame\orchestrator-src`
* 当前分支：`phase/1-process-supervisor`
* 基线提交：`c7acd67 chore(orchestrator): bootstrap project and contracts`
* Python 版本：`Python 3.12.4`
* 操作系统：Windows
* 实施前状态：工作树干净
* 实施后状态：22 个文件已暂存
* 实施代理：OpenCode + DeepSeek V4 Pro
* Git commit：未由实施代理执行

## 二、阶段目标

阶段 1A 的目标是建立通用进程监督所需的底层基础：

1. 基于单调时钟的硬截止时间；
2. 基于 `threading.Event` 的取消令牌；
3. 不可变进程启动规格；
4. 受管进程资源对象；
5. Win32 句柄所有权；
6. Windows Job Object；
7. 挂起进程创建；
8. 进程加入 Job 后恢复执行；
9. stdout/stderr 文件重定向；
10. Fake Program 和进程树测试资产。

本阶段不实现完整 `ProcessSupervisor`，也不接入任何真实业务程序。

## 三、阶段范围

### 3.1 修改文件

* `docs/architecture.md`
* `docs/phase-plan.md`
* `tests/fakes/fake_stage.py`

### 3.2 新增生产代码

* `src/autogame_orchestrator/process/__init__.py`
* `src/autogame_orchestrator/process/deadline.py`
* `src/autogame_orchestrator/process/cancellation.py`
* `src/autogame_orchestrator/process/models.py`
* `src/autogame_orchestrator/process/errors.py`
* `src/autogame_orchestrator/process/win32_handles.py`
* `src/autogame_orchestrator/process/win32_job.py`
* `src/autogame_orchestrator/process/win32_process.py`
* `src/autogame_orchestrator/process/launcher.py`

### 3.3 新增测试资产

* `tests/fakes/fake_child.py`
* `tests/process/__init__.py`
* `tests/process/test_deadline.py`
* `tests/process/test_cancellation.py`
* `tests/process/test_models.py`
* `tests/process/test_win32_handles.py`
* `tests/process/test_win32_job.py`
* `tests/process/test_win32_launcher.py`

### 3.4 新增文档

* `docs/decisions/ADR-0002-windows-process-containment.md`
* `docs/acceptance/phase-1a.md`

最终文件清单以以下命令输出为准：

```powershell id="f7xuma"
git diff --cached --name-status
```

## 四、Deadline 验收

`Deadline` 基于：

```python id="l35usx"
time.monotonic()
```

已验证：

* [x] 支持相对时长创建。
* [x] 支持绝对单调时刻创建。
* [x] 负时长被拒绝。
* [x] 零时长立即过期。
* [x] `remaining_seconds` 不返回负值。
* [x] remaining 随时间不增加。
* [x] `expired` 行为正确。
* [x] `clamp_timeout()` 不超过总预算。
* [x] 不提供重置总预算的接口。

## 五、CancellationToken 验收

`CancellationToken` 基于：

```python id="ehmcg6"
threading.Event
```

已验证：

* [x] 初始状态未取消。
* [x] `cancel()` 可重复调用。
* [x] 多线程可以观察取消状态。
* [x] `wait()` 可以等待取消。
* [x] 等待可以超时返回。
* [x] 负 timeout 被拒绝。
* [x] 本阶段未提前实现进程等待组合逻辑。

## 六、ProcessSpec 验收

已验证：

* [x] 使用冻结 dataclass。
* [x] name 不允许为空。
* [x] executable 不允许为空。
* [x] arguments 使用不可变 tuple。
* [x] environment overrides 使用 Mapping。
* [x] 支持继承父环境。
* [x] 支持不继承父环境。
* [x] 支持 Unicode 参数。
* [x] 支持包含空格的路径。
* [x] stdout/stderr 使用显式路径。
* [x] 不存在 `shell=True` 配置。
* [x] 不在模型构造阶段启动进程。

## 七、Win32 进程创建验收

启动顺序为：

```text id="5z8tn2"
CreateProcessW(CREATE_SUSPENDED)
→ CreateJobObjectW
→ SetInformationJobObject
→ AssignProcessToJobObject
→ ResumeThread
→ 关闭 primary thread handle
→ 返回 ManagedProcess
```

已验证：

* [x] 命令行由 `subprocess.list2cmdline` 构建。
* [x] `lpCommandLine` 使用 `ctypes.create_unicode_buffer()`。
* [x] 进程以挂起状态创建。
* [x] 进程在加入 Job 前不会执行用户代码。
* [x] Job 分配成功后才恢复线程。
* [x] `ResumeThread` 后立即关闭 thread handle。
* [x] Job 分配失败时不恢复进程。
* [x] ResumeThread 失败时清理挂起进程。
* [x] 所有失败路径执行资源清理。
* [x] 未使用 `shell=True`。
* [x] 未使用 `subprocess.PIPE`。

## 八、环境块验收

已验证：

* [x] 继承父环境时可以直接使用父环境。
* [x] environment overrides 能覆盖父环境。
* [x] 不继承父环境时构造 Unicode 环境块。
* [x] 自定义环境块使用双 `NUL` 结尾。
* [x] 自定义环境块设置 `CREATE_UNICODE_ENVIRONMENT`。
* [x] 保留 Python 启动所需的必要 Windows 环境变量。
* [x] 支持 Unicode 环境变量值。
* [x] 未将完整环境写入日志或异常信息。

## 九、句柄所有权验收

已实现 `OwnedHandle` 对 Win32 HANDLE 进行有状态管理。

已验证：

* [x] 成功关闭后句柄值设置为 `None`。
* [x] 对已关闭对象再次调用 close 不执行第二次 `CloseHandle`。
* [x] process handle 可重复清理。
* [x] thread handle 可重复清理。
* [x] Job handle 可重复清理。
* [x] stdout/stderr 文件可重复清理。
* [x] 部分初始化失败后仍可安全清理。
* [x] `ManagedProcess.close_handles()` 受 `_closed` 状态保护。
* [x] 不依赖析构函数完成正常资源释放。

## 十、进程状态和退出码验收

进程存活判断使用：

```text id="k7hwxn"
WaitForSingleObject(process_handle, 0)
```

已验证：

* [x] `WAIT_TIMEOUT` 表示进程仍在运行。
* [x] `WAIT_OBJECT_0` 表示进程已退出。
* [x] 进程退出后调用 `GetExitCodeProcess`。
* [x] 正常退出码 0 可读取。
* [x] 非零退出码可读取。
* [x] 退出码 259 可作为真实退出码返回。
* [x] 不仅依赖 `STILL_ACTIVE == 259` 判断存活。
* [x] 无效句柄不会被默认为成功。

## 十一、Job Object 验收

已配置：

```text id="x1r3vp"
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
```

已验证：

* [x] 每个受管进程拥有独立 Job Object。
* [x] Job 创建后立即配置。
* [x] Job 配置失败时关闭句柄。
* [x] 进程在恢复执行前加入 Job。
* [x] `TerminateJobObject` 可以终止进程。
* [x] 关闭最后一个 Job handle 可以清理进程树。
* [x] 父进程主动退出后，子进程仍受 Job 管理。
* [x] Job 关闭后子进程退出。
* [x] 未使用进程名称扫描补救。
* [x] 未使用 WMI/CIM。
* [x] 未使用 taskkill。
* [x] 未使用 psutil 递归终止。

## 十二、stdout/stderr 验收

已验证：

* [x] 输出文件以二进制方式打开。
* [x] CRT fd 通过 `msvcrt.get_osfhandle` 转换为 Win32 HANDLE。
* [x] stdout 和 stderr 分别重定向。
* [x] 输出句柄被设置为可继承。
* [x] `CreateProcessW` 返回后恢复父进程侧不可继承状态。
* [x] 不使用长期 PIPE。
* [x] 不创建后台 reader 线程。
* [x] 5 MB stdout 不死锁。
* [x] 5 MB stderr 不死锁。
* [x] stdout 和 stderr 同时输出 5 MB 不死锁。
* [x] 输出内容长度经过测试。
* [x] 输出目录失败返回明确错误。

## 十三、Fake Program 验收

Fake Program 支持：

* [x] 指定退出码。
* [x] 退出码 259。
* [x] 睡眠指定时间。
* [x] 永久睡眠。
* [x] stdout 文本输出。
* [x] stderr 文本输出。
* [x] 大量输出。
* [x] 同时输出 stdout 和 stderr。
* [x] 写入自身 PID。
* [x] 写入生命周期事件。
* [x] 生成子进程。
* [x] 写入子进程 PID。
* [x] 生成子进程后父进程继续运行。
* [x] 生成子进程后父进程主动退出。
* [x] 回显指定环境变量。
* [x] 生产代码未导入 Fake Program。

## 十四、自动验收结果

| 检查项             | 结果                                            | 退出码 |
| --------------- | --------------------------------------------- | --: |
| 开发依赖导入          | `dev dependencies OK`                         |   0 |
| Ruff 静态检查       | `All checks passed!`                          |   0 |
| Ruff 格式检查       | `39 files already formatted`                  |   0 |
| Mypy            | `Success: no issues found in 18 source files` |   0 |
| Pytest 全量       | `143 passed`                                  |   0 |
| `tests/process` | `57 passed`                                   |   0 |
| 阶段 1A 专项        | `51 passed`                                   |   0 |
| Git 空白检查        | 无错误                                           |   0 |

退出码汇总：

```text id="872geh"
deps=0
ruff=0
format=0
mypy=0
pytest=0
process=0
phase1a=0
critical=0
diff=0
```

## 十五、安全边界验收

* [x] 未启动或停止真实 MuMu。
* [x] 未执行真实 ADB。
* [x] 未启动 StarRailCopilot。
* [x] 未执行 MAA。
* [x] 未执行 AALC。
* [x] 未探测真实业务程序。
* [x] 未按名称扫描或终止进程。
* [x] 未使用 WMI/CIM。
* [x] 未使用 taskkill。
* [x] 未使用 psutil。
* [x] 未修改阶段 0 RunReport Schema。
* [x] 未修改阶段 0 golden sample。
* [x] 未实现完整 ProcessSupervisor。
* [x] 未实现业务 Adapter。
* [x] 未实现完整工作流。
* [x] 未访问网络。
* [x] 未修改旧 PowerShell 编排器。
* [x] 实施代理未执行 Git commit。

## 十六、暂存区验收

* [x] 22 个文件进入暂存区。
* [x] 3 个文件为修改。
* [x] 其余文件为新增。
* [x] 没有未跟踪文件。
* [x] 没有暂存后再次修改的文件。
* [x] `.venv/` 未暂存。
* [x] `logs/` 未暂存。
* [x] `run-results/` 未暂存。
* [x] `__pycache__/` 未暂存。
* [x] `.pytest_cache/` 未暂存。
* [x] `.ruff_cache/` 未暂存。
* [x] `.mypy_cache/` 未暂存。
* [x] `git diff --cached --check` 通过。

## 十七、已知限制

当前实现尚未使用：

```text id="pprlkx"
STARTUPINFOEXW
PROC_THREAD_ATTRIBUTE_HANDLE_LIST
```

因此当前句柄继承依赖以下前提：

1. Python 创建的普通文件描述符默认不可继承；
2. 只有 stdout/stderr 被本模块显式设置为可继承；
3. 当前编排器只启动受信任的本地程序；
4. 当前不并发执行多个进程创建操作；
5. 阶段 1B 不得在未重新审查的情况下增加并行 launch。

在当前本地、单用户、受信任程序和串行启动范围内接受此限制。

出现以下任一需求时，必须重新实施严格句柄白名单：

* 并发启动多个程序；
* 允许第三方插件启动程序；
* 进程内存在其他主动创建可继承句柄的模块；
* 发现文件、管道、socket 或同步对象被意外继承；
* 生产运行出现因继承句柄导致的文件无法关闭或流程不退出。

升级目标为：

```text id="nw7icf"
STARTUPINFOEXW
+
PROC_THREAD_ATTRIBUTE_HANDLE_LIST
+
EXTENDED_STARTUPINFO_PRESENT
```

## 十八、验收结论

验收决定：

* [ ] 已验收
* [ ] 未通过
* [x] 有条件通过

验收说明：

> 阶段 1A 已通过静态检查、格式检查、类型检查、143 项全量测试、57 项进程专项测试、Win32 退出码测试、Job Object 进程树清理测试、句柄幂等测试和大输出防死锁测试。阶段 1A 已建立挂起创建、Job 分配、恢复执行和资源清理的可靠基础。当前尚未实现严格句柄继承白名单，但在本地受信任程序、串行启动和 Python 默认不可继承句柄的范围内可以接受，允许提交阶段 1A。阶段 1B 不得扩大此限制的适用范围。

遗留问题：

> 严格句柄继承白名单延后。除非阶段 1B 需要并发启动，否则不阻塞当前实用 MVP。

## 十九、提交信息

建议提交信息：

```text id="nsr1k9"
feat(orchestrator): add Win32 process containment foundation
```
