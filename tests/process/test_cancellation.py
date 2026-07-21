"""CancellationToken 单元测试。"""

from __future__ import annotations

import pytest

from autogame_orchestrator.process.cancellation import CancellationToken


def test_initially_not_cancelled() -> None:
    """初始未取消。"""
    t = CancellationToken()
    assert not t.is_cancelled


def test_cancel() -> None:
    """cancel 后为已取消。"""
    t = CancellationToken()
    t.cancel()
    assert t.is_cancelled


def test_cancel_idempotent() -> None:
    """重复 cancel 不产生异常。"""
    t = CancellationToken()
    t.cancel()
    t.cancel()
    t.cancel()
    assert t.is_cancelled


def test_wait_timeout() -> None:
    """wait 在超时后返回 False。"""
    t = CancellationToken()
    result = t.wait(timeout_seconds=0.01)
    assert not result


def test_wait_cancelled() -> None:
    """wait 在取消后立即返回 True。"""
    t = CancellationToken()
    t.cancel()
    result = t.wait(timeout_seconds=1.0)
    assert result


def test_negative_timeout_rejected() -> None:
    """负 timeout 被拒绝。"""
    t = CancellationToken()
    with pytest.raises(ValueError, match="不能为负"):
        t.wait(timeout_seconds=-1.0)
