"""用于 MAA 适配器集成测试的伪 CLI。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _write(path: str, value: str) -> None:
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="exit_zero")
    parser.add_argument("--pid-file", default="")
    parser.add_argument("--child-pid-file", default="")
    parser.add_argument("--capture-file", default="")
    parser.add_argument("--delay-seconds", type=float, default=0.2)
    args, remaining = parser.parse_known_args()
    _write(args.pid_file, str(os.getpid()))
    if args.capture_file:
        Path(args.capture_file).write_text(
            json.dumps(
                {
                    "arguments": remaining,
                    "working_directory": os.getcwd(),
                    "python_io_encoding": os.environ.get("PYTHONIOENCODING", ""),
                    "maa_test_token": os.environ.get("MAA_TEST_TOKEN", ""),
                }
            ),
            encoding="utf-8",
        )
    if args.mode == "exit_zero":
        return
    if args.mode == "exit_nonzero":
        raise SystemExit(7)
    if args.mode in {"hang", "delayed_exit_zero"}:
        time.sleep(120 if args.mode == "hang" else args.delay_seconds)
        return
    if args.mode == "large_output_exit_zero":
        print("O" * (70 * 1024))
        print("E" * (70 * 1024), file=sys.stderr)
        return
    if args.mode == "utf16_output_exit_zero":
        sys.stdout.buffer.write("中文输出".encode("utf-16"))
        return
    if args.mode in {"child_exit_zero", "child_hang"}:
        subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("fake_child.py")),
                "--pid-file",
                args.child_pid_file,
                "--sleep-seconds",
                "120",
            ]
        )
        if args.mode == "child_hang":
            time.sleep(120)
        return
    raise SystemExit(9)


if __name__ == "__main__":
    main()
