# 阶段 2D 验收标准

> **状态:** 待用户验收。请勿自行勾选。
> **阶段结论:** 附注接受——探针工具完成，真实候选执行待安全窗口。

## 阶段目标

实现 MuMu 候选 CLI 安全诊断探针，对白名单候选文件依次执行固定帮助参数，收集受限输出并判定帮助证据。

## 新增模块

| 模块 | 职责 |
|---|---|
| `diagnostics/mumu_cli_probe.py` | MumuCliProbe、数据模型、CLI 入口 |
| `diagnostics/__init__.py` | 包初始化，公开导出 |
| `tests/fakes/fake_mumu_cli.py` | Fake CLI（7 种模式） |
| `tests/diagnostics/test_mumu_cli_probe.py` | 22 项测试 |

## 固定安全边界

- [x] 仅允许 `--help`、`-h`、`/?` 三个帮助参数
- [x] 仅允许 `MuMuManager.exe` 和 `NemuShell.exe` 两个候选
- [x] 禁止 `MuMuNxMain.exe`、`MuMuNxDevice.exe`、`MuMuVMMManage.exe`、`MuMuVMMHeadless.exe`
- [x] 禁止 start/stop/restart/launch/shutdown/quit 命令
- [x] 单次超时 3 秒，总超时 10 秒
- [x] stdout/stderr 各 64 KiB 上限
- [x] `runtime_approved` 始终为 `False`

## 自动验收

| 命令 | 退出码 | passed/failed |
|---|---|---|
| `ruff check .` | 0 | All checks passed |
| `ruff format --check .` | 0 | 65 files |
| `mypy src` | 0 | 31 source files |
| `pytest -q` | 0 | 260 passed |
| `pytest tests/diagnostics` | 0 | 22 passed |
| `pytest -k 'help or utf16 or output or timeout or cancellation or deadline'` | 0 | 9 passed/13 deselected |
| `pytest -k 'validate_candidate or forbidden or cli or json'` | 0 | 12 passed/10 deselected |

## 安全边界

- [x] 生产代码未使用 subprocess.run 等禁用调用
- [x] 未启动真实 MuMu/ADB
- [x] 未修改 process/probes/runtime 包
- [x] 未修改 config_model.py
- [x] 未修改阶段 0 Schema
- [x] 未执行 Git commit
