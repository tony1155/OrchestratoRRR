# OrchestratoRRR

OrchestratoRRR 是一个面向 Windows 本地桌面自动化场景的有界进程编排器。

项目正在逐阶段替换旧的单体 PowerShell 编排流程，目标是可靠管理 MuMu Player、StarRailCopilot、MAA 和 AALC，并为每个外部进程提供明确的超时、取消、进程树清理和结构化结果。

> 当前阶段：Phase 2D——MuMu 候选 CLI 安全探针。
> 真实 MuMu 的 start、stop 和 restart 尚未获得生产使用批准。

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
