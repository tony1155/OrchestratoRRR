from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import autogame_orchestrator.maa_sync.synchronizer as sync_module
from autogame_orchestrator.config_model import MAASyncConfig
from autogame_orchestrator.maa_sync.models import MAASyncErrorCode, MAASyncStatus
from autogame_orchestrator.maa_sync.synchronizer import MAASynchronizer
from autogame_orchestrator.process.cancellation import CancellationToken
from autogame_orchestrator.process.deadline import Deadline


def run(config: MAASyncConfig, deadline: Deadline | None = None, cancel: CancellationToken | None = None):
    return MAASynchronizer(config).run(deadline, cancel)


def test_disabled_completes_without_filesystem() -> None:
    result = run(MAASyncConfig())
    assert (result.status, result.error_code, result.enabled, result.changed) == (
        MAASyncStatus.COMPLETED,
        MAASyncErrorCode.OK,
        False,
        False,
    )


def test_invalid_configuration_is_structured() -> None:
    result = run(MAASyncConfig(enabled=True))
    assert (result.status, result.error_code) == (MAASyncStatus.FAILED, MAASyncErrorCode.INVALID_CONFIGURATION)


@pytest.mark.parametrize("missing", ["gui_settings_source", "gui_tasks_source"])
def test_missing_source_is_structured(sync_config: MAASyncConfig, missing: str) -> None:
    Path(getattr(sync_config, missing)).unlink()
    result = run(sync_config)
    assert result.error_code == MAASyncErrorCode.SOURCE_NOT_FOUND


@pytest.mark.parametrize("source", ["gui_settings_source", "gui_tasks_source"])
def test_source_too_large(sync_config: MAASyncConfig, source: str) -> None:
    Path(getattr(sync_config, source)).write_bytes(b"x" * 30)
    result = run(MAASyncConfig(**{**vars(sync_config), "max_source_bytes": 20}))
    assert result.error_code == MAASyncErrorCode.SOURCE_TOO_LARGE


def test_utf8_bom_is_supported(sync_config: MAASyncConfig) -> None:
    source = Path(sync_config.gui_settings_source)
    source.write_bytes(b"\xef\xbb\xbf" + source.read_bytes())
    assert run(sync_config).status == MAASyncStatus.COMPLETED


def test_invalid_utf8_is_rejected(sync_config: MAASyncConfig) -> None:
    Path(sync_config.gui_settings_source).write_bytes(b"\xff\xfe")
    assert run(sync_config).error_code == MAASyncErrorCode.SOURCE_PARSE_FAILED


@pytest.mark.parametrize("content", [b"{", b"[]", b"null", b"1", b'"text"'])
def test_invalid_json_or_top_level_is_rejected(sync_config: MAASyncConfig, content: bytes) -> None:
    Path(sync_config.gui_tasks_source).write_bytes(content)
    assert run(sync_config).error_code == MAASyncErrorCode.SOURCE_PARSE_FAILED


def test_both_targets_are_created(sync_config: MAASyncConfig) -> None:
    result = run(sync_config)
    assert result.status == MAASyncStatus.COMPLETED
    assert result.changed is True
    assert result.profile_written is True
    assert result.tasks_written is True
    assert Path(sync_config.cli_profile_destination).is_file()
    assert Path(sync_config.cli_tasks_destination).is_file()


def test_output_is_deterministic_utf8_with_newline(sync_config: MAASyncConfig) -> None:
    run(sync_config)
    for value in (sync_config.cli_profile_destination, sync_config.cli_tasks_destination):
        data = Path(value).read_bytes()
        assert data.endswith(b"\n")
        assert json.loads(data.decode("utf-8"))


def test_no_change_does_not_rewrite_or_backup(sync_config: MAASyncConfig) -> None:
    run(sync_config)
    profile = Path(sync_config.cli_profile_destination)
    tasks = Path(sync_config.cli_tasks_destination)
    profile_time = profile.stat().st_mtime_ns
    tasks_time = tasks.stat().st_mtime_ns
    result = run(sync_config)
    assert (result.changed, result.profile_written, result.tasks_written) == (False, False, False)
    assert profile.stat().st_mtime_ns == profile_time
    assert tasks.stat().st_mtime_ns == tasks_time
    assert not profile.with_name(profile.name + ".bak").exists()
    assert not tasks.with_name(tasks.name + ".bak").exists()


@pytest.mark.parametrize("target", ["cli_profile_destination", "cli_tasks_destination"])
def test_existing_target_gets_atomic_backup(sync_config: MAASyncConfig, target: str) -> None:
    path = Path(getattr(sync_config, target))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"old-bytes")
    result = run(sync_config)
    assert path.with_name(path.name + ".bak").read_bytes() == b"old-bytes"
    assert getattr(result, "profile_backup_written" if target.startswith("cli_profile") else "tasks_backup_written")


def test_backup_can_be_disabled(sync_config: MAASyncConfig) -> None:
    profile = Path(sync_config.cli_profile_destination)
    profile.parent.mkdir(parents=True)
    profile.write_bytes(b"old")
    config = MAASyncConfig(**{**vars(sync_config), "backup_enabled": False})
    assert run(config).status == MAASyncStatus.COMPLETED
    assert not profile.with_name(profile.name + ".bak").exists()


@pytest.mark.parametrize("target", ["cli_profile_destination", "cli_tasks_destination"])
def test_existing_target_over_limit_fails_before_replace(sync_config: MAASyncConfig, target: str) -> None:
    path = Path(getattr(sync_config, target))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"z" * 1000)
    config = MAASyncConfig(**{**vars(sync_config), "max_source_bytes": 500})
    result = run(config)
    assert result.error_code == MAASyncErrorCode.TARGET_PREPARE_FAILED
    assert path.read_bytes() == b"z" * 1000


def test_second_replace_failure_rolls_back_existing_profile(
    sync_config: MAASyncConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = Path(sync_config.cli_profile_destination)
    tasks = Path(sync_config.cli_tasks_destination)
    profile.parent.mkdir(parents=True)
    profile.write_bytes(b"old-profile")
    tasks.write_bytes(b"old-tasks")
    original = sync_module._replace_file

    def fail_tasks(source: Path, destination: Path) -> None:
        if destination == tasks:
            raise OSError("sensitive failure")
        original(source, destination)

    monkeypatch.setattr(sync_module, "_replace_file", fail_tasks)
    result = run(MAASyncConfig(**{**vars(sync_config), "backup_enabled": False}))
    assert result.error_code == MAASyncErrorCode.TARGET_WRITE_FAILED
    assert result.rollback_attempted is True and result.rollback_succeeded is True
    assert profile.read_bytes() == b"old-profile"
    assert tasks.read_bytes() == b"old-tasks"


def test_second_replace_failure_removes_new_profile(
    sync_config: MAASyncConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = Path(sync_config.cli_tasks_destination)
    original = sync_module._replace_file

    def fail_tasks(source: Path, destination: Path) -> None:
        if destination == tasks:
            raise OSError("failure")
        original(source, destination)

    monkeypatch.setattr(sync_module, "_replace_file", fail_tasks)
    result = run(MAASyncConfig(**{**vars(sync_config), "backup_enabled": False}))
    assert result.error_code == MAASyncErrorCode.TARGET_WRITE_FAILED
    assert not Path(sync_config.cli_profile_destination).exists()


def test_rollback_failure_is_distinct(sync_config: MAASyncConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = Path(sync_config.cli_profile_destination)
    tasks = Path(sync_config.cli_tasks_destination)
    profile.parent.mkdir(parents=True)
    profile.write_bytes(b"old-profile")
    tasks.write_bytes(b"old-tasks")
    original = sync_module._replace_file
    target_calls = 0

    def fail_write_and_rollback(source: Path, destination: Path) -> None:
        nonlocal target_calls
        if destination in {profile, tasks}:
            target_calls += 1
            if target_calls >= 2:
                raise OSError("failure")
        original(source, destination)

    monkeypatch.setattr(sync_module, "_replace_file", fail_write_and_rollback)
    result = run(MAASyncConfig(**{**vars(sync_config), "backup_enabled": False}))
    assert result.error_code == MAASyncErrorCode.ROLLBACK_FAILED
    assert result.rollback_attempted is True and result.rollback_succeeded is False


def test_temporary_files_are_cleaned_on_failure(sync_config: MAASyncConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync_module, "_replace_file", lambda _source, _destination: (_ for _ in ()).throw(OSError()))
    run(MAASyncConfig(**{**vars(sync_config), "backup_enabled": False}))
    output = Path(sync_config.cli_profile_destination).parent
    assert list(output.glob(".orchestratorrr-maa-sync-*.tmp")) == []


def test_start_pre_cancel(sync_config: MAASyncConfig) -> None:
    token = CancellationToken()
    token.cancel()
    result = run(sync_config, cancel=token)
    assert (result.status, result.error_code) == (MAASyncStatus.CANCELLED, MAASyncErrorCode.CANCELLED)
    assert not Path(sync_config.cli_profile_destination).exists()


def test_start_expired_deadline(sync_config: MAASyncConfig) -> None:
    result = run(sync_config, deadline=Deadline.at(time.monotonic() - 1))
    assert (result.status, result.error_code) == (MAASyncStatus.TIMEOUT, MAASyncErrorCode.PARENT_DEADLINE)


def test_cancel_after_first_replace_rolls_back(sync_config: MAASyncConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    token = CancellationToken()
    profile = Path(sync_config.cli_profile_destination)
    original = sync_module._replace_file

    def replace_then_cancel(source: Path, destination: Path) -> None:
        original(source, destination)
        if destination == profile:
            token.cancel()

    monkeypatch.setattr(sync_module, "_replace_file", replace_then_cancel)
    result = run(MAASyncConfig(**{**vars(sync_config), "backup_enabled": False}), cancel=token)
    assert result.status == MAASyncStatus.CANCELLED
    assert result.rollback_succeeded is True
    assert not profile.exists()


def test_deadline_after_first_replace_rolls_back(sync_config: MAASyncConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = Path(sync_config.cli_profile_destination)
    original = sync_module._replace_file
    deadline = Deadline.after(60)

    def replace_then_expire(source: Path, destination: Path) -> None:
        original(source, destination)
        if destination == profile:
            deadline._target = time.monotonic() - 1  # type: ignore[attr-defined]

    monkeypatch.setattr(sync_module, "_replace_file", replace_then_expire)
    result = run(MAASyncConfig(**{**vars(sync_config), "backup_enabled": False}), deadline=deadline)
    assert result.status == MAASyncStatus.TIMEOUT
    assert result.rollback_succeeded is True
    assert not profile.exists()


def test_write_path_uses_fsync(sync_config: MAASyncConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    original = sync_module.os.fsync

    def counted(fd: int) -> None:
        nonlocal calls
        calls += 1
        original(fd)

    monkeypatch.setattr(sync_module.os, "fsync", counted)
    assert run(sync_config).status == MAASyncStatus.COMPLETED
    assert calls >= 2


def test_result_contains_no_paths_or_values(sync_config: MAASyncConfig) -> None:
    encoded = repr(run(sync_config))
    for forbidden in (str(Path(sync_config.gui_settings_source).parent), "fictional-account", "fake-local-endpoint"):
        assert forbidden not in encoded


@pytest.mark.parametrize("cancel_after_read", [1, 2])
def test_cancel_after_source_read(
    sync_config: MAASyncConfig,
    monkeypatch: pytest.MonkeyPatch,
    cancel_after_read: int,
) -> None:
    token = CancellationToken()
    original = MAASynchronizer._read_source
    calls = 0

    def read_then_cancel(self: MAASynchronizer, path: Path):
        nonlocal calls
        value = original(self, path)
        calls += 1
        if calls == cancel_after_read:
            token.cancel()
        return value

    monkeypatch.setattr(MAASynchronizer, "_read_source", read_then_cancel)
    result = run(sync_config, cancel=token)
    assert result.status == MAASyncStatus.CANCELLED
    assert not Path(sync_config.cli_profile_destination).exists()


def test_cancel_after_transform(sync_config: MAASyncConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    token = CancellationToken()
    original = sync_module.transform_gui_configuration

    def transform_then_cancel(settings: object, tasks: object):
        value = original(settings, tasks)
        token.cancel()
        return value

    monkeypatch.setattr(sync_module, "transform_gui_configuration", transform_then_cancel)
    result = run(sync_config, cancel=token)
    assert result.status == MAASyncStatus.CANCELLED
    assert not Path(sync_config.cli_profile_destination).exists()


def test_deadline_after_source_read(sync_config: MAASyncConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    deadline = Deadline.after(60)
    original = MAASynchronizer._read_source

    def read_then_expire(self: MAASynchronizer, path: Path):
        value = original(self, path)
        deadline._target = time.monotonic() - 1  # type: ignore[attr-defined]
        return value

    monkeypatch.setattr(MAASynchronizer, "_read_source", read_then_expire)
    assert run(sync_config, deadline=deadline).status == MAASyncStatus.TIMEOUT


def test_transform_failure_does_not_touch_targets(sync_config: MAASyncConfig) -> None:
    profile = Path(sync_config.cli_profile_destination)
    tasks = Path(sync_config.cli_tasks_destination)
    profile.parent.mkdir(parents=True)
    profile.write_bytes(b"original-profile")
    tasks.write_bytes(b"original-tasks")
    source = Path(sync_config.gui_tasks_source)
    value = json.loads(source.read_text(encoding="utf-8"))
    value["Configurations"]["tasks"]["TaskQueue"] = [{"TaskType": "Unsupported", "IsEnable": True}]
    source.write_text(json.dumps(value), encoding="utf-8")
    result = run(sync_config)
    assert result.error_code == MAASyncErrorCode.TRANSFORM_FAILED
    assert profile.read_bytes() == b"original-profile"
    assert tasks.read_bytes() == b"original-tasks"


def test_backup_is_committed_with_replace(sync_config: MAASyncConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = Path(sync_config.cli_profile_destination)
    profile.parent.mkdir(parents=True)
    profile.write_bytes(b"old-profile")
    destinations: list[Path] = []
    original = sync_module._replace_file

    def record_replace(source: Path, destination: Path) -> None:
        destinations.append(destination)
        original(source, destination)

    monkeypatch.setattr(sync_module, "_replace_file", record_replace)
    assert run(sync_config).status == MAASyncStatus.COMPLETED
    assert profile.with_name(profile.name + ".bak") in destinations


def test_temporary_writes_flush_and_fsync(sync_config: MAASyncConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    original = sync_module._write_and_sync

    def record(stream, data: bytes) -> None:
        nonlocal calls
        calls += 1
        original(stream, data)

    monkeypatch.setattr(sync_module, "_write_and_sync", record)
    assert run(sync_config).status == MAASyncStatus.COMPLETED
    assert calls >= 2


def test_first_replace_failure_is_not_retried(sync_config: MAASyncConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fail_once(_source: Path, _destination: Path) -> None:
        nonlocal calls
        calls += 1
        raise OSError("sensitive details")

    monkeypatch.setattr(sync_module, "_replace_file", fail_once)
    result = run(MAASyncConfig(**{**vars(sync_config), "backup_enabled": False}))
    assert result.error_code == MAASyncErrorCode.TARGET_WRITE_FAILED
    assert calls == 1
