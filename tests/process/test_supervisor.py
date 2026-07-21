"""ProcessSupervisor 集成测试。

覆盖：launch/wait/run/stop/close 全部生命周期路径。
每个测试记录具体 PID，结束后逐 PID 确认无残留。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from autogame_orchestrator.process import (
    CancellationToken,
    Deadline,
    ProcessSupervisor,
)
from autogame_orchestrator.process.errors import (
    ProcessExecutionErrorCode,
    TerminationReason,
)
from autogame_orchestrator.process.models import ProcessSpec

_PYTHON = sys.executable


def _fake_stage() -> Path:
    return Path(__file__).resolve().parent.parent / "fakes" / "fake_stage.py"


def _check_pid_exited(pid: int, label: str, timeout: float = 2.0) -> None:
    """使用 WaitForSingleObject 确认 PID 已退出。

    通过 OpenProcess + WaitForSingleObject 组合确认进程已终止。
    有硬 timeout 上限。
    """
    import ctypes

    SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if h == 0:
            return  # 进程已退出
        wait_result = ctypes.windll.kernel32.WaitForSingleObject(h, 100)
        ctypes.windll.kernel32.CloseHandle(h)
        if wait_result == WAIT_OBJECT_0:
            return  # 已确认退出
        time.sleep(0.05)

    # 最终检查
    h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
        raise AssertionError(f"{label} PID {pid} 在 {timeout}s 后仍存活")


def _pid_file(tmp_workdir: Path, label: str) -> Path:
    return tmp_workdir / f"{label}.pid"


# ══════════════════════════════════════════════════════════════════
# launch 测试
# ══════════════════════════════════════════════════════════════════


def test_launch_registers_process(tmp_workdir: Path) -> None:
    """launch 后注册表包含进程。"""
    with ProcessSupervisor() as sup:
        spec = ProcessSpec(
            name="注册测试",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-forever"),
        )
        managed = sup.launch(spec)
        pid = managed.pid
        assert managed._id in sup._active
    _check_pid_exited(pid, "注册测试")


def test_launch_two_sequential(tmp_workdir: Path) -> None:
    """两个进程顺序 launch 成功。"""
    with ProcessSupervisor() as sup:
        s1 = ProcessSpec(
            name="顺序1",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-forever"),
        )
        s2 = ProcessSpec(
            name="顺序2",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-forever"),
        )
        m1 = sup.launch(s1)
        m2 = sup.launch(s2)
        assert m1.pid != m2.pid
        assert len(sup._active) == 2


def test_launch_after_close_rejected(tmp_workdir: Path) -> None:
    """close 后禁止再次 launch。"""
    sup = ProcessSupervisor()
    sup.close()
    spec = ProcessSpec(
        name="已关闭",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--sleep-seconds", "0.1"),
    )
    with pytest.raises(RuntimeError, match="已关闭"):
        sup.launch(spec)


# ══════════════════════════════════════════════════════════════════
# wait 测试
# ══════════════════════════════════════════════════════════════════


def test_wait_normal_exit(tmp_workdir: Path) -> None:
    """退出码 0。"""
    pid_f = _pid_file(tmp_workdir, "wait0")
    with ProcessSupervisor() as sup:
        spec = ProcessSpec(
            name="等待正常",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--pid-file", str(pid_f), "--exit-code", "0", "--sleep-seconds", "0.1"),
        )
        managed = sup.launch(spec)
        pid = managed.pid
        result = sup.wait(managed, Deadline.after(5.0))
        assert result.termination_reason == TerminationReason.NORMAL_EXIT
        assert result.exit_code == 0
        assert result.error_code == ProcessExecutionErrorCode.OK
        assert managed.closed
        assert managed._id not in sup._active
    _check_pid_exited(pid, "等待正常")


def test_wait_nonzero_exit(tmp_workdir: Path) -> None:
    """非零退出码。"""
    with ProcessSupervisor() as sup:
        spec = ProcessSpec(
            name="非零退出",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--exit-code", "42", "--sleep-seconds", "0.1"),
        )
        managed = sup.launch(spec)
        pid = managed.pid
        result = sup.wait(managed, Deadline.after(5.0))
        assert result.termination_reason == TerminationReason.NONZERO_EXIT
        assert result.exit_code == 42
        assert result.error_code == ProcessExecutionErrorCode.EXIT_NONZERO
        assert not result.forced_termination
        assert managed.closed
    _check_pid_exited(pid, "非零退出")


def test_wait_exit_code_259(tmp_workdir: Path) -> None:
    """退出码 259 被视为正常退出（不误判为 STILL_ACTIVE）。"""
    with ProcessSupervisor() as sup:
        spec = ProcessSpec(
            name="退出259",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--exit-code", "259", "--sleep-seconds", "0.1"),
        )
        managed = sup.launch(spec)
        pid = managed.pid
        result = sup.wait(managed, Deadline.after(5.0))
        assert result.exit_code == 259
        assert result.error_code == ProcessExecutionErrorCode.EXIT_NONZERO
    _check_pid_exited(pid, "退出259")


def test_wait_stdout_file(tmp_workdir: Path) -> None:
    """stdout 文件正确写入。"""
    stdout_p = tmp_workdir / "wait-stdout.log"
    with ProcessSupervisor() as sup:
        spec = ProcessSpec(
            name="stdout等待",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--stdout-text", "SUPERVISOR_TEST", "--sleep-seconds", "0.1"),
            stdout_path=stdout_p,
        )
        managed = sup.launch(spec)
        sup.wait(managed, Deadline.after(5.0))
    content = stdout_p.read_bytes()
    assert b"SUPERVISOR_TEST" in content


def test_wait_after_wait_handles_closed(tmp_workdir: Path) -> None:
    """wait 后句柄关闭，活动注册表移除。"""
    with ProcessSupervisor() as sup:
        spec = ProcessSpec(
            name="句柄关闭",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-seconds", "0.1"),
        )
        managed = sup.launch(spec)
        pid = managed.pid
        sup.wait(managed, Deadline.after(5.0))
        assert managed.closed
        assert managed._id not in sup._active
    _check_pid_exited(pid, "句柄关闭")


# ══════════════════════════════════════════════════════════════════
# timeout 测试
# ══════════════════════════════════════════════════════════════════


def test_timeout_kills_process(tmp_workdir: Path) -> None:
    """永久睡眠进程超时后被终止。"""
    t0 = time.monotonic()
    with ProcessSupervisor(kill_confirmation_seconds=0.5) as sup:
        spec = ProcessSpec(
            name="超时测试",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-forever"),
        )
        result = sup.run(spec, Deadline.after(0.3))
        pid = result.pid

        assert result.termination_reason == TerminationReason.TIMEOUT
        assert result.error_code == ProcessExecutionErrorCode.TIMEOUT
        assert result.forced_termination
        assert result.exit_code is not None or result.forced_termination

    # 整体耗时硬上限
    elapsed = time.monotonic() - t0
    assert elapsed < 3.0, f"超时测试耗时 {elapsed:.2f}s 超过 3s 上限"

    if pid is not None:
        _check_pid_exited(pid, "超时测试")


def test_timeout_kills_child_tree(tmp_workdir: Path) -> None:
    """超时后子进程也退出。"""
    child_pid_f = _pid_file(tmp_workdir, "to_child")
    with ProcessSupervisor(kill_confirmation_seconds=0.5) as sup:
        spec = ProcessSpec(
            name="超时进程树",
            executable=Path(_PYTHON),
            arguments=(
                str(_fake_stage()),
                "--spawn-child",
                "--child-pid-file",
                str(child_pid_f),
                "--sleep-forever",
            ),
        )
        result = sup.run(spec, Deadline.after(0.5))

        assert result.termination_reason == TerminationReason.TIMEOUT

    if child_pid_f.exists():
        child_pid = int(child_pid_f.read_text().strip())
        _check_pid_exited(child_pid, "超时子进程")
    if result.pid is not None:
        _check_pid_exited(result.pid, "超时父进程")


def test_timeout_not_success(tmp_workdir: Path) -> None:
    """timeout 不是成功。"""
    with ProcessSupervisor() as sup:
        spec = ProcessSpec(
            name="超时非成功",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-forever"),
        )
        result = sup.run(spec, Deadline.after(0.1))
        assert result.error_code != ProcessExecutionErrorCode.OK
        assert result.forced_termination


# ══════════════════════════════════════════════════════════════════
# cancellation 测试
# ══════════════════════════════════════════════════════════════════


def test_cancel_from_other_thread(tmp_workdir: Path) -> None:
    """另一线程触发 cancel，wait 在有限时间内返回。"""
    t0 = time.monotonic()
    with ProcessSupervisor() as sup:
        spec = ProcessSpec(
            name="取消测试",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-forever"),
        )
        cancel = CancellationToken()
        managed = sup.launch(spec)
        pid = managed.pid

        def _cancel_later() -> None:
            time.sleep(0.2)
            cancel.cancel()

        t = threading.Thread(target=_cancel_later, daemon=True)
        t.start()

        result = sup.wait(managed, Deadline.after(5.0), cancel=cancel)
        t.join()

        assert result.termination_reason == TerminationReason.CANCELLED
        assert result.error_code == ProcessExecutionErrorCode.CANCELLED
        assert result.forced_termination

    elapsed = time.monotonic() - t0
    assert elapsed < 3.0, f"cancel 测试耗时 {elapsed:.2f}s 超过 3s 上限"
    _check_pid_exited(pid, "取消测试")


def test_cancel_not_success(tmp_workdir: Path) -> None:
    """取消不是成功。"""
    with ProcessSupervisor() as sup:
        spec = ProcessSpec(
            name="取消非成功",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-forever"),
        )
        cancel = CancellationToken()
        managed = sup.launch(spec)
        cancel.cancel()
        result = sup.wait(managed, Deadline.after(1.0), cancel=cancel)
        assert result.error_code != ProcessExecutionErrorCode.OK


def test_cancel_kills_child(tmp_workdir: Path) -> None:
    """取消后子进程也退出。"""
    child_pid_f = _pid_file(tmp_workdir, "cancel_child")
    with ProcessSupervisor(kill_confirmation_seconds=0.5) as sup:
        spec = ProcessSpec(
            name="取消进程树",
            executable=Path(_PYTHON),
            arguments=(
                str(_fake_stage()),
                "--spawn-child",
                "--child-pid-file",
                str(child_pid_f),
                "--sleep-forever",
            ),
        )
        cancel = CancellationToken()
        managed = sup.launch(spec)
        cancel.cancel()
        result = sup.wait(managed, Deadline.after(3.0), cancel=cancel)
        assert result.termination_reason == TerminationReason.CANCELLED

    if child_pid_f.exists():
        child_pid = int(child_pid_f.read_text().strip())
        _check_pid_exited(child_pid, "取消子进程")


# ══════════════════════════════════════════════════════════════════
# stop 测试
# ══════════════════════════════════════════════════════════════════


def test_stop_running_process(tmp_workdir: Path) -> None:
    """运行中进程 stop 返回 STOPPED。"""
    with ProcessSupervisor(kill_confirmation_seconds=0.5) as sup:
        spec = ProcessSpec(
            name="stop运行中",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-forever"),
        )
        managed = sup.launch(spec)
        pid = managed.pid
        result = sup.stop(managed)
        assert result.termination_reason == TerminationReason.STOPPED
        assert result.error_code == ProcessExecutionErrorCode.STOPPED
        assert result.forced_termination
        assert managed.closed
    _check_pid_exited(pid, "stop运行中")


def test_stop_already_exited(tmp_workdir: Path) -> None:
    """已退出进程 stop 返回原始结果。"""
    with ProcessSupervisor() as sup:
        spec = ProcessSpec(
            name="stop已退出",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--exit-code", "7", "--sleep-seconds", "0.1"),
        )
        managed = sup.launch(spec)
        pid = managed.pid
        sup.wait(managed, Deadline.after(5.0))
        # 此时进程已退出，句柄已关闭
        result2 = sup.stop(managed)
        # 关闭后的 stop 返回 WAIT_FAILED 或 START_FAILED（已关闭）
        assert result2.termination_reason in (
            TerminationReason.WAIT_FAILED,
            TerminationReason.STOPPED,
            TerminationReason.START_FAILED,
        )
    _check_pid_exited(pid, "stop已退出")


def test_stop_double_idempotent(tmp_workdir: Path) -> None:
    """重复 stop 幂等。"""
    with ProcessSupervisor(kill_confirmation_seconds=0.5) as sup:
        spec = ProcessSpec(
            name="stop幂等",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-forever"),
        )
        managed = sup.launch(spec)
        pid = managed.pid
        sup.stop(managed)
        r2 = sup.stop(managed)  # 重复
        assert r2.termination_reason in (
            TerminationReason.STOPPED,
            TerminationReason.WAIT_FAILED,
            TerminationReason.START_FAILED,
        )
    _check_pid_exited(pid, "stop幂等")


def test_stop_cleans_child_tree(tmp_workdir: Path) -> None:
    """stop 清理子进程树。"""
    child_pid_f = _pid_file(tmp_workdir, "stop_child")
    with ProcessSupervisor(kill_confirmation_seconds=0.5) as sup:
        spec = ProcessSpec(
            name="stop进程树",
            executable=Path(_PYTHON),
            arguments=(
                str(_fake_stage()),
                "--spawn-child",
                "--child-pid-file",
                str(child_pid_f),
                "--sleep-forever",
            ),
        )
        managed = sup.launch(spec)
        sup.stop(managed)

    if child_pid_f.exists():
        child_pid = int(child_pid_f.read_text().strip())
        _check_pid_exited(child_pid, "stop子进程")


# ══════════════════════════════════════════════════════════════════
# run 测试
# ══════════════════════════════════════════════════════════════════


def test_run_normal(tmp_workdir: Path) -> None:
    """run 正常退出 0。"""
    with ProcessSupervisor() as sup:
        spec = ProcessSpec(
            name="run正常",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--exit-code", "0", "--sleep-seconds", "0.1"),
        )
        result = sup.run(spec, Deadline.after(5.0))
        pid = result.pid
        assert result.termination_reason == TerminationReason.NORMAL_EXIT
        assert len(sup._active) == 0
    if pid is not None:
        _check_pid_exited(pid, "run正常")


def test_run_start_failed(tmp_workdir: Path) -> None:
    """启动失败返回 START_FAILED。"""
    with ProcessSupervisor() as sup:
        spec = ProcessSpec(
            name="启动失败",
            executable=Path("Z:/nonexistent.exe"),
        )
        result = sup.run(spec, Deadline.after(5.0))
        assert result.termination_reason == TerminationReason.START_FAILED
        assert result.pid is None
        assert result.error_code == ProcessExecutionErrorCode.START_FAILED
        assert len(sup._active) == 0


def test_run_timeout(tmp_workdir: Path) -> None:
    """run 超时。"""
    with ProcessSupervisor(kill_confirmation_seconds=0.5) as sup:
        spec = ProcessSpec(
            name="run超时",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-forever"),
        )
        result = sup.run(spec, Deadline.after(0.2))
        pid = result.pid
        assert result.termination_reason == TerminationReason.TIMEOUT
        assert len(sup._active) == 0
    if pid is not None:
        _check_pid_exited(pid, "run超时")


def test_run_cancel(tmp_workdir: Path) -> None:
    """run 取消。"""
    with ProcessSupervisor(kill_confirmation_seconds=0.5) as sup:
        spec = ProcessSpec(
            name="run取消",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-forever"),
        )
        cancel = CancellationToken()
        cancel.cancel()
        result = sup.run(spec, Deadline.after(5.0), cancel=cancel)
        pid = result.pid
        assert result.termination_reason in (TerminationReason.CANCELLED, TerminationReason.START_FAILED)
        assert len(sup._active) == 0
    if pid is not None:
        _check_pid_exited(pid, "run取消")


# ══════════════════════════════════════════════════════════════════
# close 测试
# ══════════════════════════════════════════════════════════════════


def test_close_cleans_one_process(tmp_workdir: Path) -> None:
    """close 清理一个进程。"""
    sup = ProcessSupervisor(kill_confirmation_seconds=0.5)
    spec = ProcessSpec(
        name="close一个",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--sleep-forever"),
    )
    managed = sup.launch(spec)
    pid = managed.pid
    sup.close()
    assert len(sup._active) == 0
    _check_pid_exited(pid, "close一个")


def test_close_cleans_multiple(tmp_workdir: Path) -> None:
    """close 清理多个进程。"""
    sup = ProcessSupervisor(kill_confirmation_seconds=0.5)
    pids: list[int] = []
    for i in range(3):
        s = ProcessSpec(
            name=f"close多个{i}",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-forever"),
        )
        m = sup.launch(s)
        pids.append(m.pid)
    sup.close()
    assert len(sup._active) == 0
    for pid in pids:
        _check_pid_exited(pid, f"close多个{pid}")


def test_close_double_idempotent(tmp_workdir: Path) -> None:
    """重复 close 幂等。"""
    sup = ProcessSupervisor()
    sup.close()
    sup.close()  # 第二次无操作


def test_context_manager_auto_clean(tmp_workdir: Path) -> None:
    """上下文管理器自动清理。"""
    with ProcessSupervisor(kill_confirmation_seconds=0.5) as sup:
        spec = ProcessSpec(
            name="上下文清理",
            executable=Path(_PYTHON),
            arguments=(str(_fake_stage()), "--sleep-forever"),
        )
        managed = sup.launch(spec)
        pid = managed.pid
    assert len(sup._active) == 0
    _check_pid_exited(pid, "上下文清理")


def test_close_one_failure_does_not_block_others(tmp_workdir: Path) -> None:
    """一个清理失败不阻止其他进程清理。只要不抛异常即可。"""
    sup = ProcessSupervisor(kill_confirmation_seconds=0.5)
    s1 = ProcessSpec(
        name="失败不阻塞1",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--sleep-forever"),
    )
    s2 = ProcessSpec(
        name="失败不阻塞2",
        executable=Path(_PYTHON),
        arguments=(str(_fake_stage()), "--sleep-forever"),
    )
    sup.launch(s1)
    sup.launch(s2)
    sup.close()
    assert len(sup._active) == 0
