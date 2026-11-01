"""Synthetic PI project; none of these executable placeholders are runnable."""

import json
from pathlib import Path

from autogame_orchestrator.maafgo_config import ORR_PINNED_FGO_COMMIT, ORR_TRANSFORM_ID, MaaFgoConfig

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


def write_manifest(root: Path, **overrides: object) -> None:
    manifest = {
        "schema_version": 1,
        "maafgo_commit": ORR_PINNED_FGO_COMMIT,
        "orr_transform": {
            "transform_id": ORR_TRANSFORM_ID,
            "transform_version": 1,
            "bbc_listener_registered": False,
            "reporter_registered": True,
        },
    }
    manifest.update(overrides)
    (root / "distribution-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def make_native_project(root: Path, *, tasks: list[dict[str, object]] | None = None) -> MaaFgoConfig:
    """Production-shape BBC-free project: 登录 + 日常战斗(native)，import 链提供 entry。"""
    config = make_project(root)
    (root / "interface.json").write_text(
        json.dumps(
            {
                "interface_version": 2,
                "name": "MaaFgo",
                "controller": [{"name": "Synthetic Adb", "type": "Adb"}],
                "resource": [{"name": "synthetic", "path": ["resource"]}],
                "import": ["tasks/login.json", "tasks/daily.json"],
            }
        ),
        encoding="utf-8",
    )
    (root / "tasks").mkdir()
    (root / "tasks" / "login.json").write_text(
        json.dumps({"task": [{"name": "登录", "entry": "登录识别"}]}), encoding="utf-8"
    )
    (root / "tasks" / "daily.json").write_text(
        json.dumps({"task": [{"name": "日常战斗", "entry": "日常战斗"}]}), encoding="utf-8"
    )
    if tasks is None:
        tasks = [
            {"name": "登录", "option": []},
            {
                "name": "日常战斗",
                "option": [{"name": "chapter", "value": " seed"}, {"name": "battle_mode", "value": "native"}],
            },
        ]
    (root / "config" / "maa_pi_config.json").write_text(
        json.dumps(
            {
                "controller": {"name": "Synthetic Adb"},
                "adb": {"name": f"{SERIAL}-{root / 'adb.exe'}", "adb_path": str(root / "adb.exe"), "address": SERIAL},
                "resource": "synthetic",
                "task": tasks,
            }
        ),
        encoding="utf-8",
    )
    write_manifest(root)
    return config
