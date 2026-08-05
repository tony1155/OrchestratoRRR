"**Explicit runtime and elevation-launch models for source and frozen entries.**"

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class EntryRuntimeKind(StrEnum):
    """The two supported shapes of the current application entry."""

    SOURCE = "source"
    FROZEN = "frozen"


@dataclass(frozen=True)
class EntryRuntime:
    """Immutable description of the current entry executable and working directory."""

    kind: EntryRuntimeKind
    executable: Path
    working_directory: Path


@dataclass(frozen=True)
class ElevationLaunchSpec:
    """Complete, shell-free specification for an elevated child entry."""

    executable: Path
    arguments: tuple[str, ...]
    working_directory: Path


def detect_entry_runtime() -> EntryRuntime:
    """Detect the current entry shape without caching process-local values."""

    kind = EntryRuntimeKind.FROZEN if bool(getattr(sys, "frozen", False)) else EntryRuntimeKind.SOURCE
    return EntryRuntime(
        kind=kind,
        executable=Path(sys.executable),
        working_directory=Path.cwd(),
    )


__all__ = [
    "ElevationLaunchSpec",
    "EntryRuntime",
    "EntryRuntimeKind",
    "detect_entry_runtime",
]
