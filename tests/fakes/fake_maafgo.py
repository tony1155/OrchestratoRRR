"""No MaaFramework imports or real devices: invocation/Job regression fixture only.

Artifact modes emulate the ORR reporter contract (schema v1) under fault
injections; they never imply real business success.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def expected_pairs_from_env() -> list[dict[str, str]]:
    expected_path = os.environ.get("ORR_MAAFGO_EXPECTED_TASKS_PATH")
    if not expected_path:
        return []
    with Path(expected_path).open("rb") as stream:
        value = json.loads(stream.read().decode("utf-8"))
    return [{"name": item["name"], "entry": item["entry"]} for item in value]


def build_document(mode: str) -> dict[str, object]:
    run_id = os.environ.get("ORR_MAAFGO_RUN_ID", "standalone")
    plan_digest = os.environ.get("ORR_MAAFGO_PLAN_DIGEST", "standalone")
    pairs = expected_pairs_from_env()
    terminals = ["success"] * len(pairs)
    unexpected: list[str] = []
    if mode == "artifact-incomplete":
        if terminals:
            terminals[-1] = "pending"
    elif mode == "artifact-task-failed":
        if terminals:
            terminals[0] = "failed"
    elif mode == "artifact-unexpected-entry":
        unexpected = ["UnexpectedEntry"]
    tasks = [
        {"name": pair["name"], "entry": pair["entry"], "terminal": terminal}
        for pair, terminal in zip(pairs, terminals, strict=True)
    ]
    if mode == "artifact-missing-task" and tasks:
        tasks = tasks[:-1]
    if mode == "artifact-duplicate-task" and tasks:
        tasks = tasks + [dict(tasks[0])]
    if mode == "artifact-unknown-task":
        tasks = tasks + [{"name": "Unknown", "entry": "Unknown", "terminal": "success"}]
    if mode == "artifact-entry-drift" and tasks:
        tasks[0] = {**tasks[0], "entry": "Wrong" + str(tasks[0]["entry"])}
    failed = any(task["terminal"] == "failed" for task in tasks)
    pending = any(task["terminal"] == "pending" for task in tasks)
    outcome = "failed" if failed else ("incomplete" if pending else "success")
    return {
        "schema_version": 1,
        "run_id": "00000000-0000-4000-8000-000000000000" if mode == "artifact-wrong-run-id" else run_id,
        "plan_digest": "0" * 64 if mode == "artifact-wrong-digest" else plan_digest,
        "outcome": outcome,
        "tasks": tasks,
        "unexpected_entries": unexpected,
        "stop_signal_observed": False,
    }


def write_result(mode: str) -> None:
    result_path = os.environ.get("ORR_MAAFGO_RESULT_PATH")
    if not result_path:
        return
    document = build_document(mode)
    path = Path(result_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", action="store_true", required=True)
    parser.add_argument("--mode", default=os.environ.get("FAKE_MAAFGO_MODE", "zero"))
    parser.add_argument("--pid-dir", type=Path, required=True)
    args = parser.parse_args()
    mode = args.mode
    (args.pid_dir / ("child.pid" if mode == "child" else "parent.pid")).write_text(str(os.getpid()))
    if mode.startswith("artifact-"):
        if mode == "artifact-malformed":
            result_path = os.environ.get("ORR_MAAFGO_RESULT_PATH")
            if result_path:
                Path(result_path).write_bytes(b"{not-json")
        elif mode in ("artifact-ok-then-hang", "artifact-ok-then-signal"):
            write_result("artifact-ok")
            while True:
                time.sleep(0.05)
        elif mode == "artifact-missing":
            pass
        else:
            write_result(mode)
        return 0
    if mode == "nonzero":
        return 7
    if mode == "output":
        print(str(args.pid_dir) + " private stdout " + "x" * 100000, flush=True)
        print(str(args.pid_dir) + " private stderr " + "y" * 100000, file=sys.stderr, flush=True)
    if mode in ("spawn", "spawn_exit", "spawn_nonzero"):
        subprocess.Popen([sys.executable, __file__, "-d", "--mode", "child", "--pid-dir", str(args.pid_dir)])
        end = time.monotonic() + 5
        while not (args.pid_dir / "child.pid").exists():
            if time.monotonic() >= end:
                return 8
            time.sleep(0.01)
        if mode == "spawn_exit":
            return 0
        if mode == "spawn_nonzero":
            return 7
    if mode in ("hang", "spawn", "child"):
        while True:
            time.sleep(0.05)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
