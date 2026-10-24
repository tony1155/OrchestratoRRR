"""用于 Mash 适配器集成测试的伪 mash-cli。

模拟真实 mash-cli 的契约面（见集成仓库 docs/02-mash-cli-spec.md）：
- ``run``：写 run-result JSON、按 --exit-code 退出；``--mode hang`` 时监听
  cancel-request 文件（真实 CLI 位于 <app_data>/cli/cancel.request）并在收到
  后以退出码 2 结束——这使我们能在真实进程监督下验证优雅取消协议。
- ``cancel``：写 cancel-request 文件后按 --cancel-exit-code 退出。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "cancel"])
    # 适配器会传入的选项全部显式吸收，避免 argparse 把未知的裸值当成位置参数。
    parser.add_argument("--project", default="")
    parser.add_argument("--server", default="")
    parser.add_argument("--device", default="")
    parser.add_argument("--repeat", default="")
    parser.add_argument("--events", default="")
    parser.add_argument("--wait", default="")
    parser.add_argument("--result-file", default="")
    parser.add_argument("--run-id", default="fake-run-id")
    parser.add_argument("--completed-runs", type=int, default=3)
    parser.add_argument("--outcome", default="")
    parser.add_argument("--message", default="")
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--cancel-exit-code", type=int, default=0)
    parser.add_argument("--mode", default="exit")
    parser.add_argument("--poll-seconds", type=float, default=0.02)
    args, _remaining = parser.parse_known_args()

    app_data = Path.cwd() / "fake-mash-appdata"
    app_data.mkdir(parents=True, exist_ok=True)
    cancel_request = app_data / "cli" / "cancel.request"
    current = app_data / "cli" / "current.json"

    if args.command == "cancel":
        cancel_request.parent.mkdir(parents=True, exist_ok=True)
        cancel_request.write_text(json.dumps({"mode": "immediate"}), encoding="utf-8")
        print("已发送停止请求", file=sys.stderr)
        raise SystemExit(args.cancel_exit_code)

    # run
    if current.parent.exists() is False:
        current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text(
        json.dumps({"pid": 0, "runId": args.run_id, "projectId": "fake"}),
        encoding="utf-8",
    )
    print(
        json.dumps({"type": "run-started", "runId": args.run_id}),
        flush=True,
    )
    if args.mode == "hang":
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            if cancel_request.exists():
                cancel_request.unlink(missing_ok=True)
                outcome = args.outcome or "cancelled"
                _write_result(args, outcome, exit_code=2)
                current.unlink(missing_ok=True)
                raise SystemExit(2)
            time.sleep(args.poll_seconds)
        _write_result(args, "error", exit_code=1)
        current.unlink(missing_ok=True)
        raise SystemExit(1)

    outcome = args.outcome or ("finished" if args.exit_code == 0 else "error")
    _write_result(args, outcome, exit_code=args.exit_code)
    print(
        json.dumps({"type": "status", "message": "fake-status", "level": "info"}),
        flush=True,
    )
    current.unlink(missing_ok=True)
    raise SystemExit(args.exit_code)


def _write_result(args: argparse.Namespace, outcome: str, *, exit_code: int) -> None:
    if not args.result_file:
        return
    target = Path(args.result_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "runId": args.run_id,
                "outcome": outcome,
                "message": args.message or None,
                "completedRuns": args.completed_runs,
                "exitCode": exit_code,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
