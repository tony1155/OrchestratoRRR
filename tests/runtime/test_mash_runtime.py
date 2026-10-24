"""Mash 适配器的进程监督、优雅取消与结果模型验收测试。"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autogame_orchestrator.config_model import MashConfig, MashRepeatMode, MashServer
from autogame_orchestrator.process import CancellationToken, Deadline, TerminationReason
from autogame_orchestrator.process.result import ProcessExecutionErrorCode, ProcessResult
from autogame_orchestrator.runtime import MashAdapter, MashErrorCode, MashRunStatus
from autogame_orchestrator.runtime.mash import _map_process_result, build_run_arguments

_FAKE = str((Path(__file__).parents[1] / "fakes" / "fake_mash_cli.py").resolve())
_PYTHON = str(Path(sys.executable).resolve())


def _config(
    tmp_path: Path,
    *,
    extra_arguments: tuple[str, ...] = (),
    timeout_seconds: int = 30,
    stop_timeout_seconds: int = 5,
    repeat_mode: MashRepeatMode = MashRepeatMode.PROJECT_DEFAULT,
    repeat_count: int = 0,
    adb_serial: str = "",
    resource_dir: str = "",
    environment: tuple[tuple[str, str], ...] = (),
    executable: str | None = None,
    working_directory: str | None = None,
) -> MashConfig:
    return MashConfig(
        executable=executable or _PYTHON,
        working_directory=working_directory or str(tmp_path.resolve()),
        environment_overrides=environment,
        timeout_seconds=timeout_seconds,
        stop_timeout_seconds=stop_timeout_seconds,
        project_id="p-fgo-1",
        server=MashServer.CN,
        adb_serial=adb_serial,
        repeat_mode=repeat_mode,
        repeat_count=repeat_count,
        result_file=str((tmp_path / "result.json").resolve()),
        resource_dir=resource_dir,
        events="ndjson",
        # 真实部署中 executable 直接指向 mash-cli.exe，launcher_arguments 留空；
        # 测试以 python + fake 脚本代替，脚本路径经 launcher_arguments 前置。
        launcher_arguments=(_FAKE,),
        extra_arguments=extra_arguments,
    )


def _read_result(config: MashConfig) -> dict[str, object]:
    return json.loads(Path(config.result_file).read_text(encoding="utf-8"))


def test_run_arguments_follow_config() -> None:
    config = _config(
        Path("."),
        repeat_mode=MashRepeatMode.COUNT,
        repeat_count=3,
        adb_serial="127.0.0.1:16384",
        resource_dir="C:/Mash",
        extra_arguments=("--watchdog", "600"),
    )
    arguments = build_run_arguments(config)
    assert arguments[0] == "run"
    for needle in (
        "--project",
        "p-fgo-1",
        "--server",
        "cn",
        "--result-file",
        "--events",
        "ndjson",
        "--device",
        "127.0.0.1:16384",
        "--repeat",
        "count:3",
        "--watchdog",
        "600",
    ):
        assert needle in arguments, arguments


def test_run_arguments_omit_unset_options() -> None:
    arguments = build_run_arguments(_config(Path(".")))
    assert "--device" not in arguments
    assert "--repeat" not in arguments


def test_exit_zero_maps_completed_with_result_file(tmp_path: Path) -> None:
    config = _config(tmp_path, extra_arguments=("--exit-code", "0", "--completed-runs", "4"))
    result = MashAdapter(config).run()
    assert result.status is MashRunStatus.COMPLETED
    assert result.exit_code == 0
    assert result.termination_reason is TerminationReason.NORMAL_EXIT
    assert result.owned_process_cleaned is True
    # 适配器层保留结果文件的原始键；mash_* 改名发生在 StageReport 投影层。
    assert result.diagnostics["outcome"] == "finished"
    assert result.diagnostics["completedRuns"] == 4
    assert result.diagnostics["runId"] == "fake-run-id"
    assert _read_result(config)["outcome"] == "finished"


def test_exit_one_maps_failed(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        extra_arguments=("--exit-code", "1", "--outcome", "error", "--message", "device offline"),
    )
    result = MashAdapter(config).run()
    assert result.status is MashRunStatus.FAILED
    assert result.error_code is MashErrorCode.PROCESS_EXIT_NONZERO
    assert result.diagnostics["message"] == "device offline"


def test_exit_three_maps_timeout(tmp_path: Path) -> None:
    config = _config(tmp_path, extra_arguments=("--exit-code", "3", "--outcome", "timeout"))
    result = MashAdapter(config).run()
    assert result.status is MashRunStatus.TIMEOUT
    assert result.error_code is MashErrorCode.PROCESS_TIMEOUT
    assert result.diagnostics["outcome"] == "timeout"


def test_graceful_cancel_via_mash_cli_cancel(tmp_path: Path) -> None:
    """取消先走 mash-cli cancel（文件信号），进程以契约退出码 2 自行退出。"""
    config = _config(tmp_path, extra_arguments=("--mode", "hang"), stop_timeout_seconds=5)
    cancel = CancellationToken()
    holder: dict[str, object] = {}

    def worker() -> None:
        holder["result"] = MashAdapter(config).run(cancel=cancel)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    current = tmp_path / "fake-mash-appdata" / "cli" / "current.json"
    deadline = time.monotonic() + 5.0
    while not current.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert current.exists(), "fake run 未启动"
    time.sleep(0.1)
    cancel.cancel()
    thread.join(timeout=30.0)
    assert not thread.is_alive(), "适配器在取消后未返回"
    result = holder["result"]
    assert result.status is MashRunStatus.CANCELLED  # type: ignore[union-attr]
    assert result.exit_code == 2  # type: ignore[union-attr]
    assert result.termination_reason is TerminationReason.NONZERO_EXIT  # type: ignore[union-attr]
    assert result.diagnostics["graceful_stop_requested"] is True  # type: ignore[union-attr]
    assert result.diagnostics["outcome"] == "cancelled"  # type: ignore[union-attr]
    # 优雅路径不残留 current.json（fake 契约行为）。
    assert not current.exists()


def test_deadline_expiry_triggers_graceful_stop(tmp_path: Path) -> None:
    config = _config(tmp_path, extra_arguments=("--mode", "hang"), timeout_seconds=1, stop_timeout_seconds=5)
    result = MashAdapter(config).run(deadline=Deadline.after(1.0))
    assert result.status is MashRunStatus.CANCELLED
    assert result.diagnostics["graceful_stop_requested"] is True
    assert result.exit_code == 2


def test_invalid_config_maps_invalid_configuration(tmp_path: Path) -> None:
    broken = MashConfig(
        executable="",
        working_directory="",
        project_id="",
        result_file="",
    )
    assert broken.validate()
    result = MashAdapter(broken).run()
    assert result.status is MashRunStatus.FAILED
    assert result.error_code is MashErrorCode.INVALID_CONFIGURATION


def test_missing_executable_maps_not_found(tmp_path: Path) -> None:
    config = _config(tmp_path, executable=str(tmp_path / "missing.exe"))
    result = MashAdapter(config).run()
    assert result.status is MashRunStatus.FAILED
    assert result.error_code is MashErrorCode.EXECUTABLE_NOT_FOUND


def test_pre_cancelled_token_short_circuits(tmp_path: Path) -> None:
    cancel = CancellationToken()
    cancel.cancel()
    result = MashAdapter(_config(tmp_path)).run(cancel=cancel)
    assert result.status is MashRunStatus.CANCELLED
    assert result.error_code is MashErrorCode.CANCELLED


def _process_result(reason: TerminationReason, exit_code: int | None) -> ProcessResult:
    now = datetime.now(UTC)
    return ProcessResult(
        name="mash",
        pid=123,
        termination_reason=reason,
        exit_code=exit_code,
        error_code=(
            ProcessExecutionErrorCode.OK
            if reason is TerminationReason.NORMAL_EXIT
            else ProcessExecutionErrorCode.EXIT_NONZERO
        ),
        started_at=now,
        finished_at=now,
        duration_ms=100,
    )


def test_map_stopped_after_graceful_failure() -> None:
    stopped = _process_result(TerminationReason.STOPPED, None)
    status, code, cleaned = _map_process_result(
        stopped, cancelled=True, deadline_expired=False, graceful_stop_requested=True
    )
    assert (status, code, cleaned) == (MashRunStatus.CANCELLED, MashErrorCode.GRACEFUL_STOP_FAILED, True)
    status, code, _ = _map_process_result(stopped, cancelled=False, deadline_expired=True, graceful_stop_requested=True)
    assert (status, code) == (MashRunStatus.TIMEOUT, MashErrorCode.GRACEFUL_STOP_FAILED)


@pytest.mark.parametrize(
    "exit_code,expected_status,expected_code",
    [
        (2, MashRunStatus.CANCELLED, MashErrorCode.CANCELLED),
        (3, MashRunStatus.TIMEOUT, MashErrorCode.PROCESS_TIMEOUT),
        (7, MashRunStatus.FAILED, MashErrorCode.PROCESS_EXIT_NONZERO),
    ],
)
def test_map_nonzero_exit_contract(
    exit_code: int, expected_status: MashRunStatus, expected_code: MashErrorCode
) -> None:
    status, code, cleaned = _map_process_result(
        _process_result(TerminationReason.NONZERO_EXIT, exit_code),
        cancelled=False,
        deadline_expired=False,
        graceful_stop_requested=False,
    )
    assert (status, code, cleaned) == (expected_status, expected_code, True)


def test_environment_carries_resource_dir() -> None:
    from autogame_orchestrator.runtime.mash import _build_environment

    config = _config(Path("."), resource_dir="C:/Mash", environment=(("MASH_TEST_TOKEN", "42"),))
    environment = _build_environment(config)
    assert environment["MASH_RESOURCE_DIR"] == "C:/Mash"
    assert environment["MASH_TEST_TOKEN"] == "42"
    # 显式 environment_overrides 优先于 resource_dir 字段。
    explicit = _config(
        Path("."),
        resource_dir="C:/Mash",
        environment=(("MASH_RESOURCE_DIR", "C:/Other"),),
    )
    assert _build_environment(explicit)["MASH_RESOURCE_DIR"] == "C:/Other"
