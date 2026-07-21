# Phase Plan

This document defines the staged roadmap for Autogame Orchestrator.
Phases are strictly sequential; each phase must pass all tests before
the next begins.

| Phase | Title | Scope |
|---|---|---|
| 0 | Project Skeleton & Contracts | Package layout, data models, config validation, CLI skeleton (version/validate/plan), RunReport schema, JSONL logger, test suite, docs |
| 1 | Generic Process Supervisor | ProcessSupervisor with Windows Job Object support, timeouts, stdout/stderr capture, exit-code handling, fake-program integration tests |
| 2 | Probe Layer | ADB availability probe, TCP port probe, process-alive probe — each with stable ErrorCodes and configurable timeouts |
| 3 | MuMu Adapter | Start/stop/query MuMu emulator via ADB, wait-for-ready, verify-stopped |
| 4 | StarRail Adapter | Launch StarRailCopilot, monitor exit, capture output, enforce task timeout, verify-stopped |
| 5 | MAA Adapter | Launch MAA CLI, enforce timeout, collect diagnostics |
| 6 | AALC Adapter | Launch AALC with retry policy, enforce attempt timeouts |
| 7 | Full Workflow | Orchestrate the complete lifecycle: validate → sync MAA config → update MAA → ensure-mumu → run SRP → stop SRP → stop MuMu → restart MuMu → run MAA → run AALC → write report |
| 8 | Packaging & Default Entry Point | PyInstaller EXE, seamless replacement of legacy PS1 entry-point |

Each phase builds on the previous one but must not regress tests from
earlier phases.
