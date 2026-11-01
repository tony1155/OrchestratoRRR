"""Read MXU selections and atomically prepare the MaaPiCli profile."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from autogame_orchestrator.maafgo_config import (
    MAX_INTERFACE_BYTES,
    MAX_INTERFACE_IMPORT_FILES,
    MaaFgoConfig,
    MaaFgoConfigurationError,
    _read_object,
    normalize_adb_endpoint,
    validate_profile_tasks,
)


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MaaFgoConfigurationError()
    return value


def _names(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise MaaFgoConfigurationError()
    return value


def _interface(root: Path) -> dict[str, Any]:
    pending = [root / "interface.json"]
    seen: set[Path] = set()
    result: dict[str, Any] = {"task": [], "option": {}}
    while pending:
        path = pending.pop(0).resolve()
        if path in seen:
            continue
        if not path.is_relative_to(root.resolve()) or len(seen) >= MAX_INTERFACE_IMPORT_FILES:
            raise MaaFgoConfigurationError()
        seen.add(path)
        document = _read_object(path, max_bytes=MAX_INTERFACE_BYTES)
        for key, value in document.items():
            if key == "import":
                pending.extend(root / name for name in _names(value))
            elif key == "task":
                if not isinstance(value, list):
                    raise MaaFgoConfigurationError()
                result[key].extend(value)
            elif key == "option":
                result[key].update(_object(value))
            else:
                result[key] = value
    return result


def _options(keys: list[str], saved: dict[str, Any], definitions: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    visited: set[str] = set()
    pending = list(keys)
    while pending:
        name = pending.pop(0)
        if name in visited:
            continue
        visited.add(name)
        definition = _object(definitions.get(name))
        kind = definition.get("type", "select")
        value = _object(saved.get(name, {}))
        cases = definition.get("cases", [])
        converted: dict[str, Any] = {"name": name}
        selected: list[str] = []
        if kind in {"select", "switch"}:
            if not isinstance(cases, list) or not cases:
                raise MaaFgoConfigurationError()
            case_names = [str(_object(case)["name"]) for case in cases]
            if kind == "switch" and value:
                state = value.get("value")
                if type(state) is not bool:
                    raise MaaFgoConfigurationError()
                accepted = {"Yes", "yes", "Y", "y"} if state else {"No", "no", "N", "n"}
                choice = next((case for case in case_names if case in accepted), None)
            else:
                choice = value.get("caseName", definition.get("default_case", case_names[0]))
            if choice not in case_names:
                raise MaaFgoConfigurationError()
            converted["value"] = choice
            selected = [choice]
        elif kind == "checkbox":
            selected = _names(value.get("caseNames", definition.get("default_case", [])))
            if any(choice not in [case["name"] for case in cases] for choice in selected):
                raise MaaFgoConfigurationError()
            converted["values"] = selected
        elif kind == "input":
            if value.get("encryptedValues"):
                raise MaaFgoConfigurationError()
            inputs = _object(value.get("values", {}))
            if any(not isinstance(v, str) for v in inputs.values()):
                raise MaaFgoConfigurationError()
            converted["inputs"] = {
                item["name"]: inputs.get(item["name"], str(item.get("default", "")))
                for item in definition.get("inputs", [])
            }
        else:
            raise MaaFgoConfigurationError()
        output.append(converted)
        for case in cases:
            if case["name"] in selected:
                pending.extend(_names(case.get("option", [])))
    return output


def sync_mxu_profile(config: MaaFgoConfig, *, adb_path: str, serial: str) -> bool:
    """GUI remains authoritative; invalid selections never overwrite the CLI profile."""
    if not config.gui_config_source:
        return False
    try:
        gui = _read_object(Path(config.gui_config_source))
        instances = gui.get("instances")
        if not isinstance(instances, list):
            raise MaaFgoConfigurationError()
        selected_id = config.gui_instance_id or gui.get("lastActiveInstanceId")
        choices = [v for v in instances if _object(v).get("id") == selected_id]
        if len(choices) != 1:
            raise MaaFgoConfigurationError()
        instance = _object(choices[0])
        interface = _interface(Path(config.working_directory))
        controller = instance.get("controllerName")
        resource = instance.get("resourceName")
        if not any(c.get("name") == controller and c.get("type") == "Adb" for c in interface["controller"]):
            raise MaaFgoConfigurationError()
        if not any(r.get("name") == resource for r in interface["resource"]):
            raise MaaFgoConfigurationError()
        device = _object(instance.get("savedDevice", {}))
        address = device.get("adbDeviceAddress")
        if address and normalize_adb_endpoint(address) != normalize_adb_endpoint(serial):
            raise MaaFgoConfigurationError()
        definitions = {t["name"]: t for t in interface["task"]}
        tasks = []
        for raw in instance["tasks"]:
            task = _object(raw)
            enabled = _object(task.get("enabledByController", {})).get(
                str(instance.get("controllerId", "")), task.get("enabled")
            )
            if type(enabled) is not bool:
                raise MaaFgoConfigurationError()
            if not enabled:
                continue
            name = task["taskName"]
            if name not in definitions:
                raise MaaFgoConfigurationError()
            options = _options(
                _names(definitions[name].get("option", [])), _object(task.get("optionValues", {})), interface["option"]
            )
            tasks.append({"name": name, "option": options})
        selected_resource = next(r for r in interface["resource"] if r.get("name") == resource)
        selected_controller = next(c for c in interface["controller"] if c.get("name") == controller)
        # MaaPiCli compares Toolkit's raw UTF-8 path strings, which use '/'.
        # Windows Path equality hides this difference, but the C++ comparison does not.
        cli_adb_path = Path(adb_path).as_posix()
        profile = {
            "controller": {"name": controller},
            "adb": {
                "name": device.get("adbDeviceName") or f"{serial}-{cli_adb_path}",
                "adb_path": cli_adb_path,
                "address": serial,
            },
            "resource": resource,
            "task": tasks,
            "global_option": _options(
                _names(interface.get("global_option", [])),
                _object(gui.get("globalOptionValues", {})),
                interface["option"],
            ),
            "resource_option": _options(
                _names(selected_resource.get("option", [])),
                _object(gui.get("globalOptionValues", {})),
                interface["option"],
            ),
            "controller_option": _options(
                _names(selected_controller.get("option", [])),
                _object(gui.get("globalOptionValues", {})),
                interface["option"],
            ),
        }
        validate_profile_tasks([(task["name"], task["option"]) for task in tasks])
        encoded = (json.dumps(profile, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        target = config.profile_path
        if target.is_file() and target.read_bytes() == encoded:
            config.check_profile(serial)
            config.check_profile_policy()
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".orr-profile-", dir=target.parent) as directory:
            staged = Path(directory) / "config"
            staged.mkdir()
            candidate = staged / "maa_pi_config.json"
            with candidate.open("wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if target.exists():
                backup = Path(directory) / "backup.json"
                backup.write_bytes(target.read_bytes())
                os.replace(backup, target.with_suffix(".json.bak"))
            os.replace(candidate, target)
        return True
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        raise MaaFgoConfigurationError() from exc
