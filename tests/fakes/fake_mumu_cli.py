"""伪造候选 CLI——供 MumuCliProbe 诊断测试使用。

通过 --mode 控制行为。其余参数作为被探测的帮助参数写入 capture file。
"""

from __future__ import annotations

import argparse
import sys
import time


def _write_capture(path: str, content: str) -> None:
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mode", type=str, default="help_stdout")
    parser.add_argument("--capture-file", type=str, default="")
    parser.add_argument("--pid-file", type=str, default="")
    known_args, remaining = parser.parse_known_args()

    mode = known_args.mode
    capture = known_args.capture_file

    if known_args.pid_file:
        from pathlib import Path

        Path(known_args.pid_file).parent.mkdir(parents=True, exist_ok=True)
        Path(known_args.pid_file).write_text(str(__import__("os").getpid()))

    # 记录收到的剩余参数
    arg_str = " ".join(remaining) if remaining else "(no args)"
    if capture:
        _write_capture(capture, arg_str)

    if mode == "help_stdout":
        print("Usage: FakeMuMuManager [options]")
        print("Commands: start stop status")
        print("Options: --instance <id>")
        sys.exit(0)

    if mode == "help_stderr_nonzero":
        sys.stderr.write("Usage: FakeMuMuManager [options]\n")
        sys.stderr.write("Commands: start stop status\n")
        sys.stderr.write("Options: --instance <id>\n")
        sys.exit(1)

    if mode == "no_output":
        sys.exit(0)

    if mode == "unrelated_output":
        print("Fake component initialized")
        sys.exit(0)

    if mode == "utf16_help":
        text = "用法：FakeMuMuManager\n命令：start stop status\n选项：--instance <id>\n启动 停止 实例\n"
        sys.stdout.buffer.write(text.encode("utf-16"))
        sys.exit(0)

    if mode == "large_output":
        chunk = b"E" * 65536
        total = 128 * 1024
        remaining = total
        while remaining > 0:
            size = min(len(chunk), remaining)
            sys.stderr.buffer.write(chunk[:size])
            remaining -= size
        sys.stderr.buffer.flush()
        sys.exit(0)

    if mode == "sleep_forever":
        while True:
            time.sleep(1.0)

    sys.exit(0)


if __name__ == "__main__":
    main()
