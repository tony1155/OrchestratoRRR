"""生产 Stage 所需的最小 Runtime Protocol。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from autogame_orchestrator.maa_sync.models import MAASyncResult
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.runtime.aalc_models import AALCRunResult
from autogame_orchestrator.runtime.maa_models import MAARunResult
from autogame_orchestrator.runtime.models import MumuRuntimeResult
from autogame_orchestrator.runtime.starrail_models import StarRailRunResult


class StarRailRunPort(Protocol):
    def run(
        self,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
    ) -> StarRailRunResult: ...


class MAARunPort(Protocol):
    def run(
        self,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
    ) -> MAARunResult: ...


class AALCRunPort(Protocol):
    def run(
        self,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
    ) -> AALCRunResult: ...


class MumuRuntimePort(Protocol):
    """只读基础契约：external 模式只需满足这一层，物理上不具备启停能力。"""

    def status(
        self,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> MumuRuntimeResult: ...

    def ensure_external_ready(
        self,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> MumuRuntimeResult: ...


@runtime_checkable
class ManagedMumuRuntimePort(MumuRuntimePort, Protocol):
    """managed 模式额外要求生命周期能力；仅当配置为 managed 时才提供。"""

    def start(
        self,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> MumuRuntimeResult: ...

    def stop(
        self,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> MumuRuntimeResult: ...


class MAASyncPort(Protocol):
    def run(
        self,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
    ) -> MAASyncResult: ...


class MAAUpdatePort(Protocol):
    def run(
        self,
        deadline: Deadline | None = None,
        cancel: CancellationToken | None = None,
    ) -> MAARunResult: ...


@dataclass(frozen=True)
class RuntimeFactories:
    """仅在对应 Stage 到达时才调用的 Runtime 构造器。"""

    starrail: Callable[[], StarRailRunPort]
    maa: Callable[[], MAARunPort]
    aalc: Callable[[], AALCRunPort]
    mumu: Callable[[], MumuRuntimePort]
    maa_sync: Callable[[], MAASyncPort] | None = None
    maa_update: Callable[[], MAAUpdatePort] | None = None
