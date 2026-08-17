"""Phase 6B1 使用的纯内存 Runtime Port。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from autogame_orchestrator.config_model import (
    AALCConfig,
    AppConfig,
    MAAConfig,
    MuMuConfig,
    OrchestratorConfig,
    StarRailConfig,
)
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.process.errors import TerminationReason
from autogame_orchestrator.runtime.aalc_models import (
    AALCAttemptResult,
    AALCAttemptStatus,
    AALCCompletionMode,
    AALCErrorCode,
    AALCRunResult,
    AALCRunStatus,
)
from autogame_orchestrator.runtime.maa_models import MAAErrorCode, MAARunResult, MAARunStatus
from autogame_orchestrator.runtime.models import (
    MumuAction,
    MumuRuntimeErrorCode,
    MumuRuntimeResult,
    MumuRuntimeStatus,
)
from autogame_orchestrator.runtime.starrail_models import (
    StarRailCompletionMode,
    StarRailErrorCode,
    StarRailRunResult,
    StarRailRunStatus,
)

NOW = datetime(2026, 7, 30, tzinfo=UTC)
LATER = NOW + timedelta(seconds=2)


def valid_config(root: Path) -> AppConfig:
    root.mkdir(parents=True, exist_ok=True)
    work = root / "work"
    logs = root / "logs"
    work.mkdir(exist_ok=True)
    logs.mkdir(exist_ok=True)
    executables = {}
    for name in ("mumu.exe", "adb.exe", "starrail.exe", "maa.exe", "aalc.exe"):
        path = root / name
        path.write_text("fake", encoding="utf-8")
        executables[name] = str(path)
    return AppConfig(
        orchestrator=OrchestratorConfig(log_dir=str(logs), report_dir=str(root / "reports")),
        mumu=MuMuConfig(executable=executables["mumu.exe"], adb_executable=executables["adb.exe"]),
        starrail=StarRailConfig(
            executable=executables["starrail.exe"],
            working_directory=str(work),
            arguments=("--fake",),
            log_path_template=str(logs / "{date}.log"),
        ),
        maa=MAAConfig(executable=executables["maa.exe"], working_directory=str(work)),
        aalc=AALCConfig(executable=executables["aalc.exe"], working_directory=str(work)),
    )


def starrail_result(status: StarRailRunStatus = StarRailRunStatus.COMPLETED) -> StarRailRunResult:
    values = {
        StarRailRunStatus.COMPLETED: (StarRailErrorCode.OK, StarRailCompletionMode.LOG_SUCCESS),
        StarRailRunStatus.FAILED: (StarRailErrorCode.INTERNAL_ERROR, StarRailCompletionMode.START_FAILURE),
        StarRailRunStatus.TIMEOUT: (StarRailErrorCode.TASK_TIMEOUT, StarRailCompletionMode.TASK_TIMEOUT),
        StarRailRunStatus.CANCELLED: (StarRailErrorCode.CANCELLED, StarRailCompletionMode.CANCELLATION),
    }
    code, mode = values[status]
    return StarRailRunResult(
        status,
        code,
        mode,
        NOW,
        LATER,
        2000,
        123456,
        0 if status == StarRailRunStatus.COMPLETED else None,
        "secret keyword" if status == StarRailRunStatus.COMPLETED else "",
        "E:\\private\\starrail.log",
        status == StarRailRunStatus.COMPLETED,
        "stdout secret",
        "stderr secret",
        True,
        True,
        {"token": "TOKEN_VALUE"},
    )


def maa_result(status: MAARunStatus = MAARunStatus.COMPLETED) -> MAARunResult:
    values = {
        MAARunStatus.COMPLETED: (MAAErrorCode.OK, TerminationReason.NORMAL_EXIT),
        MAARunStatus.FAILED: (MAAErrorCode.PROCESS_EXIT_NONZERO, TerminationReason.NONZERO_EXIT),
        MAARunStatus.TIMEOUT: (MAAErrorCode.PROCESS_TIMEOUT, TerminationReason.TIMEOUT),
        MAARunStatus.CANCELLED: (MAAErrorCode.CANCELLED, TerminationReason.CANCELLED),
    }
    code, reason = values[status]
    return MAARunResult(
        status,
        code,
        NOW,
        LATER,
        2000,
        654321,
        0 if status == MAARunStatus.COMPLETED else 7,
        reason,
        True,
        "stdout secret",
        "stderr secret",
        True,
        True,
        {"path": "E:\\private\\maa.exe"},
    )


def aalc_result(status: AALCRunStatus = AALCRunStatus.COMPLETED) -> AALCRunResult:
    if status == AALCRunStatus.COMPLETED:
        attempt = AALCAttemptResult(
            1,
            AALCAttemptStatus.COMPLETED,
            AALCErrorCode.OK,
            NOW,
            LATER,
            2.0,
            777777,
            0,
            True,
            "stdout secret",
            "stderr secret",
            diagnostics={"token": "TOKEN_VALUE"},
        )
        return AALCRunResult(
            status,
            AALCErrorCode.OK,
            AALCCompletionMode.NORMAL_EXIT,
            NOW,
            LATER,
            2.0,
            3,
            1,
            1,
            (attempt,),
            {"path": "E:\\private\\aalc.exe"},
        )
    values = {
        AALCRunStatus.FAILED: (AALCErrorCode.PROCESS_START_FAILED, AALCCompletionMode.START_FAILURE),
        AALCRunStatus.TIMEOUT: (AALCErrorCode.PARENT_DEADLINE, AALCCompletionMode.PARENT_DEADLINE),
        AALCRunStatus.CANCELLED: (AALCErrorCode.CANCELLED, AALCCompletionMode.CANCELLATION),
    }
    code, mode = values[status]
    return AALCRunResult(status, code, mode, NOW, LATER, 2.0, 3, 0, None)


def mumu_result(status: MumuRuntimeStatus, *, changed: bool = False) -> MumuRuntimeResult:
    success = status in {
        MumuRuntimeStatus.READY,
        MumuRuntimeStatus.STOPPED,
        MumuRuntimeStatus.STARTED,
        MumuRuntimeStatus.RESTARTED,
    }
    code = MumuRuntimeErrorCode.OK if success else MumuRuntimeErrorCode.READINESS_FAILED
    if status == MumuRuntimeStatus.CANCELLED:
        code = MumuRuntimeErrorCode.CANCELLED
    return MumuRuntimeResult(
        MumuAction.STATUS,
        status,
        code,
        NOW,
        LATER,
        2000,
        changed,
        {"executable": "E:\\private\\mumu.exe"},
    )


class FakeRunPort:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0
        self.deadline: Deadline | None = None
        self.cancel: CancellationToken | None = None

    def run(self, deadline=None, cancel=None):
        self.calls += 1
        self.deadline = deadline
        self.cancel = cancel
        return self.result


class FakeMumuPort:
    def __init__(self, result: MumuRuntimeResult, ensure_result: MumuRuntimeResult | None = None) -> None:
        self.result = result
        self.ensure_result = ensure_result
        self.calls = 0
        self.status_calls = 0
        self.ensure_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.deadline: Deadline | None = None
        self.cancel: CancellationToken | None = None

    def status(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        self.calls += 1
        self.status_calls += 1
        self.deadline = deadline
        self.cancel = cancel
        return self.result

    def ensure_external_ready(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        self.calls += 1
        self.ensure_calls += 1
        self.deadline = deadline
        self.cancel = cancel
        return self.ensure_result if self.ensure_result is not None else self.result

    def start(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        self.calls += 1
        self.start_calls += 1
        self.deadline = deadline
        self.cancel = cancel
        return self.result

    def stop(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        self.calls += 1
        self.stop_calls += 1
        self.deadline = deadline
        self.cancel = cancel
        return self.result


class FakeExternalMumuStatusPort:
    """镜像生产 ``_ExternalMumuStatusPort``：只暴露 status/ensure，不含生命周期方法。"""

    def __init__(self, result: MumuRuntimeResult, ensure_result: MumuRuntimeResult | None = None) -> None:
        self._inner = FakeMumuPort(result, ensure_result)

    @property
    def calls(self) -> int:
        return self._inner.calls

    @property
    def status_calls(self) -> int:
        return self._inner.status_calls

    @property
    def ensure_calls(self) -> int:
        return self._inner.ensure_calls

    @property
    def deadline(self) -> Deadline | None:
        return self._inner.deadline

    @property
    def cancel(self) -> CancellationToken | None:
        return self._inner.cancel

    def status(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        return self._inner.status(deadline, cancel)

    def ensure_external_ready(self, deadline: Deadline, cancel: CancellationToken | None = None) -> MumuRuntimeResult:
        return self._inner.ensure_external_ready(deadline, cancel)
