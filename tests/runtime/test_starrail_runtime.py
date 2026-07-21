"""StarRailCopilot Adapter 集成测试。使用 Fake StarRail 通过 ProcessSupervisor 真实执行。"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from autogame_orchestrator.config_model import StarRailConfig
from autogame_orchestrator.process import CancellationToken, Deadline
from autogame_orchestrator.runtime.starrail import StarRailAdapter
from autogame_orchestrator.runtime.starrail_log import (
    MAX_LOG_READ_BYTES,
    capture_log_cursor,
    match_starrail_keyword,
    read_log_update,
    resolve_starrail_log_path,
)
from autogame_orchestrator.runtime.starrail_models import (
    MAX_OUTPUT_EXCERPT_CHARS,
    StarRailCompletionMode,
    StarRailErrorCode,
    StarRailRunStatus,
)

_FAKE_SR = str(Path(__file__).resolve().parent.parent / "fakes" / "fake_starrail.py")
_PYTHON = Path(sys.executable)


def _check_pid_exited(pid: int, label: str, timeout: float = 3.0) -> None:
    import ctypes

    dl = time.monotonic() + timeout
    while time.monotonic() < dl:
        h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if h == 0:
            return
        r = ctypes.windll.kernel32.WaitForSingleObject(h, 100)
        ctypes.windll.kernel32.CloseHandle(h)
        if r == 0:
            return
        time.sleep(0.05)
    h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
        raise AssertionError(f"{label} PID {pid} 在 {timeout}s 后仍存活")


def _make_config(
    *,
    mode: str = "success_log",
    executable: Path = _PYTHON,
    working_directory: str | None = None,
    log_file: str | None = None,
    child_pid_file: str | None = None,
    timeout_seconds: int = 120,
) -> tuple[StarRailConfig, str, str]:
    import tempfile

    tmp_dir = tempfile.mkdtemp(prefix="sr-test-")
    wd = working_directory or tmp_dir
    lg = log_file or os.path.join(tmp_dir, "log", f"{time.strftime('%Y-%m-%d')}_src.txt")
    os.makedirs(Path(lg).parent, exist_ok=True)

    args = [_FAKE_SR, "--mode", mode, "--log-file", lg, "--pid-file", os.path.join(tmp_dir, "pid.txt")]
    if child_pid_file:
        args.extend(["--child-pid-file", child_pid_file])

    cfg = StarRailConfig(
        executable=str(executable),
        working_directory=wd,
        arguments=tuple(args),
        log_path_template=lg,
        success_keywords=("No task pending", "for task `Restart`"),
        failure_keywords=("ScriptError:", "Request human takeover", "Retry screenshot() failed", "NemuIpcError"),
        task_timeout_seconds=timeout_seconds,
        stop_timeout_seconds=2,
    )
    return cfg, lg, tmp_dir


# ════════════════════════════════════════════════════════════════════
# 日志模块测试
# ════════════════════════════════════════════════════════════════════


def test_resolve_relative_log_path_with_date(tmp_path: Path) -> None:
    cfg = StarRailConfig(
        executable=str(_PYTHON),
        working_directory=str(tmp_path),
        arguments=("gui.py",),
        log_path_template="log\\{date}_src.txt",
    )
    resolved = resolve_starrail_log_path(cfg)
    date_str = time.strftime("%Y-%m-%d")
    assert date_str in resolved.name
    assert resolved.parent == (tmp_path / "log").resolve()


def test_resolve_absolute_log_path(tmp_path: Path) -> None:
    abs_log = tmp_path / "custom" / "test.log"
    cfg = StarRailConfig(
        executable=str(_PYTHON),
        working_directory="C:/any",
        arguments=("gui.py",),
        log_path_template=str(abs_log),
    )
    resolved = resolve_starrail_log_path(cfg)
    assert resolved == abs_log.resolve()


def test_capture_cursor_ignores_existing_content(tmp_path: Path) -> None:
    log_file = tmp_path / "src.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("No task pending\n", encoding="utf-8")
    cursor = capture_log_cursor(log_file)
    assert cursor.offset > 0
    update = read_log_update(cursor)
    assert update.text == ""


def test_log_cursor_reads_only_appended_content(tmp_path: Path) -> None:
    log_file = tmp_path / "src.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("before\n", encoding="utf-8")
    cursor = capture_log_cursor(log_file)
    log_file.write_text("before\nappended\n", encoding="utf-8")
    update = read_log_update(cursor)
    assert "appended" in update.text
    assert "before" not in update.text


def test_log_cursor_detects_truncation(tmp_path: Path) -> None:
    log_file = tmp_path / "src.log"
    log_file.write_text("original content\n", encoding="utf-8")
    cursor = capture_log_cursor(log_file)
    log_file.write_text("shortened\n", encoding="utf-8")
    update = read_log_update(cursor)
    assert update.rotated
    assert "original" not in update.text
    assert "shortened" in update.text


def test_split_keyword_is_detected_across_reads(tmp_path: Path) -> None:
    log_file = tmp_path / "src.log"
    log_file.write_text("old\n", encoding="utf-8")
    cursor = capture_log_cursor(log_file)
    # Append "No task " then wait, then append "pending" on same logical line
    with open(log_file, "a", encoding="utf-8") as f:
        f.write("No task ")
        f.flush()
    read_log_update(cursor, max_bytes=8)
    assert "No task " in cursor.rolling_text
    with open(log_file, "a", encoding="utf-8") as f:
        f.write("pending\n")
        f.flush()
    read_log_update(cursor, max_bytes=8)
    match = match_starrail_keyword(
        cursor.rolling_text, success_keywords=("No task pending",), failure_keywords=("ScriptError:",)
    )
    assert match is not None
    assert match.kind == "success"


def test_failure_keyword_has_priority(tmp_path: Path) -> None:
    log_file = tmp_path / "src.log"
    log_file.write_text("", encoding="utf-8")
    cursor = capture_log_cursor(log_file)
    log_file.write_text("No task pending\nScriptError: fail\n", encoding="utf-8")
    read_log_update(cursor)
    match = match_starrail_keyword(
        cursor.rolling_text, success_keywords=("No task pending",), failure_keywords=("ScriptError:",)
    )
    assert match is not None
    assert match.kind == "failure"
    assert match.keyword == "ScriptError:"


def test_log_read_overflow_is_reported(tmp_path: Path) -> None:
    log_file = tmp_path / "src.log"
    log_file.write_text("", encoding="utf-8")
    cursor = capture_log_cursor(log_file)
    log_file.write_text("A" * (MAX_LOG_READ_BYTES + 100), encoding="utf-8")
    update = read_log_update(cursor)
    assert update.overflow


# ════════════════════════════════════════════════════════════════════
# Adapter 集成测试
# ════════════════════════════════════════════════════════════════════


def test_success_keyword_completes_and_cleans_process(tmp_path: Path) -> None:
    cfg, log, _ = _make_config(mode="success_log")
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    result = adapter.run(Deadline.after(10.0))
    assert result.status == StarRailRunStatus.COMPLETED
    assert result.error_code == StarRailErrorCode.OK
    assert result.completion_mode == StarRailCompletionMode.LOG_SUCCESS
    assert result.matched_keyword == "No task pending"
    assert result.owned_process_cleaned is True
    if result.pid:
        _check_pid_exited(result.pid, "success父进程")


def test_restart_success_keyword_completes(tmp_path: Path) -> None:
    cfg, log, _ = _make_config(mode="restart_success_log")
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    result = adapter.run(Deadline.after(10.0))
    assert result.status == StarRailRunStatus.COMPLETED
    assert "Restart" in result.matched_keyword


def test_failure_keyword_fails_and_cleans_process(tmp_path: Path) -> None:
    cfg, log, _ = _make_config(mode="failure_log")
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    result = adapter.run(Deadline.after(10.0))
    assert result.status == StarRailRunStatus.FAILED
    assert result.error_code == StarRailErrorCode.FAILURE_KEYWORD
    assert result.completion_mode == StarRailCompletionMode.LOG_FAILURE
    assert result.matched_keyword == "ScriptError:"
    if result.pid:
        _check_pid_exited(result.pid, "failure父进程")


def test_failure_keyword_wins_over_success(tmp_path: Path) -> None:
    cfg, log, _ = _make_config(mode="both_keywords")
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    result = adapter.run(Deadline.after(10.0))
    assert result.status == StarRailRunStatus.FAILED
    assert result.error_code == StarRailErrorCode.FAILURE_KEYWORD
    assert "ScriptError:" in result.matched_keyword


def test_split_success_keyword_completes(tmp_path: Path) -> None:
    cfg, log, _ = _make_config(mode="split_success")
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    result = adapter.run(Deadline.after(10.0))
    assert result.status == StarRailRunStatus.COMPLETED
    assert result.matched_keyword == "No task pending"


def test_rotated_log_is_read(tmp_path: Path) -> None:
    cfg, log, _ = _make_config(mode="rotate_success")
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    result = adapter.run(Deadline.after(10.0))
    assert result.status == StarRailRunStatus.COMPLETED
    assert result.matched_keyword == "No task pending"


def test_stale_success_keyword_is_ignored(tmp_path: Path) -> None:
    log_file = Path(tmp_path) / "log" / f"{time.strftime('%Y-%m-%d')}_src.txt"
    log_file.parent.mkdir(parents=True)
    log_file.write_text("No task pending\n", encoding="utf-8")
    cfg, log, tmp = _make_config(mode="hang", log_file=str(log_file))
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    result = adapter.run(Deadline.after(0.5))
    assert result.status == StarRailRunStatus.TIMEOUT


def test_exit_zero_before_success_fails(tmp_path: Path) -> None:
    cfg, log, _ = _make_config(mode="exit_zero")
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    result = adapter.run(Deadline.after(5.0))
    assert result.status == StarRailRunStatus.FAILED
    assert result.error_code == StarRailErrorCode.PROCESS_EXIT_BEFORE_SUCCESS
    assert result.exit_code == 0


def test_exit_nonzero_fails(tmp_path: Path) -> None:
    cfg, log, _ = _make_config(mode="exit_nonzero")
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    result = adapter.run(Deadline.after(5.0))
    assert result.status == StarRailRunStatus.FAILED
    assert result.error_code == StarRailErrorCode.PROCESS_EXIT_NONZERO
    assert result.exit_code == 7


def test_timeout_is_bounded_and_cleans_pid(tmp_path: Path) -> None:
    cfg, log, _ = _make_config(mode="hang")
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    t0 = time.monotonic()
    result = adapter.run(Deadline.after(0.3))
    elapsed = time.monotonic() - t0
    assert elapsed < 5.0
    assert result.status == StarRailRunStatus.TIMEOUT
    assert result.error_code == StarRailErrorCode.TASK_TIMEOUT
    assert result.owned_process_cleaned is True
    if result.pid:
        _check_pid_exited(result.pid, "timeout父进程")


def test_cancellation_is_not_timeout(tmp_path: Path) -> None:
    cfg, log, _ = _make_config(mode="hang")
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    cancel = CancellationToken()
    t0 = time.monotonic()

    def _cancel() -> None:
        time.sleep(0.2)
        cancel.cancel()

    import threading

    t = threading.Thread(target=_cancel, daemon=True)
    t.start()
    result = adapter.run(Deadline.after(10.0), cancel=cancel)
    t.join()
    elapsed = time.monotonic() - t0
    assert elapsed < 5.0
    assert result.status == StarRailRunStatus.CANCELLED
    assert result.error_code == StarRailErrorCode.CANCELLED
    if result.pid:
        _check_pid_exited(result.pid, "cancel父进程")


def test_parent_deadline_caps_config_timeout(tmp_path: Path) -> None:
    cfg, log, _ = _make_config(mode="hang", timeout_seconds=120)
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    t0 = time.monotonic()
    result = adapter.run(Deadline.after(0.5))
    elapsed = time.monotonic() - t0
    assert elapsed < 2.0  # 父 deadline 0.5s 应优先
    assert result.status == StarRailRunStatus.TIMEOUT


def test_large_log_fails_closed(tmp_path: Path) -> None:
    cfg, log, _ = _make_config(mode="large_log")
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    result = adapter.run(Deadline.after(5.0))
    assert result.status == StarRailRunStatus.FAILED
    assert result.error_code == StarRailErrorCode.LOG_OUTPUT_LIMIT


def test_large_stdout_and_stderr_are_truncated(tmp_path: Path) -> None:
    cfg, log, _ = _make_config(mode="large_output_success")
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    result = adapter.run(Deadline.after(10.0))
    assert result.status == StarRailRunStatus.COMPLETED
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert len(result.stdout_excerpt) <= MAX_OUTPUT_EXCERPT_CHARS
    assert len(result.stderr_excerpt) <= MAX_OUTPUT_EXCERPT_CHARS


def test_arguments_working_directory_and_environment_propagate(tmp_path: Path) -> None:
    capture_file = Path(tmp_path) / "capture.json"
    cfg = StarRailConfig(
        executable=str(_PYTHON),
        working_directory=str(tmp_path),
        arguments=(
            _FAKE_SR,
            "--mode",
            "success_log",
            "--log-file",
            str(tmp_path / "log.log"),
            "--pid-file",
            str(tmp_path / "pid.txt"),
            "--capture-file",
            str(capture_file),
        ),
        log_path_template=str(tmp_path / "log.log"),
        environment_overrides=(("PYTHONIOENCODING", "utf-8"),),
        task_timeout_seconds=120,
        stop_timeout_seconds=2,
    )
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    result = adapter.run(Deadline.after(10.0))
    assert result.status == StarRailRunStatus.COMPLETED
    assert capture_file.exists()
    data = json.loads(capture_file.read_text(encoding="utf-8"))
    assert data["python_io_encoding"] == "utf-8"
    assert str(tmp_path) in data["working_directory"]


def test_child_process_is_cleaned_after_success(tmp_path: Path) -> None:
    child_pid_file = Path(tmp_path) / "child.pid"
    cfg, log, _ = _make_config(mode="child_success", child_pid_file=str(child_pid_file))
    adapter = StarRailAdapter(cfg, poll_interval_seconds=0.05)
    result = adapter.run(Deadline.after(10.0))
    assert result.status == StarRailRunStatus.COMPLETED
    if result.pid:
        _check_pid_exited(result.pid, "child父进程")
    if child_pid_file.exists():
        child_pid = int(child_pid_file.read_text().strip())
        _check_pid_exited(child_pid, "child子进程")


def test_start_failure_is_structured(tmp_path: Path) -> None:
    cfg = StarRailConfig(
        executable=str(tmp_path / "nonexistent"),
        working_directory=str(tmp_path),
        arguments=("gui.py",),
        log_path_template=str(tmp_path / "log.log"),
    )
    adapter = StarRailAdapter(cfg)
    result = adapter.run(Deadline.after(5.0))
    assert result.status == StarRailRunStatus.FAILED
    assert result.error_code == StarRailErrorCode.EXECUTABLE_NOT_FOUND
    assert result.completion_mode == StarRailCompletionMode.START_FAILURE
    assert result.pid is None


def test_missing_log_parent_is_rejected(tmp_path: Path) -> None:
    cfg = StarRailConfig(
        executable=str(_PYTHON),
        working_directory=str(tmp_path),
        arguments=("gui.py",),
        log_path_template=str(tmp_path / "nonexistent_dir" / "log.log"),
    )
    adapter = StarRailAdapter(cfg)
    result = adapter.run(Deadline.after(5.0))
    assert result.status == StarRailRunStatus.FAILED
    assert result.error_code == StarRailErrorCode.LOG_PARENT_NOT_FOUND


def test_pre_cancel_does_not_launch(tmp_path: Path) -> None:
    cancel = CancellationToken()
    cancel.cancel()
    cfg = StarRailConfig(
        executable=str(_PYTHON),
        working_directory=str(tmp_path),
        arguments=("gui.py",),
        log_path_template=str(tmp_path / "log.log"),
    )
    adapter = StarRailAdapter(cfg)
    result = adapter.run(Deadline.after(5.0), cancel=cancel)
    assert result.status == StarRailRunStatus.CANCELLED
    assert result.pid is None
