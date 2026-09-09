"""No MaaFramework imports or real devices: invocation/Job regression fixture only."""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", action="store_true", required=True)
    parser.add_argument("--mode", default=os.environ.get("FAKE_MAAFGO_MODE", "zero"))
    parser.add_argument("--pid-dir", type=Path, required=True)
    args = parser.parse_args()
    (args.pid_dir / ("child.pid" if args.mode == "child" else "parent.pid")).write_text(str(os.getpid()))
    if args.mode == "nonzero":
        return 7
    if args.mode == "output":
        print(str(args.pid_dir) + " private stdout " + "x" * 100000, flush=True)
        print(str(args.pid_dir) + " private stderr " + "y" * 100000, file=sys.stderr, flush=True)
    if args.mode in ("spawn", "spawn_exit", "spawn_nonzero"):
        subprocess.Popen([sys.executable, __file__, "-d", "--mode", "child", "--pid-dir", str(args.pid_dir)])
        end = time.monotonic() + 5
        while not (args.pid_dir / "child.pid").exists():
            if time.monotonic() >= end:
                return 8
            time.sleep(0.01)
        if args.mode == "spawn_exit":
            return 0
        if args.mode == "spawn_nonzero":
            return 7
    if args.mode in ("hang", "spawn", "child"):
        while True:
            time.sleep(0.05)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
