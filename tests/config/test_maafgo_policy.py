"""生产 profile policy 与 ORR 私有分发校验的契约测试（全部只读）。"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from autogame_orchestrator.maafgo_config import (
    ORR_PINNED_FGO_COMMIT,
    MaaFgoConfigurationError,
    read_expected_task_pairs,
)
from autogame_orchestrator.runtime.maafgo_models import MaaFgoErrorCode as Code
from tests.fakes.maafgo_support import SERIAL, make_native_project, write_manifest


@pytest.fixture
def project(tmp_path):
    return make_native_project(tmp_path / "native project")


def test_expected_task_pairs_resolve_interface_entries(project):
    assert read_expected_task_pairs(project.interface_path, project.profile_path) == (
        ("登录", "登录识别"),
        ("日常战斗", "日常战斗"),
    )


def test_policy_accepts_full_native_profile(project):
    before = project.profile_path.read_bytes()
    project.check_profile_policy()
    project.check_distribution()
    assert project.profile_path.read_bytes() == before


def test_policy_requires_login_first(project):
    tasks = [
        {"name": "日常战斗", "option": [{"name": "battle_mode", "value": "native"}]},
        {"name": "登录", "option": []},
    ]
    config = replace(project)
    _rewrite_profile(config, tasks)
    with pytest.raises(MaaFgoConfigurationError) as excinfo:
        config.check_profile_policy()
    assert excinfo.value.code is Code.PROFILE_POLICY_REJECTED


@pytest.mark.parametrize("task", ["启动bbc", "关闭游戏", "直接bbc战斗", "Chaldea 一键战斗"])
def test_policy_rejects_bbc_and_shutdown_tasks(project, task):
    _rewrite_profile(project, [{"name": "登录", "option": []}, {"name": task, "option": []}])
    with pytest.raises(MaaFgoConfigurationError) as excinfo:
        project.check_profile_policy()
    assert excinfo.value.code is Code.PROFILE_POLICY_REJECTED


@pytest.mark.parametrize(
    "tasks",
    [
        # 只有需要人工预置战斗页的任务
        [{"name": "登录", "option": []}, {"name": "原生自动战斗", "option": []}],
        # 没有任何业务任务
        [{"name": "登录", "option": []}],
    ],
)
def test_policy_rejects_incomplete_profiles(project, tasks):
    _rewrite_profile(project, tasks)
    with pytest.raises(MaaFgoConfigurationError) as excinfo:
        project.check_profile_policy()
    assert excinfo.value.code is Code.PROFILE_POLICY_REJECTED


@pytest.mark.parametrize("battle_mode", [None, "bbc", "NATIVE"])
def test_policy_requires_explicit_native_battle_mode(project, battle_mode):
    options = [] if battle_mode is None else [{"name": "battle_mode", "value": battle_mode}]
    _rewrite_profile(project, [{"name": "登录", "option": []}, {"name": "日常战斗", "option": options}])
    with pytest.raises(MaaFgoConfigurationError) as excinfo:
        project.check_profile_policy()
    assert excinfo.value.code is Code.PROFILE_POLICY_REJECTED


def test_policy_rejects_duplicate_tasks(project):
    _rewrite_profile(
        project,
        [
            {"name": "登录", "option": []},
            {"name": "日常战斗", "option": [{"name": "battle_mode", "value": "native"}]},
            {"name": "日常战斗", "option": [{"name": "battle_mode", "value": "native"}]},
        ],
    )
    with pytest.raises(MaaFgoConfigurationError) as excinfo:
        project.check_profile_policy()
    assert excinfo.value.code is Code.PROFILE_POLICY_REJECTED


def test_policy_rejects_import_escape(project):
    outside = project.working_directory + "-outside"
    Path(outside).mkdir()
    (Path(outside) / "evil.json").write_text("{}", encoding="utf-8")
    interface = json.loads(project.interface_path.read_text(encoding="utf-8"))
    interface["import"] = ["tasks/login.json", "../evil.json"]
    project.interface_path.write_text(json.dumps(interface), encoding="utf-8")
    with pytest.raises(MaaFgoConfigurationError):
        project.check_profile_policy()


def test_policy_rejects_conflicting_entry_definitions(project):
    (Path(project.working_directory) / "tasks" / "daily2.json").write_text(
        json.dumps({"task": [{"name": "日常战斗", "entry": "另一些entry"}]}), encoding="utf-8"
    )
    interface = json.loads(project.interface_path.read_text(encoding="utf-8"))
    interface["import"] = interface["import"] + ["tasks/daily2.json"]
    project.interface_path.write_text(json.dumps(interface), encoding="utf-8")
    with pytest.raises(MaaFgoConfigurationError):
        project.check_profile_policy()


def test_distribution_accepts_pinned_manifest(project):
    project.check_distribution()


def test_distribution_requires_manifest(project):
    (Path(project.working_directory) / "distribution-manifest.json").unlink()
    with pytest.raises(MaaFgoConfigurationError) as excinfo:
        project.check_distribution()
    assert excinfo.value.code is Code.DISTRIBUTION_UNVERIFIED


def test_distribution_rejects_unknown_revision(project):
    write_manifest(Path(project.working_directory), maafgo_commit="0" * 40)
    with pytest.raises(MaaFgoConfigurationError) as excinfo:
        project.check_distribution()
    assert excinfo.value.code is Code.DISTRIBUTION_UNVERIFIED


def test_distribution_rejects_transform_drift(project):
    write_manifest(
        Path(project.working_directory),
        orr_transform={
            "transform_id": "unknown-transform",
            "transform_version": 1,
            "bbc_listener_registered": False,
            "reporter_registered": True,
        },
    )
    with pytest.raises(MaaFgoConfigurationError) as excinfo:
        project.check_distribution()
    assert excinfo.value.code is Code.DISTRIBUTION_UNVERIFIED


def test_distribution_rejects_listener_registered(project):
    write_manifest(
        Path(project.working_directory),
        orr_transform={
            "transform_id": ORR_PINNED_FGO_COMMIT[:0] + "orr-bbc-free-native-reporter",
            "transform_version": 1,
            "bbc_listener_registered": True,
            "reporter_registered": True,
        },
    )
    with pytest.raises(MaaFgoConfigurationError) as excinfo:
        project.check_distribution()
    assert excinfo.value.code is Code.DISTRIBUTION_UNVERIFIED


def test_distribution_rejects_malformed_manifest(project):
    (Path(project.working_directory) / "distribution-manifest.json").write_bytes(b"{nope")
    with pytest.raises(MaaFgoConfigurationError) as excinfo:
        project.check_distribution()
    assert excinfo.value.code is Code.DISTRIBUTION_UNVERIFIED


def test_project_without_manifest_is_not_production_ready(tmp_path):
    """旧 make_project（无 manifest、Synthetic task）在生产 policy 下不可用。"""
    from tests.fakes.maafgo_support import make_project

    config = make_project(tmp_path / "plain")
    with pytest.raises(MaaFgoConfigurationError) as excinfo:
        config.check_profile_policy()
    assert excinfo.value.code is Code.PROFILE_POLICY_REJECTED
    with pytest.raises(MaaFgoConfigurationError) as excinfo:
        config.check_distribution()
    assert excinfo.value.code is Code.DISTRIBUTION_UNVERIFIED


def _rewrite_profile(config, tasks: list[dict[str, object]]) -> None:
    profile = json.loads(config.profile_path.read_text(encoding="utf-8"))
    profile["task"] = tasks
    config.profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")


def test_adb_identity_still_enforced(project):
    with pytest.raises(MaaFgoConfigurationError) as excinfo:
        project.check_profile("127.0.0.1:9999")
    assert excinfo.value.code is Code.ADB_CONFIGURATION_MISMATCH
    project.check_profile(SERIAL)
