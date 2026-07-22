"""供用户手工触发的单 Adapter 真实 smoke 门禁。"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import cast

from autogame_orchestrator.config_loader import load_config
from autogame_orchestrator.config_model import AALCConfig, MAAConfig, StarRailConfig
from autogame_orchestrator.models import JsonValue
from autogame_orchestrator.process import CancellationToken, Deadline
from autogame_orchestrator.runtime import AALCAdapter, MAAAdapter, StarRailAdapter
from autogame_orchestrator.runtime.aalc_models import AALCRunResult
from autogame_orchestrator.runtime.maa_models import MAARunResult
from autogame_orchestrator.runtime.starrail_models import StarRailRunResult

CONFIRMATION = "I_UNDERSTAND_THIS_LAUNCHES_A_REAL_PROGRAM"
EXIT_INPUT_ERROR = 2
EXIT_INTERNAL_ERROR = 8


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="受控执行单个真实 Adapter smoke")
    parser.add_argument("--adapter")
    parser.add_argument("--config")
    parser.add_argument("--deadline-seconds")
    parser.add_argument("--output")
    parser.add_argument("--confirm-real-execution")
    parser.add_argument("--allow-aalc-retries", action="store_true")
    return parser


def _value(value: object) -> str:
    return str(getattr(value, "value", value))


def _common(result: object, adapter: str, cancelled: bool) -> dict[str, JsonValue]:
    fields = vars(result)
    duration = fields.get("duration_seconds")
    if duration is None:
        duration = cast(int, fields["duration_ms"]) / 1000.0
    mode = fields.get("completion_mode")
    if mode is None:
        mode = fields.get("termination_reason")
    return {
        "schema_version": 1,
        "adapter": adapter,
        "started_at": cast(datetime, fields["started_at"]).astimezone(UTC).isoformat(),
        "finished_at": cast(datetime, fields["finished_at"]).astimezone(UTC).isoformat(),
        "duration_seconds": float(cast(float, duration)),
        "status": _value(fields["status"]),
        "error_code": _value(fields["error_code"]),
        "completion_mode": _value(mode) if mode is not None else None,
        "exit_code": cast(int | None, fields.get("exit_code")),
        "owned_process_cleaned": bool(fields.get("owned_process_cleaned", True)),
        "cancel_requested": cancelled,
    }


def _project_starrail(result: StarRailRunResult, cancelled: bool) -> dict[str, JsonValue]:
    payload = _common(result, "starrail", cancelled)
    payload.update(
        {
            "matched_keyword": result.matched_keyword,
            "log_path_present": bool(result.log_path),
            "stdout_truncated": result.stdout_truncated,
            "stderr_truncated": result.stderr_truncated,
        }
    )
    return payload


def _project_maa(result: MAARunResult, cancelled: bool) -> dict[str, JsonValue]:
    payload = _common(result, "maa", cancelled)
    payload.update(
        {
            "pid_present": result.pid is not None,
            "stdout_truncated": result.stdout_truncated,
            "stderr_truncated": result.stderr_truncated,
        }
    )
    return payload


def _project_aalc(result: AALCRunResult, cancelled: bool) -> dict[str, JsonValue]:
    payload = _common(result, "aalc", cancelled)
    attempts: list[JsonValue] = [
        {
            "attempt_number": item.attempt_number,
            "status": _value(item.status),
            "error_code": _value(item.error_code),
            "exit_code": item.exit_code,
            "owned_process_cleaned": item.owned_process_cleaned,
            "duration_seconds": item.duration_seconds,
        }
        for item in result.attempt_results
    ]
    payload.update(
        {
            "configured_attempts": result.configured_attempts,
            "attempts_started": result.attempts_started,
            "successful_attempt_number": result.successful_attempt_number,
            "attempts": attempts,
        }
    )
    if result.attempt_results:
        payload["exit_code"] = result.attempt_results[-1].exit_code
        payload["owned_process_cleaned"] = all(item.owned_process_cleaned for item in result.attempt_results)
    if _value(result.error_code) == "CLEANUP_FAILED":
        payload["owned_process_cleaned"] = False
    return payload


def _atomic_write_json(path: Path, payload: dict[str, JsonValue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _exit_code(payload: dict[str, JsonValue]) -> int:
    if payload["error_code"] == "CLEANUP_FAILED":
        return 6
    return {"completed": 0, "failed": 3, "timeout": 4, "cancelled": 5}.get(
        cast(str, payload["status"]), EXIT_INTERNAL_ERROR
    )


def _deadline(raw: str | None) -> float | None:
    try:
        value = float(raw) if raw is not None else math.nan
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def main(argv: Sequence[str] | None = None) -> int:
    """执行单个 Adapter；参数错误以稳定退出码返回。"""
    try:
        args = _parser().parse_args(argv)
    except SystemExit:
        return EXIT_INPUT_ERROR
    if args.confirm_real_execution != CONFIRMATION:
        print("拒绝执行：必须提供完全一致的真实程序执行确认值。")
        return EXIT_INPUT_ERROR
    if args.adapter not in {"starrail", "maa", "aalc"}:
        print("拒绝执行：必须且只能选择 starrail、maa 或 aalc。")
        return EXIT_INPUT_ERROR
    seconds = _deadline(args.deadline_seconds)
    if seconds is None or not isinstance(args.config, str) or not isinstance(args.output, str):
        print("拒绝执行：配置、输出路径和有限正数 deadline 均为必填项。")
        return EXIT_INPUT_ERROR
    try:
        config, errors = load_config(Path(args.config), check_paths=False)
        if errors or config is None:
            print("拒绝执行：本地配置结构校验失败。")
            return EXIT_INPUT_ERROR
        selected: StarRailConfig | MAAConfig | AALCConfig
        if args.adapter == "starrail":
            selected = config.starrail
        elif args.adapter == "maa":
            selected = config.maa
        else:
            selected = config.aalc
        if selected.check_paths():
            print("拒绝执行：所选 Adapter 路径校验失败。")
            return EXIT_INPUT_ERROR
        token = CancellationToken()
        previous = signal.getsignal(signal.SIGINT)

        def request_cancel(_signum: int, _frame: FrameType | None) -> None:
            token.cancel()

        signal.signal(signal.SIGINT, request_cancel)
        try:
            deadline = Deadline.after(seconds)
            if args.adapter == "starrail":
                payload = _project_starrail(
                    StarRailAdapter(cast(StarRailConfig, selected)).run(deadline, token), token.is_cancelled
                )
            elif args.adapter == "maa":
                payload = _project_maa(MAAAdapter(cast(MAAConfig, selected)).run(deadline, token), token.is_cancelled)
            else:
                aalc = cast(AALCConfig, selected)
                if not args.allow_aalc_retries:
                    aalc = replace(aalc, attempts=1)
                payload = _project_aalc(AALCAdapter(aalc).run(deadline, token), token.is_cancelled)
        finally:
            signal.signal(signal.SIGINT, previous)
        try:
            _atomic_write_json(Path(args.output), payload)
        except OSError:
            print("Adapter 已结束，但结果文件原子写入失败。")
            return 7
        print(f"Adapter smoke 结束：status={payload['status']} error_code={payload['error_code']}")
        return _exit_code(payload)
    except Exception:
        print("诊断入口发生内部错误；未输出本机路径或异常详情。")
        return EXIT_INTERNAL_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
