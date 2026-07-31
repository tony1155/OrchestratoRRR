"""现有 Runtime Adapter 的默认 composition root。"""

from __future__ import annotations

from pathlib import Path

from autogame_orchestrator.config_model import AppConfig, MumuLifecycleMode
from autogame_orchestrator.maa_sync.synchronizer import MAASynchronizer
from autogame_orchestrator.maa_update import build_maa_update_runtime_config
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.runtime.aalc import AALCAdapter
from autogame_orchestrator.runtime.maa import MAAAdapter
from autogame_orchestrator.runtime.models import MumuRuntimeResult
from autogame_orchestrator.runtime.mumu import MumuAdapter
from autogame_orchestrator.runtime.starrail import StarRailAdapter
from autogame_orchestrator.workflow.production.ports import MumuRuntimePort, RuntimeFactories


class RuntimeBindingError(ValueError):
    """默认 Runtime 绑定配置无效，消息不得向结果透传。"""


class _ExternalMumuStatusPort:
    """只公开 readiness/status，不暴露任何生命周期管理方法。"""

    def __init__(self, adapter: MumuAdapter) -> None:
        self._adapter = adapter

    def status(
        self,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> MumuRuntimeResult:
        return self._adapter.status(deadline, cancel)

    def ensure_external_ready(
        self,
        deadline: Deadline,
        cancel: CancellationToken | None = None,
    ) -> MumuRuntimeResult:
        return self._adapter.ensure_external_ready(deadline, cancel)


def parse_local_adb_serial(serial: str) -> tuple[str, int]:
    """仅接受 ``127.0.0.1:<1-65535>``。"""
    if not isinstance(serial, str) or serial.count(":") != 1:
        raise RuntimeBindingError("ADB serial 格式无效")
    host, raw_port = serial.split(":", 1)
    if host != "127.0.0.1" or not raw_port.isascii() or not raw_port.isdecimal():
        raise RuntimeBindingError("ADB serial 仅允许本地 IPv4 端点")
    port = int(raw_port)
    if not 1 <= port <= 65535:
        raise RuntimeBindingError("ADB 端口超出范围")
    return host, port


def build_default_runtime_factories(config: AppConfig) -> RuntimeFactories:
    """只创建闭包；本函数不构造 Adapter。"""

    def build_starrail() -> StarRailAdapter:
        return StarRailAdapter(config.starrail)

    def build_maa() -> MAAAdapter:
        return MAAAdapter(config.maa)

    def build_aalc() -> AALCAdapter:
        return AALCAdapter(config.aalc)

    def build_mumu() -> MumuRuntimePort:
        host, port = parse_local_adb_serial(config.mumu.adb_serial)
        external = config.mumu.lifecycle_mode == MumuLifecycleMode.EXTERNAL
        adapter = MumuAdapter(
            executable=Path() if external else Path(config.mumu.executable),
            start_arguments=() if external else config.mumu.start_arguments,
            stop_arguments=() if external else config.mumu.stop_arguments,
            adb_executable=Path(config.mumu.adb_executable),
            adb_serial=config.mumu.adb_serial,
            adb_host=host,
            adb_port=port,
            start_timeout_seconds=float(config.mumu.start_timeout_seconds),
            stop_timeout_seconds=float(config.mumu.stop_timeout_seconds),
        )
        return _ExternalMumuStatusPort(adapter) if external else adapter

    def build_maa_sync() -> MAASynchronizer:
        return MAASynchronizer(config.maa_sync)

    def build_maa_update() -> MAAAdapter:
        return MAAAdapter(build_maa_update_runtime_config(config.maa, config.maa_update))

    return RuntimeFactories(build_starrail, build_maa, build_aalc, build_mumu, build_maa_sync, build_maa_update)
