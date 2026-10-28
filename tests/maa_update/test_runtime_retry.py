from __future__ import annotations

import sys
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autogame_orchestrator.config_model import AppConfig, MAAConfig, MAAUpdateConfig
from autogame_orchestrator.maa_update import runtime
from autogame_orchestrator.maa_update.runtime import MAAUpdateAdapter
from autogame_orchestrator.process import CancellationToken, Deadline, TerminationReason
from autogame_orchestrator.runtime.maa import MAAAdapter
from autogame_orchestrator.runtime.maa_models import MAAErrorCode, MAARunResult, MAARunStatus
from autogame_orchestrator.workflow.production.projection import maa_output_diagnostics
from autogame_orchestrator.workflow.production.runtime_bindings import build_default_runtime_factories

INTERRUPTED = "Error: Failed to install MaaCore\nCaused by:\n  I/O error\n  Peer disconnected"


def result(error: str = "") -> MAARunResult:
    now = datetime.now(UTC)
    return MAARunResult(
        MAARunStatus.FAILED if error else MAARunStatus.COMPLETED,
        MAAErrorCode.PROCESS_EXIT_NONZERO if error else MAAErrorCode.OK,
        now,
        now,
        0,
        123,
        1 if error else 0,
        TerminationReason.NONZERO_EXIT if error else TerminationReason.NORMAL_EXIT,
        True,
        "",
        error,
        False,
        False,
    )


def config(tmp_path: Path) -> MAAConfig:
    return MAAConfig(
        executable=sys.executable,
        working_directory=str(tmp_path),
        arguments=("update",),
        environment_overrides=(("MAA_CACHE_DIR", str(tmp_path)),),
        timeout_seconds=5,
    )


def test_only_update_binding_retries(tmp_path: Path) -> None:
    factories = build_default_runtime_factories(AppConfig(maa=config(tmp_path), maa_update=MAAUpdateConfig(True, True)))
    assert type(factories.maa()) is MAAAdapter
    assert isinstance(factories.maa_update(), MAAUpdateAdapter)


def test_resume_progress_permits_more_than_five_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Deadline, CancellationToken]] = []
    partial = tmp_path / "package.zip.partial"
    token = CancellationToken()
    parent = Deadline.after(2)

    def run(self, deadline, cancel):
        calls.append((deadline, cancel))
        if len(calls) <= 7:
            with partial.open("ab") as f:
                f.write(b"downloaded bytes")
            return result(INTERRUPTED)
        return result()

    monkeypatch.setattr(MAAAdapter, "run", run)
    monkeypatch.setattr(runtime, "RETRY_DELAY_SECONDS", 0)
    final = MAAUpdateAdapter(config(tmp_path)).run(parent, token)
    assert final.status == MAARunStatus.COMPLETED
    assert final.diagnostics["update_attempts"] == 8
    assert partial.read_bytes() == b"downloaded bytes" * 7
    assert all(deadline is calls[0][0] and cancel is token for deadline, cancel in calls)
    assert calls[0][0].remaining_seconds <= parent.remaining_seconds + 0.01
    assert maa_output_diagnostics(final)["update_attempts"] == 8


def test_stalled_download_stops_and_reports_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MAAAdapter, "run", lambda *args: result(INTERRUPTED))
    monkeypatch.setattr(runtime, "RETRY_DELAY_SECONDS", 0)
    final = MAAUpdateAdapter(config(tmp_path)).run()
    assert final.status == MAARunStatus.FAILED
    assert final.diagnostics["update_attempts"] == 5
    assert maa_output_diagnostics(final)["failure_markers"] == ["core_install_failed", "download_interrupted"]


@pytest.mark.parametrize(
    "error",
    [
        "Failed to install MaaCore: Access is denied",
        "Failed to install MaaCore: Failed to extract archive",
        "Failed to pull resource repository: Peer disconnected",
        "Task failed: Peer disconnected",
    ],
)
def test_other_failures_are_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: str) -> None:
    monkeypatch.setattr(MAAAdapter, "run", lambda *args: result(error))
    final = MAAUpdateAdapter(config(tmp_path)).run()
    assert final.diagnostics["update_attempts"] == 1


def test_unclean_process_is_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MAAAdapter, "run", lambda *args: replace(result(INTERRUPTED), owned_process_cleaned=False))
    assert MAAUpdateAdapter(config(tmp_path)).run().diagnostics["update_attempts"] == 1


def test_cache_restarts_do_not_count_as_download_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    partial = tmp_path / "package.zip.partial"
    partial.write_bytes(b"1234567890")
    attempts = []

    def run(*args):
        attempts.append(1)
        partial.write_bytes(b"123" if len(attempts) % 2 else b"1234567890")
        return result(INTERRUPTED)

    monkeypatch.setattr(MAAAdapter, "run", run)
    monkeypatch.setattr(runtime, "RETRY_DELAY_SECONDS", 0)
    final = MAAUpdateAdapter(config(tmp_path)).run()
    assert final.diagnostics["update_attempts"] == 5


def test_total_attempt_limit_applies_even_with_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    partial = tmp_path / "package.zip.partial"

    def run(*args):
        with partial.open("ab") as f:
            f.write(b"1")
        return result(INTERRUPTED)

    monkeypatch.setattr(MAAAdapter, "run", run)
    monkeypatch.setattr(runtime, "RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(runtime, "MAX_UPDATE_ATTEMPTS", 3)
    final = MAAUpdateAdapter(config(tmp_path)).run()
    assert final.diagnostics["update_attempts"] == 3
    assert partial.read_bytes() == b"111"


@pytest.mark.parametrize("cancelled", [False, True])
def test_deadline_and_cancellation_interrupt_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancelled: bool,
) -> None:
    script = tmp_path / "interrupt.py"
    launches = tmp_path / "launches"
    script.write_text(
        "from pathlib import Path\n"
        f"p=Path({str(launches)!r})\n"
        "p.write_text(p.read_text()+'x' if p.exists() else 'x')\n"
        f"raise SystemExit({INTERRUPTED!r})\n",
        encoding="utf-8",
    )
    adapter = MAAUpdateAdapter(replace(config(tmp_path), arguments=(str(script),)))
    token = CancellationToken()
    original = MAAAdapter.run

    def run(self, deadline, cancel):
        value = original(self, deadline, cancel)
        if cancelled and launches.exists():
            threading.Timer(0.02, token.cancel).start()
        return value

    monkeypatch.setattr(MAAAdapter, "run", run)
    started = time.monotonic()
    final = adapter.run(Deadline.after(3 if cancelled else 0.5), token)
    assert final.status == (MAARunStatus.CANCELLED if cancelled else MAARunStatus.TIMEOUT)
    assert launches.read_text() == "x"
    assert time.monotonic() - started < 2
    assert final.duration_ms >= 15
