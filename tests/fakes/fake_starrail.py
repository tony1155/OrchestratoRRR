"""伪造 StarRailCopilot——供集成测试使用。

通过 --mode 控制行为。生产代码不得导入。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_FAKE_CHILD = str(Path(__file__).resolve().with_name("fake_child.py"))


def _write_pid(path: str) -> None:
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(str(os.getpid()), encoding="utf-8")


def _append_log(path: str, text: str) -> None:
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
            f.flush()


def _write_capture(path: str, data: dict) -> None:
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mode", type=str, default="success_log")
    parser.add_argument("--log-file", type=str, default="")
    parser.add_argument("--pid-file", type=str, default="")
    parser.add_argument("--child-pid-file", type=str, default="")
    parser.add_argument("--capture-file", type=str, default="")
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    known_args, remaining = parser.parse_known_args()

    mode = known_args.mode
    log_file = known_args.log_file
    pid_file = known_args.pid_file
    child_pid = known_args.child_pid_file
    capture_file = known_args.capture_file

    _write_pid(pid_file)

    # capture
    _write_capture(
        capture_file,
        {
            "arguments": remaining,
            "working_directory": os.getcwd(),
            "python_io_encoding": os.environ.get("PYTHONIOENCODING", ""),
        },
    )

    if known_args.delay_seconds > 0:
        time.sleep(known_args.delay_seconds)

    if mode == "success_log":
        _append_log(log_file, "No task pending")
        while True:
            time.sleep(1.0)

    elif mode == "restart_success_log":
        _append_log(log_file, "for task `Restart`")
        while True:
            time.sleep(1.0)

    elif mode == "failure_log":
        _append_log(log_file, "ScriptError: fake failure")
        while True:
            time.sleep(1.0)

    elif mode == "both_keywords":
        _append_log(log_file, "No task pending\nScriptError: fake failure")
        while True:
            time.sleep(1.0)

    elif mode == "split_success":
        _append_log(log_file, "No task ")
        time.sleep(0.15)
        _append_log(log_file, "pending")
        while True:
            time.sleep(1.0)

    elif mode == "rotate_success":
        Path(log_file).write_text("[truncated old log]\n", encoding="utf-8")
        _append_log(log_file, "No task pending")
        while True:
            time.sleep(1.0)

    elif mode == "exit_zero":
        sys.exit(0)

    elif mode == "exit_nonzero":
        sys.exit(7)

    elif mode == "hang":
        while True:
            time.sleep(1.0)

    elif mode == "large_log":
        _append_log(log_file, "X" * 128 * 1024)
        while True:
            time.sleep(1.0)

    elif mode == "large_output_success":
        chunk = b"B" * 65536
        for _ in range(3):
            sys.stdout.buffer.write(chunk)
            sys.stderr.buffer.write(chunk)
        sys.stdout.buffer.flush()
        sys.stderr.buffer.flush()
        _append_log(log_file, "No task pending")
        while True:
            time.sleep(1.0)

    elif mode == "child_success":
        if child_pid:
            subprocess.Popen(
                [sys.executable, _FAKE_CHILD, "--pid-file", child_pid],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        _append_log(log_file, "No task pending")
        while True:
            time.sleep(1.0)

    else:
        _append_log(log_file, "No task pending")
        while True:
            time.sleep(1.0)


if __name__ == "__main__":
    main()
