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


def test_status_device_not_found_is_not_stopped() -> None:
    """DEVICE_NOT_FOUND 不得映射为 STOPPED：TCP 端口是开着的，模拟器还活着。

    回归保护：MuMu 的 ADB 是网络设备（``127.0.0.1:16384``），宿主 ADB server
    一旦重启就会忘掉网络设备注册，必须重新 ``adb connect`` 才能列出。此时
    probe 的 TCP 探测通过（端口 OPEN），但 ``adb devices -l`` 是空列表，
    ``select_adb_device`` 抛 DEVICE_NOT_FOUND。若把它当成 STOPPED，
    ``stop()`` 会走幂等短路，``MuMuManager shutdown`` 永不执行，
    表现为阶段报告 success 但模拟器仍在运行。
    """
    adapter = _make_adapter()
    with patch.object(adapter, "_create_probe", return_value=_FakeProbe(not_found=True)):
        result = adapter.status(Deadline.after(5.0))
    assert result.status == MumuRuntimeStatus.NOT_READY
    assert result.error_code == MumuRuntimeErrorCode.READINESS_FAILED


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


def test_external_ensure_ready_preserves_ready_result() -> None:
    adapter = _make_adapter()
    with patch.object(adapter, "_create_probe", return_value=_FakeProbe(ready=True)):
        result = adapter.ensure_external_ready(Deadline.after(5.0))
    assert result.status == MumuRuntimeStatus.READY
    assert result.error_code == MumuRuntimeErrorCode.OK


def test_external_ensure_does_not_map_missing_target_to_stopped() -> None:
    adapter = _make_adapter()
    with patch.object(adapter, "_create_probe", return_value=_FakeProbe(refused=True)):
        result = adapter.ensure_external_ready(Deadline.after(5.0))
    assert result.status == MumuRuntimeStatus.NOT_READY
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
        not_found: bool = False,
        offline: bool = False,
        unauthorized: bool = False,
        timed_out: bool = False,
    ) -> None:
        self._ready = ready
        self._refused = refused
        self._not_found = not_found
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
        if self._not_found:
            return ProbeResult.from_monotonic(
                "test", ProbeStatus.NOT_READY, ProbeErrorCode.DEVICE_NOT_FOUND, time.monotonic()
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

    def ensure_ready(
        self, host: str, port: int, serial: str | None, deadline: Deadline, cancel: CancellationToken | None = None
    ) -> ProbeResult:
        return self.probe(host, port, serial, deadline, cancel)


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


def test_stop_does_not_short_circuit_on_device_not_found() -> None:
    """DEVICE_NOT_FOUND 时 ``stop()`` 必须执行停止命令，不得幂等短路。

    回归保护：真实事故 run_id ``8f96fb14``，第 15 阶段 ``shutdown_mumu``
    仅耗时 78 ms 且 ``changed=false``，report 判定 success，但模拟器仍在跑。
    根因是 AALC 退出时重启了 ADB server，probe 返回 DEVICE_NOT_FOUND，
    被 ``status()`` 误判成 STOPPED，``stop()`` 因此直接短路返回。
    """
    adapter = _make_adapter()
    with (
        patch.object(adapter, "_create_probe", return_value=_FakeProbe(not_found=True)),
        patch.object(
            adapter,
            "_run_manager_command",
            return_value={
                "ok": False,
                "status": MumuRuntimeStatus.FAILED,
                "error_code": MumuRuntimeErrorCode.COMMAND_EXIT_NONZERO,
                "diag": {},
            },
        ) as mock_cmd,
    ):
        result = adapter.stop(Deadline.after(5.0))
    mock_cmd.assert_called_once()
    assert result.status != MumuRuntimeStatus.STOPPED


def test_stop_confirmation_requires_port_closed() -> None:
    """停止确认只接受 PORT_CLOSED；DEVICE_NOT_FOUND 不构成已停止的证据。

    回归保护：``_wait_stopped`` 曾把 DEVICE_NOT_FOUND 也当作停止确认。
    执行 shutdown 命令后若 ADB server 恰好为空，会立刻误判成功返回，
    而 VM 进程其实还在。改为只认 PORT_CLOSED 后，这种情况会诚实地
    等到 STOP_TIMEOUT，而不是谎报 success。
    """
    adapter = _make_adapter()
    with (
        patch.object(adapter, "_create_probe", return_value=_FakeProbe(not_found=True)),
        patch.object(
            adapter,
            "_run_manager_command",
            return_value={
                "ok": True,
                "status": MumuRuntimeStatus.STOPPED,
                "error_code": MumuRuntimeErrorCode.OK,
                "diag": {},
            },
        ),
    ):
        result = adapter.stop(Deadline.after(0.4))
    assert result.status == MumuRuntimeStatus.TIMEOUT
    assert result.error_code == MumuRuntimeErrorCode.STOP_TIMEOUT


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


# ════════════════════════════════════════════════════════════════════
# 启动等待必须执行受控 adb connect
# ════════════════════════════════════════════════════════════════════


class _ConnectRequiredProbe:
    """模拟真实情况：新启动的模拟器只有经 ``ensure_ready`` 的 adb connect 后才可见。

    只读 ``probe()`` 永远返回 DEVICE_NOT_FOUND，``ensure_ready()`` 才返回 ready。
    """

    def __init__(self) -> None:
        self.probe_calls = 0
        self.ensure_calls = 0

    def probe(
        self, host: str, port: int, serial: str | None, deadline: Deadline, cancel: CancellationToken | None = None
    ) -> ProbeResult:
        self.probe_calls += 1
        return ProbeResult.from_monotonic(
            "test", ProbeStatus.NOT_READY, ProbeErrorCode.DEVICE_NOT_FOUND, time.monotonic()
        )

    def ensure_ready(
        self, host: str, port: int, serial: str | None, deadline: Deadline, cancel: CancellationToken | None = None
    ) -> ProbeResult:
        self.ensure_calls += 1
        return ProbeResult.ready("test")


def test_start_readiness_wait_uses_controlled_connect(tmp_path: Path) -> None:
    """``start()`` 的 readiness 等待必须走 ``ensure_ready``，否则新启动的模拟器永不就绪。

    回归保护：曾因 ``_wait_readiness`` 只调只读 ``probe()`` 而不执行 adb connect，
    导致管理命令报告成功但 readiness 永远等不到，最终 START_TIMEOUT。
    """
    manager = tmp_path / "manager.exe"
    manager.write_text("fake", encoding="utf-8")
    adb = tmp_path / "adb.exe"
    adb.write_text("fake", encoding="utf-8")
    adapter = MumuAdapter(
        executable=manager,
        start_arguments=("control", "-v", "0", "launch"),
        stop_arguments=("control", "-v", "0", "shutdown"),
        adb_executable=adb,
        adb_serial="127.0.0.1:16384",
    )
    probe = _ConnectRequiredProbe()
    stopped_then_probe = _FakeProbe(refused=True)

    call_count = {"n": 0}

    def fake_create_probe() -> object:
        # 首次用于 start() 的前置 status 检查（须报告未就绪），其后用于 readiness 等待。
        call_count["n"] += 1
        return stopped_then_probe if call_count["n"] == 1 else probe

    with (
        patch.object(adapter, "_create_probe", side_effect=fake_create_probe),
        patch.object(
            adapter,
            "_run_manager_command",
            return_value={
                "ok": True,
                "status": MumuRuntimeStatus.STARTED,
                "error_code": MumuRuntimeErrorCode.OK,
                "diag": {},
            },
        ),
    ):
        result = adapter.start(Deadline.after(5.0))

    assert result.status == MumuRuntimeStatus.STARTED
    assert result.error_code == MumuRuntimeErrorCode.OK
    assert probe.ensure_calls >= 1, "readiness 等待必须调用 ensure_ready 以执行受控 adb connect"
