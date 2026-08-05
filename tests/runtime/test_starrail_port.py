"""StarRail 启动参数端口占位符契约测试。

覆盖：
* 单元级占位符替换契约（零 / 一 / 多个占位符）；
* 端口分配的 TCP 端口形状；
* 端口分配失败的 fail-closed 行为；
* 通过 Fake StarRail 的端到端验证（占位符在启动前被替换、
  传给外部进程的参数不含字面量占位符）；
* 实际端口不进入公开诊断、日志或报告。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from autogame_orchestrator.config_model import StarRailConfig
from autogame_orchestrator.process.deadline import Deadline
from autogame_orchestrator.runtime import starrail_port
from autogame_orchestrator.runtime.starrail import StarRailAdapter
from autogame_orchestrator.runtime.starrail_models import (
    StarRailCompletionMode,
    StarRailErrorCode,
    StarRailRunStatus,
)
from autogame_orchestrator.runtime.starrail_port import (
    PROGRAM_PORT_PLACEHOLDER,
    PortAllocationError,
    allocate_local_tcp_port,
    contains_program_port_placeholder,
    resolve_launch_arguments,
)

_FAKE_SR = str(Path(__file__).resolve().parent.parent / "fakes" / "fake_starrail.py")
_PYTHON = Path(sys.executable)


# ════════════════════════════════════════════════════════════════════
# 单元：端口分配形状
# ════════════════════════════════════════════════════════════════════


def test_allocate_local_tcp_port_returns_valid_tcp_port() -> None:
    port = allocate_local_tcp_port()
    assert isinstance(port, int)
    assert 1 <= port <= 65535


def test_allocate_local_tcp_port_is_not_a_fixed_constant() -> None:
    # 不保证唯一，但至少不能硬编码为固定端口。多次取值应落在有效范围。
    ports = {allocate_local_tcp_port() for _ in range(5)}
    assert all(1 <= p <= 65535 for p in ports)


# ════════════════════════════════════════════════════════════════════
# 单元：占位符替换契约（零 / 一 / 多）
# ════════════════════════════════════════════════════════════════════


def test_zero_occurrence_returns_arguments_unchanged() -> None:
    args = ("gui.py", "--run", "src")
    resolved = resolve_launch_arguments(args)
    assert resolved == args
    assert not contains_program_port_placeholder(resolved)


def test_zero_occurrence_does_not_allocate_port(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> int:
        raise AssertionError("无占位符时不得分配端口")

    monkeypatch.setattr(starrail_port, "allocate_local_tcp_port", _boom)
    args = ("gui.py", "--run", "src")
    assert resolve_launch_arguments(args) == args


def test_single_occurrence_is_replaced_with_valid_port() -> None:
    args = ("gui.py", "--run", "src", "--port", PROGRAM_PORT_PLACEHOLDER)
    resolved = resolve_launch_arguments(args)
    assert PROGRAM_PORT_PLACEHOLDER not in resolved
    replaced = resolved[-1]
    assert replaced.isdecimal()
    assert 1 <= int(replaced) <= 65535
    # 其余无占位符参数保持不变
    assert resolved[:4] == args[:4]


def test_multiple_occurrences_share_single_port() -> None:
    args = (
        "gui.py",
        "--port",
        PROGRAM_PORT_PLACEHOLDER,
        "--mirror-port",
        PROGRAM_PORT_PLACEHOLDER,
    )
    resolved = resolve_launch_arguments(args)
    assert PROGRAM_PORT_PLACEHOLDER not in " ".join(resolved)
    assert resolved[2] == resolved[4]
    assert resolved[2].isdecimal()
    assert 1 <= int(resolved[2]) <= 65535


def test_multiple_occurrences_within_single_argument_share_port() -> None:
    args = ("gui.py", f"--endpoint=127.0.0.1:{PROGRAM_PORT_PLACEHOLDER}:{PROGRAM_PORT_PLACEHOLDER}")
    resolved = resolve_launch_arguments(args)
    assert PROGRAM_PORT_PLACEHOLDER not in resolved[1]
    # 同一端口值被复用两次
    tail = resolved[1].split("127.0.0.1:", 1)[1]
    first, second = tail.split(":")
    assert first == second
    assert first.isdecimal()


def test_placeholder_must_match_exactly() -> None:
    # 近似但不精确的串不得被替换
    args = ("gui.py", "--port", "_PROGRAM_PORT_", "--x", "PROGRAM_PORT")
    resolved = resolve_launch_arguments(args)
    assert resolved == args


# ════════════════════════════════════════════════════════════════════
# 单元：分配失败 fail-closed（不泄漏端口）
# ════════════════════════════════════════════════════════════════════


def test_allocation_failure_raises_port_allocation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket as socket_module

    class _FailingSocket:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def bind(self, *_a: object, **_k: object) -> None:
            raise OSError("bind refused")

        def getsockname(self) -> tuple[str, int]:  # pragma: no cover - 不应到达
            return ("127.0.0.1", 0)

        def close(self) -> None:
            pass

    monkeypatch.setattr(socket_module, "socket", _FailingSocket)
    with pytest.raises(PortAllocationError) as excinfo:
        allocate_local_tcp_port()
    # 异常消息不得泄漏端口值
    assert PROGRAM_PORT_PLACEHOLDER not in str(excinfo.value)
    assert not any(ch.isdigit() for ch in str(excinfo.value))


def test_resolve_propagates_allocation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail() -> int:
        raise PortAllocationError("无法取得可用的本地 TCP 端口")

    monkeypatch.setattr(starrail_port, "allocate_local_tcp_port", _fail)
    with pytest.raises(PortAllocationError):
        resolve_launch_arguments(("gui.py", "--port", PROGRAM_PORT_PLACEHOLDER))


# ════════════════════════════════════════════════════════════════════
# 集成：Adapter 启动边界
# ════════════════════════════════════════════════════════════════════


def _make_config_with_capture(
    *,
    capture_file: str,
    log_file: str,
    extra_args: tuple[str, ...],
    timeout_seconds: int = 120,
) -> StarRailConfig:
    tmp_dir = os.path.dirname(capture_file)
    os.makedirs(Path(log_file).parent, exist_ok=True)
    args = (
        _FAKE_SR,
        "--mode",
        "success_log",
        "--log-file",
        log_file,
        "--pid-file",
        os.path.join(tmp_dir, "pid.txt"),
        "--capture-file",
        capture_file,
        *extra_args,
    )
    return StarRailConfig(
        executable=str(_PYTHON),
        working_directory=tmp_dir,
        arguments=args,
        log_path_template=log_file,
        success_keywords=("No task pending",),
        failure_keywords=("ScriptError:",),
        task_timeout_seconds=timeout_seconds,
        stop_timeout_seconds=2,
    )


def test_placeholder_replaced_before_launch_via_fake(tmp_path: Path) -> None:
    capture_file = str(tmp_path / "capture.json")
    log_file = str(tmp_path / "log" / f"{time.strftime('%Y-%m-%d')}_src.txt")
    cfg = _make_config_with_capture(
        capture_file=capture_file,
        log_file=log_file,
        extra_args=("--port", PROGRAM_PORT_PLACEHOLDER),
    )
    result = StarRailAdapter(cfg, poll_interval_seconds=0.05).run(Deadline.after(10.0))
    assert result.status == StarRailRunStatus.COMPLETED

    captured = json.loads(Path(capture_file).read_text(encoding="utf-8"))
    passed_args = captured["arguments"]
    # 传给外部进程的参数不再包含字面量占位符
    assert PROGRAM_PORT_PLACEHOLDER not in passed_args
    # --port 后面是有效 TCP 端口
    port_index = passed_args.index("--port") + 1
    port_value = passed_args[port_index]
    assert port_value.isdecimal()
    assert 1 <= int(port_value) <= 65535


def test_no_placeholder_arguments_unchanged_via_fake(tmp_path: Path) -> None:
    capture_file = str(tmp_path / "capture.json")
    log_file = str(tmp_path / "log" / f"{time.strftime('%Y-%m-%d')}_src.txt")
    cfg = _make_config_with_capture(
        capture_file=capture_file,
        log_file=log_file,
        extra_args=("--port", "22367"),
    )
    result = StarRailAdapter(cfg, poll_interval_seconds=0.05).run(Deadline.after(10.0))
    assert result.status == StarRailRunStatus.COMPLETED

    captured = json.loads(Path(capture_file).read_text(encoding="utf-8"))
    passed_args = captured["arguments"]
    port_index = passed_args.index("--port") + 1
    assert passed_args[port_index] == "22367"


def test_allocation_failure_does_not_start_external_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture_file = str(tmp_path / "capture.json")
    log_file = str(tmp_path / "log" / f"{time.strftime('%Y-%m-%d')}_src.txt")
    cfg = _make_config_with_capture(
        capture_file=capture_file,
        log_file=log_file,
        extra_args=("--port", PROGRAM_PORT_PLACEHOLDER),
    )

    # 让端口分配失败
    import autogame_orchestrator.runtime.starrail as starrail_module

    def _fail(_arguments: tuple[str, ...]) -> tuple[str, ...]:
        raise PortAllocationError("无法取得可用的本地 TCP 端口")

    monkeypatch.setattr(starrail_module, "resolve_launch_arguments", _fail)

    result = StarRailAdapter(cfg, poll_interval_seconds=0.05).run(Deadline.after(10.0))

    assert result.status == StarRailRunStatus.FAILED
    assert result.error_code == StarRailErrorCode.PORT_ALLOCATION_FAILED
    assert result.completion_mode == StarRailCompletionMode.START_FAILURE
    assert result.pid is None
    assert result.owned_process_cleaned is True
    # 外部进程从未启动 → fake 未写 capture 文件
    assert not Path(capture_file).exists()


def test_actual_port_not_leaked_in_result(tmp_path: Path) -> None:
    capture_file = str(tmp_path / "capture.json")
    log_file = str(tmp_path / "log" / f"{time.strftime('%Y-%m-%d')}_src.txt")
    cfg = _make_config_with_capture(
        capture_file=capture_file,
        log_file=log_file,
        extra_args=("--port", PROGRAM_PORT_PLACEHOLDER),
    )
    result = StarRailAdapter(cfg, poll_interval_seconds=0.05).run(Deadline.after(10.0))
    assert result.status == StarRailRunStatus.COMPLETED

    # 读取被实际替换成的端口值
    captured = json.loads(Path(capture_file).read_text(encoding="utf-8"))
    passed_args = captured["arguments"]
    port_value = passed_args[passed_args.index("--port") + 1]

    # 该端口值不得出现在结果的任何公开诊断字段中
    assert port_value not in json.dumps(dict(result.diagnostics))
    assert port_value not in (result.matched_keyword or "")
    # stdout/stderr 摘录不由本适配器注入端口（fake 不回显端口）
    assert port_value not in (result.stdout_excerpt or "")
    assert port_value not in (result.stderr_excerpt or "")
