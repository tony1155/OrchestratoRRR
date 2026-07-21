# ADR-0001: Python Orchestrator with Staged Delivery

**Date:** 2026-07-21
**Status:** Accepted

## Context

The existing Autogame automation uses a monolithic PowerShell script
(`Invoke-LocalOrchestrator.ps1`) to drive MuMu, StarRailCopilot, MAA,
and AALC. The script has grown organically and is now difficult to reason
about, test, or extend.

## Decision

We will build a new Python-based orchestrator in a separate repository
and deliver it in eight stages.

### Why Not Extend the PowerShell Script

- PowerShell lacks a mature testing ecosystem for complex orchestration.
- Error handling in PS1 is string-based and brittle.
- The monolith is hard to split into independently testable modules.
- No structured RunReport or schema-validated output.

### Why Python

- Rich stdlib (`dataclasses`, `enum.StrEnum`, `tomllib`, `pathlib`).
- Mature testing (pytest), linting (ruff), and type-checking (mypy).
- Cross-platform-capable (even though the target is Windows).
- Easy to package with PyInstaller for single-EXE deployment.

### Why a Separate Repository

- Clean break from legacy code; no risk of accidentally breaking the fallback.
- Independent CI, versioning, and review cycle.
- Clear ownership boundary between old and new orchestrator.

### Why Staged Delivery

- Each phase delivers a testable, reviewable increment.
- Phase 0 establishes contracts (schemas, ErrorCodes, CLI) before any process
  supervision code is written.
- Prevents "big bang" integration risk.

### Why Phase 0 Does Not Launch Real Programs

- Phase 0 is the foundation: we validate that the configuration and reporting
  contracts are correct before building anything that touches real processes.
- Launching real programs in Phase 0 would create a dependency on external state
  (is MuMu installed? Is ADB working?) that distracts from the structural work.

### Why No ProcessSupervisor in Phase 0

- ProcessSupervisor requires Job Objects, subprocess management, and real
  programs to test. That belongs in Phase 1 where it can be developed alongside
  fake-program integration tests.

## Consequences

- The legacy PS1 remains the production entry point until Phase 8.
- Each phase requires passing all prior-phase tests — regressions are caught early.
- The project structure (`src/autogame_orchestrator/`) is fixed from Phase 0 forward.
