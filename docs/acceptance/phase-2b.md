# 阶段 2B 验收标准

> **状态:** 附注接受。
> **重要:** 真实 MuMu 控制尚未获准。仓库中没有可安全使用的短生命周期管理命令证据。
> **日期:** 2026-07-21

## 基线

| 项目 | 值 |
|---|---|
| 工作目录 | `E:\Program Files\Games\Autogame\orchestrator-src` |
| 分支 | `phase/2-mumu-adapter` |
| HEAD | `aee6064 feat(orchestrator): add local runtime and adb probes` |
| Python | 3.12.4 |
| 文件数量 | 10（7 新增 + 2 修改 + 1 新增空文件） |

## 完成范围

- [x] `MumuRuntimeResult` 模型（`MumuAction`、`MumuRuntimeStatus`、`MumuRuntimeErrorCode`）
- [x] `MumuAdapter.status()` — readiness 映射到结构化状态
- [x] `MumuAdapter.start()` — 启动管理命令 + 等待 readiness
- [x] `MumuAdapter.stop()` — 停止管理命令 + 确认端口关闭
- [x] `MumuAdapter.restart()` — 先 stop 再 start，共享 Deadline
- [x] Deadline 传播到所有子操作
- [x] CancellationToken 传播到所有管理命令和等待
- [x] Fake Manager 集成测试（7 个生产路径）
- [x] 空参数安全拒绝（6 个专属测试）

## 默认拒绝行为

| 场景 | status | error_code | changed | 是否执行命令 |
|---|---|---|---|---|
| READY + 空 start_arguments | STARTED | OK | False | 否 |
| 非 READY + 空 start_arguments | FAILED | INVALID_CONFIGURATION | False | 否 |
| STOPPED + 空 stop_arguments | STOPPED | OK | False | 否 |
| 非 STOPPED + 空 stop_arguments | FAILED | INVALID_CONFIGURATION | False | 否 |
| restart 缺少 stop 参数 | FAILED | INVALID_CONFIGURATION | False | 否（不调用 start） |
| restart 缺少 start 参数 | FAILED | INVALID_CONFIGURATION | False | 否 |

## Job Object 限制

`ProcessSupervisor.run()` 会清理管理命令派生的整个进程树。会派生长期模拟器进程的普通 GUI 启动器不能直接通过此路径执行。`test_manager_spawn_child_then_exit` 已通过逐 PID 验证子进程清理。

## 真实 MuMu 限制

- 仓库中没有可信短生命周期 MuMu 管理 CLI 的证据；
- `MuMuNxDevice.exe` 只有占位路径；
- 无官方或仓库内 start/stop 参数证据；
- 默认空参数不会执行未知可执行文件；
- 真实 MuMu start/stop/restart 尚未获得生产批准；
- 手工 smoke 文档（`docs/manual/phase-2b-mumu-smoke.md`）只提供步骤，实施代理不得执行。

## 配置

- [x] `MuMuConfig` 新增 `start_arguments`、`stop_arguments`
- [x] `instance_id` 已删除

## 自动验收数据

| 命令 | 退出码 | passed/selected | 说明 |
|---|---|---|---|
| `ruff check .` | 0 | — | All checks passed |
| `ruff format --check .` | 0 | — | 60 files |
| `mypy src` | 0 | — | 29 source files |
| `pytest -q` | 0 | 237 passed | 全量测试 |
| `pytest tests/runtime` | 0 | 19 passed | runtime 测试 |
| `pytest tests/runtime/test_mumu_runtime.py` | 0 | 19 passed | MuMu 测试 |
| `pytest -k 'empty or unsupported or invalid or idempotent or restart'` | 0 | 7 passed/12 deselected | 安全拒绝专项 |
| `pytest -k 'manager_start or manager_stop or manager_nonzero or manager_timeout or manager_cancellation or manager_spawn_child'` | 0 | 7 passed/12 deselected | Fake Manager 集成专项 |

## 安全边界

- [x] 生产代码未使用 subprocess.run/Popen/os.system/shell=True/PIPE
- [x] 未使用 taskkill/WMI/CIM/psutil
- [x] 未引入 StarRail/MAA/AALC
- [x] 未修改阶段 0 Schema
- [x] 未修改 ProcessSupervisor 核心
- [x] 未运行真实 MuMu 或 ADB
- [x] 未执行 Git commit
- [x] `phase-2a.md` 未修改
