"""MAA 适配器的进程监督集成测试。"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from autogame_orchestrator.config_model import MAAConfig
from autogame_orchestrator.process import CancellationToken, Deadline
from autogame_orchestrator.runtime import MAAAdapter, MAAErrorCode, MAARunStatus

_FAKE = str(Path(__file__).parents[1] / "fakes" / "fake_maa.py")


def _config(tmp_path: Path, mode: str, timeout: int = 5) -> MAAConfig:
    return MAAConfig(
        str(Path(sys.executable)),
        str(tmp_path),
        (_FAKE, "--mode", mode),
        timeout_seconds=timeout,
        stop_timeout_seconds=2,
    )


def test_exit_zero(tmp_path: Path) -> None:
    result = MAAAdapter(_config(tmp_path, "exit_zero")).run()
    assert (
        result.status == MAARunStatus.COMPLETED
        and result.error_code == MAAErrorCode.OK
        and result.pid is not None
        and result.pid > 0
    )


def test_exit_nonzero(tmp_path: Path) -> None:
    result = MAAAdapter(_config(tmp_path, "exit_nonzero")).run()
    assert result.status == MAARunStatus.FAILED and result.exit_code == 7


def test_timeout(tmp_path: Path) -> None:
    result = MAAAdapter(_config(tmp_path, "hang", 1)).run(Deadline.after(0.2))
    assert result.status == MAARunStatus.TIMEOUT and result.owned_process_cleaned


def test_cancellation_is_not_timeout(tmp_path: Path) -> None:
    pid_file = tmp_path / "maa.pid"
    config = MAAConfig(
        str(Path(sys.executable)),
        str(tmp_path),
        (_FAKE, "--mode", "hang", "--pid-file", str(pid_file)),
        timeout_seconds=5,
        stop_timeout_seconds=2,
    )
    cancellation = CancellationToken()
    holder = []
    thread = threading.Thread(target=lambda: holder.append(MAAAdapter(config).run(cancel=cancellation)))
    thread.start()
    deadline = time.monotonic() + 3
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pid_file.exists()
    cancellation.cancel()
    thread.join(3)
    assert not thread.is_alive()
    assert len(holder) == 1 and holder[0].status == MAARunStatus.CANCELLED


def test_parent_deadline_caps_timeout(tmp_path: Path) -> None:
    result = MAAAdapter(_config(tmp_path, "hang", 5)).run(Deadline.after(0.1))
    assert result.status == MAARunStatus.TIMEOUT


def test_pre_cancel_does_not_start(tmp_path: Path) -> None:
    cancellation = CancellationToken()
    cancellation.cancel()
    result = MAAAdapter(_config(tmp_path, "hang")).run(cancel=cancellation)
    assert result.status == MAARunStatus.CANCELLED and result.pid is None


def test_large_output_and_utf16(tmp_path: Path) -> None:
    large = MAAAdapter(_config(tmp_path, "large_output_exit_zero")).run()
    assert large.stdout_truncated and large.stderr_truncated
    utf16 = MAAAdapter(_config(tmp_path, "utf16_output_exit_zero")).run()
    assert "中文输出" in utf16.stdout_excerpt
