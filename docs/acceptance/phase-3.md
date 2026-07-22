# 阶段 3 验收标准

> **状态:** 附注接受——Fake 环境完成，
> 真实 StarRailCopilot smoke 待用户批准。

## 完成项

- [x] 清理失败不再返回成功（所有终态记录实际 cleaned）
- [x] 所有终态通过 `_stop_and_collect()` 统一处理
- [x] 日志路径写入结果（`log_path` 字段）
- [x] 启动后首次日志文件记录 identity（rotated=False）
- [x] loader 严格拒绝错误类型和无效 environment
- [x] executable/working directory 类型检查
- [x] PID 文件和 PID 必须存在
- [x] Cleanup failure 映射测试（success + failure）
- [x] INTERNAL_ERROR 错误码
- [x] 日志路径结果测试
- [x] 首次文件 identity + 替换 rotation 测试
- [x] 配置非字符串字段拒绝测试
- [x] 配置 environment 缺失/错误类型拒绝
- [x] Smoke 文档使用正式 loader

## 自动验收

| 命令 | 实际结果 | 退出码 |
|---|---|---:|
| `python -m ruff check .` | `All checks passed!` | 0 |
| `python -m ruff format --check .` | `71 files already formatted` | 0 |
| `python -m mypy src` | `Success: no issues found in 34 source files` | 0 |
| diagnostics 单文件 | `28 passed in 3.21s` | 0 |
| diagnostics 目录 | `28 passed in 3.19s` | 0 |
| StarRail runtime | `32 passed in 3.79s` | 0 |
| StarRail config | `23 passed in 0.16s` | 0 |
| 完整 `pytest -q` 第一次 | `323 passed in 21.63s` | 0 |
| 完整 `pytest -q` 第二次 | `323 passed in 21.27s` | 0 |
| Phase 2D cancellation 压力验证 | `20/20 次通过` | 0 |

## 回归稳定性

Phase 2D 的 cancellation 测试已改为：

1. 启动真实 Fake CLI 进程；
2. 等待 PID 文件出现并包含有效正整数；
3. 再触发 `CancellationToken`；
4. 等待测试工作线程有界退出；
5. 精确断言 `CANCELLED`，不接受 `TIMEOUT`；
6. 验证具体 Fake PID 已退出。

该测试连续执行 20 次全部通过。

完整 `pytest -q` 未排除 diagnostics、未使用 skip、xfail、flaky marker 或 rerun 插件，并连续两次得到 `323 passed`。

StarRail child cleanup 测试强制验证：

- 父 PID 存在且已退出；
- 子 PID 文件存在；
- 子 PID 是正整数；
- 具体子 PID 已退出。

不存在条件跳过 PID 清理验证。

## 安全边界

- [x] 未运行真实 StarRailCopilot、MuMu、ADB、MAA 或 AALC
- [x] 自动测试只运行仓库 Fake 子进程
- [x] 未按进程名、端口或 WMI 扫描并终止进程
- [x] 生产 StarRail Adapter 未使用 `subprocess.run`、`subprocess.Popen` 或 `os.system`
- [x] 未修改 `ProcessSupervisor` 和 Win32 Job Object 核心
- [x] 完整测试未排除 diagnostics
- [x] 未增加 skip、xfail、flaky marker 或 rerun 插件
- [x] 真实 StarRailCopilot smoke 仍待用户明确批准

## 验收结论

Phase 3 的配置解析、受管进程启动、增量日志判定、失败优先、进程退出映射、超时、取消、清理失败映射、日志轮转、输出上限和父子进程树清理已在 Fake 环境完成自动验收。

**附注接受：Fake 环境完成，真实 StarRailCopilot smoke 待用户批准。**
