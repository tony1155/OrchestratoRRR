"""MumuCliProbe 测试。使用 Fake CLI 通过 ProcessSupervisor 真实执行。"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from autogame_orchestrator.diagnostics.mumu_cli_probe import (
    MumuCliAttemptStatus,
    MumuCliCandidateStatus,
    MumuCliProbe,
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
    with pytest.raises(ValueError, match="绝对路径"):
        validate_mumu_candidate(Path("relative/MuMuManager.exe"))


def test_validate_candidate_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="普通文件"):
        validate_mumu_candidate(tmp_path)


def test_validate_candidate_rejects_mumu_nx_main(tmp_path: Path) -> None:
    p = tmp_path / "MuMuNxMain.exe"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="禁止"):
        validate_mumu_candidate(p)


def test_validate_candidate_rejects_mumu_nx_device(tmp_path: Path) -> None:
    p = tmp_path / "MuMuNxDevice.exe"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="禁止"):
        validate_mumu_candidate(p)


def test_validate_candidate_rejects_vmm_manage(tmp_path: Path) -> None:
    p = tmp_path / "MuMuVMMManage.exe"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="禁止"):
        validate_mumu_candidate(p)


def test_validate_candidate_rejects_unknown_filename(tmp_path: Path) -> None:
    p = tmp_path / "unknown.exe"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="允许"):
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
    # 中文 marker 应被匹配
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
    # 应在第一个参数找到证据后停止
    assert len(report.attempts) == 1
    assert report.attempts[0].status == MumuCliAttemptStatus.HELP_EVIDENCE


# ════════════════════════════════════════════════════════════════════
# 输出边界
# ════════════════════════════════════════════════════════════════════


def test_large_output_is_rejected() -> None:
    cmd = _make_command("large_output")
    probe = MumuCliProbe()
    report = probe.probe(cmd)
    assert report.status == MumuCliCandidateStatus.NO_HELP_DISCOVERED


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


# ════════════════════════════════════════════════════════════════════
# timeout 和清理
# ════════════════════════════════════════════════════════════════════


def test_timeout_is_bounded_and_process_exits(tmp_path: Path) -> None:
    """sleep_forever → TIMEOUT，进程退出。"""
    pid_file = tmp_path / "pid.txt"
    cmd = ProbeCommand(
        display_name="MuMuManager.exe",
        executable=Path(_PYTHON),
        prefix_arguments=(_FAKE_CLI, "--mode", "sleep_forever", "--pid-file", str(pid_file)),
    )
    probe = MumuCliProbe(attempt_timeout_seconds=0.2, total_timeout_seconds=1.0)
    t0 = time.monotonic()
    report = probe.probe(cmd)
    elapsed = time.monotonic() - t0

    assert elapsed < 5.0
    assert report.status == MumuCliCandidateStatus.UNSAFE_OR_HANGING
    attempt = report.attempts[0]
    assert attempt.status == MumuCliAttemptStatus.TIMEOUT
    if pid_file.exists():
        pid = int(pid_file.read_text().strip())
        _check_pid_exited(pid, "timeout测试")


# ════════════════════════════════════════════════════════════════════
# cancellation
# ════════════════════════════════════════════════════════════════════


def test_cancellation_is_not_timeout(tmp_path: Path) -> None:
    """cancel → CANCELLED，非 timeout。"""
    pid_file = tmp_path / "pid.txt"
    cmd = ProbeCommand(
        display_name="MuMuManager.exe",
        executable=Path(_PYTHON),
        prefix_arguments=(_FAKE_CLI, "--mode", "sleep_forever", "--pid-file", str(pid_file)),
    )
    probe = MumuCliProbe(attempt_timeout_seconds=2.0, total_timeout_seconds=10.0)
    cancel = CancellationToken()
    t0 = time.monotonic()

    def _cancel() -> None:
        time.sleep(0.15)
        cancel.cancel()

    t = threading.Thread(target=_cancel, daemon=True)
    t.start()

    report = probe.probe(cmd, cancel=cancel)
    t.join()
    elapsed = time.monotonic() - t0

    assert elapsed < 5.0
    assert report.status == MumuCliCandidateStatus.CANCELLED
    attempt = report.attempts[0]
    assert attempt.status == MumuCliAttemptStatus.CANCELLED
    if pid_file.exists():
        pid = int(pid_file.read_text().strip())
        _check_pid_exited(pid, "cancel测试")


# ════════════════════════════════════════════════════════════════════
# 总预算
# ════════════════════════════════════════════════════════════════════


def test_total_deadline_not_reset_between_arguments() -> None:
    """三个参数各自不会获得完整总超时。"""
    cmd = _make_command("no_output")  # 每个参数无帮助，会全部尝试
    probe = MumuCliProbe(attempt_timeout_seconds=0.5, total_timeout_seconds=1.0)
    t0 = time.monotonic()
    report = probe.probe(cmd)
    elapsed = time.monotonic() - t0
    # 三个参数共 1.0 秒总预算，即使单个不会超过 0.5 秒
    assert elapsed < 2.0
    # 可能未用完所有参数（取决于 wall clock）
    assert 1 <= len(report.attempts) <= 3
    assert report.status == MumuCliCandidateStatus.NO_HELP_DISCOVERED


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


def test_cli_emits_json_for_fake_candidate(tmp_path: Path) -> None:
    from autogame_orchestrator.diagnostics.mumu_cli_probe import main

    p = tmp_path / "MuMuManager.exe"
    p.write_text("", encoding="utf-8")
    rv = main(["--candidate", str(p), "--total-timeout-seconds", "3"])
    assert rv == 0
