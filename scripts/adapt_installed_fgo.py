"""Adapt the verified local MaaFgo v2.0.17 entry to the ORR completion contract.

Keeps upstream battle logic and GUI behaviour. ORR runs omit BBC process
handlers and register the result reporter. Backs up every changed file.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from autogame_orchestrator.maafgo_config import INSTALLED_RUNTIME_FILES, INSTALLED_RUNTIME_VERSION


def compatible_scan_select(name: str, definition: dict, filenames: list[str]) -> dict:
    """Expand MXU's scan_select extension into standard PI select cases."""

    def replace_value(value, selected):
        if isinstance(value, dict):
            return {
                key: selected if key == name and item in ("", "{" + name + "}") else replace_value(item, selected)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [replace_value(item, selected) for item in value]
        if isinstance(value, str):
            return value.replace("{" + name + "}", selected)
        return value

    result = copy.deepcopy(definition)
    result["type"] = "select"
    template = result.pop("pipeline_override", {})
    choices = sorted(filenames)
    result["cases"] = [
        {"name": filename, "pipeline_override": replace_value(template, filename)} for filename in choices
    ] or [{"name": "__orr_no_file__", "label": "无可用文件", "pipeline_override": replace_value(template, "")}]
    default = definition.get("default", "")
    result["default_case"] = default if default in choices else result["cases"][0]["name"]
    return result


def compatible_option_files(root: Path, *, scan_root: Path | None = None) -> dict[Path, bytes]:
    result = {}
    for path in sorted((root / "options").rglob("*.json")):
        document = json.loads(path.read_text("utf-8-sig"))
        changed = False
        for name, definition in document.get("option", {}).items():
            if definition.get("type") != "scan_select":
                continue
            directory = ((scan_root or root) / definition["scan_dir"]).resolve()
            if not directory.is_relative_to((scan_root or root).resolve()):
                raise ValueError("scan_select directory leaves the project")
            filenames = [p.name for p in directory.glob(definition.get("scan_filter", "*")) if p.is_file()]
            document["option"][name] = compatible_scan_select(name, definition, filenames)
            changed = True
        if changed:
            result[path.relative_to(root)] = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return result


def reporting_task_files(root: Path) -> tuple[dict[Path, bytes], dict]:
    files = {}
    pipeline = {}
    for path in sorted((root / "tasks").glob("*.json")):
        document = json.loads(path.read_text("utf-8-sig"))
        changed = False
        for task in document.get("task", []):
            name = task["name"]
            original = task.get("orr_original_entry", task.get("entry", name))
            task["orr_original_entry"] = original
            task["entry"] = reported = "ORR_" + name
            pipeline[reported] = {
                "action": {
                    "type": "Custom",
                    "param": {
                        "custom_action": "orr_run_task",
                        "custom_action_param": {"original_entry": original, "report_entry": reported},
                    },
                },
                "on_error": [],
            }
            changed = True
        if changed:
            files[path.relative_to(root)] = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return files, pipeline


def resource_completion_overlay(root: Path) -> dict:
    """Catch explicit resource-exhaustion dialogs along AP-aware battle branches."""
    pipeline = root / "resource/base/pipeline"
    dummy = json.loads((pipeline / "Dummy.json").read_text("utf-8-sig"))
    overlay = {}
    triggers = {"全局-战前吃体力", "风暴罐副本-体力不足", "戴冠战-体力不足"}
    for path in sorted(pipeline.glob("*.json")):
        document = json.loads(path.read_text("utf-8-sig"))
        for name, node in document.items():
            following = node.get("next", [])
            if any(item.removeprefix("[JumpBack]") in triggers for item in following):
                # Use terminal successors: a resource shortage ends this task,
                # rather than returning to a parent which may start battle.
                overlay[name] = {
                    **node,
                    "next": [
                        "风暴罐不足",
                        "风暴罐不足2",
                        *[item for item in following if item not in {"风暴罐不足", "风暴罐不足2"}],
                    ],
                }
    for name in ("风暴罐不足", "风暴罐不足2"):
        overlay[name] = {**dummy[name], "next": ["ORR-资源耗尽完成"]}
    # The upstream OCR fallback also matches the bare label on the map. Only
    # an explicit shortage message is a completion signal.
    overlay["风暴罐不足2"]["recognition"] = {"type": "OCR", "param": {"expected": [r"风暴罐\s*不足"]}}
    overlay["ORR-资源耗尽完成"] = {
        "action": {"type": "StopTask"},
        "focus": {"Node.Action.Succeeded": "风暴罐不足，本次战斗任务正常结束"},
    }
    return overlay


def adapt_main(source: str) -> str:
    root_line = "AGENT_ROOT = os.path.dirname(os.path.abspath(__file__))"
    root_import = "if AGENT_ROOT not in sys.path:\n    sys.path.insert(0, AGENT_ROOT)"
    if root_line in source and root_import not in source:
        source = source.replace(root_line, root_line + "\n" + root_import, 1)
    # GUI task entries also use the reporting action; without an ORR contract
    # its persistence is inert and it just runs the upstream entry.
    if "import mfaalog\n" in source and "import mfaalog\nimport orr_reporter\n" not in source:
        source = source.replace("import mfaalog\n", "import mfaalog\nimport orr_reporter\n", 1)
    marker = "# ORR installed-runtime integration v1"
    if marker in source:
        return source
    block = """    import bbc_action
    import bbc_start
    import bbc_stop
    import bbc_stop_listener
"""
    if source.count(block) != 1 or source.count("if not IS_ANDROID:\n") != 1:
        raise ValueError("Unexpected upstream agent entry; no files changed")
    replacement = """    # ORR installed-runtime integration v1
    if not os.environ.get("ORR_MAAFGO_RUN_ID"):
        import bbc_action
        import bbc_start
        import bbc_stop
        import bbc_stop_listener
    else:
        import orr_reporter
"""
    result = source.replace(block, replacement)
    ast.parse(result)
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    interface = json.loads((root / "interface.json").read_text("utf-8-sig"))
    if interface.get("version") != INSTALLED_RUNTIME_VERSION or interface.get("agent") != {
        "child_exec": "./python/python.exe",
        "child_args": ["-u", "./agent/main.py"],
    }:
        raise ValueError("Expected the locally validated v2.0.17 embedded-Python installation")
    entry = root / "agent/main.py"
    original = entry.read_text("utf-8-sig")
    adapted = adapt_main(original)
    reporter = Path(__file__).parent / "maafgo-orr-agent/orr_reporter.py"
    overlay = resource_completion_overlay(root)
    option_files = compatible_option_files(root)
    task_files, task_pipeline = reporting_task_files(root)
    option_files.update(task_files)
    task_pipeline_name = "resource/base/pipeline/orr-task-reporting.json"
    # Validate all expected inputs before changing the installation.
    overlay_name = "resource/orr-workflow/pipeline/resource-completion.json"
    for name in INSTALLED_RUNTIME_FILES - {
        "agent/orr_reporter.py",
        "agent/orr_cli_runner.py",
        overlay_name,
        task_pipeline_name,
    }:
        if not (root / name).is_file():
            raise ValueError(f"Missing runtime file: {name}")
    backup = root.parent / "_config-backups" / ("fgo-workflow-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup.mkdir(parents=True, exist_ok=False)
    for name in (
        "agent/main.py",
        "agent/orr_reporter.py",
        "agent/orr_cli_runner.py",
        "distribution-manifest.json",
        "interface.json",
        overlay_name,
        task_pipeline_name,
        *[str(path) for path in option_files],
    ):
        if (root / name).is_file():
            (backup / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, backup / name)
    entry.write_bytes(adapted.encode("utf-8"))
    shutil.copyfile(reporter, root / "agent/orr_reporter.py")
    shutil.copyfile(reporter.with_name("orr_cli_runner.py"), root / "agent/orr_cli_runner.py")
    for relative, content in option_files.items():
        (root / relative).write_bytes(content)
    # Prevent the GUI updater from replacing the private CLI integration again.
    interface.pop("mirrorchyan_rid", None)
    for resource in interface["resource"]:
        if "resource/cn" in resource["path"] and "resource/orr-workflow" not in resource["path"]:
            resource["path"].append("resource/orr-workflow")
    (root / overlay_name).parent.mkdir(parents=True, exist_ok=True)
    (root / overlay_name).write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (root / task_pipeline_name).write_text(json.dumps(task_pipeline, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (root / "interface.json").write_text(json.dumps(interface, ensure_ascii=False, indent=2) + "\n", "utf-8")
    manifest = {
        "schema_version": 2,
        "source_kind": "installed-runtime",
        "maafgo_version": interface["version"],
        "upstream_agent_source_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
        "backup_directory": str(backup),
        "note": "Local integration; does not claim the original assembler's pinned source identity.",
        "guarded_files": {name: sha256(root / name) for name in sorted(INSTALLED_RUNTIME_FILES)},
    }
    (root / "distribution-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    print(f"Installed-runtime integration prepared. Backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
