"""Phase 5 AALC Adapter 使用的伪 CLI。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _write(path: str, text: str) -> None:
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def _next_attempt(state_file: str) -> int:
    if not state_file:
        return int(os.environ.get("AALC_ATTEMPT_NUMBER", "1"))
    path = Path(state_file)
    try:
        number = int(path.read_text(encoding="utf-8")) + 1
    except (FileNotFoundError, OSError, ValueError):
        number = 1
    path.write_text(str(number), encoding="utf-8")
    return number


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="exit_zero")
    parser.add_argument("--state-file", default="")
    parser.add_argument("--capture-file", default="")
    parser.add_argument("--pid-file", default="")
    parser.add_argument("--child-pid-file", default="")
    parser.add_argument("--pid-dir", default="")
    args, remaining = parser.parse_known_args()
    attempt = _next_attempt(args.state_file)
    _write(args.pid_file, str(os.getpid()))
    if args.pid_dir:
        _write(str(Path(args.pid_dir) / f"parent-{attempt}.pid"), str(os.getpid()))
    if args.capture_file:
        Path(args.capture_file).write_text(
            json.dumps(
                {
                    "arguments": remaining,
                    "working_directory": os.getcwd(),
                    "python_io_encoding": os.environ.get("PYTHONIOENCODING", ""),
                    "aalc_test_token": os.environ.get("AALC_TEST_TOKEN", ""),
                    "attempt_number": attempt,
                }
            ),
            encoding="utf-8",
        )
    mode = args.mode
    if mode in {"child_exit_zero", "child_exit_nonzero", "child_hang"}:
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("fake_child.py")), "--sleep-seconds", "120"]
        )
        child_file = args.child_pid_file or (str(Path(args.pid_dir) / f"child-{attempt}.pid") if args.pid_dir else "")
        _write(child_file, str(proc.pid))
        if mode == "child_exit_zero":
            return
        if mode == "child_exit_nonzero":
            raise SystemExit(7)
        time.sleep(120)
        return
    if mode in {"exit_zero", "capture"}:
        return
    if mode == "exit_nonzero":
        raise SystemExit(7)
    if mode == "hang":
        time.sleep(120)
        return
    if mode == "large_output":
        print("O" * (70 * 1024))
        print("E" * (70 * 1024), file=sys.stderr)
        return
    if mode == "utf16_output":
        sys.stdout.buffer.write("中文输出".encode("utf-16"))
        return
    if mode == "fail_once_then_success":
        if attempt == 1:
            raise SystemExit(7)
        return
    if mode == "hang_once_then_success":
        if attempt == 1:
            time.sleep(120)
        return
    raise SystemExit(9)


if __name__ == "__main__":
    main()
