from __future__ import annotations

import json
import signal
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from autogame_orchestrator.config_model import AALCConfig, MAAConfig, StarRailConfig
from autogame_orchestrator.diagnostics import adapter_smoke as smoke

NOW = datetime(2026, 7, 22, tzinfo=UTC)


def _result(adapter: str = "maa", status: str = "completed", error: str = "OK") -> SimpleNamespace:
    common = {
        "status": status,
        "error_code": error,
        "started_at": NOW,
        "finished_at": NOW,
        "exit_code": 0 if status == "completed" else 7,
        "owned_process_cleaned": error != "CLEANUP_FAILED",
    }
    if adapter == "starrail":
        return SimpleNamespace(
            **common,
            completion_mode="log_success",
            duration_ms=12,
            pid=123,
            matched_keyword="done",
            log_path="secret.log",
            stdout_excerpt="secret stdout",
            stderr_excerpt="secret stderr",
            stdout_truncated=False,
            stderr_truncated=True,
            diagnostics={"path": "secret"},
        )
    if adapter == "maa":
        return SimpleNamespace(
            **common,
            termination_reason="normal_exit",
            duration_ms=13,
            pid=456,
            stdout_excerpt="secret stdout",
            stderr_excerpt="secret stderr",
            stdout_truncated=True,
            stderr_truncated=False,
            diagnostics={"path": "secret"},
        )
    attempt = SimpleNamespace(
        attempt_number=1,
        status=status,
        error_code=error,
        exit_code=common["exit_code"],
        owned_process_cleaned=common["owned_process_cleaned"],
        duration_seconds=0.02,
        pid=789,
        stdout_excerpt="secret stdout",
        stderr_excerpt="secret stderr",
    )
    return SimpleNamespace(
        **common,
        completion_mode="normal_exit",
        duration_seconds=0.02,
        configured_attempts=1,
        attempts_started=1,
        successful_attempt_number=1 if status == "completed" else None,
        attempt_results=(attempt,),
        diagnostics={"path": "secret"},
    )


def _configs() -> SimpleNamespace:
    return SimpleNamespace(
        starrail=StarRailConfig(
            executable="starrail-secret.exe",
            working_directory="starrail-dir",
            arguments=("run",),
            log_path_template="logs/{date}.txt",
        ),
        maa=MAAConfig(executable="maa-secret.exe", working_directory="maa-dir"),
        aalc=AALCConfig(executable="aalc-secret.exe", working_directory="aalc-dir", attempts=3),
    )


def _args(tmp_path: Path, adapter: str = "maa") -> list[str]:
    return [
        "--adapter",
        adapter,
        "--config",
        str(tmp_path / "secret.local.toml"),
        "--deadline-seconds",
        "5",
        "--output",
        str(tmp_path / "result.json"),
        "--confirm-real-execution",
        smoke.CONFIRMATION,
    ]


def _prepare(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, adapter: str = "maa", status: str = "completed", error: str = "OK"
) -> dict[str, Any]:
    calls: dict[str, Any] = {"constructed": []}
    monkeypatch.setattr(smoke, "load_config", lambda path, check_paths=False: (_configs(), []))
    for cls in (StarRailConfig, MAAConfig, AALCConfig):
        monkeypatch.setattr(cls, "check_paths", lambda self: [])

    def adapter_class(name: str) -> type:
        class FakeAdapter:
            def __init__(self, config: object) -> None:
                calls["constructed"].append((name, config))

            def run(self, deadline: object, cancel: object) -> SimpleNamespace:
                calls["deadline"] = deadline
                calls["cancel"] = cancel
                return _result(name, status, error)

        return FakeAdapter

    monkeypatch.setattr(smoke, "StarRailAdapter", adapter_class("starrail"))
    monkeypatch.setattr(smoke, "MAAAdapter", adapter_class("maa"))
    monkeypatch.setattr(smoke, "AALCAdapter", adapter_class("aalc"))
    calls["args"] = _args(tmp_path, adapter)
    return calls


def _payload(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))


def test_requires_exact_confirmation(tmp_path: Path) -> None:
    args = _args(tmp_path)
    args[-1] = "wrong"
    assert smoke.main(args) == 2


def test_refusal_does_not_construct_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(smoke, "MAAAdapter", lambda config: pytest.fail("不应构造 Adapter"))
    assert smoke.main(_args(tmp_path)[:-2]) == 2


def test_requires_one_adapter(tmp_path: Path) -> None:
    assert smoke.main(_args(tmp_path)[2:]) == 2


def test_rejects_unknown_adapter(tmp_path: Path) -> None:
    assert smoke.main(_args(tmp_path, "unknown")) == 2


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_rejects_non_positive_deadline(tmp_path: Path, value: str) -> None:
    args = _args(tmp_path)
    args[5] = value
    assert smoke.main(args) == 2


def test_loads_config_without_global_path_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[bool] = []
    calls = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(
        smoke, "load_config", lambda path, check_paths=False: (seen.append(check_paths) or _configs(), [])
    )
    assert smoke.main(calls["args"]) == 0
    assert seen == [False]


@pytest.mark.parametrize(("adapter", "expected"), [("starrail", "starrail"), ("maa", "maa"), ("aalc", "aalc")])
def test_checks_only_selected_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, adapter: str, expected: str
) -> None:
    calls = _prepare(monkeypatch, tmp_path, adapter)
    checked: list[str] = []
    monkeypatch.setattr(StarRailConfig, "check_paths", lambda self: checked.append("starrail") or [])
    monkeypatch.setattr(MAAConfig, "check_paths", lambda self: checked.append("maa") or [])
    monkeypatch.setattr(AALCConfig, "check_paths", lambda self: checked.append("aalc") or [])
    assert smoke.main(calls["args"]) == 0
    assert checked == [expected]


def test_checks_only_selected_starrail_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_checks_only_selected_paths(monkeypatch, tmp_path, "starrail", "starrail")


def test_checks_only_selected_maa_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_checks_only_selected_paths(monkeypatch, tmp_path, "maa", "maa")


def test_checks_only_selected_aalc_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_checks_only_selected_paths(monkeypatch, tmp_path, "aalc", "aalc")


@pytest.mark.parametrize("adapter", ["starrail", "maa", "aalc"])
def test_selection_constructs_only_one_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, adapter: str) -> None:
    calls = _prepare(monkeypatch, tmp_path, adapter)
    assert smoke.main(calls["args"]) == 0
    assert [item[0] for item in calls["constructed"]] == [adapter]


def test_starrail_selection_does_not_construct_other_adapters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_selection_constructs_only_one_adapter(monkeypatch, tmp_path, "starrail")


def test_maa_selection_does_not_construct_other_adapters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_selection_constructs_only_one_adapter(monkeypatch, tmp_path, "maa")


def test_aalc_selection_does_not_construct_other_adapters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_selection_constructs_only_one_adapter(monkeypatch, tmp_path, "aalc")


def test_aalc_smoke_forces_one_attempt_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _prepare(monkeypatch, tmp_path, "aalc")
    original = _configs().aalc
    monkeypatch.setattr(
        smoke,
        "load_config",
        lambda path, check_paths=False: (
            SimpleNamespace(starrail=_configs().starrail, maa=_configs().maa, aalc=original),
            [],
        ),
    )
    assert smoke.main(calls["args"]) == 0
    assert calls["constructed"][0][1].attempts == 1
    assert original.attempts == 3


def test_aalc_retries_require_explicit_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _prepare(monkeypatch, tmp_path, "aalc")
    calls["args"].append("--allow-aalc-retries")
    assert smoke.main(calls["args"]) == 0
    assert calls["constructed"][0][1].attempts == 3


def test_sigint_sets_cancellation_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _prepare(monkeypatch, tmp_path)
    handlers: list[object] = []
    monkeypatch.setattr(signal, "getsignal", lambda sig: "original")
    monkeypatch.setattr(signal, "signal", lambda sig, handler: handlers.append(handler))

    class Adapter:
        def __init__(self, config: object) -> None:
            pass

        def run(self, deadline: object, cancel: object) -> SimpleNamespace:
            handlers[0](signal.SIGINT, None)
            assert cancel.is_cancelled
            return _result()

    monkeypatch.setattr(smoke, "MAAAdapter", Adapter)
    assert smoke.main(calls["args"]) == 0
    assert _payload(tmp_path)["cancel_requested"] is True


def test_signal_handler_is_restored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _prepare(monkeypatch, tmp_path)
    installed: list[object] = []
    monkeypatch.setattr(signal, "getsignal", lambda sig: "original")
    monkeypatch.setattr(signal, "signal", lambda sig, handler: installed.append(handler))
    assert smoke.main(calls["args"]) == 0
    assert installed[-1] == "original"


def test_passes_deadline_and_cancellation_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _prepare(monkeypatch, tmp_path)
    assert smoke.main(calls["args"]) == 0
    assert calls["deadline"].remaining_seconds > 0
    assert calls["cancel"].is_cancelled is False


@pytest.mark.parametrize(
    ("status", "error", "code"),
    [
        ("completed", "OK", 0),
        ("failed", "BAD", 3),
        ("timeout", "TIMEOUT", 4),
        ("cancelled", "CANCELLED", 5),
        ("timeout", "CLEANUP_FAILED", 6),
    ],
)
def test_status_exit_mapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str, error: str, code: int
) -> None:
    calls = _prepare(monkeypatch, tmp_path, status=status, error=error)
    assert smoke.main(calls["args"]) == code


def test_completed_maps_to_exit_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_status_exit_mapping(monkeypatch, tmp_path, "completed", "OK", 0)


def test_failed_maps_to_exit_three(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_status_exit_mapping(monkeypatch, tmp_path, "failed", "BAD", 3)


def test_timeout_maps_to_exit_four(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_status_exit_mapping(monkeypatch, tmp_path, "timeout", "TIMEOUT", 4)


def test_cancelled_maps_to_exit_five(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_status_exit_mapping(monkeypatch, tmp_path, "cancelled", "CANCELLED", 5)


def test_cleanup_failure_maps_to_exit_six(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_status_exit_mapping(monkeypatch, tmp_path, "timeout", "CLEANUP_FAILED", 6)


def test_output_write_failure_maps_to_exit_seven(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(smoke, "_atomic_write_json", lambda path, payload: (_ for _ in ()).throw(OSError()))
    assert smoke.main(calls["args"]) == 7


def test_result_file_is_atomic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _prepare(monkeypatch, tmp_path)
    replaced: list[tuple[Path, Path]] = []
    original = smoke.os.replace
    monkeypatch.setattr(
        smoke.os,
        "replace",
        lambda source, target: (replaced.append((Path(source), Path(target))), original(source, target))[1],
    )
    assert smoke.main(calls["args"]) == 0
    assert replaced and replaced[0][1] == tmp_path / "result.json"
    assert not replaced[0][0].exists()


def test_result_is_json_serializable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _prepare(monkeypatch, tmp_path)
    assert smoke.main(calls["args"]) == 0
    json.dumps(_payload(tmp_path))


@pytest.mark.parametrize(
    "secret",
    ["secret.local.toml", "maa-secret.exe", "maa-dir", "secret stdout", "secret stderr", "456", "orchestratorrr-maa-"],
)
def test_result_omits_sensitive_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, secret: str) -> None:
    calls = _prepare(monkeypatch, tmp_path)
    assert smoke.main(calls["args"]) == 0
    assert secret not in json.dumps(_payload(tmp_path))


def test_result_omits_config_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_result_omits_sensitive_values(monkeypatch, tmp_path, "secret.local.toml")


def test_result_omits_executable_and_working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_result_omits_sensitive_values(monkeypatch, tmp_path, "maa-secret.exe")
    assert "maa-dir" not in json.dumps(_payload(tmp_path))


def test_result_omits_environment_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _prepare(monkeypatch, tmp_path)
    assert smoke.main(calls["args"]) == 0
    assert "environment" not in json.dumps(_payload(tmp_path)).lower()


def test_result_omits_stdout_and_stderr_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_result_omits_sensitive_values(monkeypatch, tmp_path, "secret stdout")
    assert "secret stderr" not in json.dumps(_payload(tmp_path))


def test_result_omits_pid_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_result_omits_sensitive_values(monkeypatch, tmp_path, "456")


def test_result_omits_temp_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_result_omits_sensitive_values(monkeypatch, tmp_path, "orchestratorrr-maa-")


@pytest.mark.parametrize("adapter", ["starrail", "maa", "aalc"])
def test_result_projection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, adapter: str) -> None:
    calls = _prepare(monkeypatch, tmp_path, adapter)
    assert smoke.main(calls["args"]) == 0
    payload = _payload(tmp_path)
    assert payload["adapter"] == adapter
    assert payload["schema_version"] == 1
    if adapter == "starrail":
        assert payload["matched_keyword"] == "done"
    if adapter == "maa":
        assert payload["pid_present"] is True
    if adapter == "aalc":
        assert payload["attempts"][0]["attempt_number"] == 1


def test_starrail_result_projection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_result_projection(monkeypatch, tmp_path, "starrail")


def test_maa_result_projection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_result_projection(monkeypatch, tmp_path, "maa")


def test_aalc_result_projection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    test_result_projection(monkeypatch, tmp_path, "aalc")
