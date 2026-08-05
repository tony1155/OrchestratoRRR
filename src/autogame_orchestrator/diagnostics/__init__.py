"""诊断子包。

阶段 2D：MuMu 候选 CLI 安全探针。
"""

from importlib import import_module

__all__ = [
    "MumuCliAttemptStatus",
    "MumuCliCandidateStatus",
    "MumuCliProbe",
    "MumuCliProbeAttempt",
    "MumuCliProbeReport",
    "ProbeCommand",
    "validate_mumu_candidate",
]


def __getattr__(name: str) -> object:
    """按需提供 MuMu 探针导出，避免包初始化时提前加载诊断入口。"""
    if name not in __all__:
        raise AttributeError(name)
    module = import_module("autogame_orchestrator.diagnostics.mumu_cli_probe")
    return getattr(module, name)
