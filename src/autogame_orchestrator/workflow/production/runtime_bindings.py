"""现有 Runtime Adapter 的默认 composition root。"""

from __future__ import annotations

from pathlib import Path

from autogame_orchestrator.config_model import AppConfig
from autogame_orchestrator.maa_sync.synchronizer import MAASynchronizer
from autogame_orchestrator.runtime.aalc import AALCAdapter
from autogame_orchestrator.runtime.maa import MAAAdapter
from autogame_orchestrator.runtime.mumu import MumuAdapter
from autogame_orchestrator.runtime.starrail import StarRailAdapter
from autogame_orchestrator.workflow.production.ports import RuntimeFactories


class RuntimeBindingError(ValueError):
    """默认 Runtime 绑定配置无效，消息不得向结果透传。"""


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

    def build_mumu() -> MumuAdapter:
        host, port = parse_local_adb_serial(config.mumu.adb_serial)
        return MumuAdapter(
            executable=Path(config.mumu.executable),
            start_arguments=config.mumu.start_arguments,
            stop_arguments=config.mumu.stop_arguments,
            adb_executable=Path(config.mumu.adb_executable),
            adb_serial=config.mumu.adb_serial,
            adb_host=host,
            adb_port=port,
            start_timeout_seconds=float(config.mumu.start_timeout_seconds),
            stop_timeout_seconds=float(config.mumu.stop_timeout_seconds),
        )

    def build_maa_sync() -> MAASynchronizer:
        return MAASynchronizer(config.maa_sync)

    return RuntimeFactories(build_starrail, build_maa, build_aalc, build_mumu, build_maa_sync)
