"""Static execution-plan builder.

Produces a dry-run plan as a list of *StageName* values ordered
according to the real-life lifecycle contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autogame_orchestrator.models import StageName

if TYPE_CHECKING:
    pass

_DEFAULT_PLAN: tuple[StageName, ...] = (
    StageName.VALIDATE_CONFIG,
    StageName.SYNC_MAA_CONFIG,
    StageName.UPDATE_MAA,
    StageName.ENSURE_MUMU_RUNNING,
    StageName.WAIT_MUMU_ADB_READY,
    StageName.RUN_STARRAIL,
    StageName.STOP_STARRAIL,
    StageName.VERIFY_STARRAIL_STOPPED,
    StageName.STOP_MUMU,
    StageName.VERIFY_MUMU_STOPPED,
    StageName.START_MUMU,
    StageName.WAIT_MUMU_ADB_READY_AFTER_RESTART,
    StageName.RUN_MAA,
    StageName.RUN_AALC,
    StageName.WRITE_RUN_REPORT,
)


def build_plan() -> tuple[StageName, ...]:
    """Return the static execution plan (no dynamic resolution)."""
    return _DEFAULT_PLAN


PLAN_HEADER = "DRY PLAN — no external programs will be executed"
