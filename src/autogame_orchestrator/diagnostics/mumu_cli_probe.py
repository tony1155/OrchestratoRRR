"""MuMu 候选 CLI 安全诊断探针。

对白名单中的候选可执行文件，依次尝试固定的帮助参数（--help、-h、/?），
通过 ProcessSupervisor 有界执行，收集受限 stdout/stderr 输出并判定帮助证据。
不执行 start/stop/restart 等真实命令。不自动批准生产使用。
"""

from __future__ import annotations

import json
import locale
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from autogame_orchestrator.models import JsonValue
from autogame_orchestrator.process import CancellationToken, Deadline, ProcessSpec, ProcessSupervisor
from autogame_orchestrator.process.errors import TerminationReason

# ── 固定常量 ─────────────────────────────────────────────────────

HELP_ARGUMENTS: tuple[tuple[str, ...], ...] = (
    ("--help",),
    ("-h",),
    ("/?",),
)

ALLOWED_CANDIDATE_NAMES: frozenset[str] = frozenset(
    {
        "mumumanager.exe",
        "nemushell.exe",
    }
)

FORBIDDEN_CANDIDATE_NAMES: frozenset[str] = frozenset(
    {
        "mumunxmain.exe",
        "mumunxdevice.exe",
        "mumuvmmmanage.exe",
        "mumuvmmheadless.exe",
    }
)

DEFAULT_ATTEMPT_TIMEOUT_SECONDS = 3.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 10.0
MAX_STDOUT_BYTES = 64 * 1024
MAX_STDERR_BYTES = 64 * 1024
MAX_EXCERPT_CHARS = 8 * 1024

HELP_MARKERS: tuple[str, ...] = (
    "usage",
    "options",
    "commands",
    "command",
    "help",
    "start",
    "stop",
    "instance",
    "device",
    "用法",
    "选项",
    "命令",
    "帮助",
    "启动",
    "停止",
    "实例",
    "设备",
)


# ── 状态枚举 ────────────────────────────────────────────────────


class MumuCliAttemptStatus(StrEnum):
    """单次尝试的状态。"""

    HELP_EVIDENCE = "help_evidence"
    NO_HELP_EVIDENCE = "no_help_evidence"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    START_FAILED = "start_failed"
    OUTPUT_INVALID = "output_invalid"


class MumuCliCandidateStatus(StrEnum):
    """候选可执行文件探测结论。"""

    HELP_DISCOVERED = "help_discovered"
    NO_HELP_DISCOVERED = "no_help_discovered"
    UNSAFE_OR_HANGING = "unsafe_or_hanging"
    INVALID_CANDIDATE = "invalid_candidate"
    CANCELLED = "cancelled"


# ── 数据模型 ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProbeCommand:
    """被探测的命令描述。"""

    display_name: str
    executable: Path
    prefix_arguments: tuple[str, ...] = ()


@dataclass(frozen=True)
class MumuCliProbeAttempt:
    """单次帮助参数尝试的结果。"""

    arguments: tuple[str, ...]
    status: MumuCliAttemptStatus
    exit_code: int | None
    duration_ms: int
    stdout_excerpt: str
    stderr_excerpt: str
    stdout_truncated: bool
    stderr_truncated: bool
    matched_markers: tuple[str, ...]


@dataclass(frozen=True)
class MumuCliProbeReport:
    """候选可执行文件探测汇总报告。"""

    candidate_name: str
    candidate_path: str
    status: MumuCliCandidateStatus
    attempts: tuple[MumuCliProbeAttempt, ...]
    runtime_approved: bool
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)


# ── 候选验证 ────────────────────────────────────────────────────


def validate_mumu_candidate(path: Path) -> ProbeCommand:
    """验证候选路径并返回 ProbeCommand。

    Raises:
        ValueError: 路径无效或不在白名单中。
    """
    if not path.is_absolute():
        msg = f"候选路径必须是绝对路径: {path}"
        raise ValueError(msg)
    if not path.exists():
        msg = f"候选路径不存在: {path}"
        raise ValueError(msg)
    if not path.is_file():
        msg = f"候选路径不是普通文件: {path}"
        raise ValueError(msg)

    name_lower = path.name.casefold()

    if name_lower in FORBIDDEN_CANDIDATE_NAMES:
        msg = f"候选文件被禁止: {path.name}"
        raise ValueError(msg)

    if name_lower not in ALLOWED_CANDIDATE_NAMES:
        msg = f"候选文件不在允许列表中: {path.name}"
        raise ValueError(msg)

    return ProbeCommand(display_name=path.name, executable=path, prefix_arguments=())


# ── 输出读取 ────────────────────────────────────────────────────


def _read_limited_text(path: Path, byte_limit: int) -> tuple[str, bool]:
    """有界读取文本文件，自动检测编码。

    Returns:
        (解码后文本, 是否超限)
    """
    try:
        with path.open("rb") as stream:
            data = stream.read(byte_limit + 1)
    except OSError:
        return "", False

    truncated = len(data) > byte_limit
    if truncated:
        data = data[:byte_limit]

    # 解码：BOM → UTF-16LE NUL 检测 → 系统编码 → UTF-8 replace
    text = ""
    if data.startswith(b"\xff\xfe") or len(data) >= 2 and data[1] == 0:  # UTF-16LE BOM
        try:
            text = data.decode("utf-16-le")
        except UnicodeDecodeError:
            pass

    if not text:
        try:
            text = data.decode(locale.getpreferredencoding(False))
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")

    # 最终裁剪到摘录上限
    if len(text) > MAX_EXCERPT_CHARS:
        text = text[:MAX_EXCERPT_CHARS]
        truncated = True

    return text.strip(), truncated


# ── 帮助证据判定 ────────────────────────────────────────────────


def _match_help_markers(text: str) -> tuple[str, ...]:
    """在文本中匹配帮助关键词。"""
    folded = text.casefold()
    found: list[str] = []
    for marker in HELP_MARKERS:
        if marker in folded:
            if marker not in found:
                found.append(marker)
            if len(found) >= 12:
                break
    return tuple(found)


def _has_help_evidence(text: str) -> bool:
    """判定文本是否包含帮助证据。"""
    markers = _match_help_markers(text)
    if not markers:
        return False
    # 必须包含 usage/用法，或者至少匹配两个不同 marker
    if "usage" in markers or "用法" in markers:
        return True
    return len(markers) >= 2


# ── MumuCliProbe ────────────────────────────────────────────────


class MumuCliProbe:
    """MuMu 候选 CLI 帮助探针。

    对候选文件依次执行固定的帮助参数，通过 ProcessSupervisor 有界运行，
    收集受限输出并判定是否存在帮助证据。
    """

    def __init__(
        self,
        *,
        attempt_timeout_seconds: float = DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
        total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
    ) -> None:
        if attempt_timeout_seconds <= 0:
            msg = f"attempt_timeout_seconds 必须 > 0，收到 {attempt_timeout_seconds}"
            raise ValueError(msg)
        if total_timeout_seconds <= 0:
            msg = f"total_timeout_seconds 必须 > 0，收到 {total_timeout_seconds}"
            raise ValueError(msg)
        if attempt_timeout_seconds > total_timeout_seconds:
            msg = (
                f"attempt_timeout_seconds ({attempt_timeout_seconds}) 不得大于"
                f" total_timeout_seconds ({total_timeout_seconds})"
            )
            raise ValueError(msg)

        self._attempt_timeout = attempt_timeout_seconds
        self._total_timeout = total_timeout_seconds

    def probe(
        self,
        command: ProbeCommand,
        cancel: CancellationToken | None = None,
    ) -> MumuCliProbeReport:
        """执行完整探测。"""
        total_deadline = Deadline.after(self._total_timeout)
        attempts: list[MumuCliProbeAttempt] = []

        for arg_tuple in HELP_ARGUMENTS:
            if cancel is not None and cancel.is_cancelled:
                break
            if total_deadline.expired:
                break

            attempt_sec = min(self._attempt_timeout, total_deadline.remaining_seconds)
            attempt_deadline = Deadline.after(attempt_sec)
            attempt = self._run_attempt(command, arg_tuple, attempt_deadline, cancel)
            attempts.append(attempt)

            if attempt.status == MumuCliAttemptStatus.HELP_EVIDENCE:
                break

        status = self._aggregate(attempts)
        return MumuCliProbeReport(
            candidate_name=command.display_name,
            candidate_path=str(command.executable),
            status=status,
            attempts=tuple(attempts),
            runtime_approved=False,
            diagnostics={
                "attempt_count": len(attempts),
                "help_argument_count": len(HELP_ARGUMENTS),
                "total_timeout_seconds": self._total_timeout,
                "attempt_timeout_seconds": self._attempt_timeout,
                "reason": str(status.value),
            },
        )

    def _run_attempt(
        self,
        command: ProbeCommand,
        arguments: tuple[str, ...],
        deadline: Deadline,
        cancel: CancellationToken | None,
    ) -> MumuCliProbeAttempt:
        """执行单次帮助参数尝试。"""
        t0 = time.monotonic()
        args = (*command.prefix_arguments, *arguments)

        try:
            with tempfile.TemporaryDirectory(prefix="autogame-mumu-cli-probe-") as tmp_dir:
                td = Path(tmp_dir)
                stdout_path = td / "stdout.bin"
                stderr_path = td / "stderr.bin"

                spec = ProcessSpec(
                    name="mumu_cli_probe",
                    executable=command.executable,
                    arguments=args,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                )

                with ProcessSupervisor() as supervisor:
                    proc_result = supervisor.run(spec, deadline, cancel)

                reason = proc_result.termination_reason
                exit_code = proc_result.exit_code
                # 读取受限文本
                stdout_text, stdout_trunc = _read_limited_text(stdout_path, MAX_STDOUT_BYTES)
                stderr_text, stderr_trunc = _read_limited_text(stderr_path, MAX_STDERR_BYTES)
                combined = stdout_text + "\n" + stderr_text

                duration_ms = max(0, int((time.monotonic() - t0) * 1000))

                # 判定
                if stdout_trunc or stderr_trunc:
                    return MumuCliProbeAttempt(
                        arguments=arguments,
                        status=MumuCliAttemptStatus.OUTPUT_INVALID,
                        exit_code=exit_code,
                        duration_ms=duration_ms,
                        stdout_excerpt=stdout_text[:MAX_EXCERPT_CHARS] if stdout_text else "",
                        stderr_excerpt=stderr_text[:MAX_EXCERPT_CHARS] if stderr_text else "",
                        stdout_truncated=stdout_trunc,
                        stderr_truncated=stderr_trunc,
                        matched_markers=(),
                    )

                if reason == TerminationReason.NORMAL_EXIT or reason == TerminationReason.NONZERO_EXIT:
                    if _has_help_evidence(combined):
                        return MumuCliProbeAttempt(
                            arguments=arguments,
                            status=MumuCliAttemptStatus.HELP_EVIDENCE,
                            exit_code=exit_code,
                            duration_ms=duration_ms,
                            stdout_excerpt=stdout_text[:MAX_EXCERPT_CHARS] if stdout_text else "",
                            stderr_excerpt=stderr_text[:MAX_EXCERPT_CHARS] if stderr_text else "",
                            stdout_truncated=stdout_trunc,
                            stderr_truncated=stderr_trunc,
                            matched_markers=_match_help_markers(combined),
                        )
                    return MumuCliProbeAttempt(
                        arguments=arguments,
                        status=MumuCliAttemptStatus.NO_HELP_EVIDENCE,
                        exit_code=exit_code,
                        duration_ms=duration_ms,
                        stdout_excerpt=stdout_text[:MAX_EXCERPT_CHARS] if stdout_text else "",
                        stderr_excerpt=stderr_text[:MAX_EXCERPT_CHARS] if stderr_text else "",
                        stdout_truncated=stdout_trunc,
                        stderr_truncated=stderr_trunc,
                        matched_markers=(),
                    )

                if reason == TerminationReason.TIMEOUT:
                    return MumuCliProbeAttempt(
                        arguments=arguments,
                        status=MumuCliAttemptStatus.TIMEOUT,
                        exit_code=None,
                        duration_ms=duration_ms,
                        stdout_excerpt="",
                        stderr_excerpt="",
                        stdout_truncated=False,
                        stderr_truncated=False,
                        matched_markers=(),
                    )

                if reason == TerminationReason.CANCELLED:
                    return MumuCliProbeAttempt(
                        arguments=arguments,
                        status=MumuCliAttemptStatus.CANCELLED,
                        exit_code=None,
                        duration_ms=duration_ms,
                        stdout_excerpt="",
                        stderr_excerpt="",
                        stdout_truncated=False,
                        stderr_truncated=False,
                        matched_markers=(),
                    )

                if reason == TerminationReason.START_FAILED:
                    return MumuCliProbeAttempt(
                        arguments=arguments,
                        status=MumuCliAttemptStatus.START_FAILED,
                        exit_code=None,
                        duration_ms=duration_ms,
                        stdout_excerpt="",
                        stderr_excerpt="",
                        stdout_truncated=False,
                        stderr_truncated=False,
                        matched_markers=(),
                    )

                # fallback
                return MumuCliProbeAttempt(
                    arguments=arguments,
                    status=MumuCliAttemptStatus.START_FAILED,
                    exit_code=None,
                    duration_ms=duration_ms,
                    stdout_excerpt="",
                    stderr_excerpt="",
                    stdout_truncated=False,
                    stderr_truncated=False,
                    matched_markers=(),
                )

        except Exception:
            duration_ms = max(0, int((time.monotonic() - t0) * 1000))
            return MumuCliProbeAttempt(
                arguments=arguments,
                status=MumuCliAttemptStatus.START_FAILED,
                exit_code=None,
                duration_ms=duration_ms,
                stdout_excerpt="",
                stderr_excerpt="",
                stdout_truncated=False,
                stderr_truncated=False,
                matched_markers=(),
            )

    @staticmethod
    def _aggregate(attempts: list[MumuCliProbeAttempt]) -> MumuCliCandidateStatus:
        """从尝试列表聚合候选状态。"""
        if any(a.status == MumuCliAttemptStatus.HELP_EVIDENCE for a in attempts):
            return MumuCliCandidateStatus.HELP_DISCOVERED
        if any(a.status == MumuCliAttemptStatus.CANCELLED for a in attempts):
            return MumuCliCandidateStatus.CANCELLED
        if any(a.status == MumuCliAttemptStatus.TIMEOUT for a in attempts):
            return MumuCliCandidateStatus.UNSAFE_OR_HANGING
        return MumuCliCandidateStatus.NO_HELP_DISCOVERED


# ── JSON 序列化 ────────────────────────────────────────────────


def report_to_dict(report: MumuCliProbeReport) -> dict[str, JsonValue]:
    """将 MumuCliProbeReport 转换为 JSON 可序列化字典。"""
    attempts_list: list[JsonValue] = []
    for a in report.attempts:
        attempts_list.append(
            {
                "arguments": list(a.arguments),
                "status": a.status.value,
                "exit_code": a.exit_code,
                "duration_ms": a.duration_ms,
                "stdout_excerpt": a.stdout_excerpt,
                "stderr_excerpt": a.stderr_excerpt,
                "stdout_truncated": a.stdout_truncated,
                "stderr_truncated": a.stderr_truncated,
                "matched_markers": list(a.matched_markers),
            }
        )
    return {
        "candidate_name": report.candidate_name,
        "candidate_path": report.candidate_path,
        "status": report.status.value,
        "attempts": attempts_list,
        "runtime_approved": report.runtime_approved,
        "diagnostics": dict(report.diagnostics),
    }


# ── CLI 入口 ────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    """命令行入口。"""
    import argparse as _argparse_mod

    parser = _argparse_mod.ArgumentParser(description="MuMu 候选 CLI 安全诊断探针", add_help=True)
    parser.add_argument("--candidate", type=str, action="append", required=True, help="候选可执行文件路径（可重复）")
    parser.add_argument(
        "--attempt-timeout-seconds",
        type=float,
        default=DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
        help=f"单次尝试超时秒数（默认 {DEFAULT_ATTEMPT_TIMEOUT_SECONDS}）",
    )
    parser.add_argument(
        "--total-timeout-seconds",
        type=float,
        default=DEFAULT_TOTAL_TIMEOUT_SECONDS,
        help=f"总超时秒数（默认 {DEFAULT_TOTAL_TIMEOUT_SECONDS}）",
    )

    args = parser.parse_args(argv)

    # 验证候选路径
    commands: list[ProbeCommand] = []
    for cand_path_str in args.candidate:
        try:
            cmd = validate_mumu_candidate(Path(cand_path_str))
            commands.append(cmd)
        except ValueError as exc:
            print(f"错误: {exc}", file=sys.stdout)
            return 2

    probe = MumuCliProbe(
        attempt_timeout_seconds=args.attempt_timeout_seconds,
        total_timeout_seconds=args.total_timeout_seconds,
    )

    for cmd in commands:
        try:
            report = probe.probe(cmd)
            d = report_to_dict(report)
            print(json.dumps(d, indent=2, ensure_ascii=False))
        except Exception as exc:
            print(f"内部错误 ({cmd.display_name}): {exc}", file=sys.stdout)
            return 3

    # 检查进程残留
    try:
        import time as _time

        _time.sleep(0.2)
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
