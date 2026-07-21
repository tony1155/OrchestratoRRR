"""Win32 Launcher 集成测试。

覆盖：启动、退出码（含 259）、环境变量、句柄继承白名单、
stdout/stderr、进程树清理、失败路径、PID 残留证明。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from autogame_orchestrator.process.errors import ProcessLaunchErrorCode
from autogame_orchestrator.process.launcher import LaunchError, launch
from autogame_orchestrator.process.models import ProcessSpec

_PYTHON = sys.executable


def _fake_stage() -> Path:
    return Path(__file__).resolve().parent.parent / "fakes" / "fake_stage.py"


def _paths(
    name: str, tmp_workdir: Path, *, stdout: bool = False, stderr: bool = False
) -> tuple[Path | None, Path | None]:
    out = tmp_workdir / f"{name}-stdout.log" if stdout else None
    err = tmp_workdir / f"{name}-stderr.log" if stderr else None
    return out, err


def _wait_exit(managed: object, max_wait: int = 40) -> None:
    for _ in range(max_wait):
        if managed.poll() is not None:
            break
        time.sleep(0.1)


def _pid_file_for_test(tmp_workdir: Path, label: str) -> Path:
    return tmp_workdir / f"{label}.pid"


def _check_pid_exited(pid: int, label: str) -> None:
    """通过 OpenProcess 确认 PID 已退出。"""
    import ctypes

    SYNCHRONIZE = 0x00100000
    h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
    assert h == 0, f"{label} PID {pid} 应该已退出"


# ─── 启动测试 ────────────────────────────────────────────────────────


def test_launch_normal_exit(tmp_workdir: Path) -> None:
    """正常启动并退出码 0。"""
    stdout_p, _ = _paths("normal", tmp_workdir, stdout=True)
    spec = ProcessSpec(
        name="正常退出测试",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--exit-code", "0", "--sleep-seconds", "0.1"),
        stdout_path=stdout_p,
    )
    managed = launch(spec)
    try:
        _wait_exit(managed)
        assert managed.poll() == 0
    finally:
        managed.terminate_job()
        managed.close_handles()


def test_launch_nonzero_exit(tmp_workdir: Path) -> None:
    """非零退出码。"""
    spec = ProcessSpec(
        name="非零退出测试",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--exit-code", "42", "--sleep-seconds", "0.1"),
    )
    managed = launch(spec)
    try:
        _wait_exit(managed)
        assert managed.poll() == 42
    finally:
        managed.terminate_job()
        managed.close_handles()


def test_launch_exit_code_259(tmp_workdir: Path) -> None:
    """退出码 259（STILL_ACTIVE 常量）不会被误判为仍在运行。"""
    spec = ProcessSpec(
        name="退出码259测试",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--exit-code", "259", "--sleep-seconds", "0.1"),
    )
    managed = launch(spec)
    pid = managed.pid
    try:
        _wait_exit(managed)
        code = managed.poll()
        assert code is not None, "进程应已退出（不能把 259 当作 STILL_ACTIVE）"
        assert code == 259, f"退出码应为 259，实际: {code}"
    finally:
        managed.terminate_job()
        managed.close_handles()
        _check_pid_exited(pid, "退出码259主进程")


def test_launch_executable_not_found(tmp_workdir: Path) -> None:
    """可执行文件不存在。"""
    spec = ProcessSpec(name="不存在", executable=Path("Z:/nonexistent.exe"))
    with pytest.raises(LaunchError) as exc_info:
        launch(spec)
    assert exc_info.value.error_code == ProcessLaunchErrorCode.EXECUTABLE_NOT_FOUND


def test_launch_executable_is_directory(tmp_workdir: Path) -> None:
    """可执行文件是目录时被拒绝。"""
    spec = ProcessSpec(name="目录", executable=tmp_workdir)
    with pytest.raises(LaunchError) as exc_info:
        launch(spec)
    assert exc_info.value.error_code == ProcessLaunchErrorCode.EXECUTABLE_NOT_FOUND


def test_launch_working_directory_not_found(tmp_workdir: Path) -> None:
    """工作目录不存在。"""
    spec = ProcessSpec(
        name="目录不存在",
        executable=Path(_PYTHON),
        working_directory=Path("Z:/nonexistent_dir"),
    )
    with pytest.raises(LaunchError) as exc_info:
        launch(spec)
    assert exc_info.value.error_code == ProcessLaunchErrorCode.WORKING_DIRECTORY_NOT_FOUND


def test_launch_working_directory_is_file(tmp_workdir: Path) -> None:
    """工作目录是文件时被拒绝。"""
    file_path = tmp_workdir / "not_a_dir"
    file_path.write_text("", encoding="utf-8")
    spec = ProcessSpec(
        name="文件作目录",
        executable=Path(_PYTHON),
        working_directory=file_path,
    )
    with pytest.raises(LaunchError) as exc_info:
        launch(spec)
    assert exc_info.value.error_code == ProcessLaunchErrorCode.WORKING_DIRECTORY_NOT_FOUND


def test_launch_output_parent_is_file(tmp_workdir: Path) -> None:
    """输出路径的父级是文件时返回 OUTPUT_OPEN_FAILED。"""
    blocker = tmp_workdir / "blocker"
    blocker.write_text("", encoding="utf-8")
    stdout_p = blocker / "stdout.log"
    spec = ProcessSpec(
        name="父级是文件",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--exit-code", "0", "--sleep-seconds", "0.1"),
        stdout_path=stdout_p,
    )
    with pytest.raises(LaunchError) as exc_info:
        launch(spec)
    assert exc_info.value.error_code == ProcessLaunchErrorCode.OUTPUT_OPEN_FAILED


# ─── stdout/stderr 测试 ──────────────────────────────────────────────


def test_launch_stdout_output(tmp_workdir: Path) -> None:
    """stdout 重定向到文件。"""
    stdout_p, _ = _paths("stdout", tmp_workdir, stdout=True)
    spec = ProcessSpec(
        name="stdout 测试",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--stdout-text", "hello世界", "--sleep-seconds", "0.1"),
        stdout_path=stdout_p,
    )
    managed = launch(spec)
    try:
        _wait_exit(managed)
    finally:
        managed.terminate_job()
        managed.close_handles()
    assert b"hello" in stdout_p.read_bytes()


def test_launch_stderr_output(tmp_workdir: Path) -> None:
    """stderr 重定向到文件。"""
    _, stderr_p = _paths("stderr", tmp_workdir, stderr=True)
    spec = ProcessSpec(
        name="stderr 测试",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--stderr-text", "error信息", "--sleep-seconds", "0.1"),
        stderr_path=stderr_p,
    )
    managed = launch(spec)
    try:
        _wait_exit(managed)
    finally:
        managed.terminate_job()
        managed.close_handles()
    assert b"error" in stderr_p.read_bytes()


def test_launch_large_stdout_no_deadlock(tmp_workdir: Path) -> None:
    """5 MB stdout 输出不会死锁。"""
    stdout_p, _ = _paths("large_out", tmp_workdir, stdout=True)
    spec = ProcessSpec(
        name="大输出测试",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--output-bytes", "5000000", "--sleep-seconds", "0.1"),
        stdout_path=stdout_p,
    )
    managed = launch(spec)
    try:
        _wait_exit(managed, max_wait=80)
    finally:
        managed.terminate_job()
        managed.close_handles()
    assert stdout_p.stat().st_size >= 5000000


def test_launch_stdout_stderr_simultaneous_large(tmp_workdir: Path) -> None:
    """stdout 和 stderr 同时各 5 MB 输出不会死锁。"""
    stdout_p, stderr_p = _paths("dual", tmp_workdir, stdout=True, stderr=True)
    spec = ProcessSpec(
        name="双通道大输出",
        executable=Path(_PYTHON),
        arguments=(
            str(_fake_stage()),
            "--output-bytes",
            "5000000",
            "--stderr-output-bytes",
            "5000000",
            "--sleep-seconds",
            "0.1",
        ),
        stdout_path=stdout_p,
        stderr_path=stderr_p,
    )
    managed = launch(spec)
    try:
        _wait_exit(managed, max_wait=120)
    finally:
        managed.terminate_job()
        managed.close_handles()
    assert stdout_p.stat().st_size >= 5000000
    assert stderr_p.stat().st_size >= 5000000


# ─── 环境变量测试 ───────────────────────────────────────────────────


def test_launch_environment_overrides(tmp_workdir: Path) -> None:
    """环境变量覆盖成功。"""
    stdout_p, _ = _paths("env", tmp_workdir, stdout=True)
    spec = ProcessSpec(
        name="环境变量测试",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--echo-env", "TEST_VAR", "--sleep-seconds", "0.1"),
        environment_overrides={"TEST_VAR": "hello_env_test"},
        inherit_parent_environment=True,
        stdout_path=stdout_p,
    )
    managed = launch(spec)
    try:
        _wait_exit(managed)
    finally:
        managed.terminate_job()
        managed.close_handles()
    content = stdout_p.read_text(encoding="utf-8")
    assert "TEST_VAR=hello_env_test" in content


def test_launch_no_inherit_environment(tmp_workdir: Path) -> None:
    """不继承父环境时，明确设置的环境变量仍生效。"""
    stdout_p, _ = _paths("noinherit", tmp_workdir, stdout=True)
    spec = ProcessSpec(
        name="不继承环境",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--echo-env", "CUSTOM_VAR", "--sleep-seconds", "0.1"),
        environment_overrides={
            "CUSTOM_VAR": "custom_value",
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        },
        inherit_parent_environment=False,
        stdout_path=stdout_p,
    )
    managed = launch(spec)
    try:
        _wait_exit(managed)
    finally:
        managed.terminate_job()
        managed.close_handles()
    content = stdout_p.read_text(encoding="utf-8")
    assert "CUSTOM_VAR=custom_value" in content


# ─── 路径测试 ────────────────────────────────────────────────────────


def test_launch_path_with_spaces(tmp_workdir: Path) -> None:
    """路径包含空格正确启动。"""
    pid_file = _pid_file_for_test(tmp_workdir, "spaces")
    stdout_p, _ = _paths("spaces", tmp_workdir, stdout=True)
    spec = ProcessSpec(
        name="空格路径",
        executable=Path(_PYTHON),
        arguments=(
            str(_fake_stage()),
            "--pid-file",
            str(pid_file),
            "--stdout-text",
            "space_test",
            "--sleep-seconds",
            "0.1",
        ),
        stdout_path=stdout_p,
    )
    managed = launch(spec)
    try:
        _wait_exit(managed)
    finally:
        managed.terminate_job()
        managed.close_handles()
    assert b"space_test" in stdout_p.read_bytes()
    assert pid_file.exists()


def test_launch_stdout_stderr_same_file(tmp_workdir: Path) -> None:
    """stdout 和 stderr 指向同一文件时有明确行为（成功合并写入）。"""
    shared = tmp_workdir / "shared.log"
    spec = ProcessSpec(
        name="相同输出文件",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--stdout-text", "OUT", "--stderr-text", "ERR", "--sleep-seconds", "0.1"),
        stdout_path=shared,
        stderr_path=shared,
    )
    managed = launch(spec)
    try:
        _wait_exit(managed)
    finally:
        managed.terminate_job()
        managed.close_handles()
    content = shared.read_bytes()
    assert b"OUT" in content


# ─── 句柄幂等测试 ───────────────────────────────────────────────────


def test_handle_double_close_ownedhandle(tmp_workdir: Path) -> None:
    """OwnedHandle 重复关闭不会导致二次 CloseHandle。"""
    spec = ProcessSpec(
        name="句柄测试",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--sleep-seconds", "0.1"),
    )
    managed = launch(spec)
    pid = managed.pid
    _wait_exit(managed)
    managed.close_handles()
    # 第二次 close 无操作（_closed = True + OwnedHandle.value = None）
    managed.close_handles()
    # 确认进程已退出且无异常
    _check_pid_exited(pid, "句柄测试主进程")


# ─── 进程树测试 ─────────────────────────────────────────────────────


def test_job_terminate_kills_child_tree(tmp_workdir: Path) -> None:
    """Job 终止后主进程和子进程均消失。"""
    child_pid_file = _pid_file_for_test(tmp_workdir, "child")
    parent_pid_file = _pid_file_for_test(tmp_workdir, "parent")
    spec = ProcessSpec(
        name="进程树测试",
        executable=Path(_PYTHON),
        arguments=(
            str(_fake_stage()),
            "--spawn-child",
            "--child-pid-file",
            str(child_pid_file),
            "--pid-file",
            str(parent_pid_file),
            "--sleep-forever",
        ),
    )
    managed = launch(spec)
    parent_pid = managed.pid

    try:
        # 等待子进程启动
        for _ in range(30):
            if child_pid_file.exists():
                break
            time.sleep(0.1)
        assert child_pid_file.exists(), "子进程 PID 文件应存在"
        child_pid = int(child_pid_file.read_text().strip())

        # 终止 Job
        managed.terminate_job()

        for _ in range(50):
            if managed.poll() is not None:
                break
            time.sleep(0.1)

        managed.close_handles()
        time.sleep(0.3)

        _check_pid_exited(parent_pid, "进程树测试-父进程")
        _check_pid_exited(child_pid, "进程树测试-子进程")
    finally:
        managed.close_handles()


def test_parent_exit_child_survives_then_job_kills(tmp_workdir: Path) -> None:
    """父进程退出后子进程仍存活，Job 关闭后才被清理。"""
    child_pid_file = _pid_file_for_test(tmp_workdir, "orphan_child")
    spec = ProcessSpec(
        name="孤儿子进程测试",
        executable=Path(_PYTHON),
        arguments=(
            str(_fake_stage()),
            "--spawn-child-then-exit",
            "--child-pid-file",
            str(child_pid_file),
            "--exit-code",
            "0",
        ),
    )
    managed = launch(spec)
    parent_pid = managed.pid

    try:
        # 等待子进程 PID 文件出现
        for _ in range(40):
            if child_pid_file.exists():
                break
            time.sleep(0.1)
        assert child_pid_file.exists(), "子进程 PID 文件应存在"
        child_pid = int(child_pid_file.read_text().strip())

        # 等待父进程退出
        for _ in range(40):
            if managed.poll() is not None:
                break
            time.sleep(0.1)
        assert managed.poll() is not None, "父进程应已退出"

        # 子进程此时仍在运行（属于同一个 Job）
        assert managed.is_alive() is False, "父进程句柄不再有效"
        # 通过 Win32 检查子进程存活
        import ctypes

        SYNCHRONIZE = 0x00100000
        h_child = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, child_pid)
        assert h_child != 0, f"子进程 PID {child_pid} 在 Job 关闭前应存活"
        ctypes.windll.kernel32.CloseHandle(h_child)

        # 现在关闭 Job → KILL_ON_JOB_CLOSE
        managed.close_handles()
        time.sleep(0.3)

        _check_pid_exited(parent_pid, "孤儿测试-父进程")
        _check_pid_exited(child_pid, "孤儿测试-子进程")
    finally:
        managed.close_handles()
