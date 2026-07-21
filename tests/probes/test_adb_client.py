"""AdbClient 测试。使用 Fake ADB。"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from autogame_orchestrator.probes.adb_client import AdbClient, AdbClientConfig
from autogame_orchestrator.probes.models import ProbeErrorCode, ProbeStatus
from autogame_orchestrator.process import CancellationToken, Deadline

_FAKE_ADB = str(Path(__file__).resolve().parent.parent / "fakes" / "fake_adb.py")


def _make_client(mode: str = "normal") -> AdbClient:
    return AdbClient(
        AdbClientConfig(
            executable=Path(sys.executable),
            base_arguments=(_FAKE_ADB, "--mode", mode),
        )
    )


def test_version_success() -> None:
    """version 成功。"""
    client = _make_client("normal")
    result = client.version(Deadline.after(5.0))
    assert result.status == ProbeStatus.READY
    assert result.error_code == ProbeErrorCode.OK


def test_version_executable_not_found() -> None:
    """可执行文件不存在。"""
    client = AdbClient(AdbClientConfig(executable=Path("Z:/nonexistent.exe")))
    result = client.version(Deadline.after(1.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_NOT_FOUND


def test_version_executable_is_directory(tmp_path: Path) -> None:
    """可执行文件是目录。"""
    client = AdbClient(AdbClientConfig(executable=tmp_path))
    result = client.version(Deadline.after(1.0))
    assert result.error_code == ProbeErrorCode.ADB_NOT_FOUND


def test_nonzero_exit() -> None:
    """非零退出返回 ADB_EXIT_NONZERO。"""
    client = _make_client("exit_nonzero")
    result = client.version(Deadline.after(5.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_EXIT_NONZERO


def test_timeout() -> None:
    """timeout 返回 ADB_TIMEOUT。"""
    client = _make_client("sleep_forever")
    t0 = time.monotonic()
    result = client.version(Deadline.after(0.2))
    assert result.status == ProbeStatus.TIMEOUT
    assert result.error_code == ProbeErrorCode.ADB_TIMEOUT
    assert time.monotonic() - t0 < 3.0


def test_cancellation() -> None:
    """另一线程触发 cancel，ADB 命令返回 CANCELLED。"""
    client = _make_client("sleep_forever")
    cancel = CancellationToken()
    t0 = time.monotonic()

    def _cancel() -> None:
        time.sleep(0.1)
        cancel.cancel()

    t = threading.Thread(target=_cancel, daemon=True)
    t.start()

    result = client.version(Deadline.after(5.0), cancel=cancel)
    t.join()

    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_CANCELLED
    assert time.monotonic() - t0 < 3.0


def test_list_devices_normal() -> None:
    """list_devices 返回设备列表。"""
    client = _make_client("normal")
    result = client.list_devices(Deadline.after(5.0))
    assert result.probe.status == ProbeStatus.READY
    assert len(result.devices) == 1
    assert result.devices[0].serial == "127.0.0.1:16384"


def test_list_devices_no_devices() -> None:
    """list_devices 无设备。"""
    client = _make_client("no_devices")
    result = client.list_devices(Deadline.after(5.0))
    assert result.probe.status == ProbeStatus.READY
    assert result.devices == ()


def test_list_devices_malformed() -> None:
    """list_devices 格式错误返回 FAILED。"""
    client = _make_client("malformed")
    result = client.list_devices(Deadline.after(5.0))
    assert result.probe.status == ProbeStatus.FAILED


def test_output_large_stdout() -> None:
    """超大 stdout 返回 ADB_OUTPUT_INVALID。"""
    client = _make_client("large_stdout")
    result = client.version(Deadline.after(10.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_OUTPUT_INVALID


def test_output_large_stderr() -> None:
    """超大 stderr 返回 ADB_OUTPUT_INVALID。"""
    client = _make_client("large_stderr")
    result = client.version(Deadline.after(10.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_OUTPUT_INVALID


def test_stderr_summary() -> None:
    """stderr 输出出现在 diagnostics 摘要中。"""
    client = _make_client("stderr_output")
    result = client.version(Deadline.after(5.0))
    assert result.status == ProbeStatus.READY
    diag = result.diagnostics.get("stderr_trimmed", "")
    assert isinstance(diag, str) and len(diag) > 0


def test_no_pipe_no_shell() -> None:
    """验证 AdbClientConfig 不含 shell/PIPE 字段。"""
    config = AdbClientConfig(executable=Path(sys.executable))
    assert not hasattr(config, "shell")
    assert not hasattr(config, "use_pipe")
