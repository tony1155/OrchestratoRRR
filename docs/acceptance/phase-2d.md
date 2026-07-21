# 阶段 2D 验收标准

> **状态:** 附注接受——探针工具完成，真实候选执行待安全窗口。

## 完成项

- [x] 固定帮助参数白名单（`--help`、`-h`、`/?`）
- [x] 候选白名单 + 禁止名单验证
- [x] UTF-8 优先解码（BOM + strict + 回退）
- [x] UTF-16LE 检测（NUL 比例判断 + BOM 检测）
- [x] 系统首选编码回退
- [x] 用户目录路径脱敏（`_redact_user_home`）
- [x] START_FAILED 聚合 reason
- [x] CLI 禁止候选 + 未知参数退出码 2
- [x] Fake CLI 通过 ProcessSupervisor 真实执行
- [x] timeout PID 逐 PID 清理验证
- [x] cancellation PID 逐 PID 清理验证
- [x] 总 Deadline 不重置（sleep_forever 实测）
- [x] 无意义延迟已删除
- [x] README 和品牌名更新（OrchestratoRRR）
- [x] 28 项 diagnostics 测试（pytest 收集确认）
- [x] `runtime_approved` 始终 `False`
- [x] README UTF-8 无 BOM
- [x] 调试残留 `debug_utf16.txt` 已从版本控制和工作树移除
- [x] 精确品牌版本输出（`OrchestratoRRR {__version__}`）
- [x] pyproject description 一致性测试（含 "Windows"）

## 自动验收

| 命令 | pass/deselect | 退出码 |
|---|---|---|
| `ruff check .` | All checks passed | 0 |
| `ruff format --check .` | 65 files | 0 |
| `mypy src` | 31 source files | 0 |
| `pytest -q` | 268 passed | 0 |
| `pytest -q tests/diagnostics` | 28 passed | 0 |
| `pytest -q tests/diagnostics/test_mumu_cli_probe.py` | 28 passed | 0 |
| boundary 筛选 | 12 passed, 16 deselected | 0 |
| validation 筛选 | 28 passed | 0 |
| `pytest -q tests/cli/test_cli.py` | 14 passed | 0 |

## 边界测试持续时间（本次验收环境）

| 测试 | 本次持续时间 | PID 验证 |
|---|---|---|
| `test_timeout_is_bounded_and_process_exits` | 0.37s | ✓ 具体 PID 已退出 |
| `test_cancellation_is_not_timeout` | 0.22s | ✓ 具体 PID 已退出 |
| `test_total_deadline_not_reset_between_arguments` | 0.81s | ✓ 具体 PID 已退出 |

以上为本次验收环境中的 pytest 测试持续时间，不是性能承诺。

## 调试残留

- `debug_utf16.txt` 已从版本控制和工作树移除
- 仓库中无其他本阶段生成的调试输出、PID 文件、临时输出或日志

## 安全边界

- 生产代码未使用 subprocess.run/Popen/os.system/shell=True
- 未启动真实 MuMu/ADB
- 未修改 process/probes/runtime 包
- 未修改 config_model.py
- 未修改阶段 0 Schema
- 未修改历史验收文件（phase-2a、phase-2b、phase-2c）
- 未执行 Git commit
