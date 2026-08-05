from __future__ import annotations

import pytest

from autogame_orchestrator.config_model import MAAConfig, MAAUpdateConfig
from autogame_orchestrator.maa_update import build_maa_update_runtime_config


def base() -> MAAConfig:
    return MAAConfig(
        executable="X:/fictional/maa",
        working_directory="X:/fictional/work",
        arguments=("old",),
        environment_overrides=(("FICTIONAL_ENCODING", "utf-8"),),
        timeout_seconds=9,
        stop_timeout_seconds=7,
    )


def projected() -> MAAConfig:
    return build_maa_update_runtime_config(
        base(),
        MAAUpdateConfig(True, True, False, ("update", "--channel", "stable"), 321),
    )


def test_executable_is_reused() -> None:
    assert projected().executable == base().executable


def test_working_directory_is_reused() -> None:
    assert projected().working_directory == base().working_directory


def test_environment_is_reused() -> None:
    assert projected().environment_overrides == base().environment_overrides


def test_stop_timeout_is_reused() -> None:
    assert projected().stop_timeout_seconds == base().stop_timeout_seconds


def test_update_arguments_replace_run_arguments() -> None:
    assert projected().arguments == ("update", "--channel", "stable")


def test_update_timeout_replaces_run_timeout() -> None:
    assert projected().timeout_seconds == 321


@pytest.mark.parametrize(
    "update",
    [
        MAAUpdateConfig(),
        MAAUpdateConfig(enabled=True),
        MAAUpdateConfig(enabled=True, allow_network=True, arguments=("self",)),
    ],
)
def test_unapproved_or_invalid_projection_fails(update: MAAUpdateConfig) -> None:
    with pytest.raises(ValueError):
        build_maa_update_runtime_config(base(), update)
