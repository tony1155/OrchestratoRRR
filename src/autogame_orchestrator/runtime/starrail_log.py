"""StarRailCopilot 增量日志读取与完成判定模块。

提供日志路径解析、启动前游标捕获、增量读取、关键词匹配功能。
"""

from __future__ import annotations

import locale
import os
import stat as stat_module
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from autogame_orchestrator.config_model import StarRailConfig

MAX_LOG_READ_BYTES = 64 * 1024
MAX_LOG_ROLLING_CHARS = 64 * 1024
MAX_LOG_CANDIDATES = 128
LOG_CANDIDATE_AMBIGUOUS = "LOG_CANDIDATE_AMBIGUOUS"
LOG_DISCOVERY_FAILED = "LOG_DISCOVERY_FAILED"


@dataclass
class StarRailLogCursor:
    path: Path
    offset: int
    file_identity: tuple[int, int] | None
    rolling_text: str = ""


@dataclass(frozen=True)
class StarRailLogUpdate:
    text: str
    overflow: bool
    rotated: bool


@dataclass(frozen=True)
class StarRailKeywordMatch:
    kind: str
    keyword: str


@dataclass(frozen=True)
class StarRailLogCandidateSnapshot:
    path: Path
    file_identity: tuple[int, int]
    size: int
    is_exact: bool


@dataclass(frozen=True)
class StarRailLogTemplateSpec:
    exact_path: Path
    dynamic_discovery_enabled: bool
    filename_prefix: str
    filename_suffix: str

    def matches_name(self, name: str) -> bool:
        if name == self.exact_path.name:
            return True
        if not self.dynamic_discovery_enabled:
            return False
        if not name.startswith(self.filename_prefix) or not name.endswith(self.filename_suffix):
            return False
        insertion_end = len(name) - len(self.filename_suffix) if self.filename_suffix else len(name)
        return insertion_end > len(self.filename_prefix)


class StarRailLogDiscoveryError(OSError):
    """Fail-closed bounded log candidate discovery error."""

    def __init__(self, primary_error: str, candidate_count: int) -> None:
        super().__init__(primary_error)
        self.primary_error = primary_error
        self.candidate_count = candidate_count


class StarRailLogTracker:
    """Track one bounded log candidate from a pre-launch directory snapshot."""

    def __init__(
        self,
        spec: StarRailLogTemplateSpec,
        snapshot: tuple[StarRailLogCandidateSnapshot, ...],
    ) -> None:
        self.spec = spec
        self.snapshot = snapshot
        self.active_cursor: StarRailLogCursor | None = None
        self._snapshot_by_path = {_path_key(item.path): item for item in snapshot}

    @property
    def log_path(self) -> Path:
        if self.active_cursor is not None:
            return self.active_cursor.path
        return self.spec.exact_path

    def discover(self) -> StarRailLogCursor | None:
        """Activate exactly one candidate changed since the pre-launch snapshot."""
        current = _scan_log_candidates(self.spec)
        changed = [item for item in current if self._changed_since_snapshot(item)]

        if self.active_cursor is not None:
            active_key = _path_key(self.active_cursor.path)
            competing = [item for item in changed if _path_key(item.path) != active_key]
            if competing:
                raise StarRailLogDiscoveryError(LOG_CANDIDATE_AMBIGUOUS, 1 + len(competing))
            return self.active_cursor

        if not changed:
            return None
        if len(changed) > 1:
            raise StarRailLogDiscoveryError(LOG_CANDIDATE_AMBIGUOUS, len(changed))

        candidate = changed[0]
        previous = self._snapshot_by_path.get(_path_key(candidate.path))
        offset = 0
        if (
            previous is not None
            and previous.file_identity == candidate.file_identity
            and candidate.size >= previous.size
        ):
            offset = previous.size
        self.active_cursor = StarRailLogCursor(
            path=candidate.path,
            offset=offset,
            file_identity=candidate.file_identity,
            rolling_text="",
        )
        return self.active_cursor

    def _changed_since_snapshot(self, candidate: StarRailLogCandidateSnapshot) -> bool:
        previous = self._snapshot_by_path.get(_path_key(candidate.path))
        if previous is None:
            return True
        return previous.file_identity != candidate.file_identity or previous.size != candidate.size


def resolve_starrail_log_path(config: StarRailConfig, *, now: datetime | None = None) -> Path:
    """解析日志路径，替换 {date} 占位符为当前本地日期。"""
    effective_now = now or datetime.now()
    date_str = effective_now.strftime("%Y-%m-%d")
    rendered = config.log_path_template.replace("{date}", date_str)

    if "{" in rendered or "}" in rendered:
        msg = f"日志模板替换后仍包含未识别的占位符: {rendered}"
        raise ValueError(msg)

    path = Path(rendered)
    if not path.is_absolute():
        path = Path(config.working_directory) / rendered

    return path.resolve(strict=False)


def capture_starrail_log_snapshot(
    config: StarRailConfig, *, now: datetime | None = None
) -> StarRailLogTracker:
    """Capture all bounded matching candidates before the managed process starts."""
    spec = _build_log_template_spec(config, now=now)
    return StarRailLogTracker(spec, _scan_log_candidates(spec))


def _build_log_template_spec(config: StarRailConfig, *, now: datetime | None = None) -> StarRailLogTemplateSpec:
    effective_now = now or datetime.now()
    date_str = effective_now.strftime("%Y-%m-%d")
    exact_path = resolve_starrail_log_path(config, now=effective_now)
    template_path = Path(config.log_path_template)
    filename = template_path.name
    dynamic_enabled = filename.count("{date}") == 1 and "{date}" not in str(template_path.parent)
    prefix = exact_path.name
    suffix = ""
    if dynamic_enabled:
        before, after = filename.split("{date}", 1)
        prefix = before + date_str
        suffix = after
    return StarRailLogTemplateSpec(
        exact_path=exact_path,
        dynamic_discovery_enabled=dynamic_enabled,
        filename_prefix=prefix,
        filename_suffix=suffix,
    )


def _scan_log_candidates(spec: StarRailLogTemplateSpec) -> tuple[StarRailLogCandidateSnapshot, ...]:
    paths: list[Path]
    if spec.dynamic_discovery_enabled:
        paths = [path for path in spec.exact_path.parent.iterdir() if spec.matches_name(path.name)]
    else:
        paths = [spec.exact_path] if spec.exact_path.exists() else []

    if len(paths) > MAX_LOG_CANDIDATES:
        raise StarRailLogDiscoveryError(LOG_DISCOVERY_FAILED, len(paths))

    candidates: list[StarRailLogCandidateSnapshot] = []
    for path in paths:
        try:
            item_stat = path.lstat()
        except FileNotFoundError:
            continue
        attributes = getattr(item_stat, "st_file_attributes", 0)
        reparse_flag = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if path.is_symlink() or (reparse_flag and attributes & reparse_flag):
            raise StarRailLogDiscoveryError(LOG_DISCOVERY_FAILED, len(paths))
        if not stat_module.S_ISREG(item_stat.st_mode):
            continue
        resolved = path.resolve(strict=False)
        candidates.append(
            StarRailLogCandidateSnapshot(
                path=resolved,
                file_identity=(item_stat.st_dev, item_stat.st_ino),
                size=item_stat.st_size,
                is_exact=_path_key(resolved) == _path_key(spec.exact_path),
            )
        )
    return tuple(candidates)


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def capture_log_cursor(path: Path) -> StarRailLogCursor:
    """捕获启动前的日志游标。已有内容视为旧日志。"""
    try:
        stat = path.stat()
        offset = stat.st_size
        identity = (stat.st_dev, stat.st_ino)
    except FileNotFoundError:
        offset = 0
        identity = None

    return StarRailLogCursor(
        path=path,
        offset=offset,
        file_identity=identity,
        rolling_text="",
    )


def _decode_log_data(data: bytes) -> str:
    """解码日志数据。"""
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", errors="strict")
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        pass
    if data.startswith(b"\xff\xfe") or (len(data) >= 2 and data[1::2].count(0) * 3 >= len(data[1::2])):
        try:
            enc = "utf-16" if data.startswith(b"\xff\xfe") else "utf-16-le"
            return data.decode(enc, errors="strict")
        except UnicodeDecodeError:
            pass
    preferred = locale.getpreferredencoding(False)
    try:
        return data.decode(preferred, errors="strict")
    except (LookupError, UnicodeDecodeError):
        pass
    return data.decode("utf-8", errors="replace")


def read_log_update(cursor: StarRailLogCursor, *, max_bytes: int = MAX_LOG_READ_BYTES) -> StarRailLogUpdate:
    """增量读取日志文件的新增内容。"""
    try:
        stat = cursor.path.stat()
    except FileNotFoundError:
        return StarRailLogUpdate(text="", overflow=False, rotated=False)
    except OSError:
        raise

    new_identity = (stat.st_dev, stat.st_ino)

    rotated = False

    if cursor.file_identity is None:
        cursor.file_identity = new_identity
    elif new_identity != cursor.file_identity:
        cursor.offset = 0
        cursor.rolling_text = ""
        cursor.file_identity = new_identity
        rotated = True
    elif stat.st_size < cursor.offset:
        cursor.offset = 0
        cursor.rolling_text = ""
        rotated = True

    if stat.st_size <= cursor.offset:
        return StarRailLogUpdate(text="", overflow=False, rotated=rotated)

    with cursor.path.open("rb") as stream:
        stream.seek(cursor.offset)
        data = stream.read(max_bytes + 1)

    overflow = len(data) > max_bytes
    if overflow:
        data = data[:max_bytes]

    text = _decode_log_data(data)
    cursor.offset += len(data)
    cursor.rolling_text = (cursor.rolling_text + text)[-MAX_LOG_ROLLING_CHARS:]

    return StarRailLogUpdate(text=text, overflow=overflow, rotated=rotated)


def match_starrail_keyword(
    text: str, *, success_keywords: tuple[str, ...], failure_keywords: tuple[str, ...]
) -> StarRailKeywordMatch | None:
    """在文本中按配置顺序搜索关键词。failure 优先。"""
    for kw in failure_keywords:
        if kw in text:
            return StarRailKeywordMatch(kind="failure", keyword=kw)
    for kw in success_keywords:
        if kw in text:
            return StarRailKeywordMatch(kind="success", keyword=kw)
    return None
