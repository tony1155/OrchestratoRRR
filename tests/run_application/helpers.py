"""Phase 6C1 测试专用配置与依赖，不被生产代码导入。"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

from autogame_orchestrator.runtime.aalc_models import AALCRunStatus
from autogame_orchestrator.runtime.maa_models import MAARunStatus
from autogame_orchestrator.runtime.models import MumuRuntimeStatus
from autogame_orchestrator.runtime.starrail_models import StarRailRunStatus
from autogame_orchestrator.workflow.production.application import ProductionApplicationDependencies
from autogame_orchestrator.workflow.production.ports import RuntimeFactories
from tests.workflow.fakes import FakeElevationGateway, MemorySink
from tests.workflow.production.fakes import (
    FakeExternalMumuStatusPort,
    FakeRunPort,
    aalc_result,
    maa_result,
    mumu_result,
    starrail_result,
)


class CountingFactory:
    def __init__(self, name: str, value: object, counts: Counter[str]) -> None:
        self._name = name
        self._value = value
        self._counts = counts

    def __call__(self):
        self._counts[self._name] += 1
        return self._value


class MemoryLog:
    def __init__(self, _path: Path, _run_id: str, *, fail_open: bool = False) -> None:
        self.fail_open = fail_open
        self.entered = False
        self.exited = False
        self.records: list[tuple[str, str, dict[str, object]]] = []

    def __enter__(self):
        if self.fail_open:
            raise OSError("sensitive log path")
        self.entered = True
        return self

    def __exit__(self, *args: object) -> None:
        self.exited = True

    def info(self, event: str, message: str, details: dict[str, object] | None = None) -> None:
        self.records.append((event, message, details or {}))


def write_run_config(
    root: Path,
    *,
    lifecycle_mode: str = "external",
    sync_enabled: bool = False,
    update_enabled: bool = False,
    aalc_attempts: int = 1,
    aalc_requires_administrator: bool = False,
    mumu_arguments: bool = True,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    work = root / "work"
    logs = root / "logs"
    reports = root / "reports"
    work.mkdir(exist_ok=True)
    logs.mkdir(exist_ok=True)
    reports.mkdir(exist_ok=True)
    files: dict[str, Path] = {}
    for name in (
        "mumu-placeholder.exe",
        "adb-placeholder.exe",
        "starrail-placeholder.exe",
        "maa-placeholder.exe",
        "aalc-placeholder.exe",
    ):
        path = root / name
        path.write_text("fake", encoding="utf-8")
        files[name] = path
    settings = root / "gui-settings.json"
    tasks = root / "gui-tasks.json"
    settings.write_text("{}", encoding="utf-8")
    tasks.write_text("{}", encoding="utf-8")
    mumu_executable = "" if lifecycle_mode == "external" else files["mumu-placeholder.exe"].as_posix()
    managed_with_arguments = lifecycle_mode == "managed" and mumu_arguments
    start_arguments = '["control", "-v", "0", "launch"]' if managed_with_arguments else "[]"
    stop_arguments = '["control", "-v", "0", "shutdown"]' if managed_with_arguments else "[]"
    local_serial = "127.0.0.1:" + "16384"
    path = root / "run.toml"
    path.write_text(
        f'''[orchestrator]
log_dir = "{logs.as_posix()}"
report_dir = "{reports.as_posix()}"
heartbeat_interval_seconds = 10
poll_interval_seconds = 1

[mumu]
lifecycle_mode = "{lifecycle_mode}"
executable = "{mumu_executable}"
adb_executable = "{files["adb-placeholder.exe"].as_posix()}"
adb_serial = "{local_serial}"
start_timeout_seconds = 120
stop_timeout_seconds = 20
start_arguments = {start_arguments}
stop_arguments = {stop_arguments}

[starrail]
executable = "{files["starrail-placeholder.exe"].as_posix()}"
working_directory = "{work.as_posix()}"
arguments = ["fake-entry"]
log_path_template = "logs/{{date}}.log"
success_keywords = ["fake-success"]
failure_keywords = ["fake-failure"]
task_timeout_seconds = 3600
stop_timeout_seconds = 10

[maa]
executable = "{files["maa-placeholder.exe"].as_posix()}"
working_directory = "{work.as_posix()}"
arguments = []
timeout_seconds = 1800
stop_timeout_seconds = 10

[maa_sync]
enabled = {str(sync_enabled).lower()}
gui_settings_source = "{settings.as_posix()}"
gui_tasks_source = "{tasks.as_posix()}"
cli_profile_destination = "{(root / "profile.json").as_posix()}"
cli_tasks_destination = "{(root / "tasks.json").as_posix()}"

[maa_update]
enabled = {str(update_enabled).lower()}
allow_network = {str(update_enabled).lower()}
arguments = ["update"]
timeout_seconds = 1800

[aalc]
executable = "{files["aalc-placeholder.exe"].as_posix()}"
working_directory = "{work.as_posix()}"
arguments = []
attempts = {aalc_attempts}
attempt_timeout_seconds = 7200
stop_timeout_seconds = 10
requires_administrator = {str(aalc_requires_administrator).lower()}

[starrail.environment]

[maa.environment]

[aalc.environment]
''',
        encoding="utf-8",
    )
    return path


def fake_dependencies(
    *,
    elevated: bool = False,
    mumu_status: MumuRuntimeStatus = MumuRuntimeStatus.READY,
    starrail_status: StarRailRunStatus = StarRailRunStatus.COMPLETED,
    maa_status: MAARunStatus = MAARunStatus.COMPLETED,
    aalc_status: AALCRunStatus = AALCRunStatus.COMPLETED,
    fail_log_open: bool = False,
):
    counts: Counter[str] = Counter()
    mumu = FakeExternalMumuStatusPort(mumu_result(mumu_status))
    starrail = FakeRunPort(starrail_result(starrail_status))
    maa = FakeRunPort(maa_result(maa_status))
    aalc = FakeRunPort(
        replace(
            aalc_result(aalc_status),
            configured_attempts=1,
        )
    )
    factories = RuntimeFactories(
        CountingFactory("starrail", starrail, counts),
        CountingFactory("maa", maa, counts),
        CountingFactory("aalc", aalc, counts),
        CountingFactory("mumu", mumu, counts),
    )
    sink = MemorySink()
    logs: list[MemoryLog] = []

    def log_factory(path: Path, run_id: str) -> MemoryLog:
        log = MemoryLog(path, run_id, fail_open=fail_log_open)
        logs.append(log)
        return log

    dependencies = ProductionApplicationDependencies(
        FakeElevationGateway(elevated=elevated),
        runtime_factories=factories,
        report_sink_factory=lambda config: sink,
        log_factory=log_factory,
    )
    return dependencies, counts, sink, logs, mumu, starrail, maa, aalc
