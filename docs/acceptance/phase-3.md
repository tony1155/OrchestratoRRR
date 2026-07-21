# 阶段 3 验收标准

> **状态:** 附注接受——Fake 环境完成，真实 StarRailCopilot smoke 待用户批准。

## 阶段范围

- 由本次 Adapter 启动的 StarRailCopilot 进程树管理
- 增量日志游标捕获与读取
- failure 关键词优先判定
- success 关键词完成判定
- 进程退出（含 exit 0）但无 success 关键词视为失败
- timeout / cancellation 清理进程树
- stdout/stderr 有界读取

## 配置字段

- `executable`、`working_directory`、`arguments`、`log_path_template`
- `success_keywords`、`failure_keywords`
- `environment_overrides`（`PYTHONIOENCODING`）
- `task_timeout_seconds`、`stop_timeout_seconds`

## 调用链

```text
StarRailAdapter.run()
→ 解析日志路径 → 捕获启动前游标 → ProcessSupervisor.launch()
→ 循环：cancel → deadline → 增量日志 → failure → success → 进程退出 → 有限等待
→ stop → 收集输出 → StarRailRunResult
```

## 日志游标

- 启动前已有内容视为旧日志，不读取
- 文件被截断或轮转时自动重新从头读取
- 每次读取最多 64 KiB，超过立即失败
- 滚动文本保留最近 64 KiB 用于跨读取的关键词匹配

## Fake 集成

所有集成测试真实经过：
```text
StarRailAdapter → ProcessSupervisor.launch() → sys.executable → fake_starrail.py
```

未 monkeypatch `run()`、`launch()` 或 `stop()`。

## 自动验收

| 命令 | 退出码 | 结果 |
|---|---|---|
| `ruff check .` | 0 | All checks passed |
| `ruff format --check .` | 0 | 通过 |
| `mypy src` | 0 | 34 source files |
| `pytest -q` | 0 | **309 passed** |
| `pytest tests/runtime/test_starrail_runtime.py` | 0 | **26 passed** |
| `pytest tests/config/test_starrail_config.py` | 0 | **16 passed** |
| completion 筛选 | 0 | 通过 |
| log_boundary 筛选 | 0 | 通过 |
| ownership 筛选 | 0 | 通过 |
| collected starrail tests | **26** |  |
| `git diff --cached --check` | 0 | 通过 |

## 安全边界

- [x] 未运行真实 StarRailCopilot
- [x] 未运行真实 MuMu/ADB
- [x] 未按进程名/端口/WMI 扫描
- [x] 未使用 subprocess.run/Popen/os.system
- [x] 未修改 ProcessSupervisor 核心
- [x] 未修改阶段 0 Schema
- [x] 未执行 Git commit
