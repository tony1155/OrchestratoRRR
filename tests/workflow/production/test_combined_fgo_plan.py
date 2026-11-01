from dataclasses import replace

import pytest

from autogame_orchestrator.config_model import FgoConfig, MumuLifecycleMode
from autogame_orchestrator.models import StageName
from autogame_orchestrator.run_application import validate_external_plan
from autogame_orchestrator.workflow.plan import build_execution_plan
from tests.fakes.maafgo_support import make_native_project
from tests.workflow.production.fakes import valid_config


@pytest.mark.parametrize("mode", list(MumuLifecycleMode))
@pytest.mark.parametrize("bettergi", [True, False])
def test_appended_fgo_runs_after_maa_before_shutdown_and_bettergi(tmp_path, mode, bettergi):
    config = valid_config(tmp_path / "base")
    config = replace(
        config,
        mumu=replace(config.mumu, lifecycle_mode=mode),
        bettergi=replace(config.bettergi, enabled=bettergi),
        fgo=FgoConfig(package_name="com.bilibili.fatego", append_to_workflow=True),
        maafgo=make_native_project(tmp_path / "fgo"),
    )
    plan = build_execution_plan(config)
    stages = plan.stages
    index = stages.index(StageName.RUN_MAA)
    assert stages[index + 1 : index + 4] == (StageName.PREPARE_MAAFGO_RUN, StageName.RUN_MAAFGO, StageName.STOP_FGO)
    assert validate_external_plan(plan) is None
    if mode == MumuLifecycleMode.MANAGED:
        assert stages.index(StageName.STOP_FGO) < stages.index(StageName.SHUTDOWN_MUMU)
    if bettergi:
        assert stages.index(StageName.STOP_FGO) < stages.index(StageName.RUN_BETTERGI)


def test_appended_fgo_requires_valid_provider_configuration(tmp_path):
    config = valid_config(tmp_path / "base")
    config = replace(config, fgo=FgoConfig(append_to_workflow=True))
    assert config.validate()


@pytest.mark.parametrize("mode", list(MumuLifecycleMode))
@pytest.mark.parametrize("bettergi", [True, False])
def test_temporarily_skipping_maa_preserves_fgo_and_can_be_reversed(tmp_path, mode, bettergi):
    config = valid_config(tmp_path / "base")
    config = replace(
        config,
        mumu=replace(config.mumu, lifecycle_mode=mode),
        bettergi=replace(config.bettergi, enabled=bettergi),
        fgo=FgoConfig(append_to_workflow=True),
        orchestrator=replace(config.orchestrator, skip_maa=True),
    )
    plan = build_execution_plan(config)
    for stage in (StageName.SYNC_MAA_CONFIG, StageName.UPDATE_MAA, StageName.MERGE_MAA_RESOURCE, StageName.RUN_MAA):
        assert stage not in plan.stages
    assert plan.stages.index(StageName.RUN_STARRAIL) < plan.stages.index(StageName.RUN_MAAFGO)
    if bettergi:
        assert plan.stages.index(StageName.RUN_MAAFGO) < plan.stages.index(StageName.RUN_BETTERGI)
    assert validate_external_plan(plan) is None
    restored = replace(config, orchestrator=replace(config.orchestrator, skip_maa=False))
    assert StageName.RUN_MAA in build_execution_plan(restored).stages
