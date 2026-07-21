# 阶段规划

本文档定义 Autogame Orchestrator 的阶段性路线。
各阶段严格按顺序实施，每个阶段完成前必须通过所有测试。

| 阶段 | 标题 | 范围 |
|---|---|---|
| 0 | 项目骨架与行为契约 | 包布局、数据模型、配置校验、CLI（version/validate/plan）、RunReport schema、JSONL 日志、测试套件、文档 |
| 1A | 进程基础契约与 Job Object 底座 | Deadline、CancellationToken、ProcessSpec、ManagedProcess、Win32 句柄封装、Job Object、CreateProcessW 启动器、Fake 程序扩展 |
| 1B | 通用进程监督器 | ProcessSupervisor 完整生命周期：launch/wait/run/stop/close、超时升级、取消升级、幂等关闭、进程树清理 |
| 2 | 探针层 | ADB 可用性探针、TCP 端口探针、进程存活探针 |
| 3 | MuMu Adapter | 通过 ADB 启动/停止/查询 MuMu 模拟器 |
| 4 | StarRail Adapter | 启动 StarRailCopilot、监控退出、捕获输出 |
| 5 | MAA Adapter | 启动 MAA CLI |
| 6 | AALC Adapter | 启动 AALC（支持重试） |
| 7 | 完整工作流 | 编排完整生命周期 |
| 8 | 打包与默认入口 | PyInstaller EXE、无缝替换旧 PS1 入口点 |

每个阶段基于前一阶段构建，但不得退化先前阶段的测试。
