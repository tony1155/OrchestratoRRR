"""伪造 MuMu Manager——供运行时测试使用。

通过 --mode 控制行为。写入状态文件供 Fake readiness 读取。

用法::

    fake_mumu_manager.py --mode normal start
    fake_mumu_manager.py --mode sleep_forever stop
    fake_mumu_manager.py --mode spawn_child_then_exit --child-pid-file child.pid start
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

_FAKE_CHILD = str(Path(__file__).resolve().with_name("fake_child.py"))


def _write_status(state_file: str, state: str) -> None:
    if state_file:
        Path(state_file).parent.mkdir(parents=True, exist_ok=True)
        Path(state_file).write_text(state, encoding="utf-8")


def _write_args(args_file: str, sys_argv: list[str]) -> None:
    if args_file:
        Path(args_file).parent.mkdir(parents=True, exist_ok=True)
        Path(args_file).write_text(json.dumps(sys_argv, ensure_ascii=False), encoding="utf-8")


def _spawn_child(child_pid_file: str) -> None:
    cmd = [sys.executable, _FAKE_CHILD, "--pid-file", child_pid_file]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> None:
    parser = argparse.ArgumentParser(description="伪造 MuMu Manager")
    parser.add_argument("--mode", type=str, default="normal", help="场景模式")
    parser.add_argument("--state-file", type=str, default="", help="状态文件路径")
    parser.add_argument("--args-file", type=str, default="", help="记录收到参数的文件路径")
    parser.add_argument("--child-pid-file", type=str, default="", help="子进程 PID 文件")
    parser.add_argument("command", nargs="*", help="start/stop/status")

    args = parser.parse_args()
    mode = args.mode
    state_file = args.state_file
    args_file = args.args_file
    cmd = " ".join(args.command) if args.command else "status"

    # 记录参数
    _write_args(args_file, sys.argv)

    if mode == "sleep_forever":
        while True:
            time.sleep(1.0)

    if mode == "exit_nonzero":
        sys.stderr.write("manager error\n")
        sys.exit(1)

    if mode == "start_no_effect":
        sys.exit(0)

    if mode == "stop_no_effect":
        sys.exit(0)

    if mode == "spawn_child_then_exit":
        _spawn_child(args.child_pid_file)
        _write_status(state_file, "ready")
        sys.exit(0)

    if cmd == "start":
        _write_status(state_file, "ready")
    elif cmd == "stop":
        _write_status(state_file, "stopped")
    elif cmd == "status":
        current = "unknown"
        if state_file:
            try:
                current = Path(state_file).read_text(encoding="utf-8").strip()
            except OSError:
                pass
        print(current)
    else:
        sys.stderr.write(f"unknown command: {cmd}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
