import json
import sys
from dataclasses import replace

import pytest

from autogame_orchestrator.maafgo_config import (
    MAX_CONFIG_BYTES,
    MaaFgoConfig,
    MaaFgoConfigurationError,
    normalize_adb_endpoint,
    read_adb_identity,
)
from autogame_orchestrator.runtime.maafgo_models import MaaFgoErrorCode as Code
from tests.fakes.maafgo_support import SERIAL, make_project


@pytest.fixture
def config(tmp_path):
    return make_project(tmp_path / "project with spaces")


def test_disabled_needs_no_paths():
    assert MaaFgoConfig().validate() == []
    assert MaaFgoConfig().check_paths() == []
    assert MaaFgoConfig().arguments == ("-d",)


@pytest.mark.parametrize("field", ["timeout_seconds", "stop_timeout_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "20", None])
def test_strict_timeouts(field, value):
    assert replace(MaaFgoConfig(), **{field: value}).validate() == [Code.INVALID_CONFIGURATION]


@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": 1},
        {"executable": "MaaPiCli.exe"},
        {"working_directory": "."},
        {"executable": None},
        {"working_directory": None},
        {"executable": "C:\\Bad\nMaaPiCli.exe"},
    ],
)
def test_invalid_values(config, changes):
    assert replace(config, **changes).validate() == [Code.INVALID_CONFIGURATION]


def test_wrong_name_and_separate_directory(config, tmp_path):
    assert replace(config, executable=str(tmp_path / "MaaFgo.exe")).validate()
    assert replace(config, working_directory=str(tmp_path)).validate()


@pytest.mark.parametrize(
    "relative,code",
    [
        ("MaaPiCli.exe", Code.EXECUTABLE_NOT_FOUND),
        ("interface.json", Code.PROJECT_INTERFACE_NOT_FOUND),
        ("config/maa_pi_config.json", Code.PROFILE_NOT_FOUND),
    ],
)
@pytest.mark.parametrize("as_directory", [False, True])
def test_missing_files(config, relative, code, as_directory):
    from pathlib import Path

    path = Path(config.working_directory) / relative
    path.unlink()
    if as_directory:
        path.mkdir()
    assert config.check_paths() == [code]


def test_missing_working_directory(tmp_path):
    root = tmp_path / "missing"
    config = MaaFgoConfig(True, str(root / "MaaPiCli.exe"), str(root))
    assert config.check_paths() == [Code.WORKING_DIRECTORY_NOT_FOUND]


def test_windows_only(config, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert config.validate() == [Code.UNSUPPORTED_PLATFORM]
    assert MaaFgoConfig().validate() == []


def test_identity_and_read_only(config):
    before = [(p, p.read_bytes(), p.stat().st_mtime_ns) for p in (config.interface_path, config.profile_path)]
    assert read_adb_identity(config.profile_path).address == SERIAL
    config.check_profile(SERIAL)
    for path, content, mtime in before:
        assert path.read_bytes() == content
        assert path.stat().st_mtime_ns == mtime


def test_endpoint_mismatch(config):
    with pytest.raises(MaaFgoConfigurationError) as exc:
        config.check_profile("127.0.0.1:16416")
    assert exc.value.code == Code.ADB_CONFIGURATION_MISMATCH


@pytest.mark.parametrize(
    "value",
    [
        "localhost:16384",
        "127.0.0.2:16384",
        "192.168.1.2:16384",
        "[::1]:16384",
        "emulator-5554",
        "127.0.0.1:0",
        "127.0.0.1:65536",
        "127.0.0.1:016384",
        "127.0.0.1:+16384",
        " 127.0.0.1:16384",
        "127.0.0.1:16384\n",
        "127.0.0.1:16384:1",
        "127.0.0.1:１２３",
        None,
    ],
)
def test_endpoint_rejects_ambiguous_forms(value):
    with pytest.raises(MaaFgoConfigurationError):
        normalize_adb_endpoint(value)


@pytest.mark.parametrize("port", [1, 16384, 65535])
def test_canonical_endpoint(port):
    serial = f"127.0.0.1:{port}"
    assert normalize_adb_endpoint(serial) == serial


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        "null",
        "{",
        '{"controller":{},"controller":{}}',
        '{"a":NaN}',
        "x" * (MAX_CONFIG_BYTES + 1),
        "[" * 2000 + "]" * 2000,
    ],
    ids=["array", "null", "syntax", "duplicate", "nan", "oversize", "deep"],
)
def test_malformed_profile(config, content):
    config.profile_path.write_text(content, encoding="utf-8")
    with pytest.raises(MaaFgoConfigurationError):
        config.check_profile(SERIAL)


@pytest.mark.parametrize(
    "field,value",
    [
        ("adb", {}),
        ("controller", {"name": "other"}),
        ("task", []),
        ("task", ["task"]),
        ("resource", None),
    ],
)
def test_wrong_profile_shape(config, field, value):
    data = json.loads(config.profile_path.read_text())
    data[field] = value
    config.profile_path.write_text(json.dumps(data))
    with pytest.raises(MaaFgoConfigurationError):
        config.check_profile(SERIAL)


def test_auto_detect_profile_rejected_without_rewrite(config):
    data = json.loads(config.profile_path.read_text())
    data["adb"]["name"] = "MuMuPlayer12"
    config.profile_path.write_text(json.dumps(data))
    before = config.profile_path.read_bytes()
    with pytest.raises(MaaFgoConfigurationError) as exc:
        config.check_profile(SERIAL)
    assert exc.value.code == Code.ADB_AUTODETECT_UNSUPPORTED
    assert config.profile_path.read_bytes() == before


@pytest.mark.parametrize("field,value", [("type", "Win32"), ("permission_required", True), ("permission_required", 1)])
def test_controller_cannot_escape_job_via_elevation(config, field, value):
    data = json.loads(config.interface_path.read_text())
    data["controller"][0][field] = value
    config.interface_path.write_text(json.dumps(data))
    with pytest.raises(MaaFgoConfigurationError):
        config.check_profile(SERIAL)


def test_duplicate_controller_and_wrong_project(config):
    data = json.loads(config.interface_path.read_text())
    data["controller"] *= 2
    config.interface_path.write_text(json.dumps(data))
    with pytest.raises(MaaFgoConfigurationError):
        config.check_profile(SERIAL)
    data["name"] = "MAA"
    config.interface_path.write_text(json.dumps(data))
    with pytest.raises(MaaFgoConfigurationError):
        config.check_profile(SERIAL)


def test_missing_adb_binary(config):
    from pathlib import Path

    Path(read_adb_identity(config.profile_path).adb_path).unlink()
    with pytest.raises(MaaFgoConfigurationError):
        config.check_profile(SERIAL)
