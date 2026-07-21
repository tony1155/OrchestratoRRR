# Autogame Orchestrator

A bounded process orchestrator for MuMu, StarRailCopilot, MAA, and AALC.

This project replaces the monolithic legacy PowerShell orchestrator
(`Invoke-LocalOrchestrator.ps1`) with a staged, testable Python implementation.

**Current phase: Phase 0 — Project skeleton and behavioural contracts.**
No real external programs are launched at this stage.

## Requirements

- Python 3.11 or later
- Windows (the orchestrator manages Windows desktop applications)

## Quick Start

```powershell
# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install the project and dev dependencies
python -m pip install -e ".[dev]"
```

## CLI Commands

```powershell
# Print version
python -m autogame_orchestrator version
# or
autogame-orch version

# Validate a configuration file (structural checks only)
python -m autogame_orchestrator validate --config config/orchestrator.example.toml

# Validate with real path checks
python -m autogame_orchestrator validate --config config/orchestrator.example.toml --check-paths

# Print a static execution plan
python -m autogame_orchestrator plan --config config/orchestrator.example.toml
```

> **Important**: These commands do **not** launch, stop, or probe any external programs.
> They perform structural validation and print a plan — nothing more.

## Configuration

Copy `config/orchestrator.example.toml` to `config/orchestrator.local.toml`
and adjust the paths. The `.local.toml` file is git-ignored.

## Testing

```powershell
python -m pytest -q
```

## Linting and Type Checking

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy src
```
