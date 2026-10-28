"""STOP_FGO：scoped ADB force-stop 的契约测试（真实 Windows 子进程 + Fake adb）。"""

import sys
import textwrap
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from autogame_orchestrator.process import CancellationToken, Deadline, ProcessSupervisor
from autogame_orchestrator.runtime.fgo_app import FgoAppStopper
from autogame_orchestrator.runtime.fgo_models import FgoAppStopErrorCode as Code
from autogame_orchestrator.runtime.fgo_models import FgoAppStopStatus as Status
from autogame_orchestrator.runtime.fgo_models import FgoStopVerification

SERIAL = "127.0.0.1:16384"
PACKAGE = "com.bilibili.fatego"

FAKE_ADB = textwrap.dedent(
    """\
    import sys
    import time
    from pathlib import Path

    argv = sys.argv[1:]
    stop = argv.index("--record")
    record = argv[stop + 1]
    mode = argv[argv.index("--mode") + 1]
    # 只记录模拟的 adb 参数（--record 之前的部分）。
    with Path(record).open("a", encoding="utf-8") as stream:
        stream.write(repr(argv[:stop]) + chr(10))
    if mode == "stop-ok":
        sys.exit(0)
    if mode == "stop-fail":
        sys.exit(1)
    if mode == "pidof-empty":
        sys.exit(1)
    if mode == "pidof-empty-zero":
        sys.exit(0)
    if mode == "pidof-alive":
        print("12345")
        sys.exit(0)
    if mode == "hang":
        time.sleep(30)
    sys.exit(0)
    """
)


FAKE_ADB_SCRIPT_PATH = Path(__file__).parent / "_fake_adb_for_fgo.py"
FAKE_ADB_SCRIPT_PATH.write_text(FAKE_ADB, encoding="utf-8")


class ScriptedSupervisor(ProcessSupervisor):
    """按序执行 stop / verify 模式的 Fake adb；真实 Job/supervisor 语义不变。"""

    sequence: list[str] = []
    record_path: Path | None = None

    def run(self, spec, deadline, cancel=None):
        mode = self.sequence.pop(0) if self.sequence else "stop-ok"
        # 保留被模拟的 adb 参数（spec.arguments），供 Fake 记录与断言。
        arguments = (
            str(FAKE_ADB_SCRIPT_PATH),
            *spec.arguments,
            "--record",
            str(self.record_path),
            "--mode",
            mode,
        )
        return super().run(replace(spec, executable=Path(sys._base_executable), arguments=arguments), deadline, cancel)


def stopper(tmp_path: Path) -> FgoAppStopper:
    return FgoAppStopper(
        adb_executable=tmp_path / "adb.exe",
        adb_serial=SERIAL,
        package_name=PACKAGE,
        stop_timeout_seconds=5.0,
    )


def scripted(tmp_path: Path, monkeypatch, modes: list[str]) -> Path:
    record = tmp_path / "adb-calls.txt"
    ScriptedSupervisor.sequence = list(modes)
    ScriptedSupervisor.record_path = record
    monkeypatch.setattr("autogame_orchestrator.runtime.fgo_app.ProcessSupervisor", ScriptedSupervisor)
    return record


def test_force_stop_exact_arguments(tmp_path, monkeypatch):
    record = scripted(tmp_path, monkeypatch, ["stop-ok", "pidof-empty"])
    result = stopper(tmp_path).stop(Deadline.after(30))
    assert (result.status, result.error_code) == (Status.STOPPED, Code.OK)
    assert result.verification is FgoStopVerification.VERIFIED
    lines = record.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = eval(lines[0])  # noqa: S307 - test fixture
    second = eval(lines[1])  # noqa: S307 - test fixture
    assert first == ["-s", SERIAL, "shell", "am", "force-stop", PACKAGE]
    assert second == ["-s", SERIAL, "shell", "pidof", PACKAGE]


def test_verify_exit_zero_empty_output_is_verified(tmp_path, monkeypatch):
    scripted(tmp_path, monkeypatch, ["stop-ok", "pidof-empty-zero"])
    result = stopper(tmp_path).stop(Deadline.after(30))
    assert result.status is Status.STOPPED and result.verification is FgoStopVerification.VERIFIED


def test_pid_still_alive_fails_verification_after_retry(tmp_path, monkeypatch):
    scripted(tmp_path, monkeypatch, ["stop-ok", "pidof-alive", "pidof-alive"])
    result = stopper(tmp_path).stop(Deadline.after(30))
    assert (result.status, result.error_code) == (Status.FAILED, Code.VERIFY_FAILED)


def test_force_stop_nonzero(tmp_path, monkeypatch):
    record = scripted(tmp_path, monkeypatch, ["stop-fail"])
    result = stopper(tmp_path).stop(Deadline.after(30))
    assert (result.status, result.error_code) == (Status.FAILED, Code.ADB_COMMAND_FAILED)
    # force-stop 失败后不做验证。
    assert len(record.read_text(encoding="utf-8").splitlines()) == 1


def test_stop_timeout_terminates_hang(tmp_path, monkeypatch):
    scripted(tmp_path, monkeypatch, ["hang"])
    started = time.monotonic()
    result = stopper(tmp_path).stop(Deadline.after(30))
    assert time.monotonic() - started < 15
    assert (result.status, result.error_code) == (Status.TIMEOUT, Code.TIMEOUT)


def test_stop_cancellation(tmp_path, monkeypatch):
    scripted(tmp_path, monkeypatch, ["hang"])
    cancel = CancellationToken()
    outcome: list[object] = []
    thread = threading.Thread(target=lambda: outcome.append(stopper(tmp_path).stop(Deadline.after(30), cancel)))
    thread.start()
    time.sleep(0.5)
    cancel.cancel()
    thread.join(10)
    assert outcome and outcome[0].status is Status.CANCELLED  # type: ignore[union-attr]


def test_exhausted_budget_is_timeout(tmp_path, monkeypatch):
    scripted(tmp_path, monkeypatch, ["hang"])
    result = stopper(tmp_path).stop(Deadline.after(0.1))
    assert (result.status, result.error_code) == (Status.TIMEOUT, Code.TIMEOUT)


def test_rejects_invalid_identity(tmp_path):
    with pytest.raises(ValueError):
        FgoAppStopper(adb_executable=tmp_path / "adb.exe", adb_serial="emulator-5554", package_name=PACKAGE)
    with pytest.raises(ValueError):
        FgoAppStopper(adb_executable=tmp_path / "adb.exe", adb_serial=SERIAL, package_name="com.bad;package")
    with pytest.raises(ValueError):
        FgoAppStopper(adb_executable=tmp_path / "adb.exe", adb_serial=SERIAL, package_name="")
    with pytest.raises(ValueError):
        FgoAppStopper(adb_executable=Path("relative-adb.exe"), adb_serial=SERIAL, package_name=PACKAGE)


def test_never_reaches_forbidden_shell_shape(tmp_path, monkeypatch):
    """所有命令都是 argument array；记录里不允许出现拼接的 shell 字符串。"""
    record = scripted(tmp_path, monkeypatch, ["stop-ok", "pidof-empty"])
    stopper(tmp_path).stop(Deadline.after(30))
    for line in record.read_text(encoding="utf-8").splitlines():
        arguments = eval(line)  # noqa: S307 - test fixture
        assert all(";" not in argument and "|" not in argument and "`" not in argument for argument in arguments)
