# OrchestratoRRR 架构

## 当前验证状态

StarRail、MAA、AALC 的受控真实 Adapter smoke 已于 2026-07-30 完成脱敏验收。当前完成 Phase 6A、Phase 6B1、Phase 6B2A 与 Phase 6B2B1；MAA 更新、MuMu 实例化控制、公开 run CLI 和真实完整工作流仍未实现，Phase 6 整体尚未完成。

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

配置验证 Stage 只调用 `validate()` 与 `check_paths()`。StarRail、MAA、AALC Stage 原样传递父 Deadline 和 CancellationToken，复用既有 Adapter 生命周期；Stage 外层不重试。MuMu Stage 只允许调用一次 `status()`，并且 ADB 端点只接受 `127.0.0.1:<1-65535>`。StarRail 停止/验证 Stage 只检查本次受管进程清理证据，不扫描系统进程。

默认完整生产计划在 `SYNC_MAA_CONFIG` 返回 `WORKFLOW_STAGE_BLOCKED`，阻断前 Runtime 构造数为零。

## Phase 6B2A 旧流程静态契约调查

Phase 6B2A 只通过 PowerShell Parser/AST、文本和文件元数据调查旧流程，没有执行旧脚本、真实程序、网络或 UAC。调查确认旧同步会生成并直接覆盖两个目标配置，旧更新按开关顺序执行有限命令，且二者失败均阻断后续流程；但原子替换、隐私白名单、更新子进程和取消契约仍未闭合。

旧 MuMu 流程直接管理长期 GUI 进程，并通过进程树和安装根候选集合停止，不提供可验证的管理 CLI 或精确实例选择器。该模型与当前“短管理命令受管、长期模拟器仅做 readiness 验证”的安全边界不直接兼容，错误绑定到 kill-on-close Job 可能终止刚启动的长期进程。因此 MuMu start/stop 仍为 `UNSAFE`，实例选择为 `BLOCKED`，所有权仅为 `PARTIAL`。

6B2 已继续拆分为 6B2A 调查、6B2B1 安全同步、6B2B2 MAA 更新与 6B2B3 MuMu 实例化控制。完整调查见 `docs/acceptance/phase-6b2a-discovery.md`。

## Phase 6B2B1 安全 MAA 配置同步

`maa_sync` 包将 GUI 根对象通过显式字段白名单纯转换为 CLI profile/tasks。同步器在触碰目标前完成双源有界读取、转换、编码和目标快照；目标临时文件与备份均 flush/fsync，并通过同目录 `os.replace()` 原子提交。第二个目标失败、取消或父 Deadline 到期时回滚已替换的首目标，回滚失败使用独立稳定错误码。

同步默认关闭，关闭时不构造同步器。启用后生产 Stage 惰性构造服务并原样传递父 Deadline 与 CancellationToken，只投影稳定错误码和布尔状态。源/目标路径、配置值、异常文本和临时文件信息不会进入 StageReport 或 RunReport。

默认完整生产计划的首个安全阻断点已移至 `UPDATE_MAA`；在该点之前不会构造业务 Runtime。MAA 更新继续留在 6B2B2，MuMu start/stop/实例选择继续留在 6B2B3，均未实现。Phase 6B2、Phase 6B 和 Phase 6 整体尚未完成；Phase 6C 才会增加公开 run CLI 和真实完整工作流验收。

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
