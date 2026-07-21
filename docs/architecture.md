# 架构

## 当前状态

阶段 1B —— 通用 ProcessSupervisor。
尚未启动任何真实外部程序。

## 项目身份

Autogame Orchestrator 是一个**独立的、不与旧项目共享目录的**新编排器。
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
