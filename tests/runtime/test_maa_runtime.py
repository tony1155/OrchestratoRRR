"""MAA 适配器的进程监督、进程树和结果模型验收测试。"""

from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from autogame_orchestrator.config_model import MAAConfig
from autogame_orchestrator.process import (
    CancellationToken,
    Deadline,
    ProcessExecutionErrorCode,
    ProcessResult,
    ProcessSupervisor,
    ProcessSupervisorCloseError,
    TerminationReason,
)
from autogame_orchestrator.runtime import MAAAdapter, MAAErrorCode, MAARunResult, MAARunStatus
from autogame_orchestrator.runtime.maa import MAX_OUTPUT_EXCERPT_CHARS, _map_process_result

_FAKE = str((Path(__file__).parents[1] / "fakes" / "fake_maa.py").resolve())
_PYTHON = str(Path(sys.executable).resolve())


def _config(
    tmp_path: Path,
    mode: str,
    *,
    timeout_seconds: int = 5,
    extra_arguments: tuple[str, ...] = (),
    environment: tuple[tuple[str, str], ...] = (),
) -> MAAConfig:
    return MAAConfig(
        executable=_PYTHON,
        working_directory=str(tmp_path.resolve()),
        arguments=(_FAKE, "--mode", mode, *extra_arguments),
        environment_overrides=environment,
        timeout_seconds=timeout_seconds,
        stop_timeout_seconds=2,
    )


def _wait_for_pid_file(path: Path, *, timeout_seconds: float = 3.0) -> int:
    deadline = time.monotonic() + timeout_seconds
    last_text = ""
    while time.monotonic() < deadline:
        try:
            last_text = path.read_text(encoding="utf-8").strip()
            pid = int(last_text)
        except (FileNotFoundError, OSError, ValueError):
            time.sleep(0.02)
            continue
        if pid > 0:
            return pid
        time.sleep(0.02)
    raise AssertionError(f"等待 PID 文件超时：path={path}, last_text={last_text!r}")


def _check_pid_exited(pid: int, label: str, timeout_seconds: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if handle == 0:
            return
        wait_result = ctypes.windll.kernel32.WaitForSingleObject(handle, 100)
        ctypes.windll.kernel32.CloseHandle(handle)
        if wait_result == 0:
            return
        time.sleep(0.02)
    raise AssertionError(f"{label} PID {pid} 在 {timeout_seconds}s 后仍存活")


def _run_in_thread(adapter: MAAAdapter, cancellation: CancellationToken) -> tuple[threading.Thread, list[MAARunResult]]:
    results: list[MAARunResult] = []
    thread = threading.Thread(target=lambda: results.append(adapter.run(cancel=cancellation)), daemon=True)
    thread.start()
    return thread, results


def _join_result(thread: threading.Thread, results: list[MAARunResult]) -> MAARunResult:
    thread.join(5.0)
    assert not thread.is_alive()
    assert len(results) == 1
    return results[0]


def _result_json(result: MAARunResult) -> str:
    payload: dict[str, Any] = {}
    for item in fields(result):
        value = getattr(result, item.name)
        if isinstance(value, datetime):
            payload[item.name] = value.isoformat()
        elif hasattr(value, "value"):
            payload[item.name] = value.value
        elif item.name == "diagnostics":
            payload[item.name] = dict(value)
        else:
            payload[item.name] = value
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _valid_model_result(**overrides: object) -> MAARunResult:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "status": MAARunStatus.COMPLETED,
        "error_code": MAAErrorCode.OK,
        "started_at": now,
        "finished_at": now,
        "duration_ms": 0,
        "pid": 1,
        "exit_code": 0,
        "termination_reason": TerminationReason.NORMAL_EXIT,
        "owned_process_cleaned": True,
        "stdout_excerpt": "",
        "stderr_excerpt": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "diagnostics": {},
    }
    values.update(overrides)
    return MAARunResult(**values)  # type: ignore[arg-type]


def test_exit_zero_completes(tmp_path: Path) -> None:
    result = MAAAdapter(_config(tmp_path, "exit_zero")).run()
    assert result.status == MAARunStatus.COMPLETED
    assert result.error_code == MAAErrorCode.OK
    assert result.exit_code == 0
    assert result.termination_reason == TerminationReason.NORMAL_EXIT
    assert result.pid is not None
    assert result.pid > 0
    _check_pid_exited(result.pid, "exit zero 父进程")


def test_exit_nonzero_fails(tmp_path: Path) -> None:
    result = MAAAdapter(_config(tmp_path, "exit_nonzero")).run()
    assert result.status == MAARunStatus.FAILED
    assert result.error_code == MAAErrorCode.PROCESS_EXIT_NONZERO
    assert result.exit_code == 7
    assert result.termination_reason == TerminationReason.NONZERO_EXIT


def test_timeout_is_bounded_and_cleans_pid(tmp_path: Path) -> None:
    pid_file = tmp_path / "timeout-parent.pid"
    config = _config(tmp_path, "hang", extra_arguments=("--pid-file", str(pid_file)))
    started = time.monotonic()
    result = MAAAdapter(config).run(Deadline.after(0.2))
    assert time.monotonic() - started < 3.0
    assert result.status == MAARunStatus.TIMEOUT
    assert result.error_code == MAAErrorCode.PROCESS_TIMEOUT
    assert result.termination_reason == TerminationReason.TIMEOUT
    assert result.pid is not None
    assert result.pid > 0
    fake_pid = _wait_for_pid_file(pid_file)
    _check_pid_exited(result.pid, "timeout 父进程")
    _check_pid_exited(fake_pid, "timeout Fake 进程")


def test_cancellation_is_not_timeout(tmp_path: Path) -> None:
    pid_file = tmp_path / "cancel-parent.pid"
    config = _config(tmp_path, "hang", extra_arguments=("--pid-file", str(pid_file)))
    cancellation = CancellationToken()
    thread, results = _run_in_thread(MAAAdapter(config), cancellation)
    parent_pid = _wait_for_pid_file(pid_file)
    cancellation.cancel()
    result = _join_result(thread, results)
    assert result.status == MAARunStatus.CANCELLED
    assert result.error_code == MAAErrorCode.CANCELLED
    assert result.termination_reason == TerminationReason.CANCELLED
    assert result.pid is not None
    assert result.pid > 0
    _check_pid_exited(result.pid, "cancel 受管进程")
    _check_pid_exited(parent_pid, "cancel 父进程")


def test_parent_deadline_caps_config_timeout(tmp_path: Path) -> None:
    started = time.monotonic()
    result = MAAAdapter(_config(tmp_path, "hang", timeout_seconds=30)).run(Deadline.after(0.1))
    assert time.monotonic() - started < 2.0
    assert result.status == MAARunStatus.TIMEOUT
    assert result.error_code == MAAErrorCode.PROCESS_TIMEOUT


def test_pre_cancel_does_not_launch(tmp_path: Path) -> None:
    pid_file = tmp_path / "pre-cancel.pid"
    cancellation = CancellationToken()
    cancellation.cancel()
    config = _config(tmp_path, "hang", extra_arguments=("--pid-file", str(pid_file)))
    result = MAAAdapter(config).run(cancel=cancellation)
    assert result.status == MAARunStatus.CANCELLED
    assert result.error_code == MAAErrorCode.CANCELLED
    assert result.pid is None
    assert not pid_file.exists()


def test_start_failure_is_structured(tmp_path: Path) -> None:
    text_executable = tmp_path / "not-executable.txt"
    text_executable.write_text("不是可执行文件", encoding="utf-8")
    config = MAAConfig(str(text_executable), str(tmp_path), timeout_seconds=1)
    assert config.check_paths() == []
    result = MAAAdapter(config).run()
    assert result.status == MAARunStatus.FAILED
    assert result.error_code == MAAErrorCode.PROCESS_START_FAILED
    assert result.pid is None
    assert result.owned_process_cleaned is True
    assert str(text_executable.resolve()) not in json.dumps(dict(result.diagnostics), ensure_ascii=False)


def test_missing_executable_is_rejected(tmp_path: Path) -> None:
    result = MAAAdapter(MAAConfig(str(tmp_path / "missing.exe"), str(tmp_path))).run()
    assert result.error_code == MAAErrorCode.EXECUTABLE_NOT_FOUND
    assert result.pid is None


def test_missing_working_directory_is_rejected(tmp_path: Path) -> None:
    result = MAAAdapter(MAAConfig(_PYTHON, str(tmp_path / "missing"))).run()
    assert result.error_code == MAAErrorCode.WORKING_DIRECTORY_NOT_FOUND
    assert result.pid is None


def test_executable_directory_is_rejected(tmp_path: Path) -> None:
    result = MAAAdapter(MAAConfig(str(tmp_path), str(tmp_path))).run()
    assert result.error_code == MAAErrorCode.EXECUTABLE_NOT_FOUND


def test_working_directory_file_is_rejected(tmp_path: Path) -> None:
    working_file = tmp_path / "file"
    working_file.write_text("x", encoding="utf-8")
    result = MAAAdapter(MAAConfig(_PYTHON, str(working_file))).run()
    assert result.error_code == MAAErrorCode.WORKING_DIRECTORY_NOT_FOUND


def test_arguments_working_directory_and_environment_propagate(tmp_path: Path) -> None:
    capture_file = tmp_path / "capture.json"
    extra = ("--capture-file", str(capture_file), "--first", "one", "tail")
    environment = (("PYTHONIOENCODING", "utf-8"), ("MAA_TEST_TOKEN", "secret-token"))
    result = MAAAdapter(_config(tmp_path, "exit_zero", extra_arguments=extra, environment=environment)).run()
    data = json.loads(capture_file.read_text(encoding="utf-8"))
    assert data["arguments"] == ["--first", "one", "tail"]
    assert Path(data["working_directory"]).resolve() == tmp_path.resolve()
    assert data["python_io_encoding"] == "utf-8"
    assert data["maa_test_token"] == "secret-token"
    diagnostics = json.dumps(dict(result.diagnostics), ensure_ascii=False)
    assert "secret-token" not in diagnostics
    assert "MAA_TEST_TOKEN" not in diagnostics


def test_large_output_is_truncated(tmp_path: Path) -> None:
    result = MAAAdapter(_config(tmp_path, "large_output_exit_zero")).run()
    assert result.status == MAARunStatus.COMPLETED
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert len(result.stdout_excerpt) <= MAX_OUTPUT_EXCERPT_CHARS
    assert len(result.stderr_excerpt) <= MAX_OUTPUT_EXCERPT_CHARS


def test_utf16_output_is_decoded(tmp_path: Path) -> None:
    result = MAAAdapter(_config(tmp_path, "utf16_output_exit_zero")).run()
    assert result.status == MAARunStatus.COMPLETED
    assert "中文输出" in result.stdout_excerpt


def test_child_is_cleaned_after_parent_exit_zero(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    result = MAAAdapter(
        _config(tmp_path, "child_exit_zero", extra_arguments=("--child-pid-file", str(child_pid_file)))
    ).run()
    assert result.status == MAARunStatus.COMPLETED
    assert result.pid is not None
    assert result.pid > 0
    assert child_pid_file.exists()
    child_pid = int(child_pid_file.read_text(encoding="utf-8").strip())
    assert child_pid > 0
    _check_pid_exited(result.pid, "exit zero 父进程")
    _check_pid_exited(child_pid, "exit zero 子进程")


def test_child_is_cleaned_after_timeout(tmp_path: Path) -> None:
    parent_pid_file = tmp_path / "parent.pid"
    child_pid_file = tmp_path / "child.pid"
    extra = ("--pid-file", str(parent_pid_file), "--child-pid-file", str(child_pid_file))
    result = MAAAdapter(_config(tmp_path, "child_hang", extra_arguments=extra)).run(Deadline.after(0.3))
    parent_pid = _wait_for_pid_file(parent_pid_file)
    assert child_pid_file.exists()
    child_pid = int(child_pid_file.read_text(encoding="utf-8").strip())
    assert parent_pid > 0
    assert child_pid > 0
    assert result.status == MAARunStatus.TIMEOUT
    assert result.error_code == MAAErrorCode.PROCESS_TIMEOUT
    assert result.pid is not None
    assert result.pid > 0
    _check_pid_exited(result.pid, "timeout 受管进程")
    _check_pid_exited(parent_pid, "timeout 父进程")
    _check_pid_exited(child_pid, "timeout 子进程")


def test_child_is_cleaned_after_cancellation(tmp_path: Path) -> None:
    parent_pid_file = tmp_path / "parent.pid"
    child_pid_file = tmp_path / "child.pid"
    extra = ("--pid-file", str(parent_pid_file), "--child-pid-file", str(child_pid_file))
    cancellation = CancellationToken()
    thread, results = _run_in_thread(MAAAdapter(_config(tmp_path, "child_hang", extra_arguments=extra)), cancellation)
    parent_pid = _wait_for_pid_file(parent_pid_file)
    child_pid = _wait_for_pid_file(child_pid_file)
    cancellation.cancel()
    result = _join_result(thread, results)
    assert parent_pid > 0
    assert child_pid_file.exists()
    assert child_pid > 0
    assert result.status == MAARunStatus.CANCELLED
    assert result.error_code == MAAErrorCode.CANCELLED
    assert result.pid is not None
    assert result.pid > 0
    _check_pid_exited(result.pid, "cancel 受管进程")
    _check_pid_exited(parent_pid, "cancel 父进程")
    _check_pid_exited(child_pid, "cancel 子进程")


def test_result_does_not_expose_temp_paths(tmp_path: Path) -> None:
    config = _config(tmp_path, "exit_zero")
    result = MAAAdapter(config).run()
    strings = [value for item in fields(result) if isinstance((value := getattr(result, item.name)), str)]
    strings.append(json.dumps(dict(result.diagnostics), ensure_ascii=False, sort_keys=True))
    combined = "\n".join(strings)
    for forbidden in (
        "orchestratorrr-maa-",
        "stdout.bin",
        "stderr.bin",
        str(tmp_path.resolve()),
        str(Path(config.executable).resolve()),
        str(Path(config.working_directory).resolve()),
    ):
        assert forbidden not in combined


def test_result_is_json_serializable(tmp_path: Path) -> None:
    result = MAAAdapter(_config(tmp_path, "exit_zero")).run()
    encoded = _result_json(result)
    assert json.loads(encoded)["status"] == "completed"


def test_completed_result_invariants() -> None:
    assert _valid_model_result().status == MAARunStatus.COMPLETED
    with pytest.raises(ValueError):
        _valid_model_result(exit_code=1)
    with pytest.raises(ValueError):
        _valid_model_result(stdout_excerpt=1)
    with pytest.raises(ValueError):
        _valid_model_result(duration_ms=-1)
    with pytest.raises(ValueError):
        _valid_model_result(started_at=datetime.now())
    with pytest.raises(ValueError):
        _valid_model_result(diagnostics={"bad": object()})


def test_non_completed_result_rejects_ok() -> None:
    with pytest.raises(ValueError):
        _valid_model_result(status=MAARunStatus.FAILED)


def test_cleanup_failed_requires_false() -> None:
    with pytest.raises(ValueError):
        _valid_model_result(status=MAARunStatus.FAILED, error_code=MAAErrorCode.CLEANUP_FAILED)


def test_timeout_result_invariants() -> None:
    result = _valid_model_result(
        status=MAARunStatus.TIMEOUT,
        error_code=MAAErrorCode.PROCESS_TIMEOUT,
        exit_code=None,
        termination_reason=TerminationReason.TIMEOUT,
    )
    assert result.status == MAARunStatus.TIMEOUT
    with pytest.raises(ValueError):
        _valid_model_result(status=MAARunStatus.TIMEOUT, error_code=MAAErrorCode.INTERNAL_ERROR)


def test_cancelled_result_invariants() -> None:
    result = _valid_model_result(
        status=MAARunStatus.CANCELLED,
        error_code=MAAErrorCode.CANCELLED,
        exit_code=None,
        termination_reason=TerminationReason.CANCELLED,
    )
    assert result.status == MAARunStatus.CANCELLED
    with pytest.raises(ValueError):
        _valid_model_result(status=MAARunStatus.CANCELLED, error_code=MAAErrorCode.INTERNAL_ERROR)


def test_unexpected_stopped_reason_maps_internal_error() -> None:
    now = datetime.now(UTC)
    process_result = ProcessResult(
        name="maa_cli",
        pid=123,
        termination_reason=TerminationReason.STOPPED,
        exit_code=None,
        error_code=ProcessExecutionErrorCode.STOPPED,
        started_at=now,
        finished_at=now,
        duration_ms=0,
    )
    assert _map_process_result(process_result, cancelled=False, deadline_expired=False) == (
        MAARunStatus.FAILED,
        MAAErrorCode.INTERNAL_ERROR,
        False,
    )


def _raise_after_real_close(self: ProcessSupervisor) -> None:
    original_close = _raise_after_real_close.original
    original_close(self)
    raise ProcessSupervisorCloseError("测试关闭失败", ())


_raise_after_real_close.original = ProcessSupervisor.close  # type: ignore[attr-defined]


def test_close_failure_turns_success_into_cleanup_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ProcessSupervisor, "close", _raise_after_real_close)
    result = MAAAdapter(_config(tmp_path, "exit_zero")).run()
    assert result.status == MAARunStatus.FAILED
    assert result.error_code == MAAErrorCode.CLEANUP_FAILED
    assert result.owned_process_cleaned is False


def test_close_failure_preserves_timeout_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ProcessSupervisor, "close", _raise_after_real_close)
    result = MAAAdapter(_config(tmp_path, "hang")).run(Deadline.after(0.1))
    assert result.status == MAARunStatus.TIMEOUT
    assert result.error_code == MAAErrorCode.CLEANUP_FAILED
    assert result.owned_process_cleaned is False


def test_close_failure_preserves_cancelled_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ProcessSupervisor, "close", _raise_after_real_close)
    pid_file = tmp_path / "close-cancel.pid"
    cancellation = CancellationToken()
    config = _config(tmp_path, "hang", extra_arguments=("--pid-file", str(pid_file)))
    thread, results = _run_in_thread(MAAAdapter(config), cancellation)
    parent_pid = _wait_for_pid_file(pid_file)
    cancellation.cancel()
    result = _join_result(thread, results)
    assert result.status == MAARunStatus.CANCELLED
    assert result.error_code == MAAErrorCode.CLEANUP_FAILED
    assert result.owned_process_cleaned is False
    _check_pid_exited(parent_pid, "close failure cancel 父进程")


def test_unknown_fake_mode_fails(tmp_path: Path) -> None:
    result = MAAAdapter(_config(tmp_path, "unknown-mode")).run()
    assert result.status == MAARunStatus.FAILED
    assert result.error_code == MAAErrorCode.PROCESS_EXIT_NONZERO
    assert result.exit_code == 9
