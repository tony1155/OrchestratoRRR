# 阶段 1B 验收记录

## 一、基线信息

* 项目：Autogame Orchestrator
* 阶段：阶段 1B——通用 ProcessSupervisor
* 工作目录：`E:\Program Files\Games\Autogame\orchestrator-src`
* 当前分支：`phase/1-process-supervisor`
* 基线提交：`af50a75 feat(orchestrator): add Win32 process containment foundation`
* Python 版本：`Python 3.12.4`
* 操作系统：Windows
* 实施前状态：工作树干净
* 实施后状态：10 个文件已暂存
* 新增文件：4 个
* 修改文件：6 个
* 删除文件：0 个
* 实施代理：OpenCode + DeepSeek V4 Pro
* 实施代理是否提交 Git：否

## 二、阶段目标

阶段 1B 的目标是在阶段 1A 的 Win32 进程容器基础上，实现一个简单、同步、串行的通用进程监督器。

本阶段完成：

1. 启动受管进程；
2. 注册和跟踪受管进程；
3. 等待正常退出；
4. 获取真实退出码；
5. 识别非零退出；
6. 实施硬超时；
7. 响应取消令牌；
8. 主动停止进程；
9. 终止整个 Windows Job Object；
10. 有界确认进程退出；
11. 统一生成 `ProcessResult`；
12. 自动关闭进程、Job 和输出文件句柄；
13. 清理多个活动进程；
14. 支持上下文管理器；
15. 保证各清理入口幂等。

本阶段不接入 MuMu、ADB、StarRailCopilot、MAA 或 AALC。

## 三、修改范围

### 3.1 新增文件

* `src/autogame_orchestrator/process/result.py`
* `src/autogame_orchestrator/process/supervisor.py`
* `tests/process/test_supervisor.py`
* `docs/acceptance/phase-1b.md`

### 3.2 修改文件

* `src/autogame_orchestrator/process/__init__.py`
* `src/autogame_orchestrator/process/errors.py`
* `src/autogame_orchestrator/process/models.py`
* `src/autogame_orchestrator/process/launcher.py`
* `docs/architecture.md`
* `docs/phase-plan.md`

### 3.3 未修改内容

本阶段未修改：

* 阶段 0 RunReport Schema；
* 阶段 0 golden sample；
* CLI 执行入口；
* 配置文件结构；
* 旧 PowerShell 编排器；
* 阶段 1A 的 Job Object 核心设计；
* 任何真实业务程序 Adapter。

## 四、ProcessSupervisor API

### 4.1 launch

```python
launch(spec: ProcessSpec) -> ManagedProcess
```

行为：

1. 验证 supervisor 尚未关闭；
2. 通过阶段 1A launcher 启动进程；
3. 使用串行 launch lock 保护进程创建；
4. 将进程注册到活动表；
5. 使用内部 `process_id` 标识资源所有权；
6. 返回由当前 supervisor 拥有的 `ManagedProcess`。

资源所有权：

* 成功 launch 后，进程归当前 supervisor 所有；
* 调用方不能把其他 supervisor 或外部构造的对象交给本 supervisor 管理；
* 活动进程以 `process_id` 注册，不把 PID 当成唯一稳定身份。

### 4.2 wait

```python
wait(
    process: ManagedProcess,
    deadline: Deadline,
    cancel: CancellationToken | None = None,
) -> ProcessResult
```

行为：

1. 检查进程所有权；
2. 检查取消状态；
3. 检查硬截止时间；
4. 使用有限轮询获取进程状态；
5. 正常退出时读取真实退出码；
6. 超时时终止整个 Job；
7. 取消时终止整个 Job；
8. 有界确认进程退出；
9. 生成 `ProcessResult`；
10. 关闭全部资源；
11. 从活动表移除进程。

### 4.3 run

```python
run(
    spec: ProcessSpec,
    deadline: Deadline,
    cancel: CancellationToken | None = None,
) -> ProcessResult
```

行为：

```text
launch
→ wait
→ timeout 或 cancel 时终止 Job
→ 关闭资源
→ 返回 ProcessResult
```

保证：

* 启动失败转换为 `START_FAILED`；
* 普通调用方不会收到裸 Win32 启动异常；
* `KeyboardInterrupt` 不会被吞掉；
* 收到 `KeyboardInterrupt` 时先清理受管进程，再重新抛出；
* 返回后不保留活动资源。

### 4.4 stop

```python
stop(
    process: ManagedProcess,
    confirmation_deadline: Deadline | None = None,
) -> ProcessResult
```

行为：

1. 检查进程所有权；
2. 已自然退出时保留原始退出语义；
3. 仍在运行时调用 `TerminateJobObject`；
4. 在硬截止时间内确认退出；
5. 生成 `STOPPED` 结果；
6. 关闭全部资源；
7. 从活动表移除进程。

本阶段不发送 `CTRL_BREAK_EVENT`，不实现应用程序专用优雅退出。

### 4.5 close

```python
close() -> None
```

行为：

1. 遍历当前 supervisor 的全部活动进程；
2. 对每个进程执行有界 Job 终止；
3. 尽力清理所有进程；
4. 一个进程失败不阻止其他进程继续清理；
5. 清空活动注册表；
6. close 可重复调用；
7. close 后拒绝再次 launch；
8. 上下文管理器退出时自动调用。

## 五、ProcessResult

`ProcessResult` 为冻结 dataclass。

包含：

* 内部进程 ID；
* 进程名称；
* PID；
* 终止原因；
* 退出码；
* 进程执行错误码；
* 启动时间；
* 结束时间；
* duration；
* stdout 路径；
* stderr 路径；
* 是否执行强制终止；
* 可 JSON 序列化 diagnostics。

约束：

* [x] 对外时间使用带时区 `datetime`。
* [x] duration 使用 `time.monotonic()` 计算。
* [x] `duration_ms` 不得为负。
* [x] diagnostics 必须可 JSON 序列化。
* [x] 不记录完整环境变量。
* [x] 不记录 Win32 HANDLE。
* [x] 不修改 RunReport v1。
* [x] 不直接承担 StageReport 映射职责。

## 六、终止结果语义

| 场景         | TerminationReason    | ProcessExecutionErrorCode | forced_termination |
| ---------- | -------------------- | ------------------------- | -----------------: |
| 正常退出码 0    | `NORMAL_EXIT`        | `OK`                      |              false |
| 非零退出码      | `NONZERO_EXIT`       | `EXIT_NONZERO`            |              false |
| 启动失败       | `START_FAILED`       | `START_FAILED`            |              false |
| 超时         | `TIMEOUT`            | `TIMEOUT`                 |               true |
| 取消         | `CANCELLED`          | `CANCELLED`               |               true |
| 主动停止       | `STOPPED`            | `STOPPED`                 |               true |
| Win32 等待失败 | `WAIT_FAILED`        | `WAIT_FAILED`             |            视清理路径而定 |
| 终止确认失败     | `TERMINATION_FAILED` | `TERMINATION_FAILED`      |               true |

约束：

* [x] 只有正常退出码 0 使用 `OK`。
* [x] 非零退出不被标记为成功。
* [x] 超时不被标记为成功。
* [x] 取消不被标记为成功。
* [x] 主动停止不被标记为成功。
* [x] 启动失败时 PID 为 `None`。
* [x] 退出码 259 被保留为真实非零退出码。

## 七、进程所有权和注册表

已验证：

* [x] supervisor 只管理自己成功 launch 的进程。
* [x] 活动表使用内部进程 ID。
* [x] 不使用 PID 作为唯一身份。
* [x] launch 成功后立即注册。
* [x] wait 返回前移除活动进程。
* [x] stop 返回前移除活动进程。
* [x] close 后活动表为空。
* [x] 外部构造的 `ManagedProcess` 被拒绝。
* [x] 其他 supervisor 创建的进程不能被当前 supervisor 管理。
* [x] close 后再次 launch 被拒绝。

## 八、串行启动限制

阶段 1B 保持串行 launch。

原因：

阶段 1A 当前尚未使用：

```text
STARTUPINFOEXW
PROC_THREAD_ATTRIBUTE_HANDLE_LIST
```

已采取以下限制：

* [x] supervisor 内部使用 launch lock。
* [x] 所有 launcher 调用串行执行。
* [x] 不提供并发 launch API。
* [x] 不在持有 launch lock 时等待进程退出。
* [x] 不创建后台线程或线程池。
* [x] 两个进程顺序 launch 已通过测试。

该限制满足当前本地、受信任程序和串行工作流需求。

## 九、wait 验收

已验证：

* [x] 不调用无 timeout 的永久 wait。
* [x] 使用有限轮询。
* [x] 轮询间隔有上限。
* [x] 单轮等待不超过 deadline 剩余时间。
* [x] deadline 不会被内部操作重置。
* [x] 正常退出码 0 被正确识别。
* [x] 普通非零退出码被正确识别。
* [x] 退出码 259 被正确识别。
* [x] Unicode 参数正常传递。
* [x] stdout/stderr 正确写入文件。
* [x] wait 后全部句柄关闭。
* [x] wait 后进程从活动表移除。
* [x] Win32 等待错误不会被视为成功。

## 十、timeout 验收

超时流程：

```text
Deadline 到期
→ 记录 TIMEOUT
→ TerminateJobObject
→ 创建终止确认 Deadline
→ 确认根进程退出
→ 确认子进程退出
→ 关闭资源
→ 返回 ProcessResult
```

已验证：

* [x] timeout 结果不是成功。
* [x] `forced_termination` 为 true。
* [x] 终止整个 Job，而不是只终止根进程。
* [x] 终止确认有硬上限。
* [x] 根进程在超时后退出。
* [x] 子进程在超时后退出。
* [x] timeout 后无受管进程残留。
* [x] 测试整体耗时有上限。

## 十一、CancellationToken 验收

取消流程：

```text
CancellationToken 触发
→ 记录 CANCELLED
→ TerminateJobObject
→ 有界确认退出
→ 关闭资源
→ 返回 ProcessResult
```

已验证：

* [x] cancel 可以由另一个线程触发。
* [x] wait 在有限时间内返回。
* [x] 取消不是成功。
* [x] 根进程被清理。
* [x] 子进程被清理。
* [x] 取消后句柄关闭。
* [x] 取消后进程从活动表移除。
* [x] supervisor 没有创建后台线程。

## 十二、stop 验收

本阶段 stop 直接终止 Job。

已验证：

* [x] 运行中的进程可以 stop。
* [x] stop 终止整个进程树。
* [x] 已自然退出的进程保留原始结果。
* [x] 重复 stop 不重复关闭句柄。
* [x] stop 后句柄全部关闭。
* [x] stop 后活动表移除。
* [x] 不使用 `CTRL_BREAK_EVENT`。
* [x] 不使用 taskkill。
* [x] 不按名称终止进程。

应用程序专用优雅退出由未来 Adapter 在调用 supervisor stop 前处理。

## 十三、close 验收

已验证：

* [x] close 可以清理一个活动进程。
* [x] close 可以清理多个活动进程。
* [x] close 可以清理父子进程树。
* [x] close 可重复调用。
* [x] context manager 自动调用 close。
* [x] 一个清理失败不会阻止其他进程继续清理。
* [x] close 后活动注册表为空。
* [x] close 后不能再次 launch。
* [x] 不静默忽略清理失败。

## 十四、自动验收结果

| 检查项                  | 实际结果                                          | 退出码 |
| -------------------- | --------------------------------------------- | --: |
| Python               | `Python 3.12.4`                               |   0 |
| 开发依赖导入               | `dev dependencies OK`                         |   0 |
| Ruff 静态检查            | `All checks passed!`                          |   0 |
| Ruff 格式检查            | `42 files already formatted`                  |   0 |
| Mypy                 | `Success: no issues found in 20 source files` |   0 |
| Pytest 全量            | `170 passed`                                  |   0 |
| `tests/process`      | `84 passed`                                   |   0 |
| ProcessSupervisor 专项 | `27 passed`                                   |   0 |
| 阶段 1B 关键词专项          | `36 passed`                                   |   0 |
| Git 空白检查             | 无错误                                           |   0 |

退出码汇总：

```text
python=0
deps=0
ruff=0
format=0
mypy=0
pytest=0
process=0
supervisor=0
phase1b=0
critical=0
diff=0
```

## 十五、进程清理证明

所有 ProcessSupervisor 测试均使用测试创建的具体 PID 进行检查。

检查方式：

```text
OpenProcess
+
WaitForSingleObject
```

检查硬上限：

```text
2 秒
```

已验证：

* [x] 每个正常退出 PID 最终不存在。
* [x] 每个非零退出 PID 最终不存在。
* [x] timeout 根 PID 最终不存在。
* [x] timeout 子 PID 最终不存在。
* [x] cancel 根 PID 最终不存在。
* [x] cancel 子 PID 最终不存在。
* [x] stop 根 PID 最终不存在。
* [x] stop 子 PID 最终不存在。
* [x] close 清理的所有 PID 最终不存在。
* [x] 不使用按名称扫描代替 PID 检查。
* [x] 不终止其他 Python 进程。

## 十六、安全边界验收

* [x] 未启动或停止真实 MuMu。
* [x] 未执行真实 ADB。
* [x] 未启动 StarRailCopilot。
* [x] 未执行 MAA。
* [x] 未执行 AALC。
* [x] 未按名称扫描进程。
* [x] 未按名称终止进程。
* [x] 未使用 WMI。
* [x] 未使用 CIM。
* [x] 未使用 taskkill。
* [x] 未使用 psutil。
* [x] 未使用 `subprocess.PIPE`。
* [x] 未使用 `shell=True`。
* [x] 未修改阶段 0 Schema。
* [x] 未修改阶段 0 golden sample。
* [x] 未实现真实业务 Adapter。
* [x] 未实现完整工作流。
* [x] 未添加真实执行 CLI。
* [x] 未访问网络。
* [x] 未修改旧 PowerShell 编排器。
* [x] 实施代理未执行 Git commit。

## 十七、暂存区验收

* [x] 暂存文件总数为 10。
* [x] 新增文件为 4 个。
* [x] 修改文件为 6 个。
* [x] 删除文件为 0 个。
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

## 十八、已知限制

阶段 1B 当前限制如下：

1. 只支持同步 API；
2. 只支持串行 launch；
3. 不提供异步 API；
4. 不提供线程池；
5. 不实现通用优雅停止；
6. 不实现 `CTRL_BREAK_EVENT`；
7. 不实现程序专用关闭协议；
8. 不管理启动前已经存在的进程；
9. 不按进程名称查找或接管进程；
10. 不接入任何真实业务程序；
11. 不直接生成 RunReport StageReport；
12. 严格句柄继承白名单仍为阶段 1A 已记录限制。

以上限制符合当前实用 MVP 范围，不阻塞阶段 1B。

## 十九、验收结论

验收决定：

* [x] 已验收
* [ ] 未通过
* [ ] 有条件通过

验收说明：

> 阶段 1B 已通过 Ruff、格式检查、Mypy、170 项全量测试、84 项进程测试、27 项 ProcessSupervisor 专项测试，以及 timeout、cancel、stop、进程树清理和 PID 残留验证。ProcessSupervisor 已能够以同步、串行和有硬边界的方式启动、等待、超时终止、取消、停止和清理自己创建的进程树。未发现真实业务程序接入、进程名称扫描、无限等待或后续阶段越界实现。阶段 1B 验收通过。

遗留问题：

> 无阶段 1B 阻塞问题。程序专用优雅退出和真实业务程序接入留给后续 Adapter 阶段。

## 二十、提交信息

建议提交信息：

```text
feat(orchestrator): add process supervisor lifecycle
```
