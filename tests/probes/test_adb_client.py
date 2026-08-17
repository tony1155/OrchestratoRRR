"""AdbClient 测试。使用 Fake ADB。"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from autogame_orchestrator.probes.adb_client import AdbClient, AdbClientConfig
from autogame_orchestrator.probes.models import ProbeErrorCode, ProbeResult, ProbeStatus
from autogame_orchestrator.process import CancellationToken, Deadline

_FAKE_ADB = str(Path(__file__).resolve().parent.parent / "fakes" / "fake_adb.py")


def _make_client(
    mode: str = "normal",
    args_file: Path | None = None,
    *,
    command_timeout_seconds: float = 5.0,
) -> AdbClient:
    base_arguments = [_FAKE_ADB, "--mode", mode]
    if args_file is not None:
        base_arguments.extend(["--args-file", str(args_file)])
    return AdbClient(
        AdbClientConfig(
            executable=Path(sys.executable),
            base_arguments=tuple(base_arguments),
            command_timeout_seconds=command_timeout_seconds,
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


def test_command_timeout_is_shorter_than_long_parent_deadline() -> None:
    """One blocked ADB process returns control without consuming its parent budget."""
    client = _make_client("sleep_forever", command_timeout_seconds=0.08)
    parent = Deadline.after(2.0)

    started = time.monotonic()
    result = client.version(parent)
    elapsed = time.monotonic() - started

    assert result.status == ProbeStatus.TIMEOUT
    assert result.error_code == ProbeErrorCode.ADB_TIMEOUT
    assert elapsed < 0.8
    assert parent.remaining_seconds > 1.0


def test_short_parent_deadline_clamps_command_timeout() -> None:
    client = _make_client("sleep_forever", command_timeout_seconds=5.0)

    started = time.monotonic()
    result = client.version(Deadline.after(0.08))
    elapsed = time.monotonic() - started

    assert result.status == ProbeStatus.TIMEOUT
    assert result.error_code == ProbeErrorCode.ADB_TIMEOUT
    assert elapsed < 0.8


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("inf"), float("nan"), True])
def test_invalid_command_timeout_is_rejected(timeout: float) -> None:
    with pytest.raises(ValueError, match="command_timeout_seconds"):
        AdbClientConfig(executable=Path(sys.executable), command_timeout_seconds=timeout)


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


def test_connect_success() -> None:
    result = _make_client("connect_success").connect("127.0.0.1", 16384, Deadline.after(5.0))
    assert result.status == ProbeStatus.READY
    assert result.error_code == ProbeErrorCode.OK
    assert result.diagnostics == {"connect_status": "connected"}


def test_connect_already_connected_is_success() -> None:
    result = _make_client("connect_already").connect("127.0.0.1", 16384, Deadline.after(5.0))
    assert result.status == ProbeStatus.READY
    assert result.error_code == ProbeErrorCode.OK
    assert result.diagnostics == {"connect_status": "already_connected"}


def test_connect_failure_text_with_zero_exit_is_failure() -> None:
    result = _make_client("connect_failed").connect("127.0.0.1", 16384, Deadline.after(5.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_CONNECT_FAILED
    assert result.diagnostics == {"connect_status": "failed"}


@pytest.mark.parametrize(
    ("mode", "error_code"),
    [
        ("connect_not_connected", ProbeErrorCode.ADB_CONNECT_FAILED),
        ("connect_conflict", ProbeErrorCode.ADB_CONNECT_FAILED),
        ("connect_empty", ProbeErrorCode.ADB_CONNECT_FAILED),
        ("connect_invalid_utf8", ProbeErrorCode.ADB_OUTPUT_INVALID),
    ],
)
def test_connect_negative_or_conflicting_output_is_failure(mode: str, error_code: ProbeErrorCode) -> None:
    result = _make_client(mode).connect("127.0.0.1", 16384, Deadline.after(5.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == error_code
    assert result.diagnostics == {"connect_status": "failed"}


def test_connect_unknown_text_with_zero_exit_is_failure() -> None:
    result = _make_client("connect_unknown").connect("127.0.0.1", 16384, Deadline.after(5.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_CONNECT_FAILED


def test_connect_nonzero_exit_is_failure() -> None:
    result = _make_client("connect_nonzero").connect("127.0.0.1", 16384, Deadline.after(5.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_EXIT_NONZERO
    assert result.diagnostics == {"connect_status": "failed"}


def test_connect_timeout() -> None:
    result = _make_client("sleep_forever").connect("127.0.0.1", 16384, Deadline.after(0.2))
    assert result.status == ProbeStatus.TIMEOUT
    assert result.error_code == ProbeErrorCode.ADB_TIMEOUT
    assert result.diagnostics == {"connect_status": "failed"}


def test_connect_cancellation() -> None:
    client = _make_client("sleep_forever")
    cancel = CancellationToken()

    def _cancel() -> None:
        time.sleep(0.1)
        cancel.cancel()

    thread = threading.Thread(target=_cancel, daemon=True)
    thread.start()
    result = client.connect("127.0.0.1", 16384, Deadline.after(5.0), cancel)
    thread.join()

    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_CANCELLED
    assert result.diagnostics == {"connect_status": "failed"}


def test_connect_process_start_failure(tmp_path: Path) -> None:
    executable = tmp_path / "not-an-executable"
    executable.write_text("not executable", encoding="utf-8")
    client = AdbClient(AdbClientConfig(executable=executable))
    result = client.connect("127.0.0.1", 16384, Deadline.after(1.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.ADB_START_FAILED
    assert result.diagnostics == {"connect_status": "failed"}


@pytest.mark.parametrize(
    "host",
    ["localhost", "127.0.0.01", "127.1", "0.0.0.0", "::1", "127.0.0.1\n", "127.0.0.1;echo"],
)
def test_connect_non_local_host_is_rejected_without_starting(host: str, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client("connect_success")

    def _unexpected(*args: object, **kwargs: object) -> ProbeResult:
        raise AssertionError("process must not start")

    monkeypatch.setattr(client, "_run_adb_command", _unexpected)
    result = client.connect(host, 16384, Deadline.after(5.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.NON_LOCAL_ADDRESS_REJECTED


@pytest.mark.parametrize("port", [0, -1, 65536, True, 1.5, "16384", "16:384", " 16384", "16384\n"])
def test_connect_invalid_port_is_rejected_without_starting(port: object, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client("connect_success")

    def _unexpected(*args: object, **kwargs: object) -> ProbeResult:
        raise AssertionError("process must not start")

    monkeypatch.setattr(client, "_run_adb_command", _unexpected)
    result = client.connect("127.0.0.1", port, Deadline.after(5.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.INVALID_CONFIGURATION


def test_connect_arguments_are_exact_and_diagnostics_are_safe(tmp_path: Path) -> None:
    args_file = tmp_path / "args.json"
    result = _make_client("connect_success", args_file).connect("127.0.0.1", 16384, Deadline.after(5.0))
    assert result.status == ProbeStatus.READY
    assert json.loads(args_file.read_text(encoding="utf-8")) == ["connect", "127.0.0.1:16384"]
    rendered = json.dumps(dict(result.diagnostics)) + repr(result)
    for forbidden in ("127.0.0.1", "16384", "target", "stdout", "stderr"):
        assert forbidden not in rendered


def test_disconnect_success() -> None:
    result = _make_client("normal").disconnect("127.0.0.1", 16384, Deadline.after(5.0))
    assert result.status == ProbeStatus.READY
    assert result.error_code == ProbeErrorCode.OK
    assert result.diagnostics == {"disconnect_status": "disconnected"}


@pytest.mark.parametrize(
    ("mode", "error_code"),
    [
        ("disconnect_failed", ProbeErrorCode.ADB_DISCONNECT_FAILED),
        ("disconnect_unknown", ProbeErrorCode.ADB_DISCONNECT_FAILED),
        ("disconnect_nonzero", ProbeErrorCode.ADB_EXIT_NONZERO),
    ],
)
def test_disconnect_failure_is_fail_closed(mode: str, error_code: ProbeErrorCode) -> None:
    result = _make_client(mode).disconnect("127.0.0.1", 16384, Deadline.after(5.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == error_code
    assert result.diagnostics == {"disconnect_status": "failed"}


@pytest.mark.parametrize("host", ["localhost", "0.0.0.0", "::1", "127.0.0.1;echo"])
def test_disconnect_non_local_host_is_rejected_without_starting(
    host: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client("normal")

    def _unexpected(*args: object, **kwargs: object) -> ProbeResult:
        raise AssertionError("process must not start")

    monkeypatch.setattr(client, "_run_adb_command", _unexpected)
    result = client.disconnect(host, 16384, Deadline.after(5.0))
    assert result.status == ProbeStatus.FAILED
    assert result.error_code == ProbeErrorCode.NON_LOCAL_ADDRESS_REJECTED


def test_disconnect_arguments_are_exact_and_diagnostics_are_safe(tmp_path: Path) -> None:
    args_file = tmp_path / "args.json"
    result = _make_client("normal", args_file).disconnect("127.0.0.1", 16384, Deadline.after(5.0))
    assert result.status == ProbeStatus.READY
    assert json.loads(args_file.read_text(encoding="utf-8")) == ["disconnect", "127.0.0.1:16384"]
    rendered = json.dumps(dict(result.diagnostics)) + repr(result)
    for forbidden in ("127.0.0.1", "16384", "target", "stdout", "stderr"):
        assert forbidden not in rendered


def test_recycle_local_endpoint_disconnects_then_connects() -> None:
    result = _make_client("connect_success").recycle_local_endpoint(
        "127.0.0.1",
        16384,
        Deadline.after(5.0),
    )
    assert result.status == ProbeStatus.READY
    assert result.error_code == ProbeErrorCode.OK
    assert result.diagnostics == {
        "disconnect_status": "disconnected",
        "connect_status": "connected",
    }


def test_recycle_local_endpoint_still_connects_after_disconnect_failure() -> None:
    result = _make_client("disconnect_failed").recycle_local_endpoint(
        "127.0.0.1",
        16384,
        Deadline.after(5.0),
    )
    assert result.status == ProbeStatus.READY
    assert result.error_code == ProbeErrorCode.OK
    assert result.diagnostics == {
        "disconnect_status": "failed",
        "connect_status": "connected",
    }


def test_recycle_local_endpoint_timeout_does_not_refresh_parent_budget() -> None:
    started = time.monotonic()
    result = _make_client("sleep_forever").recycle_local_endpoint(
        "127.0.0.1",
        16384,
        Deadline.after(0.2),
    )
    elapsed = time.monotonic() - started
    assert result.status == ProbeStatus.TIMEOUT
    assert result.error_code == ProbeErrorCode.ADB_TIMEOUT
    assert result.diagnostics == {
        "disconnect_status": "failed",
        "connect_status": "not_attempted",
    }
    assert elapsed < 1.0
