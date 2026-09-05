"""adb server 常驻性回归测试。

守卫一个真实事故：编排器每条 adb 命令原先都会连带杀死 adb 自己 fork 出的常驻
daemon（Job Object 默认 KILL_ON_JOB_CLOSE）。后果是 ``adb connect`` 注册的 TCP
设备在下一条 ``adb devices`` 里凭空消失，探测得到 DEVICE_NOT_FOUND；同时每条命令
都要冷启动 daemon（实测 0.06s -> 2.08s），逼近甚至超出单命令预算而报 ADB_TIMEOUT。

这里锁定三件事：
1. ``ensure_server`` 使用的 ProcessSpec 必须让后代存活；
2. 且必须**不**重定向 stdout/stderr——否则 ``bInheritHandles=TRUE`` 会让存活的
   daemon 继承编排器的 stdout 句柄，下游读取端永远收不到 EOF；
3. 普通命令仍维持默认回收行为，不泄漏句柄也不留游离进程。
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from autogame_orchestrator.probes.adb_client import AdbClient, AdbClientConfig
from autogame_orchestrator.probes.models import ProbeErrorCode, ProbeStatus
from autogame_orchestrator.process import CancellationToken, Deadline, ProcessSpec

_FAKE_ADB = str(Path(__file__).resolve().parent.parent / "fakes" / "fake_adb.py")


def _client(mode: str = "normal", *, command_timeout_seconds: float = 5.0) -> AdbClient:
    return AdbClient(
        AdbClientConfig(
            executable=Path(sys.executable),
            base_arguments=(_FAKE_ADB, "--mode", mode),
            command_timeout_seconds=command_timeout_seconds,
        )
    )


def _captured_specs(client: AdbClient, monkeypatch: pytest.MonkeyPatch) -> list[ProcessSpec]:
    """拦截 ProcessSupervisor.run，记录传入的 ProcessSpec。"""
    specs: list[ProcessSpec] = []
    import autogame_orchestrator.probes.adb_client as module

    original = module.ProcessSupervisor.run

    def spy(self, spec, deadline, cancel=None):  # type: ignore[no-untyped-def]
        specs.append(spec)
        return original(self, spec, deadline, cancel)

    monkeypatch.setattr(module.ProcessSupervisor, "run", spy)
    return specs


def test_ensure_server_spec_lets_daemon_survive(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    specs = _captured_specs(client, monkeypatch)

    result = client.ensure_server(Deadline.after(5.0))

    assert result.status == ProbeStatus.READY
    assert result.error_code == ProbeErrorCode.OK
    assert len(specs) == 1
    assert specs[0].descendants_survive_close is True


def test_ensure_server_does_not_redirect_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """重定向会触发 bInheritHandles=TRUE，使存活 daemon 继承 stdout 而挂住管道。"""
    client = _client()
    specs = _captured_specs(client, monkeypatch)

    client.ensure_server(Deadline.after(5.0))

    assert specs[0].stdout_path is None
    assert specs[0].stderr_path is None


def test_ordinary_commands_keep_default_reaping(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    specs = _captured_specs(client, monkeypatch)

    client.version(Deadline.after(5.0))
    client.list_devices(Deadline.after(5.0))

    assert specs, "预期至少捕获一条命令"
    for spec in specs:
        if spec.name == "adb_start_server":
            continue
        assert spec.descendants_survive_close is False
        assert spec.stdout_path is not None
        assert spec.stderr_path is not None


def test_ensure_server_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    specs = _captured_specs(client, monkeypatch)

    for _ in range(4):
        assert client.ensure_server(Deadline.after(5.0)).status == ProbeStatus.READY

    starts = [s for s in specs if s.name == "adb_start_server"]
    assert len(starts) == 1


def test_connect_ensures_server_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """connect 写入的设备只存于 daemon 内存，必须先保证 daemon 能活过本命令。"""
    client = _client("connect_success")
    specs = _captured_specs(client, monkeypatch)

    result = client.connect("127.0.0.1", 16384, Deadline.after(5.0))

    assert result.status == ProbeStatus.READY
    names = [s.name for s in specs]
    assert names.index("adb_start_server") < names.index("adb_connect")


def test_ensure_server_failure_is_reported_not_raised() -> None:
    client = _client("start_server_nonzero")
    result = client.ensure_server(Deadline.after(5.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_EXIT_NONZERO


def test_ensure_server_failure_does_not_latch_success() -> None:
    """失败不得把 _server_ensured 置真，否则后续再也不会重试。"""
    client = _client("start_server_nonzero")
    first = client.ensure_server(Deadline.after(5.0))
    second = client.ensure_server(Deadline.after(5.0))
    assert first.status == ProbeStatus.FAILED
    assert second.status == ProbeStatus.FAILED


def test_missing_executable_reports_not_found() -> None:
    client = AdbClient(AdbClientConfig(executable=Path("Z:/nonexistent-adb.exe")))
    result = client.ensure_server(Deadline.after(1.0))
    assert result.error_code == ProbeErrorCode.ADB_NOT_FOUND


def test_expired_deadline_reports_timeout() -> None:
    client = _client()
    result = client.ensure_server(Deadline.after(0.0))
    assert result.status == ProbeStatus.TIMEOUT
    assert result.error_code == ProbeErrorCode.ADB_TIMEOUT


def test_cancellation_is_honoured() -> None:
    client = _client()
    token = CancellationToken()
    token.cancel()
    result = client.ensure_server(Deadline.after(5.0), token)
    assert result.error_code == ProbeErrorCode.ADB_CANCELLED


def test_surviving_daemon_does_not_hold_parent_stdout(tmp_path: Path) -> None:
    """端到端：真实事故的直接表现是下游管道收不到 EOF。

    子进程用生产 AdbClient 拉起一个存活的伪 daemon，然后退出。若 daemon 继承了
    父进程的 stdout 句柄，``communicate()`` 会等到超时而非立即返回。
    """
    daemon = tmp_path / "fake_daemon.py"
    daemon.write_text(
        textwrap.dedent(
            """
            import sys, time
            if "start-server" in sys.argv:
                # 模拟 adb fork 出的常驻 daemon：不退出。
                time.sleep(30)
            """
        ),
        encoding="utf-8",
    )

    driver = tmp_path / "driver.py"
    driver.write_text(
        textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(Path.cwd() / "src")!r})
            from pathlib import Path
            from autogame_orchestrator.probes.adb_client import AdbClient, AdbClientConfig
            from autogame_orchestrator.process import Deadline

            client = AdbClient(AdbClientConfig(
                executable=Path(sys.executable),
                base_arguments=({str(daemon)!r},),
                command_timeout_seconds=2.0,
            ))
            client.ensure_server(Deadline.after(2.0))
            print("DRIVER_DONE", flush=True)
            """
        ),
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        [sys.executable, str(driver)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        stdout, _ = proc.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        pytest.fail("下游管道未收到 EOF：存活的 daemon 继承了父进程 stdout 句柄")

    assert "DRIVER_DONE" in stdout
