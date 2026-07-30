# OrchestratoRRR

Adapter 真实 smoke 门禁已于 2026-07-30 正式关闭。当前完成 Phase 6A 和 Phase 6B1——生产 Stage 投影与安全绑定骨架；Phase 6B2 和 Phase 6C 尚未实现，因此 Phase 6 整体尚未完成。脱敏 Adapter 证据见 [最终验收记录](docs/acceptance/adapter-real-smoke.md)。

Phase 5 后、Phase 6 前的单 Adapter 真实 smoke 门禁已经完成。诊断入口要求精确确认、有限 Deadline、单 Adapter 选择和原子安全结果；后续复验流程见 [统一门禁手册](docs/manual/adapter-real-smoke-gate.md)。

AALC 可通过 `requires_administrator = true` 声明管理员权限要求。普通权限 smoke 入口会在 Adapter 构造前请求一次 UAC，提升整个 OrchestratoRRR/Python 入口；拒绝 UAC 时安全停止。不会用 `runas` 单独启动 AALC，提升后仍保留 ProcessSupervisor 与 Job Object 契约。该 bootstrap 已纳入真实 smoke 验收，但不代表 Phase 6 已实现。

当前阶段：Phase 6B1——生产 Stage 投影与安全绑定骨架。既有 Adapter 结果通过白名单映射为 StageReport，Runtime 按 Stage 惰性构造且状态按运行隔离。默认完整生产计划在 `SYNC_MAA_CONFIG` 安全阻断，阻断前不构造或执行任何 Runtime Adapter。

OrchestratoRRR 是一个面向 Windows 本地桌面自动化场景的有界进程编排器。

项目正在逐阶段替换旧的单体 PowerShell 编排流程，目标是可靠管理 MuMu Player、StarRailCopilot、MAA 和 AALC，并为每个外部进程提供明确的超时、取消、进程树清理和结构化结果。

> cleanup failure、取消、路径、配置和启动失败均不重试。
> MuMu start/stop 仍未获准，MAA 配置同步和更新尚未实现，也未增加公开 run CLI；未执行真实完整工作流，未替换旧 PowerShell 编排入口。

## 当前能力

- Windows Job Object 进程树约束；
- `ProcessSupervisor` 有界启动、等待、超时、取消和清理；
- 本地 TCP 端口探测；
- ADB 版本、设备、状态和 Android 启动完成探测；
- MuMu readiness 组合探测；
- MuMu 生命周期适配器及默认拒绝策略；
- MuMu 候选 CLI 固定帮助参数诊断探针；
- JSONL 日志和结构化运行报告；
- 配置验证和静态执行计划。
- Phase 6A 冻结执行计划、Fake Stage 编排、失败/取消/Deadline 传播和 RunReport 最终化。
- Phase 6B1 Runtime 结果白名单投影、惰性生产绑定、每次运行独立状态和生产 ReportSink。

## 当前安全边界

- 生产 MuMu `start_arguments` 和 `stop_arguments` 默认保持为空；
- 未经验证的 `MuMuNxDevice.exe`、`MuMuNxMain.exe` 或底层 VMM 工具不会作为管理命令执行；
- MuMu CLI 探针只允许 `--help`、`-h`、`/?`；
- 帮助文本发现不代表管理命令获得生产批准；
- 只有获得明确的 start、stop、实例选择语法，并完成进程所有权验证后，才能解除真实 MuMu 控制阻塞；
- 当前阶段不启动 StarRailCopilot、MAA 或 AALC。

## 系统要求

- Windows 10 或更高版本；
- Python 3.11 或更高版本；
- PowerShell；
- 建议使用项目独立虚拟环境。

## 安装

```powershell
git clone https://github.com/tony1155/OrchestratoRRR.git
Set-Location OrchestratoRRR

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## 基础命令

### 输出版本

```powershell
python -m autogame_orchestrator version
```

或：

```powershell
autogame-orch version
```

### 验证配置结构

```powershell
python -m autogame_orchestrator validate `
  --config config/orchestrator.example.toml
```

### 验证真实路径

```powershell
python -m autogame_orchestrator validate `
  --config config/orchestrator.example.toml `
  --check-paths
```

### 输出静态执行计划

```powershell
python -m autogame_orchestrator plan `
  --config config/orchestrator.example.toml
```

`validate` 和 `plan` 不启动 MuMu、ADB 或其他业务程序。

## MuMu CLI 安全探针

诊断入口：

```powershell
python -m autogame_orchestrator.diagnostics.mumu_cli_probe `
  --candidate 'D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuManager.exe' `
  --candidate 'D:\Program Files\Netease\MuMu Player 12\nx_device\12.0\shell\NemuShell.exe' `
  --attempt-timeout-seconds 3 `
  --total-timeout-seconds 10
```

该命令只能尝试固定帮助参数：

```text
--help
-h
/?
```

运行真实候选前，必须先确认 MuMu 用户进程已经退出。当前仓库中的阶段 2D 调查因安全门禁未通过而没有执行真实候选程序。

## 配置

复制示例配置：

```powershell
Copy-Item `
  config/orchestrator.example.toml `
  config/orchestrator.local.toml
```

本地配置文件已被 Git 忽略。

在真实 MuMu 管理命令获得批准前，必须保持：

```toml
start_arguments = []
stop_arguments = []
```

## 测试

```powershell
python -m pytest -q
```

仅运行 diagnostics：

```powershell
python -m pytest -q tests/diagnostics
```

## 代码质量

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy src
```

## 项目结构

```text
src/autogame_orchestrator/
├─ process/       Windows 进程、Job Object 和监督器
├─ probes/        TCP、ADB 和 MuMu readiness 探测
├─ runtime/       MuMu 生命周期适配器
└─ diagnostics/   受限诊断工具

tests/
├─ fakes/         独立 Fake 子进程
├─ process/
├─ probes/
├─ runtime/
└─ diagnostics/

docs/
├─ acceptance/      阶段验收记录
├─ architecture.md  当前架构与边界
├─ investigations/  调查证据
└─ manual/          仅供用户执行的手工步骤
```

## 开发状态

| 阶段 | 状态 |
|---|---|
| Phase 0 | 项目骨架与行为契约完成 |
| Phase 1A | Win32 进程约束基础完成 |
| Phase 1B | ProcessSupervisor 生命周期完成 |
| Phase 2A | 本地 TCP、ADB 和 readiness 探测完成 |
| Phase 2B | MuMu 生命周期适配器完成，真实控制未批准 |
| Phase 2C | MuMu 管理命令调查完成，证据分类 B |
| Phase 2D | CLI 安全探针开发中，真实候选待安全窗口 |

## 许可证

本项目使用 MIT License。
