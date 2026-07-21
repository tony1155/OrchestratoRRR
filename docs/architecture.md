# Architecture

## Status

Phase 0 — project skeleton and behavioural contracts.
No real external programs are launched.

## Project Identity

Autogame Orchestrator is a **standalone, independent project**.
It does not live inside the old MAA / StarRailCopilot / AALC directory trees.
The legacy `Invoke-LocalOrchestrator.ps1` script remains in place as a
fallback implementation and is NOT modified or consumed by this project.

## Phase 0 Boundaries

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
