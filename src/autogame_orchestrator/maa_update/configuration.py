"""将 update 配置安全投影为既有 MAAAdapter 配置。"""

from __future__ import annotations

from dataclasses import replace

from autogame_orchestrator.config_model import MAAConfig, MAAUpdateConfig


def build_maa_update_runtime_config(maa: MAAConfig, update: MAAUpdateConfig) -> MAAConfig:
    """只替换固定 update 参数和超时，复用其余 MAA 运行契约。"""
    errors = update.validate()
    if errors or not update.enabled or not update.allow_network:
        raise ValueError("MAA 更新配置未获授权")
    return replace(
        maa,
        arguments=tuple(update.arguments),
        timeout_seconds=update.timeout_seconds,
    )
