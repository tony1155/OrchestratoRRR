"""Prerequisites within each game; failures do not block independent games."""

from autogame_orchestrator.models import StageName as S
from autogame_orchestrator.workflow.plan import ExecutionPlan


def production_stage_dependencies(plan: ExecutionPlan) -> dict[S, tuple[S, ...]]:
    stages = set(plan.stages)
    ready = S.WAIT_MUMU_ADB_READY_AFTER_RESTART if S.START_MUMU in stages else S.WAIT_MUMU_ADB_READY
    dependencies = {
        S.MERGE_MAA_RESOURCE: (S.UPDATE_MAA,),
        S.WAIT_MUMU_ADB_READY: (S.ENSURE_MUMU_RUNNING,),
        S.RUN_STARRAIL: (S.WAIT_MUMU_ADB_READY,),
        S.VERIFY_MUMU_STOPPED: (S.STOP_MUMU,),
        S.START_MUMU: (S.VERIFY_MUMU_STOPPED,),
        S.WAIT_MUMU_ADB_READY_AFTER_RESTART: (S.START_MUMU,),
        S.RUN_MAA: (S.SYNC_MAA_CONFIG, S.UPDATE_MAA, S.MERGE_MAA_RESOURCE, ready),
        S.PREPARE_MAAFGO_RUN: (ready,),
        S.RUN_MAAFGO: (S.PREPARE_MAAFGO_RUN,),
    }
    return {
        stage: tuple(dep for dep in deps if dep in stages) for stage, deps in dependencies.items() if stage in stages
    }
