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
- [x] 24 项 diagnostics 测试
- [x] `runtime_approved` 始终 `False`

## 自动验收

| 命令 | 退出码 | 结果 |
|---|---|---|
| `ruff check .` | 0 | All checks passed |
| `ruff format --check .` | 0 | 通过 |
| `mypy src` | 0 | 通过 |
| `pytest -q` | 0 | 全量通过 |
| `pytest tests/diagnostics` | 0 | diagnostics 测试通过 |
