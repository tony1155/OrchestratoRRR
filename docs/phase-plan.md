# OrchestratoRRR 阶段规划

## Phase 5——AALC Runtime Adapter

Fake AALC 环境完成；真实 AALC smoke 待批准。成功仅依据 exit 0，最多三次尝试，只有非零退出和单次尝试超时允许重试。未实现完整工作流、公开 run CLI，未替换旧 PowerShell。

本文档定义 Autogame Orchestrator 的阶段性路线。
各阶段严格按顺序实施，每个阶段完成前必须通过所有测试。

| 阶段 | 标题 | 范围 |
|---|---|---|
| 0 | 项目骨架与行为契约 | 包布局、数据模型、配置校验、CLI（version/validate/plan）、RunReport schema、JSONL 日志、测试套件、文档 |
| 1A | 进程基础契约与 Job Object 底座 | Deadline、CancellationToken、ProcessSpec、ManagedProcess、Win32 句柄封装、Job Object、CreateProcessW 启动器、Fake 程序扩展 |
| 1B | 通用进程监督器 | ProcessSupervisor 完整生命周期：launch/wait/run/stop/close、超时升级、取消升级、幂等关闭、进程树清理 |
| 2A | 本地运行时与 ADB 只读探测 | 本地 TCP 端口探测、ADB 命令执行（通过 ProcessSupervisor）、ADB devices 解析、设备选择、MuMu readiness 组合探测 |
| 2B | MuMu 生命周期适配器 | MumuAdapter：status/start/stop/restart、管理命令通过 ProcessSupervisor、空参数默认拒绝、真实控制尚未获准 |
| 2C | MuMu 管理命令发现 | 本机安装目录调查、候选文件元数据收集、安全性分类（B：候选存在但证据不足） |
| 2D | MuMu 候选 CLI 安全探针 | 诊断模块：固定帮助参数白名单、ProcessSupervisor 有界执行、受限输出收集；探针工具完成并完成安全收口；真实候选执行待安全窗口 |
| 3 | StarRail Adapter | 启动 StarRailCopilot、监控退出、捕获输出 |
| 4 | MAA Adapter | 启动 MAA CLI |
| 5 | AALC Adapter | 有界运行 AALC，最多三次尝试 |
| 5 | AALC Adapter | 启动 AALC（支持重试） |
| 6 | 完整工作流 | 编排完整生命周期 |
| 7 | 打包与默认入口 | PyInstaller EXE、无缝替换旧 PS1 入口点 |

> **下一门禁：** 只有获得明确 start/stop/实例选择语法，并完成独立进程所有权验证后，才允许修改生产 start_arguments/stop_arguments。

每个阶段基于前一阶段构建，但不得退化先前阶段的测试。
