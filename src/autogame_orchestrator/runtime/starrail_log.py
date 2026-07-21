"""StarRailCopilot 增量日志读取与完成判定模块。

提供日志路径解析、启动前游标捕获、增量读取、关键词匹配功能。
"""

from __future__ import annotations

import locale
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from autogame_orchestrator.config_model import StarRailConfig

MAX_LOG_READ_BYTES = 64 * 1024
MAX_LOG_ROLLING_CHARS = 64 * 1024


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
