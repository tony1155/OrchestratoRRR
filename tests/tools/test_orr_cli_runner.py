import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

RUNNER = Path(__file__).parents[2] / "scripts/maafgo-orr-agent/orr_cli_runner.py"


@pytest.mark.parametrize("address,expected", [("127.0.0.1:16384", 0), ("127.0.0.1:16385", 2)])
def test_real_identity_required_and_interactive_stdin_is_closed(tmp_path, monkeypatch, address, expected):
    spec = importlib.util.spec_from_file_location("orr_cli_runner", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/maa_pi_config.json").write_text(
        json.dumps({"adb": {"name": "configured-device", "adb_path": "adb.exe", "address": "127.0.0.1:16384"}}), "utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORR_MAAFGO_RESULT_PATH", str(tmp_path / "result.json"))
    toolkit = ModuleType("maa.toolkit")
    toolkit.Toolkit = SimpleNamespace(
        find_adb_devices=lambda: [SimpleNamespace(name="configured-device", adb_path=Path("adb.exe"), address=address)]
    )
    monkeypatch.setitem(sys.modules, "maa", ModuleType("maa"))
    monkeypatch.setitem(sys.modules, "maa.toolkit", toolkit)
    calls = []

    def popen(args, **kwargs):
        calls.append(args)
        assert kwargs["stdin"] == subprocess.DEVNULL
        return SimpleNamespace(
            stdout=io.BufferedReader(io.BytesIO(b"test stdout")),
            stderr=io.BufferedReader(io.BytesIO(b"test stderr")),
            poll=lambda: 0,
            returncode=0,
        )

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    assert module.run() == expected
    assert bool(calls) is (expected == 0)
    for handler in module.logging.getLogger("orr-cli").handlers[:]:
        handler.close()
        module.logging.getLogger("orr-cli").removeHandler(handler)
    text = (tmp_path / "maafgo-cli.log").read_text("utf-8")
    assert ("test stdout" in text) is (expected == 0)
