"""OrchestratoRRR run-scoped completion reporter (ORR private MaaFgo distribution only).

Installed by the ORR assembler in place of the upstream BBC stop listener
(transform id ``orr-bbc-free-native-reporter``). It uses the same official
``AgentServer.tasker_sink()`` API to observe per-task notifications and writes
a bounded, run-scoped, machine-readable completion artifact:

    {
      "schema_version": 1,
      "run_id": "...",            # ORR-generated UUID4 (env)
      "plan_digest": "...",       # sha256 of the expected-tasks payload (env)
      "outcome": "success" | "failed" | "incomplete",
      "tasks": [{"name": ..., "entry": ..., "terminal": "pending"|"success"|"failed"}],
      "unexpected_entries": [...],
      "stop_signal_observed": true|false
    }

Every terminal update is persisted atomically (temp file + fsync + os.replace).
Failure dominates: once a task reports ``failed`` it stays ``failed``. The
reporter never kills processes, never touches the network and never reads
anything beyond the ORR-provided environment and the local project files.
"""

import atexit
import json
import os
import uuid
from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.event_sink import NotificationType
from maa.tasker import TaskerEventSink

_RESULT_PATH_ENV = "ORR_MAAFGO_RESULT_PATH"
_RUN_ID_ENV = "ORR_MAAFGO_RUN_ID"
_PLAN_DIGEST_ENV = "ORR_MAAFGO_PLAN_DIGEST"
_EXPECTED_TASKS_ENV = "ORR_MAAFGO_EXPECTED_TASKS_PATH"
_SCHEMA_VERSION_ENV = "ORR_MAAFGO_RESULT_SCHEMA_VERSION"

_SCHEMA_VERSION = 1
_MAX_TASK_NAME_CHARS = 200
_MAX_TASKS = 32
_MAX_UNEXPECTED = 16
_MAX_EXPECTED_FILE_BYTES = 64 * 1024
_MAX_PROFILE_FILE_BYTES = 1024 * 1024

# post_stop() posts an internal EmptyTask with this entry; it is not a
# business task and must never be recorded as one.
_INTERNAL_ENTRIES = ("MaaTaskerPostStop",)


def _clean(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_TASK_NAME_CHARS:
        return ""
    return value


def _expected_pairs_from_orr() -> list[tuple[str, str]]:
    path = os.environ.get(_EXPECTED_TASKS_ENV, "")
    if not path:
        return []
    raw = Path(path).read_bytes()[:_MAX_EXPECTED_FILE_BYTES]
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, list):
        raise ValueError("expected tasks must be a list")
    pairs: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("expected task must be an object")
        name, entry = _clean(item.get("name")), _clean(item.get("entry"))
        if not name or not entry:
            raise ValueError("expected task name/entry missing")
        pairs.append((name, entry))
    return pairs


def _interface_entry_map(root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    try:
        interface = json.loads((root / "interface.json").read_bytes()[:_MAX_PROFILE_FILE_BYTES].decode("utf-8-sig"))
    except (OSError, ValueError):
        return mapping
    tasks = interface.get("task") if isinstance(interface, dict) else None
    if not isinstance(tasks, list):
        return mapping
    for task in tasks:
        if isinstance(task, dict):
            name, entry = _clean(task.get("name")), _clean(task.get("entry"))
            if name:
                mapping.setdefault(name, entry or name)
    return mapping


def _expected_pairs_standalone(root: Path) -> list[tuple[str, str]]:
    """Manual ``MaaPiCli.exe -d`` runs: fall back to the local profile itself."""
    try:
        profile = json.loads(
            (root / "config" / "maa_pi_config.json").read_bytes()[:_MAX_PROFILE_FILE_BYTES].decode("utf-8-sig")
        )
    except (OSError, ValueError):
        return []
    tasks = profile.get("task") if isinstance(profile, dict) else None
    if not isinstance(tasks, list):
        return []
    mapping = _interface_entry_map(root)
    pairs: list[tuple[str, str]] = []
    for task in tasks:
        name = _clean(task.get("name")) if isinstance(task, dict) else ""
        if name:
            pairs.append((name, mapping.get(name, name)))
    return pairs


def build_reporter():
    result_path_value = os.environ.get(_RESULT_PATH_ENV, "")
    if not result_path_value:
        # Activated only inside the ORR contract; inert otherwise so plain
        # ``MaaPiCli.exe -d`` usage keeps upstream behaviour.
        return None

    project_root = Path(os.getcwd())
    try:
        pairs = _expected_pairs_from_orr() or _expected_pairs_standalone(project_root)
    except (OSError, ValueError) as error:
        print(f"[OrrReporter] expected task setup failed: {type(error).__name__}", flush=True)
        pairs = []
    if len(pairs) > _MAX_TASKS:
        pairs = pairs[:_MAX_TASKS]

    try:
        schema_version = int(os.environ.get(_SCHEMA_VERSION_ENV, str(_SCHEMA_VERSION)))
    except ValueError:
        schema_version = -1

    state = {
        "schema_version": schema_version,
        "run_id": os.environ.get(_RUN_ID_ENV, "standalone"),
        "plan_digest": os.environ.get(_PLAN_DIGEST_ENV, "standalone"),
        "tasks": [
            {"name": name, "entry": entry, "terminal": "pending"} for name, entry in pairs
        ],
        "unexpected_entries": [],
        "stop_signal_observed": False,
    }
    entry_to_index = {entry: index for index, (_, entry) in enumerate(pairs)}

    def persist() -> None:
        try:
            terminals = [task["terminal"] for task in state["tasks"]]
            if terminals and all(terminal == "success" for terminal in terminals):
                state["outcome"] = "success"
            elif any(terminal == "failed" for terminal in terminals):
                state["outcome"] = "failed"
            else:
                state["outcome"] = "incomplete"
            document = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
            target = Path(result_path_value)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + f".tmp-{uuid.uuid4().hex[:8]}")
            try:
                with temporary.open("wb") as stream:
                    stream.write(document.encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        except OSError as error:
            # A persist failure leaves the artifact stale; ORR fails closed on
            # a missing/stale artifact, so this is safe to swallow here.
            print(f"[OrrReporter] persist failed: {type(error).__name__}", flush=True)

    if result_path_value:
        atexit.register(persist)

    class OrrTaskerSink(TaskerEventSink):
        def on_tasker_task(self, tasker, noti_type, detail) -> None:
            try:
                entry = getattr(detail, "entry", "")
                if not entry:
                    return
                if entry in _INTERNAL_ENTRIES:
                    state["stop_signal_observed"] = True
                    persist()
                    return
                index = entry_to_index.get(entry)
                if index is None:
                    if len(state["unexpected_entries"]) < _MAX_UNEXPECTED:
                        state["unexpected_entries"].append(entry[:_MAX_TASK_NAME_CHARS])
                    persist()
                    return
                task = state["tasks"][index]
                if noti_type == NotificationType.Succeeded:
                    if task["terminal"] != "failed":
                        task["terminal"] = "success"
                elif noti_type == NotificationType.Failed:
                    # Failure dominates any earlier success.
                    task["terminal"] = "failed"
                elif noti_type == NotificationType.Starting:
                    pass
                persist()
            except Exception as error:  # never crash the agent from the sink
                print(f"[OrrReporter] sink error: {type(error).__name__}", flush=True)

    return OrrTaskerSink


_sink_class = build_reporter()
if _sink_class is not None:
    AgentServer.tasker_sink()(_sink_class)
