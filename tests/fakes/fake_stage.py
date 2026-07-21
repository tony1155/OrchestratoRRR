"""伪造测试程序——供编排器阶段 1A 进程监督测试使用。

支持：睡眠、退出码（含 259）、输出生成、子进程生成、PID 文件、事件文件。
生产代码不得导入此模块。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_FAKE_CHILD_SCRIPT = str(Path(__file__).resolve().with_name("fake_child.py"))


def _write_pid_file(path: str, pid: int) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(pid), encoding="utf-8")


def _write_event(path: str, event: str) -> None:
    if not path:
        return
    record = {"timestamp": time.time(), "pid": os.getpid(), "event": event}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _generate_output(total_bytes: int, target: object) -> None:
    chunk = b"X" * min(65536, total_bytes)
    remaining = total_bytes
    while remaining > 0:
        size = min(len(chunk), remaining)
        if target is sys.stdout:
            sys.stdout.buffer.write(chunk[:size])
        elif target is sys.stderr:
            sys.stderr.buffer.write(chunk[:size])
        remaining -= size
    if target is sys.stdout:
        sys.stdout.buffer.flush()
    elif target is sys.stderr:
        sys.stderr.buffer.flush()


def _spawn_child(child_pid_file: str | None) -> None:
    cmd = [sys.executable, _FAKE_CHILD_SCRIPT]
    if child_pid_file:
        cmd.extend(["--pid-file", child_pid_file])
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _read_env(var_name: str) -> str:
    return os.environ.get(var_name, "")


def main() -> None:
    parser = argparse.ArgumentParser(description="伪造测试程序")
    parser.add_argument("--exit-code", type=int, default=0, help="退出码（默认 0）")
    parser.add_argument("--sleep-seconds", type=float, default=0.0, help="睡眠指定秒数后退出")
    parser.add_argument("--sleep-forever", action="store_true", help="永久睡眠，直到被终止")
    parser.add_argument("--stdout-text", type=str, default="", help="写入 stdout 的文本")
    parser.add_argument("--stderr-text", type=str, default="", help="写入 stderr 的文本")
    parser.add_argument("--output-bytes", type=int, default=0, help="生成指定字节数写入 stdout")
    parser.add_argument("--stderr-output-bytes", type=int, default=0, help="生成指定字节数写入 stderr")
    parser.add_argument("--pid-file", type=str, default="", help="将 PID 写入指定文件")
    parser.add_argument("--event-file", type=str, default="", help="将生命周期事件写入指定 JSONL 文件")
    parser.add_argument("--spawn-child", action="store_true", help="生成一个子进程")
    parser.add_argument(
        "--spawn-child-then-exit", action="store_true", help="生成子进程后父进程立即退出（子进程继续运行）"
    )
    parser.add_argument("--child-pid-file", type=str, default="", help="将子进程 PID 写入指定文件")
    parser.add_argument("--parent-exit-after-spawn", action="store_true", help="生成子进程后父进程立即退出")
    parser.add_argument("--echo-env", type=str, default="", help="读取环境变量并写入 stdout（格式: VAR_NAME）")
    parser.add_argument("--echo-all-env", action="store_true", help="将所有环境变量写入 stdout")

    args = parser.parse_args()

    _write_event(args.event_file, "started")

    if args.pid_file:
        _write_pid_file(args.pid_file, os.getpid())

    # 环境变量回显
    if args.echo_env:
        val = _read_env(args.echo_env)
        sys.stdout.write(f"{args.echo_env}={val}\n")
        sys.stdout.flush()

    if args.echo_all_env:
        for k in sorted(os.environ.keys()):
            sys.stdout.write(f"{k}={os.environ[k]}\n")
        sys.stdout.flush()

    # stdout/stderr 文本
    if args.stdout_text:
        sys.stdout.write(args.stdout_text)
        sys.stdout.flush()
    if args.stderr_text:
        sys.stderr.write(args.stderr_text)
        sys.stderr.flush()

    # 大输出
    if args.output_bytes > 0:
        _generate_output(args.output_bytes, sys.stdout)
    if args.stderr_output_bytes > 0:
        _generate_output(args.stderr_output_bytes, sys.stderr)

    # 衍生子进程（父进程继续运行）
    if args.spawn_child:
        _spawn_child(args.child_pid_file)
        _write_event(args.event_file, "spawned_child")

    # 衍生子进程后父进程退出
    if args.spawn_child_then_exit:
        _spawn_child(args.child_pid_file)
        _write_event(args.event_file, "spawned_child")
        _write_event(args.event_file, "parent_exiting")
        sys.exit(args.exit_code)

    if args.parent_exit_after_spawn:
        _write_event(args.event_file, "parent_exiting")
        sys.exit(args.exit_code)

    # 睡眠
    if args.sleep_forever:
        _write_event(args.event_file, "sleeping_forever")
        while True:
            time.sleep(1.0)
    elif args.sleep_seconds > 0:
        time.sleep(args.sleep_seconds)

    _write_event(args.event_file, "exiting")
    sys.exit(args.exit_code)


if __name__ == "__main__":
    main()
