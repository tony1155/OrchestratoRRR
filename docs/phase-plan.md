# OrchestratoRRR 阶段规划

Adapter 真实 smoke 门禁已于 2026-07-30 关闭。6C2A、6C2B（含真实冷连接恢复）和 6C2C 均已完成验收，6C3 已完成文档收口。6B2B2B 与 6B2B3C 仍未完成，Phase 6 按已批准的 external-only 范围完成；Phase 7A1 已完成入口契约实现与自动测试，Phase 7 尚未完成。

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
| 6B1 | 生产 Stage 投影与安全绑定骨架 | 既有 Adapter 结果白名单投影、惰性 Runtime 绑定、单次运行状态和生产 ReportSink；默认计划在同步阶段安全阻断 |
| 6B2A | 旧流程静态契约调查 | 只读固化 MAA 同步/更新与 MuMu 控制的旧行为、顺序、超时和所有权证据；已完成 |
| 6B2B1 | 安全 MAA 配置同步 | 默认关闭；白名单转换、有界读取、原子替换/备份和双输出失败回滚；已完成 |
| 6B2B2A | 安全 MaaCore/资源更新 | 默认关闭并要求显式网络授权；固定 update 动词，复用 MAAAdapter 生命周期；已完成 |
| 6B2B2B | maa-cli 自更新决策 | CLI 自替换与包管理器所有权尚未闭合；继续阻断 |
| 6B2B3A | MuMu CLI 探针加固与否定证据 | 公开投影脱敏、模块执行警告修复；只读帮助仅证明 RPC/Shell 形状，未发现生命周期管理命令；已完成 |
| 6B2B3B | 外部管理 MuMu 生命周期模式 | 用户预先启动实例，OrchestratoRRR 只验证 readiness；动态计划安全跳过 stop/start；已完成 |
| 6B2B3C | managed 实例化生命周期控制 | start/stop 语法、实例选择和长期进程所有权尚未闭合；继续阻断 |
| 6C1 | 受控 external run CLI 与完整 Fake 验收 | 公开 external-only `run` v1、精确确认、有限 Deadline、入口提权接线与完整 Fake 验收；已完成 |
| 6C2A | ADB devices 空白分隔兼容修复 | 第一次真实 smoke 在 MuMu readiness 安全停止；修复空格、Tab 与混合分隔并增强安全诊断；已完成 |
| 6C2B | 修复后 readiness 与受控连接恢复 | 6C2B3 人工 connect 后 readiness 已验证；6C2B4A 完成显式 local TCP connect 的 Fake/自动测试；6C2B4C 完成真实冷连接自动恢复；已完成 |
| 6C2C | 修复后 external 真实完整工作流 smoke | 11 阶段 external 完整真实 smoke 已通过；AALC 在线业务 UI 因网络原因未验证；已完成 |
| 6C3 | Phase 6 最终验收、文档收口与合并准备 | 脱敏证据已固化，external-only 范围完成，等待人工审核；当前完成 |
| Phase 6 external scope | 已批准的 external-only 工作流范围 | Fake、生产 Adapter、冷连接恢复和完整真实 external workflow 均已验收；完成 |
| Phase 6 managed scope | MuMu managed 生命周期范围 | start/stop/restart 与实例自动选择继续阻断；未完成且不属于当前批准范围 |
| Phase 6 overall | Phase 6 按批准范围的状态 | 已批准的 external-only Phase 6 范围完成；不表示所有 MuMu 生命周期能力完成 |
| 7 | 打包与默认入口 | PyInstaller EXE、无缝替换旧 PS1 入口点 |

> **下一门禁：** 只有获得明确 start/stop/实例选择语法，并完成独立进程所有权验证后，才允许修改生产 start_arguments/stop_arguments。

每个阶段基于前一阶段构建，但不得退化先前阶段的测试。

Phase 6A 已固化入口权限规划契约：先构建完整计划；只要计划包含 `RUN_AALC` 且 AALC 声明 `requires_administrator=true`，就在 Runner 和任何 Stage 工厂构造前决定是否重启提升整个 OrchestratoRRR。不得在执行到 AALC 时才临时提升，也不得用 `runas` 绕过现有 ProcessSupervisor 单独启动 AALC。本阶段测试只使用 Fake gateway，未触发真实 UAC。

Phase 6B1 已完成生产投影与安全绑定骨架。默认完整生产计划在 `SYNC_MAA_CONFIG` 明确阻断，且阻断前不构造或执行任何 Runtime Adapter。MuMu 只允许只读 `status()`；start/stop 仍未获准。

Phase 6B2A 已完成旧流程静态契约调查，6B2B1 已完成安全 MAA 同步。Phase 6B2B2A 只实现固定 `maa update` 的 MaaCore/资源更新，默认关闭并要求显式网络授权；未执行真实更新。maa-cli 自更新与旧 hot-update 继续阻断于 6B2B2B。Phase 6B2B3A 的只读帮助证据仅确认 NemuShell RPC/Shell 调用形状，没有发现生命周期命令或安全实例选择器；`runtime_approved=false`。Phase 6B2B3B 提供 external 安全路径：用户预先启动正确实例，OrchestratoRRR 只验证 readiness，不调用 MuMu start/stop/restart；managed 模式仍保留静态 15 阶段，实例化控制继续阻断于 6B2B3C。

Phase 6C1 已提供受控 external-only `run` v1：精确确认、有限 Deadline、MAA Sync/Update 关闭、AALC attempts 为 1，并在 Runner/Stage factory/Adapter 前统一完成 elevation 决策。完整 Fake 验收已通过。第一次真实 external smoke 曾因旧解析器拒绝合法空格分隔的 ADB devices 记录而安全停止；6C2A 修复了解析兼容和脱敏诊断，6C2B4A 增加了受控 local TCP connect，6C2B4C 已完成真实冷连接自动恢复，6C2C 已完成 11 阶段 external 真实完整工作流 smoke。Phase 6C3 现已固化脱敏证据并完成 external-only 收口；6B2B2B、6B2B3C 仍未完成，Phase 7A1 已完成入口契约实现与自动测试，Phase 7 尚未完成，旧 PowerShell 尚不可替换。
## Phase 7A1 status

Phase 7A1 closes the source/frozen entry runtime and explicit UAC re-entry
contract with Fake/automatic tests. Source mode uses the Python module
entrypoint; frozen mode uses the executable directly. The launch specification
also carries an absolute configuration path and an explicit working directory.

Phase 7A2 now owns the completed PyInstaller onedir configuration and
RunReport schema resource collection. Phase 7D still owns the default user
entry and working-directory policy. The generated EXE is retained for the
future Phase 7B1 fixture-only smoke, and the legacy PowerShell entry remains
in place.

## Phase 7A2 status

Phase 7A2 is complete within its approved packaging/resource scope. The
version-controlled PyInstaller 6.21.0 onedir console spec and cwd-independent
build script collect only the canonical schema into the package resource
directory. Three historical attempts failed before a runnable onedir; the
fourth attempt completed after removing the invalid splash reference. The
artifact was audited statically only: no packaged CLI, UAC, ADB, or workflow
claim is made.

Phase 7B1 still owns packaged `version`, `--help`, fixture-only validate and
fixture-only plan smoke. Phase 7D still owns the default user entry and final
working-directory policy. The legacy PowerShell entry remains in place and
cannot yet be removed. Phase 7 is not complete.
## Phase 7B1 packaged CLI smoke

Phase 7B1 is complete for the approved packaged CLI smoke scope. The existing
onedir artifact passed source and packaged fixture-only `validate` and
`plan` from an external temporary working directory. The prior packaged
`version` and plain help results remain cumulative evidence from the same
committed artifact; neither was rerun in the diagnostic closure.

The packaged plan is the existing static 15-stage dry plan, with lowercase
stage values and a bundled-schema-valid RunReport. It must not be confused with
the production external 11-stage run contract. No packaged `run`, real UAC,
ADB, or business program was executed. Phase 7D remains the next blocker for
the default entry and final working-directory policy; Phase 7 is not complete.
