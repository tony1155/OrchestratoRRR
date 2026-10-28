"""Bounded incremental parser for the official 0.64.0 instance-tagged log."""

import re
from dataclasses import dataclass, field
from pathlib import Path

HEADER = re.compile(
    r"^\[\d{2}:\d{2}:\d{2}\.\d{3}\] \[(\w{3})\] "
    r"\[((?:Primary|ChildSession|WebView):S\d+:P(\d+):T\d+)\] (.*)$"
)
MAX_READ = 1024 * 1024
MAX_FILES = 64
SOURCE = "BetterGenshinImpact.ViewModel.Pages.OneDragonFlowViewModel"


@dataclass
class Evidence:
    pid: int
    config_name: str
    started_after_ms: int = 0
    identity: str = ""
    configuration_confirmed: bool = False
    completion_confirmed: bool = False
    failed: bool = False
    cancelled: bool = False

    def event(self, header: re.Match[str], message: str) -> None:
        level, identity, pid, source = header.groups()
        if (
            int(pid) != self.pid
            or not identity.startswith("Primary:")
            or int(identity.rsplit(":T", 1)[1]) < self.started_after_ms
        ):
            return
        if self.identity and self.identity != identity:
            raise ValueError("Instance identity changed")
        self.identity = identity
        if level in {"ERR", "FTL"} or "执行配置组任务时失败" in message or message.startswith("任务中断:"):
            self.failed = True
        if any(text in message for text in ("任务被取消", "任务被手动取消", "一条龙在启动阶段被取消")):
            self.cancelled = True
        if source == SOURCE:
            if message == f"启用一条龙配置：{self.config_name}":
                self.configuration_confirmed = True
            elif message.startswith("启用一条龙配置："):
                self.failed = True
            if message == "一条龙和配置组任务结束" and self.configuration_confirmed:
                self.completion_confirmed = True


@dataclass
class _Cursor:
    offset: int
    inode: int
    pending: bytes = b""
    header: re.Match[str] | None = None
    lines: list[str] = field(default_factory=list)
    event_bytes: int = 0

    def consume(self, data: bytes, evidence: Evidence, *, final: bool) -> None:
        self.pending += data
        if len(self.pending) > MAX_READ * 2:
            raise ValueError("Log line exceeds limit")
        lines = self.pending.split(b"\n")
        self.pending = lines.pop()
        if final and self.pending:
            lines.append(self.pending)
            self.pending = b""
        for raw in lines:
            line = raw.decode("utf-8-sig", errors="strict").rstrip("\r")
            header = HEADER.match(line)
            if header:
                self.flush(evidence)
                self.header = header
            elif self.header:
                self.event_bytes += len(raw)
                if self.event_bytes > MAX_READ:
                    raise ValueError("Log event exceeds limit")
                self.lines.append(line)
        if final:
            self.flush(evidence)

    def flush(self, evidence: Evidence) -> None:
        if self.header:
            evidence.event(self.header, "\n".join(self.lines).strip())
        self.header = None
        self.lines.clear()
        self.event_bytes = 0


class BetterGILog:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.cursors: dict[Path, _Cursor] = {}
        for path in self.files():
            stat = path.stat()
            self.cursors[path] = _Cursor(stat.st_size, stat.st_ino)

    def files(self) -> list[Path]:
        paths = []
        for path in self.directory.glob("better-genshin-impact*.log"):
            paths.append(path)
            if len(paths) > MAX_FILES:
                raise ValueError("Too many log candidates")
        return sorted(paths)

    def read(self, evidence: Evidence, *, final: bool = False) -> None:
        budget = MAX_READ
        paths = self.files()
        if any(path not in paths and cursor.header for path, cursor in self.cursors.items()):
            raise ValueError("Active log disappeared")
        for path in paths:
            stat = path.stat()
            cursor = self.cursors.setdefault(path, _Cursor(0, stat.st_ino))
            if stat.st_ino != cursor.inode or stat.st_size < cursor.offset:
                raise ValueError("Log replaced or truncated")
            with path.open("rb") as stream:
                stream.seek(cursor.offset)
                data = stream.read(budget + 1)
            if len(data) > budget:
                raise ValueError("Log read budget exceeded")
            budget -= len(data)
            cursor.offset += len(data)
            cursor.consume(data, evidence, final=final)
