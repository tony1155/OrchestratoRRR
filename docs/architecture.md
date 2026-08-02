# OrchestratoRRR 架构

## 当前验证状态

StarRail、MAA、AALC 的受控真实 Adapter smoke 已于 2026-07-30 完成脱敏验收。Phase 6C2A、
6C2B4C 和 6C2C 的修复后真实证据均已通过：冷连接恢复成功，external 11 阶段完整 workflow
成功，RunReport 完整可读。maa-cli 自更新与 MuMu managed 实例化生命周期控制仍未完成；
Phase 6 已按批准的 external-only 范围完成，Phase 7A1 已完成入口契约实现与自动测试，
Phase 7 尚未完成。

## Phase 6 前的真实 smoke 门禁

`diagnostics.adapter_smoke` 是用户手工触发的受限诊断入口，不是公开生产 run CLI，也不属于完整工作流。它在精确确认后使用正式配置加载器，仅校验并构造所选 Adapter，传入有限 Deadline 和取消令牌，再将安全字段投影原子写入 JSON。真实进程的启动与清理仍完全由现有 Adapter 和 ProcessSupervisor 负责。

该门禁不编排 MuMu/ADB，不串联多个 Adapter，不记录本机路径、环境值、输出原文或 PID 数值。三个 Adapter 的脱敏真实 smoke 证据现已完成验收，详细记录见 `docs/acceptance/adapter-real-smoke.md`。

`platform.windows_elevation` 提供可复用的入口级 Windows 自提权 API。它先用进程 Token 判断权限，再通过 `ShellExecuteExW` 的 `runas` 提升当前 Python 模块，等待子入口结束并转发退出码。普通父入口不构造 Adapter 或 ProcessSupervisor；提升后的入口继续走 ProcessSupervisor → CreateProcessW(CREATE_SUSPENDED) → Job Object → ResumeThread。UAC 取消和提权失败分别使用独立稳定结果，命令行只转发既有 CLI 参数和路径，不传递配置内容或环境敏感值。

Phase 6A 已将入口权限决策固定在 Runner 之前：先构建完整计划，判断计划是否包含要求管理员权限的 AALC，必要时请求提升整个 OrchestratoRRR，权限满足后才允许构造 Runner 和惰性 Stage 工厂。不得运行到 AALC 阶段才临时提升。本阶段只测试可注入 Fake gateway，没有触发真实 UAC。

## Phase 6A 工作流内核

`workflow.plan.ExecutionPlan` 是冻结计划模型，并与既有 `planning.build_plan()` 的十五阶段顺序保持一致。`workflow.runner.WorkflowRunner` 只在阶段到达时请求 `StageExecutorFactory`；首次失败、超时、取消、非法结果、缺失绑定或异常后立即停止，剩余业务阶段写为 `SKIPPED`。所有到达的 Stage 共享同一 `run_id`、`CancellationToken` 和父 `Deadline`，Runner 不重置预算，也不提供全工作流重试。

`WRITE_RUN_REPORT` 是 Runner 内部最终化阶段，不向工厂请求执行器。无论业务结果如何，注入的报告 sink 只尝试一次；写入失败时，内存报告以 `RUN_REPORT_WRITE_ERROR` 为顶层错误，并用稳定诊断字段保留先前业务错误。核心继续复用 RunReport v1、`StageReport` 和 `RunReport`，没有建立第二套 schema。

工作流核心不导入具体 Runtime Adapter、`ProcessSupervisor` 或 Win32 API。具体 Adapter 只允许由 `workflow/production/runtime_bindings.py` 的 composition root 导入。

## Phase 6B1 生产绑定骨架

`workflow/production/` 定义最小 Runtime Port、白名单结果投影、每次运行独立状态、惰性 Runtime 缓存、生产 StageExecutor 和复用 `write_report_atomic()` 的 ReportSink。构建 factory 只创建闭包；Stage 到达前不创建 Adapter，同一 Runtime 在一次运行内最多构造一次，完整结果对象不会进入工作流状态。

配置验证 Stage 只调用 `validate()` 与 `check_paths()`。StarRail、MAA、AALC Stage 原样传递父 Deadline 和 CancellationToken，复用既有 Adapter 生命周期；Stage 外层不重试。MuMu 的 managed 和 WAIT 阶段使用只读 `status()`；external 的 ENSURE 阶段使用显式 ensure，其余 readiness 仍只读；ADB 端点只接受 `127.0.0.1:<1-65535>`。StarRail 停止/验证 Stage 只检查本次受管进程清理证据，不扫描系统进程。

默认完整生产计划在 `SYNC_MAA_CONFIG` 返回 `WORKFLOW_STAGE_BLOCKED`，阻断前 Runtime 构造数为零。

## Phase 6B2A 旧流程静态契约调查

Phase 6B2A 只通过 PowerShell Parser/AST、文本和文件元数据调查旧流程，没有执行旧脚本、真实程序、网络或 UAC。调查确认旧同步会生成并直接覆盖两个目标配置，旧更新按开关顺序执行有限命令，且二者失败均阻断后续流程；但原子替换、隐私白名单、更新子进程和取消契约仍未闭合。

旧 MuMu 流程直接管理长期 GUI 进程，并通过进程树和安装根候选集合停止，不提供可验证的管理 CLI 或精确实例选择器。该模型与当前“短管理命令受管、长期模拟器仅做 readiness 验证”的安全边界不直接兼容，错误绑定到 kill-on-close Job 可能终止刚启动的长期进程。因此 MuMu start/stop 仍为 `UNSAFE`，实例选择为 `BLOCKED`，所有权仅为 `PARTIAL`。

6B2 已继续拆分为 6B2A 调查、6B2B1 安全同步、6B2B2A MaaCore/资源更新、6B2B2B maa-cli 自更新决策与 6B2B3 MuMu 实例化控制。完整调查见 `docs/acceptance/phase-6b2a-discovery.md`。

## Phase 6B2B1 安全 MAA 配置同步

`maa_sync` 包将 GUI 根对象通过显式字段白名单纯转换为 CLI profile/tasks。同步器在触碰目标前完成双源有界读取、转换、编码和目标快照；目标临时文件与备份均 flush/fsync，并通过同目录 `os.replace()` 原子提交。第二个目标失败、取消或父 Deadline 到期时回滚已替换的首目标，回滚失败使用独立稳定错误码。

同步默认关闭，关闭时不构造同步器。启用后生产 Stage 惰性构造服务并原样传递父 Deadline 与 CancellationToken，只投影稳定错误码和布尔状态。源/目标路径、配置值、异常文本和临时文件信息不会进入 StageReport 或 RunReport。

## Phase 6B2B2A 安全 MaaCore/资源更新

`[maa_update]` 默认关闭并默认禁止网络，只允许固定 `update` 动词。启用且显式授权网络后，composition root 用冻结配置替换既有 MAA 参数和 timeout，继续复用 MAAAdapter → ProcessSupervisor → Job Object 生命周期，不复制监督器，也不增加 Stage 或工作流重试。

UPDATE_MAA 关闭时直接安全跳过且不构造 Port；启用时原样传递父 Deadline 和 CancellationToken。投影只包含稳定错误码、终止原因、退出码、清理与截断布尔值，不记录 PID、输出、参数、路径、环境或原始 diagnostics。

入口权限计划现在综合 AALC、启用的 MAA Sync 和启用的 MAA Update 管理员要求，并继续在 Runner/Stage factory 前统一决策。默认计划不再无条件阻断于 UPDATE_MAA：MuMu STOPPED 时在 ENSURE_MUMU_RUNNING 安全阻断，READY 时可以继续；STOP_MUMU 仍无条件禁止。

maa-cli 自更新属于安装生命周期，6B2B2B 继续阻断；旧 hot-update 缺少当前正式命令证据，也不属于生产能力。MuMu start/stop/实例选择继续留在 6B2B3。Phase 6B2、Phase 6B 和 Phase 6 整体均未完成；Phase 6C 才会增加公开 run CLI 和真实完整工作流验收。

## Phase 6B2B3A MuMu CLI 探针否定证据

2026-07-30 的受控只读帮助探针仅发现 NemuShell 的 `<HOST_NAME> <RPC_INSTANCE> <CMD>` RPC/Shell 调用形状，没有发现启动、关闭或重启实例的生命周期命令，也没有解析出可验证的管理实例选择器。`RPC_INSTANCE` 不得视为生命周期管理实例编号，`runtime_approved=false`。

诊断公开 JSON 已移除候选绝对路径和 stdout/stderr excerpt，只保留输出存在性、截断标志与固定白名单 marker；候选错误只返回稳定代码。诊断包不再提前导入模块，`python -m` 入口无 RuntimeWarning 且成功 stdout 为单一 JSON document。该否定证据不授权 managed start/stop 或实例选择；相关生产控制继续阻断于 6B2B3C。

## Phase 6B2B3B 外部管理 MuMu 模式

`MumuLifecycleMode` 提供稳定的 `managed` 与 `external` 枚举，默认 managed 以保持既有配置和静态 15 阶段计划兼容。external 要求 MuMu 已由用户或外部工具启动；配置不要求 MuMu executable，但仍严格要求本地 ADB executable/serial，且拒绝任何 start/stop arguments。

动态 `build_execution_plan(config)` 在未显式传入 stages 时为 external 精确移除 STOP_MUMU、VERIFY_MUMU_STOPPED、START_MUMU 和重启后的 readiness 阶段，保留初始 ENSURE/WAIT readiness，形成 11 阶段计划。显式 stages 不会被模式静默改写，公开 `plan` 仍使用静态 15 阶段。

生产绑定向 external Stage 暴露只读 `status()` 和显式 `ensure_external_ready()` Port。ENSURE 未达 ready 时按现有 Stage 投影阻断或失败；仅该显式 ensure 可在严格条件下尝试一次配置目标 connect，WAIT 和普通 status 不调用 connect。不调用 start/stop/restart，也不扫描进程、读取 `.nemu` 或解析 RPC instance。external MuMu 路径不增加生命周期控制权限；完整 external workflow 因 AALC 的入口权限要求仍可在 Runner 前统一请求 UAC。该模式不等价于旧 PowerShell 的完整生命周期行为，managed 控制留待 6B2B3C 且尚未获授权。

## Phase 6C1 受控 external run 入口

公开 `autogame-orch run` 首版只接受动态 11 阶段 external 计划，并在任何 Runner、Stage factory 或 Adapter 构造前校验精确确认值、有限父 Deadline、MAA Sync/Update 均关闭及 AALC attempts 为 1。CLI 不暴露阶段选择、跳过或强制执行参数；静态 `plan` 命令继续显示兼容的 15 阶段计划。

生产 application composition root 复用 `WorkflowCoordinator` 和现有 Windows elevation API。权限不足时，普通父入口先提升整个 OrchestratoRRR，再由提升子入口打开 JSONL、构造 `workflow_external` Runner、惰性 production executor factory 和 ProductionReportSink。普通父入口不构造 Adapter、不写第二份报告，并原样转发子入口退出码；UAC 取消与提升失败分别使用稳定退出码 9 和 10。UAC 等待时间不计入子入口根据原始秒数建立的业务 Deadline，两进程不共享内存 Deadline。

SIGINT handler 只取消同一个 CancellationToken，并在退出时恢复原 handler。Runner 不增加全工作流重试，对所有终态只尝试一次报告写入。run 控制台、JSONL 和 RunReport 不记录配置路径、设备地址、PID、输出原文或完整命令。Phase 6C1 只执行 Fake 验收；真实 external 工作流留待 Phase 6C2 由操作者按手册执行，Phase 6C3 和 Phase 6 最终收口尚未开始。

## Phase 6C2A ADB 解析兼容与安全诊断

第一次 external 真实工作流 smoke 已按批准执行一次，在 `ENSURE_MUMU_RUNNING` 以 `READINESS_FAILED` 安全停止。后续脱敏只读证据确认：ADB 命令正常退出、标题有效且存在一个合法状态设备行，但该行使用空格分隔，旧解析器因仅接受 Tab 而返回 `ADB_OUTPUT_INVALID`。StarRail、MAA 和 AALC 均未启动，MuMu start/stop/restart 均未调用。

Phase 6C2A 仅将设备记录改为按连续空白切分，兼容空格、Tab 和混合格式；标题位置、最少 token、重复 serial、状态和属性语义保持严格。MuMu Runtime 与生产投影只增加固定枚举值 `probe_status`、`probe_error`、`probe_step`，不传递 detail、设备地址、端口、路径或输出。未增加 ADB connect/server restart、重试、轮询或 Deadline 重置，external 11 阶段计划不变。修复后 readiness 留待 6C2B，修复后完整 smoke 留待 6C2C。

## Phase 6C2B4A 受控 external ADB 连接

Phase 6C2B3 只证明人工 connect 后 readiness 正确。Phase 6C2B4A 增加显式 external
ensure：普通 status() 和 probe() 继续只读，只有 external 的 ENSURE_MUMU_RUNNING 才可
在初始设备选择 DEVICE_NOT_FOUND、TCP 已通过、目标严格为配置的 127.0.0.1:port 且
Deadline/取消状态允许时执行一次 connect，随后最多做一次完整 readiness 复验。不会连接
emulator 或其他 host，不扫描端口，不选择 fallback。

ADB server 是 adb 客户端的默认服务入口，MuMu endpoint 是被连接的目标。OrchestratoRRR
不显式调用 adb start-server，不拥有 ADB server 生命周期，也不调用 adb kill-server 或
adb disconnect；普通 ADB 客户端命令可能按 ADB 自身行为使用或拉起默认 server。完整
workflow 成功后 WAIT_MUMU_ADB_READY 仍会额外执行一次只读 readiness，不能把整个 workflow
概括为最多两次 readiness。

Phase 6C2B4C 已完成真实冷连接自动恢复验收：精确目标由测试准备阶段一次性断开，生产
ENSURE_MUMU_RUNNING 单次执行并由生产路径触发一次受控 connect，随后 readiness 复验通过。
Phase 6C2C 已完成 external-only 11 阶段真实工作流 smoke；详细脱敏证据见对应 acceptance
文档。Phase 6C3 已完成 external-only 范围收口，但不表示 MuMu managed 生命周期能力完成。

## Phase 5——AALC Runtime Adapter

Fake AALC 环境和真实 AALC smoke 脱敏验收均已完成。AALCAdapter 通过 ProcessSupervisor 创建独立 Job Object 尝试，成功仅依据 exit 0，最多三次尝试。只有非零退出和单次尝试超时可重试；cleanup failure、取消、路径、配置和启动失败不重试。

## 当前状态

Phase 5——AALC Runtime Adapter（Fake 环境和真实 smoke 验收均已完成）。

自动测试只启动仓库 Fake 子进程；未启动任何真实业务程序。

## 项目身份

OrchestratoRRR 是一个**独立的、不与旧项目共享目录的**新编排器。
旧版 `Invoke-LocalOrchestrator.ps1` 作为回退实现保留，本项目不会修改或消费它。

## 阶段 1A 新增

阶段 1A 在 `src/autogame_orchestrator/process/` 包中新增：

| 模块 | 职责 |
|---|---|
| `deadline.py` | 基于 `time.monotonic()` 的硬截止时间 |
| `cancellation.py` | 基于 `threading.Event` 的一次性取消令牌 |
| `models.py` | `ProcessSpec`（冻结启动规格）、`ManagedProcess`（可变生命周期） |
| `errors.py` | `ProcessLaunchErrorCode` 枚举 |
| `win32_handles.py` | Win32 `CloseHandle` 的幂等、安全封装 |
| `win32_job.py` | Job Object：创建、KILL_ON_JOB_CLOSE 配置、进程分配、终止 |
| `win32_process.py` | `CreateProcessW(CREATE_SUSPENDED)` 和 `ResumeThread` 的 ctypes 封装 |
| `launcher.py` | 启动编排器：挂起→Job→分配→恢复流程 |

阶段 1A 不包含 `ProcessSupervisor`（完整生命周期编排），该功能留到阶段 1B。

## 阶段 0 边界（已冻结）

Phase 0 delivers:

| Artifact | Role |
|---|---|
| `pyproject.toml` | Package metadata, dependencies, tool config |
| `src/autogame_orchestrator/` | Production source tree |
| `models.py` | Pure-data models: ErrorCode, StageReport, RunReport |
| `config_model.py` | Configuration dataclasses |
| `config_loader.py` | TOML parsing + structural validation + ErrorCode mapping |
| `cli.py` | `version`, `validate`, `plan` commands |
| `planning.py` | Static execution-plan builder |
| `reporter.py` | RunReport schema validation + atomic JSON writer |
| `log_writer.py` | Synchronous JSONL structured-log writer |
| `schemas/` | RunReport v1 JSON Schema + golden sample |
| `tests/` | Unit, CLI, and contract tests |
| `docs/` | Architecture, phase plan, ADRs, acceptance criteria |

Phase 0 explicitly does **NOT** implement:
- Process supervision (Job Object, ProcessSupervisor)
- MuMu / ADB / SRP / MAA / AALC adapters
- Real program launching or probing
- Network access
- GUI or system-tray integration
- EXE packaging

## Dependency Direction

```
tests/
  └─► src/autogame_orchestrator/
        ├─ models.py         (no deps beyond stdlib)
        ├─ config_model.py   (→ models.py)
        ├─ config_loader.py  (→ config_model.py, models.py)
        ├─ planning.py       (→ models.py)
        ├─ log_writer.py     (→ models.py)
        ├─ reporter.py       (→ models.py, schema on disk)
        └─ cli.py            (→ config_loader, planning, log_writer, reporter, models)
```

Production code (`src/`) must never import from `tests/`.

## Key Design Decisions

1. **No Pydantic** — plain frozen dataclasses with explicit validation.
   Avoids implicit type coercion; every error maps to a single ErrorCode.

2. **Stable ErrorCodes** — descriptive enum strings (`CONFIG_FILE_NOT_FOUND`),
   not log-text-derived or numeric-only codes.

3. **`--check-paths` opt-in** — structural config validation does not touch
   the filesystem by default. Path existence checks require an explicit flag.

4. **Atomic RunReport writes** — temp file + flush + fsync + os.replace.
   No half-written final reports.

5. **Synchronous JSONL** — no async queues or background threads at this stage.

## Phase 7A1 Frozen Entry and UAC Re-entry

Phase 7A1 introduces a single immutable EntryRuntime model with SOURCE and
FROZEN kinds and a single runtime detection boundary. Detection uses only
getattr(sys, "frozen", False) and captures the current executable and working
directory when requested. It does not use packager-private extraction state or
spread packager-specific logic through the workflow.

Elevation now receives an immutable ElevationLaunchSpec containing the
executable, argument tuple, and working directory. Source children use
python.exe -m autogame_orchestrator run ...; frozen children use
OrchestratoRRR.exe run .... The configuration path is made absolute during
spec construction. The platform layer uses the supplied working directory and
executable and does not reread process state.

The elevation marker, UAC cancellation and failure mappings, handle cleanup,
exit-code forwarding, and pre-Runner permission boundary remain unchanged.
Phase 7A1 uses only Fake and automatic tests. Packaging resources, EXE
generation, the default shortcut/working-directory policy, real frozen UAC,
and legacy PowerShell replacement remain future work.

## Phase 7A2 PyInstaller resources

Phase 7A2 defines a controlled PyInstaller 6.21.0 onedir console build.
`packaging/entrypoint.py` delegates directly to the formal Typer app, while
`packaging/OrchestratoRRR.spec` collects only the canonical RunReport schema
as project data. It does not collect docs, tests, config, logs, run-results,
real configuration, or business executables.

`resource_paths.resolve_run_report_schema_path()` is the single schema lookup
boundary. Source mode uses the repository-root `schemas/` location; frozen
mode uses the fixed `_resources/` directory beside the bundled package. It
does not use the current working directory, search parent directories, or
`sys._MEIPASS`. A missing resource fails closed with a stable internal
exception and never silently skips JSON Schema validation.

The build script is cwd-independent and verifies the onedir EXE, its internal
directory, and the bundled schema without executing the EXE. The first three
historical attempts failed before a runnable onedir; the third left only a
partial root-level EXE. Phase 7A2C removed the invalid splash reference and
completed historical build attempt 4. Static audit confirmed the expected
onedir layout, canonical schema hash, project-resource boundary, and privacy
boundary. Packaged CLI behavior, frozen UAC, and a real workflow remain
unvalidated. Phase 7B1 still owns packaged CLI smoke, Phase 7D still owns the
default entry and working-directory policy, and the legacy PowerShell entry
remains retained.
## Phase 7B1 packaged CLI smoke status

Phase 7B1 is complete within its fixture-only packaged CLI scope. The retained
onedir artifact passed source and packaged `validate -> plan` comparison from a
repository-external temporary working directory. Packaged `version` and plain
root help evidence was accumulated from the same committed artifact; the
current diagnostic did not rerun either command.

The public `plan` command remains a static 15-stage dry plan and uses the
lowercase `StageName.value` representation in both console output and
RunReport. The production external run contract remains a separate controlled
11-stage plan. Validate and plan reports were independently checked with the
bundled RunReport schema. No packaged `run`, real UAC, ADB, or business program
was executed. Phase 7D still owns the default entry and final working-directory
policy, and the legacy PowerShell entry remains retained.

## Phase 7B2A isolated workflow entry

Phase 7B2A adds the hidden `_isolated-workflow-smoke` command for diagnostic
coverage of the packaged workflow entry. It accepts only an existing empty
workspace, a bounded deadline, and the exact synthetic-execution confirmation.
It generates its own inert configuration and reuses `execute_run_request` with
the formal production composition boundary.

The command injects only in-process synthetic Runtime implementations. It does
not use the default Runtime factory, concrete business adapters,
ProcessSupervisor, TCP/ADB probes, or Windows elevation. The resulting report
uses the strict `workflow_isolated` mode and the same controlled external
11-stage plan; the default production mode remains `workflow_external`.

Phase 7B2A source tests and one source-only hidden smoke passed. A new PyInstaller
6.21.0 onedir console artifact was built once and statically audited; the EXE
was not executed. Phase 7B2B owns the packaged isolated-workflow execution.
Phase 7D still owns the default entry and final working-directory policy, the
legacy PowerShell entry remains retained, and Phase 7 is not complete.

## Phase 7B2B packaged isolated workflow

Phase 7B2B completes the packaged isolated-workflow acceptance scope. The
Phase 7B2A onedir EXE was reused without rebuilding and launched exactly once
with the hidden `_isolated-workflow-smoke` command. Its process working
directory and its empty isolated workspace were separate system-temporary
directories outside the repository, build, and dist trees.

The frozen command returned success/OK in `workflow_isolated` mode with 11
stages and `forbidden_calls=0`. The unique JSONL log contained one
`workflow.start` and 11 ordered `workflow.stage.finished` events. The unique
RunReport contained the same 11 successful synthetic stages and passed an
independent validation using the bundled schema. No public `run`, real UAC,
ADB, TCP probe, or business program was executed.

The EXE hash, bundled-schema hash, schema equivalence, and dist file count were
unchanged after execution. Temporary evidence and the ignored harness were
removed. Phase 7B2 is complete, but Phase 7C remains a separately authorized
real packaged external validation scope. Phase 7D still owns the default entry
and final working-directory policy, the legacy PowerShell entry remains
retained, and Phase 7 is not complete.

## Phase 7D1 native default entry

The public start command is the native interactive default-entry boundary.
It accepts only a bounded deadline and discovers the single canonical config
at %LOCALAPPDATA%\OrchestratoRRR\config\orchestrator.toml. It requires an
interactive console before path resolution, applies a start-only absolute-path
policy, performs report-free run-v1 and exact external 11-stage preflight, and
requires the existing real-execution confirmation on every invocation.

During the single execute_run_request call, process cwd is the canonical
%LOCALAPPDATA%\OrchestratoRRR\runtime directory; the prior cwd is restored
afterward. Logs and reports are constrained to their canonical product
directories. Public validate, plan, and run contracts are unchanged.

The installer script is a fail-closed, first-install-only layout definition.
It copies an approved onedir to %LOCALAPPDATA%\Programs\OrchestratoRRR and
defines a Start Menu shortcut with argument start and the canonical runtime
working directory. Phase 7D1 did not execute that script, create a shortcut,
rebuild, or run a packaged EXE. Phase 7D2 owns those next non-business checks;
the legacy PowerShell entry remains retained.

## Phase 7D2 rebuilt packaged default entry

The committed Phase 7D1 source was rebuilt once through the formal onedir
script. Static Analysis confirms inclusion of default_entry and all required
CLI, config, run, entry-runtime, isolated-diagnostic, Typer, Click, and JSON
Schema dependencies. The canonical schema remains the only project data
resource; no installer, legacy entry, config, logs, reports, tests, or docs are
bundled.

Four packaged non-business invocations passed: version, root help, start help,
and non-interactive start. Root help exposes the five public commands, and
start help exposes only its bounded deadline option. With DEVNULL stdin,
start returns START_INTERACTIVE_CONSOLE_REQUIRED before resolving canonical
paths or creating synthetic application-data directories. No workflow,
confirmation, elevation, adapter, or business boundary was entered.

Phase 7D3 owns the separately authorized packaged synthetic preflight and
confirmation-cancel scope. Phase 7C remains separate real execution, and the
legacy PowerShell entry remains retained until a Phase 7E decision.

## Phase 7D3 composed-evidence closure

Phase 7D3 is complete using composed evidence rather than a direct packaged
interactive execution. Source control-flow and automatic tests cover the
full synthetic preflight, exact external 11-stage preview, confirmation
boundary, incorrect-confirmation cancellation, zero run-executor calls,
terminal pause, canonical directory preparation, and write-probe cleanup.

Phase 7D2 independently proves that the same committed `start` and
`default_entry` implementation is included in the formal onedir, that its
packaged command and option contracts load correctly, and that its
non-interactive gate fails closed without changing the artifact. The aborted
Phase 7D3 attempt additionally established, through source-only checks, that
its synthetic configuration passed the default-entry path policy, run-v1,
path-existence, and exact external-plan gates.

Direct packaged interactive execution did not occur: the available
computer-control backend was unavailable and the transcript probe produced no
usable evidence, so the fail-closed gate stopped before launching the EXE.
This is recorded as an acceptance-environment limitation, not an observed
product defect. No packaged confirmation cancellation, UAC, or real workflow
is claimed. Phase 7C retains the correctly confirmed real-execution boundary;
Phase 7D4 owns parallel deployment and manual operation; Phase 7E owns any
legacy-entry replacement decision.

## Phase 7D4B canonical parallel installation

The committed first-install-only installer was invoked exactly once with the
retained Phase 7D2 onedir. Before installation, the ignored machine-local
configuration passed all source-only default-entry gates and was copied
byte-for-byte to the canonical configuration location by an atomic rename.
The installed EXE and bundled schema match the source hashes, and both trees
contain 106 files.

The installer created the canonical runtime, log, and report directories and
the Start Menu shortcut. Those directories remained empty. Static shortcut
inspection confirmed the installed EXE target, the exact `start` argument,
the canonical runtime working directory, and the product description. The
shortcut and both packaged executables were not run; no UAC, ADB, TCP, or
business boundary was entered.

The legacy PowerShell entry remains available in parallel. Phase 7D4C owns a
separately authorized manual shortcut preflight with cancellation before real
execution. Phase 7C retains the correctly confirmed real packaged workflow,
and Phase 7E owns any legacy-entry replacement decision. Phase 7D and Phase 7
remain incomplete.
