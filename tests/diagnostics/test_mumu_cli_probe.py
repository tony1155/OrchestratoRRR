"""MumuCliProbe 测试。使用 Fake CLI 通过 ProcessSupervisor 真实执行。"""

from __future__ import annotations

import json
import locale
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from autogame_orchestrator.diagnostics.mumu_cli_probe import (
    MAX_EXCERPT_CHARS,
    MAX_STDOUT_BYTES,
    MumuCliAttemptStatus,
    MumuCliCandidateStatus,
    MumuCliProbe,
    MumuCliProbeReport,
    ProbeCommand,
    _read_limited_text,
    report_to_dict,
    validate_mumu_candidate,
)
from autogame_orchestrator.process import CancellationToken

_FAKE_CLI = str(Path(__file__).resolve().parent.parent / "fakes" / "fake_mumu_cli.py")
_PYTHON = sys.executable


def _make_command(mode: str) -> ProbeCommand:
    return ProbeCommand(
        display_name="MuMuManager.exe",
        executable=Path(_PYTHON),
        prefix_arguments=(_FAKE_CLI, "--mode", mode),
    )


def _check_pid_exited(pid: int, label: str, timeout: float = 2.0) -> None:
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


# ════════════════════════════════════════════════════════════════════
# 候选验证
# ════════════════════════════════════════════════════════════════════


def test_validate_candidate_accepts_mumu_manager(tmp_path: Path) -> None:
    p = tmp_path / "MuMuManager.exe"
    p.write_text("", encoding="utf-8")
    cmd = validate_mumu_candidate(p)
    assert cmd.display_name == "MuMuManager.exe"


def test_validate_candidate_accepts_nemu_shell(tmp_path: Path) -> None:
    p = tmp_path / "NemuShell.exe"
    p.write_text("", encoding="utf-8")
    cmd = validate_mumu_candidate(p)
    assert cmd.display_name == "NemuShell.exe"


def test_validate_candidate_rejects_relative_path() -> None:
    with pytest.raises(ValueError, match="^candidate_not_absolute$"):
        validate_mumu_candidate(Path("relative/MuMuManager.exe"))


def test_validate_candidate_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="^candidate_not_file$"):
        validate_mumu_candidate(tmp_path)


def test_validate_candidate_rejects_mumu_nx_main(tmp_path: Path) -> None:
    p = tmp_path / "MuMuNxMain.exe"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="^candidate_forbidden$"):
        validate_mumu_candidate(p)


def test_validate_candidate_rejects_mumu_nx_device(tmp_path: Path) -> None:
    p = tmp_path / "MuMuNxDevice.exe"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="^candidate_forbidden$"):
        validate_mumu_candidate(p)


def test_validate_candidate_rejects_vmm_manage(tmp_path: Path) -> None:
    p = tmp_path / "MuMuVMMManage.exe"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="^candidate_forbidden$"):
        validate_mumu_candidate(p)


def test_validate_candidate_rejects_unknown_filename(tmp_path: Path) -> None:
    p = tmp_path / "unknown.exe"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="^candidate_not_allowlisted$"):
        validate_mumu_candidate(p)


# ════════════════════════════════════════════════════════════════════
# 帮助识别
# ════════════════════════════════════════════════════════════════════


def test_help_stdout_detected() -> None:
    cmd = _make_command("help_stdout")
    probe = MumuCliProbe()
    report = probe.probe(cmd)
    assert report.status == MumuCliCandidateStatus.HELP_DISCOVERED
    assert report.runtime_approved is False
    assert len(report.attempts) >= 1
    a0 = report.attempts[0]
    assert a0.status == MumuCliAttemptStatus.HELP_EVIDENCE
    assert "usage" in [m.casefold() for m in a0.matched_markers]
    assert a0.exit_code == 0


def test_help_stderr_nonzero_detected() -> None:
    cmd = _make_command("help_stderr_nonzero")
    probe = MumuCliProbe()
    report = probe.probe(cmd)
    assert report.status == MumuCliCandidateStatus.HELP_DISCOVERED
    a0 = report.attempts[0]
    assert a0.status == MumuCliAttemptStatus.HELP_EVIDENCE
    assert a0.exit_code == 1


def test_utf16_help_detected() -> None:
    cmd = _make_command("utf16_help")
    probe = MumuCliProbe()
    report = probe.probe(cmd)
    assert report.status == MumuCliCandidateStatus.HELP_DISCOVERED
    a0 = report.attempts[0]
    assert a0.status == MumuCliAttemptStatus.HELP_EVIDENCE
    markers_lower = [m.casefold() for m in a0.matched_markers]
    assert "用法" in markers_lower or "启动" in markers_lower


def test_unrelated_output_not_detected() -> None:
    cmd = _make_command("unrelated_output")
    probe = MumuCliProbe()
    report = probe.probe(cmd)
    assert report.status == MumuCliCandidateStatus.NO_HELP_DISCOVERED


def test_no_output_not_detected() -> None:
    cmd = _make_command("no_output")
    probe = MumuCliProbe()
    report = probe.probe(cmd)
    assert report.status == MumuCliCandidateStatus.NO_HELP_DISCOVERED


def test_probe_stops_after_first_help_evidence() -> None:
    cmd = _make_command("help_stdout")
    probe = MumuCliProbe()
    report = probe.probe(cmd)
    assert len(report.attempts) == 1
    assert report.attempts[0].status == MumuCliAttemptStatus.HELP_EVIDENCE


# ════════════════════════════════════════════════════════════════════
# 输出边界
# ════════════════════════════════════════════════════════════════════


def test_large_output_is_rejected() -> None:
    report = MumuCliProbe().probe(_make_command("large_output"))

    assert report.status == MumuCliCandidateStatus.NO_HELP_DISCOVERED
    assert len(report.attempts) == 3

    for attempt in report.attempts:
        assert attempt.status == MumuCliAttemptStatus.OUTPUT_INVALID
        assert attempt.stderr_truncated is True
        assert len(attempt.stderr_excerpt) <= MAX_EXCERPT_CHARS
        assert attempt.matched_markers == ()

    assert report.runtime_approved is False


def test_read_limited_text_truncates() -> None:
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        f.write(b"A" * 200)
        f.flush()
        p = Path(f.name)
    try:
        text, truncated = _read_limited_text(p, 100)
        assert truncated is True
        assert len(text.encode("utf-8")) <= 100
    finally:
        p.unlink(missing_ok=True)


def test_read_limited_text_missing_file() -> None:
    text, truncated = _read_limited_text(Path("Z:/nonexistent_file_12345.bin"), 100)
    assert text == ""
    assert truncated is False


def test_read_limited_text_uses_preferred_encoding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_path = tmp_path / "preferred-encoding.bin"
    expected = "Café options"
    output_path.write_bytes(expected.encode("cp1252"))

    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=False: "cp1252")

    text, truncated = _read_limited_text(output_path, MAX_STDOUT_BYTES)
    assert text == expected
    assert truncated is False


# ════════════════════════════════════════════════════════════════════
# timeout 和清理
# ════════════════════════════════════════════════════════════════════


def test_timeout_is_bounded_and_process_exits(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid.txt"
    cmd = ProbeCommand(
        display_name="MuMuManager.exe",
        executable=Path(_PYTHON),
        prefix_arguments=(_FAKE_CLI, "--mode", "sleep_forever", "--pid-file", str(pid_file)),
    )
    probe = MumuCliProbe(attempt_timeout_seconds=0.30, total_timeout_seconds=0.30)
    t0 = time.monotonic()
    report = probe.probe(cmd)
    elapsed = time.monotonic() - t0

    assert elapsed < 5.0
    assert report.status == MumuCliCandidateStatus.UNSAFE_OR_HANGING
    assert len(report.attempts) == 1
    assert report.attempts[0].status == MumuCliAttemptStatus.TIMEOUT
    assert pid_file.exists()

    pid = int(pid_file.read_text(encoding="utf-8").strip())
    _check_pid_exited(pid, "timeout测试")


def _wait_for_pid_file(path: Path, *, timeout_seconds: float = 3.0) -> int:
    """等待 PID 文件出现并包含有效正整数。"""
    deadline = time.monotonic() + timeout_seconds
    last_text = ""

    while time.monotonic() < deadline:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError):
            time.sleep(0.02)
            continue

        last_text = text
        try:
            pid = int(text)
        except ValueError:
            time.sleep(0.02)
            continue

        if pid > 0:
            return pid
        time.sleep(0.02)

    raise AssertionError(f"等待 Fake 进程 PID 文件超时：path={path}, last_text={last_text!r}")


# ════════════════════════════════════════════════════════════════════
# cancellation（基于 PID 同步，不依赖固定延迟）
# ════════════════════════════════════════════════════════════════════


def test_cancellation_is_not_timeout(tmp_path: Path) -> None:
    pid_file = tmp_path / "cancel-pid.txt"
    cmd = ProbeCommand(
        display_name="MuMuManager.exe",
        executable=Path(_PYTHON),
        prefix_arguments=(_FAKE_CLI, "--mode", "sleep_forever", "--pid-file", str(pid_file)),
    )
    probe = MumuCliProbe(attempt_timeout_seconds=10.0, total_timeout_seconds=10.0)
    cancel = CancellationToken()

    results: list[MumuCliProbeReport] = []
    failures: list[BaseException] = []

    def run_probe() -> None:
        try:
            results.append(probe.probe(cmd, cancel=cancel))
        except BaseException as exc:
            failures.append(exc)

    worker = threading.Thread(target=run_probe, daemon=True)
    started = time.monotonic()
    worker.start()

    pid: int | None = None
    try:
        pid = _wait_for_pid_file(pid_file, timeout_seconds=3.0)
    finally:
        cancel.cancel()
        worker.join(timeout=5.0)

    elapsed = time.monotonic() - started

    assert worker.is_alive() is False
    assert failures == []
    assert len(results) == 1
    assert pid is not None
    assert pid > 0

    report = results[0]
    assert isinstance(report, MumuCliProbeReport)
    assert report.status == MumuCliCandidateStatus.CANCELLED
    assert len(report.attempts) == 1
    assert report.attempts[0].status == MumuCliAttemptStatus.CANCELLED
    assert elapsed < 5.0
    _check_pid_exited(pid, "cancel测试")


# ════════════════════════════════════════════════════════════════════
# 总预算
# ════════════════════════════════════════════════════════════════════


def test_total_deadline_not_reset_between_arguments(tmp_path: Path) -> None:
    pid_file = tmp_path / "deadline-pid.txt"
    command = ProbeCommand(
        display_name="MuMuManager.exe",
        executable=Path(_PYTHON),
        prefix_arguments=(_FAKE_CLI, "--mode", "sleep_forever", "--pid-file", str(pid_file)),
    )
    probe = MumuCliProbe(attempt_timeout_seconds=0.40, total_timeout_seconds=0.75)

    started = time.monotonic()
    report = probe.probe(command)
    elapsed = time.monotonic() - started

    assert report.status == MumuCliCandidateStatus.UNSAFE_OR_HANGING
    assert 0.50 <= elapsed < 1.50
    assert 1 <= len(report.attempts) <= 3
    assert all(attempt.status == MumuCliAttemptStatus.TIMEOUT for attempt in report.attempts)
    assert sum(attempt.duration_ms for attempt in report.attempts) < 1500
    assert pid_file.exists()

    pid = int(pid_file.read_text(encoding="utf-8").strip())
    _check_pid_exited(pid, "总Deadline测试")


# ════════════════════════════════════════════════════════════════════
# 启动失败
# ════════════════════════════════════════════════════════════════════


def test_start_failure_is_reported(tmp_path: Path) -> None:
    command = ProbeCommand(display_name="MuMuManager.exe", executable=tmp_path / "missing.exe")

    report = MumuCliProbe(attempt_timeout_seconds=0.2, total_timeout_seconds=0.6).probe(command)

    assert report.status == MumuCliCandidateStatus.NO_HELP_DISCOVERED
    assert len(report.attempts) == 3
    assert all(attempt.status == MumuCliAttemptStatus.START_FAILED for attempt in report.attempts)
    assert report.diagnostics["reason"] == "candidate process could not be started"
    assert report.runtime_approved is False


# ════════════════════════════════════════════════════════════════════
# JSON 和 CLI
# ════════════════════════════════════════════════════════════════════


def test_report_to_dict_is_json_serializable() -> None:
    cmd = _make_command("help_stdout")
    probe = MumuCliProbe()
    report = probe.probe(cmd)
    d = report_to_dict(report)
    s = json.dumps(d, ensure_ascii=False)
    assert "help_discovered" in s
    assert d["runtime_approved"] is False
    assert "candidate_path" not in d
    assert "stdout_excerpt" not in d["attempts"][0]
    assert "stderr_excerpt" not in d["attempts"][0]
    assert d["attempts"][0]["stdout_present"] is True
    assert d["attempts"][0]["stderr_present"] is False


def test_public_markers_are_fixed_allowlist() -> None:
    report = MumuCliProbe().probe(_make_command("help_stdout"))
    attempt = report_to_dict(report)["attempts"][0]

    assert set(attempt["matched_markers"]) <= {
        "usage",
        "options",
        "commands",
        "command",
        "help",
        "start",
        "stop",
        "instance",
        "device",
        "用法",
        "选项",
        "命令",
        "帮助",
        "启动",
        "停止",
        "实例",
        "设备",
    }


def test_stderr_presence_is_projected_without_excerpt() -> None:
    report = MumuCliProbe().probe(_make_command("help_stderr_nonzero"))
    attempt = report_to_dict(report)["attempts"][0]

    assert attempt["stdout_present"] is False
    assert attempt["stderr_present"] is True
    assert "stderr_excerpt" not in attempt


def test_cli_emits_json_for_fake_candidate(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from autogame_orchestrator.diagnostics import mumu_cli_probe

    fake_command = ProbeCommand(
        display_name="MuMuManager.exe",
        executable=Path(_PYTHON),
        prefix_arguments=(_FAKE_CLI, "--mode", "help_stdout"),
    )

    monkeypatch.setattr(mumu_cli_probe, "validate_mumu_candidate", lambda path: fake_command)

    result = mumu_cli_probe.main(
        [
            "--candidate",
            "C:/Fake/MuMuManager.exe",
            "--attempt-timeout-seconds",
            "1",
            "--total-timeout-seconds",
            "2",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert result == 0
    assert payload["candidate_name"] == "MuMuManager.exe"
    assert payload["status"] == "help_discovered"
    assert payload["runtime_approved"] is False
    assert "candidate_path" not in payload
    assert len(payload["attempts"]) == 1
    assert payload["attempts"][0]["status"] == "help_evidence"
    assert "stdout_excerpt" not in payload["attempts"][0]
    assert "stderr_excerpt" not in payload["attempts"][0]


def test_cli_rejects_forbidden_candidate(tmp_path: Path) -> None:
    from autogame_orchestrator.diagnostics import mumu_cli_probe

    forbidden = tmp_path / "MuMuNxMain.exe"
    forbidden.write_bytes(b"not executable")

    with patch.object(
        mumu_cli_probe.MumuCliProbe, "probe", side_effect=AssertionError("禁止候选不应进入 probe")
    ) as probe_mock:
        result = mumu_cli_probe.main(["--candidate", str(forbidden)])

    assert result == 2
    probe_mock.assert_not_called()


def test_cli_rejects_unknown_argument() -> None:
    from autogame_orchestrator.diagnostics import mumu_cli_probe

    with patch.object(
        mumu_cli_probe.MumuCliProbe, "probe", side_effect=AssertionError("未知参数不应执行 probe")
    ) as probe_mock:
        with pytest.raises(SystemExit) as exc_info:
            mumu_cli_probe.main(["--candidate", "C:/Fake/MuMuManager.exe", "--arguments", "start"])

    assert exc_info.value.code == 2
    probe_mock.assert_not_called()


# ════════════════════════════════════════════════════════════════════
# 路径隐私和模块执行
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "candidate",
    [
        Path("Q:/private-tools/NemuShell.exe"),
        Path("R:/") / ("Program" + " Files") / "NemuShell.exe",
        Path("S:/") / ("Us" + "ers") / "PrivateUser" / "NemuShell.exe",
    ],
)
def test_missing_candidate_error_does_not_expose_input_path(candidate: Path) -> None:
    with pytest.raises(ValueError) as exc_info:
        validate_mumu_candidate(candidate)

    assert str(exc_info.value) == "candidate_not_found"
    assert str(candidate) not in str(exc_info.value)


def test_forbidden_candidate_error_does_not_expose_input_path(tmp_path: Path) -> None:
    candidate = tmp_path / "MuMuNxMain.exe"
    candidate.write_bytes(b"fake")

    with pytest.raises(ValueError) as exc_info:
        validate_mumu_candidate(candidate)

    assert str(exc_info.value) == "candidate_forbidden"
    assert str(candidate) not in str(exc_info.value)


def test_not_allowlisted_error_does_not_expose_input_path(tmp_path: Path) -> None:
    candidate = tmp_path / "unknown.exe"
    candidate.write_bytes(b"fake")

    with pytest.raises(ValueError) as exc_info:
        validate_mumu_candidate(candidate)

    assert str(exc_info.value) == "candidate_not_allowlisted"
    assert str(candidate) not in str(exc_info.value)


def test_cli_candidate_error_is_one_safe_json_document(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from autogame_orchestrator.diagnostics import mumu_cli_probe

    candidate = tmp_path / ("Program" + " Files") / "NemuShell.exe"
    result = mumu_cli_probe.main(["--candidate", str(candidate)])
    captured = capsys.readouterr()

    assert result == 2
    assert json.loads(captured.out) == {"error": "candidate_not_found"}
    assert captured.out.count("{") == 1
    assert str(candidate) not in captured.out
    assert captured.err == ""


def test_cli_internal_error_is_safe_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from autogame_orchestrator.diagnostics import mumu_cli_probe

    fake_command = _make_command("help_stdout")
    monkeypatch.setattr(mumu_cli_probe, "validate_mumu_candidate", lambda path: fake_command)
    monkeypatch.setattr(
        mumu_cli_probe.MumuCliProbe,
        "probe",
        lambda self, command: (_ for _ in ()).throw(RuntimeError("private-path-and-value")),
    )

    result = mumu_cli_probe.main(["--candidate", "Q:/private/NemuShell.exe"])
    captured = capsys.readouterr()

    assert result == 3
    assert json.loads(captured.out) == {"error": "internal_error"}
    assert "private-path-and-value" not in captured.out
    assert captured.err == ""


def test_diagnostics_package_does_not_eagerly_import_probe() -> None:
    script = (
        "import sys; import autogame_orchestrator.diagnostics; "
        "print('autogame_orchestrator.diagnostics.mumu_cli_probe' in sys.modules)"
    )
    completed = subprocess.run(
        [_PYTHON, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "False"
    assert completed.stderr == ""


def test_diagnostics_package_keeps_lazy_probe_exports() -> None:
    import autogame_orchestrator.diagnostics as diagnostics

    assert diagnostics.MumuCliProbe is MumuCliProbe
    assert diagnostics.validate_mumu_candidate is validate_mumu_candidate


def test_python_module_has_no_runtime_warning(tmp_path: Path) -> None:
    candidate = tmp_path / "missing" / "NemuShell.exe"
    completed = subprocess.run(
        [
            _PYTHON,
            "-m",
            "autogame_orchestrator.diagnostics.mumu_cli_probe",
            "--candidate",
            str(candidate),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {"error": "candidate_not_found"}
    assert "RuntimeWarning" not in completed.stderr
    assert "found in sys.modules" not in completed.stderr
    assert "unpredictable behaviour" not in completed.stderr
    assert str(candidate) not in completed.stdout
    assert completed.stderr == ""


def test_python_module_success_stdout_is_one_json_document(tmp_path: Path) -> None:
    candidate = tmp_path / "NemuShell.exe"
    shutil.copy2(_PYTHON, candidate)
    completed = subprocess.run(
        [
            _PYTHON,
            "-m",
            "autogame_orchestrator.diagnostics.mumu_cli_probe",
            "--candidate",
            str(candidate),
            "--attempt-timeout-seconds",
            "2",
            "--total-timeout-seconds",
            "3",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert payload["candidate_name"] == "NemuShell.exe"
    assert payload["runtime_approved"] is False
    assert "candidate_path" not in payload
    assert "stdout_excerpt" not in completed.stdout
    assert "stderr_excerpt" not in completed.stdout
    assert completed.stderr == ""
