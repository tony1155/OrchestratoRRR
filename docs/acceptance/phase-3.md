# 阶段 3 验收标准

> **建议状态:** 附注接受——Fake 环境完成，
> 真实 StarRailCopilot smoke 待用户批准。

## 完成项

- [x] 清理失败不再返回成功（所有终态记录实际 cleaned）
- [x] 所有终态通过 `_stop_and_collect()` 统一处理
- [x] 日志路径写入结果（`log_path` 字段）
- [x] 启动后首次日志文件记录 identity（rotated=False）
- [x] loader 严格拒绝错误类型和无效 environment
- [x] executable/working directory 类型检查
- [x] PID 文件和 PID 必须存在（6 个测试精确断言）
- [x] Cleanup failure 映射测试（success + failure）
- [x] INTERNAL_ERROR 错误码
- [x] 日志路径结果测试
- [x] 首次文件 identity + 替换 rotation 测试
- [x] 配置非字符串字段拒绝测试（8 个新增）
- [x] 配置 environment 缺失/错误类型拒绝
- [x] Smoke 文档使用正式 loader

## 测试数量

| 命令 | 实际结果 | 退出码 |
|---|---|---|
| `ruff check .` | All checks passed | 0 |
| `ruff format --check .` | 71 files | 0 |
| `mypy src` | 34 source files | 0 |
| `pytest -q`（不含 diagnostics） | 295 passed | 0 |
| `pytest tests/runtime/test_starrail_runtime.py` | **32 passed** | 0 |
| `pytest tests/config/test_starrail_config.py` | **23 passed** | 0 |
| completion 筛选 | 16 passed, 16 deselected | 0 |
| log_boundary 筛选 | 10 passed, 22 deselected | 0 |
| ownership 筛选 | 4 passed, 28 deselected | 0 |
| config_boundary 筛选 | 14 passed, 9 deselected | 0 |
| collected runtime tests | **32** | — |
| collected config tests | **23** | — |

## 安全边界

- [x] 未运行真实 StarRailCopilot/MuMu/ADB
- [x] 未按进程名/端口/WMI 扫描
- [x] 未使用 subprocess.run/Popen/os.system
- [x] 未修改 ProcessSupervisor 核心
- [x] 未修改阶段 0 Schema
- [x] 未执行 Git commit
