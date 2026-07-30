"""生产 StageExecutor 的惰性构造与单次运行缓存。"""

from __future__ import annotations

from typing import TypeVar, cast

from autogame_orchestrator.config_model import AppConfig
from autogame_orchestrator.models import StageName
from autogame_orchestrator.workflow.production.executors import ProductionStageExecutor
from autogame_orchestrator.workflow.production.ports import (
    AALCRunPort,
    MAARunPort,
    MAASyncPort,
    MumuRuntimePort,
    RuntimeFactories,
    StarRailRunPort,
)
from autogame_orchestrator.workflow.production.runtime_bindings import (
    RuntimeBindingError,
    build_default_runtime_factories,
)
from autogame_orchestrator.workflow.production.state import ProductionWorkflowState

_T = TypeVar("_T")


class _RuntimeCache:
    def __init__(self, factories: RuntimeFactories) -> None:
        self._factories = factories
        self._values: dict[str, object] = {}

    def _get(self, name: str, factory: object) -> object:
        if name not in self._values:
            self._values[name] = cast("object", factory())  # type: ignore[operator]
        return self._values[name]

    def starrail(self) -> StarRailRunPort:
        return cast("StarRailRunPort", self._get("starrail", self._factories.starrail))

    def maa(self) -> MAARunPort:
        return cast("MAARunPort", self._get("maa", self._factories.maa))

    def aalc(self) -> AALCRunPort:
        return cast("AALCRunPort", self._get("aalc", self._factories.aalc))

    def mumu(self) -> MumuRuntimePort:
        return cast("MumuRuntimePort", self._get("mumu", self._factories.mumu))

    def maa_sync(self) -> MAASyncPort:
        if self._factories.maa_sync is None:
            raise RuntimeBindingError("MAA Sync 构造器未注册")
        return cast("MAASyncPort", self._get("maa_sync", self._factories.maa_sync))


class ProductionExecutorFactory:
    """一次工作流专用；状态与 Runtime 缓存不跨运行共享。"""

    def __init__(self, config: AppConfig, runtime_factories: RuntimeFactories) -> None:
        self.state = ProductionWorkflowState()
        self._config = config
        self._runtime = _RuntimeCache(runtime_factories)

    def __call__(self, stage: StageName) -> ProductionStageExecutor:
        if stage == StageName.WRITE_RUN_REPORT:
            raise KeyError(stage)
        return ProductionStageExecutor(
            stage,
            self._config,
            self.state,
            starrail=self._runtime.starrail,
            maa=self._runtime.maa,
            aalc=self._runtime.aalc,
            mumu=self._runtime.mumu,
            maa_sync=self._runtime.maa_sync,
        )


def build_production_executor_factory(
    config: AppConfig,
    *,
    runtime_factories: RuntimeFactories | None = None,
) -> ProductionExecutorFactory:
    """构建单次运行 factory；此时不创建任何 Runtime Adapter。"""
    selected = build_default_runtime_factories(config) if runtime_factories is None else runtime_factories
    return ProductionExecutorFactory(config, selected)
