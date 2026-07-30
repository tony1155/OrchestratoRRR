# OrchestratoRRR 阶段规划

Adapter 真实 smoke 门禁已于 2026-07-30 关闭。Phase 6 现正式拆分为 6A、6B、6C；当前只完成 6A 工作流契约与 Fake 编排内核，Phase 6 整体尚未完成。

## Phase 5——AALC Runtime Adapter

Fake AALC 环境和真实 AALC smoke 验收均已完成。成功仅依据 exit 0，最多三次尝试，只有非零退出和单次尝试超时允许重试。未实现完整工作流、公开 run CLI，未替换旧 PowerShell。

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
| 5 | AALC Adapter | 有界启动 AALC，最多三次尝试，仅非零退出和单次尝试超时允许重试 |
| 门禁 | Phase 6 前的真实 smoke | 已完成 StarRail、MAA、AALC 单 Adapter smoke 和人工评审；门禁已关闭，Phase 6 已获实施授权 |
| 6A | 工作流契约与 Fake 编排内核 | 冻结执行计划、惰性 Fake Stage、fail-fast、取消与父 Deadline 传播、RunReport 最终化和入口提权前置决策契约 |
| 6B | 生产 Stage 投影与真实组件绑定 | 将既有 Adapter、MuMu 生命周期和配置操作投影为生产 Stage；尚未实现 |
| 6C | 公开 run CLI 与完整验收 | 提供公开入口、完整 Fake 验收和受控真实工作流 smoke；尚未实现 |
| 7 | 打包与默认入口 | PyInstaller EXE、无缝替换旧 PS1 入口点 |

> **下一门禁：** 只有获得明确 start/stop/实例选择语法，并完成独立进程所有权验证后，才允许修改生产 start_arguments/stop_arguments。

每个阶段基于前一阶段构建，但不得退化先前阶段的测试。

Phase 6A 已固化入口权限规划契约：先构建完整计划；只要计划包含 `RUN_AALC` 且 AALC 声明 `requires_administrator=true`，就在 Runner 和任何 Stage 工厂构造前决定是否重启提升整个 OrchestratoRRR。不得在执行到 AALC 时才临时提升，也不得用 `runas` 绕过现有 ProcessSupervisor 单独启动 AALC。本阶段测试只使用 Fake gateway，未触发真实 UAC。

Phase 6B 尚未完成生产 Stage 绑定，MuMu 真实停启门禁仍存在，MAA 配置同步与更新也尚未实现。Phase 6C 尚未提供公开 run CLI，未执行任何真实完整工作流，因此旧 PowerShell 尚不可替换。
