"""伪造 ADB 程序——供探测测试使用。

通过 --mode 参数控制场景。生产代码不得导入。

用法示例::

    python tests/fakes/fake_adb.py --mode normal version
    python tests/fakes/fake_adb.py --mode offline devices -l
    python tests/fakes/fake_adb.py --mode boot_0 -s emu shell getprop sys.boot_completed
"""

from __future__ import annotations

import argparse
import sys
import time


def _cmd_version() -> None:
    print("Android Debug Bridge version 1.0.41")
    print("Version 35.0.2-12147458")
    print("Installed as adb.exe")


def _cmd_devices(mode: str) -> None:
    print("List of devices attached")
    if mode == "no_devices":
        return
    if mode == "multi_devices":
        print("127.0.0.1:16384\tdevice")
        print("emulator-5554\tdevice")
        return
    if mode == "offline":
        print("127.0.0.1:16384\toffline")
        return
    if mode == "unauthorized":
        print("127.0.0.1:16384\tunauthorized")
        return
    if mode == "malformed":
        print("bad_line_without_tab")
        return
    if mode == "state_not_device":
        print("127.0.0.1:16384\tdevice")
        return
    if mode == "duplicate_serial":
        print("127.0.0.1:16384\tdevice")
        print("127.0.0.1:16384\tdevice")
        return
    # normal 及其他
    print("127.0.0.1:16384\tdevice model:MuMu12 device:starrail")


def _cmd_get_state(mode: str) -> None:
    if mode == "state_not_device":
        print("offline")
    else:
        print("device")


def _cmd_boot_completed(mode: str) -> None:
    if mode == "boot_0":
        print("0")
    elif mode == "boot_1":
        print("1")
    else:
        print("1")


def _generate_large_stdout() -> None:
    """生成约 2 MiB 的 stdout 输出。"""
    chunk = b"X" * 65536
    total = 2 * 1024 * 1024
    remaining = total
    while remaining > 0:
        size = min(len(chunk), remaining)
        sys.stdout.buffer.write(chunk[:size])
        remaining -= size
    sys.stdout.buffer.flush()


def _generate_stderr() -> None:
    sys.stderr.write("Fake ADB error: something went wrong\n")
    sys.stderr.flush()


def _generate_large_stderr() -> None:
    """生成约 128 KiB 的 stderr 输出（超过 _STDERR_MAX）。"""
    chunk = b"E" * 65536
    total = 128 * 1024
    remaining = total
    while remaining > 0:
        size = min(len(chunk), remaining)
        sys.stderr.buffer.write(chunk[:size])
        remaining -= size
    sys.stderr.buffer.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="伪造 ADB 程序")
    parser.add_argument("--mode", type=str, default="normal", help="场景模式")
    parser.add_argument("-s", type=str, default="", help="目标设备 serial")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="ADB 命令")

    args = parser.parse_args()
    mode = args.mode
    _serial = args.s

    cmd = " ".join(args.command) if args.command else ""

    if mode == "sleep_forever":
        while True:
            time.sleep(1.0)

    if mode == "large_stdout":
        _generate_large_stdout()
        return

    if mode == "stderr_output":
        _generate_stderr()
        return

    if mode == "large_stderr":
        _generate_large_stderr()
        return

    if mode == "exit_nonzero":
        _generate_stderr()
        sys.exit(1)

    if cmd == "version":
        _cmd_version()
    elif cmd == "devices -l" or cmd == "devices":
        _cmd_devices(mode)
    elif "get-state" in cmd:
        _cmd_get_state(mode)
    elif "getprop sys.boot_completed" in cmd:
        _cmd_boot_completed(mode)
    elif cmd == "devices -l":
        _cmd_devices(mode)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
