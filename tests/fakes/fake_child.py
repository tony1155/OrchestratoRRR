"""伪造子进程——供进程树清理测试使用。

这是一个独立脚本，由 ``fake_stage.py`` 的 ``--spawn-child`` 标志衍生。
它默认睡眠很长时间，只有在父进程（或 Job Object）终止它时才会退出。
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path


def _write_pid_file(path: str, pid: int) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(pid), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="伪造子进程")
    parser.add_argument("--pid-file", type=str, default="", help="将 PID 写入指定文件")
    parser.add_argument("--sleep-seconds", type=float, default=120.0, help="睡眠秒数（默认 120）")
    args = parser.parse_args()

    if args.pid_file:
        _write_pid_file(args.pid_file, os.getpid())

    time.sleep(args.sleep_seconds)


if __name__ == "__main__":
    main()
