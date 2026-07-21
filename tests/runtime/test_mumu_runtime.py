"""MuMu 适配器测试。

包含两类测试：
1. monkeypatch 注入 Fake Probe（精确状态映射验证）
2. 生产路径集成测试（fake_mumu_manager.py 通过 ProcessSupervisor 真实执行）
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

from autogame_orchestrator.probes.models import ProbeErrorCode, ProbeResult, ProbeStatus
from autogame_orchestrator.process import CancellationToken, Deadline
from autogame_orchestrator.runtime.models import (
    MumuAction,
    MumuRuntimeErrorCode,
    MumuRuntimeResult,
    MumuRuntimeStatus,
)
from autogame_orchestrator.runtime.mumu import MumuAdapter

_FAKE_MGR = str(Path(__file__).resolve().parent.parent / "fakes" / "fake_mumu_manager.py")
_PYTHON = sys.executable


def _make_adapter(
    start_args: tuple[str, ...] | None = None,
    stop_args: tuple[str, ...] | None = None,
    executable: Path | None = None,
) -> MumuAdapter:
    return MumuAdapter(
        executable=executable or Path(_PYTHON),
        start_arguments=start_args or (_FAKE_MGR, "--mode", "normal", "start"),
        stop_arguments=stop_args or (_FAKE_MGR, "--mode", "normal", "stop"),
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
    )


def _check_pid_exited(pid: int, label: str, timeout: float = 2.0) -> None:
    import ctypes

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
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


def _ready_probe(*args: object, **kwargs: object) -> ProbeResult:
    return ProbeResult.ready("test")


def _refused_probe(*args: object, **kwargs: object) -> ProbeResult:
    return ProbeResult.from_monotonic("test", ProbeStatus.UNAVAILABLE, ProbeErrorCode.PORT_CLOSED, time.monotonic())


# ════════════════════════════════════════════════════════════════════
# 生产路径集成测试（fake_mumu_manager 真实执行）
# ════════════════════════════════════════════════════════════════════


def test_manager_start_integration(tmp_path: Path) -> None:
    """Fake Manager start 真实执行 → STARTED + OK。"""
    state_file = tmp_path / "mumu.state"
    args_file = tmp_path / "args.json"
    state_file.write_text("stopped", encoding="utf-8")

    adapter = MumuAdapter(
        executable=Path(_PYTHON),
        start_arguments=(
            _FAKE_MGR,
            "--mode",
            "normal",
            "--state-file",
            str(state_file),
            "--args-file",
            str(args_file),
            "start",
        ),
        stop_arguments=(_FAKE_MGR, "--mode", "normal", "--state-file", str(state_file), "stop"),
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
    )
    with (
        patch.object(
            adapter,
            "status",
            return_value=MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS, MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
            ),
        ),
        patch.object(adapter, "_create_probe", return_value=_FakeProbe(ready=True)),
    ):
        result = adapter.start(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.STARTED
        assert result.error_code == MumuRuntimeErrorCode.OK
        assert result.changed

    # 验证状态文件被修改
    assert state_file.read_text(encoding="utf-8").strip() == "ready"
    # 验证参数被记录
    args_data = json.loads(args_file.read_text(encoding="utf-8"))
    assert "start" in args_data


def test_manager_stop_integration(tmp_path: Path) -> None:
    """Fake Manager stop 真实执行 → STOPPED + OK。"""
    state_file = tmp_path / "mumu.state"
    state_file.write_text("ready", encoding="utf-8")

    adapter = MumuAdapter(
        executable=Path(_PYTHON),
        start_arguments=(_FAKE_MGR, "--mode", "normal", "--state-file", str(state_file), "start"),
        stop_arguments=(_FAKE_MGR, "--mode", "normal", "--state-file", str(state_file), "stop"),
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
    )
    with (
        patch.object(
            adapter,
            "status",
            return_value=MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS, MumuRuntimeStatus.READY, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
            ),
        ),
        patch.object(adapter, "_create_probe", return_value=_FakeProbe(refused=True)),
    ):
        result = adapter.stop(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.STOPPED
        assert result.changed

    assert state_file.read_text(encoding="utf-8").strip() == "stopped"


def test_manager_nonzero_exit() -> None:
    """Fake Manager 非零退出 → COMMAND_EXIT_NONZERO。"""
    adapter = MumuAdapter(
        executable=Path(_PYTHON),
        start_arguments=(_FAKE_MGR, "--mode", "exit_nonzero", "start"),
        stop_arguments=(),
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
    )
    with patch.object(
        adapter,
        "status",
        return_value=MumuRuntimeResult.from_monotonic(
            MumuAction.STATUS, MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
        ),
    ):
        result = adapter.start(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.FAILED
        assert result.error_code == MumuRuntimeErrorCode.COMMAND_EXIT_NONZERO


def test_manager_timeout() -> None:
    """Fake Manager sleep_forever → start TIMEOUT。"""
    adapter = MumuAdapter(
        executable=Path(_PYTHON),
        start_arguments=(_FAKE_MGR, "--mode", "sleep_forever", "start"),
        stop_arguments=(),
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
        start_timeout_seconds=1.0,
    )
    t0 = time.monotonic()
    with (
        patch.object(
            adapter,
            "status",
            return_value=MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS, MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
            ),
        ),
    ):
        result = adapter.start(Deadline.after(0.3))
        assert result.status == MumuRuntimeStatus.TIMEOUT
        assert result.error_code == MumuRuntimeErrorCode.START_TIMEOUT
    assert time.monotonic() - t0 < 3.0


def test_manager_stop_timeout() -> None:
    """Fake Manager sleep_forever → stop TIMEOUT。"""
    adapter = MumuAdapter(
        executable=Path(_PYTHON),
        start_arguments=(),
        stop_arguments=(_FAKE_MGR, "--mode", "sleep_forever", "stop"),
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
    )
    with (
        patch.object(
            adapter,
            "status",
            return_value=MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS, MumuRuntimeStatus.READY, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
            ),
        ),
    ):
        result = adapter.stop(Deadline.after(0.3))
        assert result.error_code == MumuRuntimeErrorCode.STOP_TIMEOUT


def test_manager_cancellation() -> None:
    """Fake Manager 永久等待 + cancel → CANCELLED。"""
    adapter = MumuAdapter(
        executable=Path(_PYTHON),
        start_arguments=(_FAKE_MGR, "--mode", "sleep_forever", "start"),
        stop_arguments=(),
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
    )
    cancel = CancellationToken()
    t0 = time.monotonic()

    def _cancel() -> None:
        time.sleep(0.1)
        cancel.cancel()

    t = threading.Thread(target=_cancel, daemon=True)
    t.start()

    with (
        patch.object(
            adapter,
            "status",
            return_value=MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS, MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
            ),
        ),
    ):
        result = adapter.start(Deadline.after(5.0), cancel)
        t.join()
        assert result.status == MumuRuntimeStatus.CANCELLED
        assert result.error_code == MumuRuntimeErrorCode.CANCELLED
        assert time.monotonic() - t0 < 3.0


def test_manager_spawn_child_then_exit(tmp_path: Path) -> None:
    """Fake Manager 派生子进程后退出 → 子进程被 Job 清理。"""
    child_pid_file = tmp_path / "child.pid"
    state_file = tmp_path / "mumu.state"
    state_file.write_text("stopped", encoding="utf-8")

    adapter = MumuAdapter(
        executable=Path(_PYTHON),
        start_arguments=(
            _FAKE_MGR,
            "--mode",
            "spawn_child_then_exit",
            "--state-file",
            str(state_file),
            "--child-pid-file",
            str(child_pid_file),
            "start",
        ),
        stop_arguments=(),
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
    )
    with (
        patch.object(
            adapter,
            "status",
            return_value=MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS, MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
            ),
        ),
        patch.object(adapter, "_create_probe", return_value=_FakeProbe(ready=True)),
    ):
        result = adapter.start(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.STARTED

    # 子进程 PID 文件存在 → 验证子进程已被 Job 清理
    if child_pid_file.exists():
        child_pid = int(child_pid_file.read_text().strip())
        _check_pid_exited(child_pid, "spawn_child_then_exit 子进程")


# ════════════════════════════════════════════════════════════════════
# Monkeypatch 状态映射测试（Fake Probe 注入）
# ════════════════════════════════════════════════════════════════════


def test_status_ready() -> None:
    adapter = _make_adapter()
    with patch.object(adapter, "_create_probe", return_value=_FakeProbe(ready=True)):
        result = adapter.status(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.READY
        assert result.error_code == MumuRuntimeErrorCode.OK


def test_status_stopped() -> None:
    adapter = _make_adapter()
    with patch.object(adapter, "_create_probe", return_value=_FakeProbe(refused=True)):
        result = adapter.status(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.STOPPED
        assert result.error_code == MumuRuntimeErrorCode.OK


def test_status_offline() -> None:
    adapter = _make_adapter()
    with patch.object(adapter, "_create_probe", return_value=_FakeProbe(offline=True)):
        result = adapter.status(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.NOT_READY
        assert result.error_code == MumuRuntimeErrorCode.READINESS_FAILED


def test_status_unauthorized() -> None:
    adapter = _make_adapter()
    with patch.object(adapter, "_create_probe", return_value=_FakeProbe(unauthorized=True)):
        result = adapter.status(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.NOT_READY
        assert result.error_code == MumuRuntimeErrorCode.READINESS_FAILED


def test_status_timeout() -> None:
    adapter = _make_adapter()
    with patch.object(adapter, "_create_probe", return_value=_FakeProbe(timed_out=True)):
        result = adapter.status(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.TIMEOUT
        assert result.error_code == MumuRuntimeErrorCode.READINESS_FAILED


def test_start_already_ready() -> None:
    adapter = _make_adapter()
    with patch.object(adapter, "_create_probe", return_value=_FakeProbe(ready=True)):
        # status 返回 READY
        with patch.object(
            adapter,
            "status",
            return_value=MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS, MumuRuntimeStatus.READY, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
            ),
        ):
            result = adapter.start(Deadline.after(5.0))
            assert result.status == MumuRuntimeStatus.STARTED
            assert not result.changed


def test_restart_stop_fails() -> None:
    adapter = _make_adapter()
    with patch.object(
        adapter,
        "stop",
        return_value=MumuRuntimeResult.from_monotonic(
            MumuAction.STOP,
            MumuRuntimeStatus.TIMEOUT,
            MumuRuntimeErrorCode.STOP_TIMEOUT,
            time.monotonic(),
            changed=False,
        ),
    ):
        result = adapter.restart(Deadline.after(5.0))
        assert result.error_code == MumuRuntimeErrorCode.STOP_TIMEOUT


# ════════════════════════════════════════════════════════════════════
# Fake Probe
# ════════════════════════════════════════════════════════════════════


class _FakeProbe:
    def __init__(
        self,
        ready: bool = False,
        refused: bool = False,
        offline: bool = False,
        unauthorized: bool = False,
        timed_out: bool = False,
    ) -> None:
        self._ready = ready
        self._refused = refused
        self._offline = offline
        self._unauthorized = unauthorized
        self._timed_out = timed_out

    def probe(
        self, host: str, port: int, serial: str | None, deadline: Deadline, cancel: CancellationToken | None = None
    ) -> ProbeResult:
        if self._ready:
            return ProbeResult.ready("test")
        if self._refused:
            return ProbeResult.from_monotonic(
                "test", ProbeStatus.UNAVAILABLE, ProbeErrorCode.PORT_CLOSED, time.monotonic()
            )
        if self._offline:
            return ProbeResult.from_monotonic(
                "test", ProbeStatus.NOT_READY, ProbeErrorCode.DEVICE_OFFLINE, time.monotonic()
            )
        if self._unauthorized:
            return ProbeResult.from_monotonic(
                "test", ProbeStatus.NOT_READY, ProbeErrorCode.DEVICE_UNAUTHORIZED, time.monotonic()
            )
        if self._timed_out:
            return ProbeResult.from_monotonic("test", ProbeStatus.TIMEOUT, ProbeErrorCode.TCP_TIMEOUT, time.monotonic())
        return ProbeResult.ready("test")


# ════════════════════════════════════════════════════════════════════
# 空参数拒绝测试（安全修正）
# ════════════════════════════════════════════════════════════════════


def test_start_empty_args_refused() -> None:
    """start_arguments=() 且非 READY → INVALID_CONFIGURATION，不执行任何命令。"""
    adapter = MumuAdapter(
        executable=Path(_PYTHON),
        start_arguments=(),  # 空
        stop_arguments=(),
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
    )
    # status 返回 STOPPED（触发 start 逻辑），_run_manager_command 不应被调用
    with (
        patch.object(
            adapter,
            "status",
            return_value=MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS, MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
            ),
        ),
        patch.object(adapter, "_run_manager_command") as mock_cmd,
    ):
        result = adapter.start(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.FAILED
        assert result.error_code == MumuRuntimeErrorCode.INVALID_CONFIGURATION
        assert result.changed is False
        mock_cmd.assert_not_called()


def test_stop_empty_args_refused() -> None:
    """stop_arguments=() 且非 STOPPED → INVALID_CONFIGURATION，不执行任何命令。"""
    adapter = MumuAdapter(
        executable=Path(_PYTHON),
        start_arguments=(),
        stop_arguments=(),  # 空
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
    )
    with (
        patch.object(
            adapter,
            "status",
            return_value=MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS, MumuRuntimeStatus.READY, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
            ),
        ),
        patch.object(adapter, "_run_manager_command") as mock_cmd,
    ):
        result = adapter.stop(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.FAILED
        assert result.error_code == MumuRuntimeErrorCode.INVALID_CONFIGURATION
        assert result.changed is False
        mock_cmd.assert_not_called()


def test_start_idempotent_no_args_needed() -> None:
    """已 READY 时即使 start_arguments=() 也应幂等成功。"""
    adapter = MumuAdapter(
        executable=Path(_PYTHON),
        start_arguments=(),
        stop_arguments=(),
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
    )
    with patch.object(
        adapter,
        "status",
        return_value=MumuRuntimeResult.from_monotonic(
            MumuAction.STATUS, MumuRuntimeStatus.READY, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
        ),
    ):
        result = adapter.start(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.STARTED
        assert result.error_code == MumuRuntimeErrorCode.OK
        assert result.changed is False


def test_stop_idempotent_no_args_needed() -> None:
    """已 STOPPED 时即使 stop_arguments=() 也应幂等成功。"""
    adapter = MumuAdapter(
        executable=Path(_PYTHON),
        start_arguments=(),
        stop_arguments=(),
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
    )
    with patch.object(
        adapter,
        "status",
        return_value=MumuRuntimeResult.from_monotonic(
            MumuAction.STATUS, MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
        ),
    ):
        result = adapter.stop(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.STOPPED
        assert result.error_code == MumuRuntimeErrorCode.OK
        assert result.changed is False


def test_restart_refused_no_stop_args() -> None:
    """restart: stop 缺少参数 → INVALID_CONFIGURATION，不进入 start。"""
    adapter = MumuAdapter(
        executable=Path(_PYTHON),
        start_arguments=(),
        stop_arguments=(),  # 空
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
    )
    with (
        patch.object(
            adapter,
            "status",
            return_value=MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS, MumuRuntimeStatus.READY, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
            ),
        ),
        patch.object(adapter, "start") as mock_start,
    ):
        result = adapter.restart(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.FAILED
        assert result.error_code == MumuRuntimeErrorCode.INVALID_CONFIGURATION
        mock_start.assert_not_called()


def test_restart_refused_no_start_args() -> None:
    """restart: stop 幂等成功 → start 缺少参数 → INVALID_CONFIGURATION，不返回 timeout。"""
    adapter = MumuAdapter(
        executable=Path(_PYTHON),
        start_arguments=(),  # 空
        stop_arguments=(_FAKE_MGR, "--mode", "normal", "stop"),
        adb_executable=Path(_PYTHON),
        adb_serial="127.0.0.1:16384",
    )
    with (
        patch.object(
            adapter,
            "status",
            return_value=MumuRuntimeResult.from_monotonic(
                MumuAction.STATUS, MumuRuntimeStatus.STOPPED, MumuRuntimeErrorCode.OK, time.monotonic(), changed=False
            ),
        ),
        patch.object(adapter, "_run_manager_command") as mock_cmd,
    ):
        result = adapter.restart(Deadline.after(5.0))
        assert result.status == MumuRuntimeStatus.FAILED
        assert result.error_code == MumuRuntimeErrorCode.INVALID_CONFIGURATION
        assert result.changed is False
        mock_cmd.assert_not_called()
