"""Synthetic PI project; none of these executable placeholders are runnable."""

import json
from pathlib import Path

from autogame_orchestrator.maafgo_config import MaaFgoConfig

SERIAL = "127.0.0.1:16384"


def make_project(root: Path) -> MaaFgoConfig:
    root.mkdir(parents=True, exist_ok=True)
    executable, adb = root / "MaaPiCli.exe", root / "adb.exe"
    executable.touch()
    adb.touch()
    (root / "interface.json").write_text(
        json.dumps(
            {
                "interface_version": 2,
                "name": "MaaFgo",
                "controller": [{"name": "Synthetic Adb", "type": "Adb"}],
                "resource": [{"name": "synthetic", "path": ["resource"]}],
            }
        ),
        encoding="utf-8",
    )
    (root / "config").mkdir()
    (root / "config" / "maa_pi_config.json").write_text(
        json.dumps(
            {
                "controller": {"name": "Synthetic Adb"},
                "adb": {"name": f"{SERIAL}-{adb}", "adb_path": str(adb), "address": SERIAL},
                "resource": "synthetic",
                "task": [{"name": "Synthetic task", "option": []}],
            }
        ),
        encoding="utf-8",
    )
    return MaaFgoConfig(True, str(executable), str(root), timeout_seconds=10, stop_timeout_seconds=2)
