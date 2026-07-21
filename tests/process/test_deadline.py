"""Deadline 单元测试。"""

from __future__ import annotations

import time

import pytest

from autogame_orchestrator.process.deadline import Deadline


def test_positive_duration() -> None:
    """正时长创建有效 Deadline。"""
    d = Deadline.after(10.0)
    assert not d.expired
    assert d.remaining_seconds > 0


def test_zero_duration() -> None:
    """零时长立即过期。"""
    d = Deadline.after(0.0)
    assert d.expired
    assert d.remaining_seconds == 0.0


def test_negative_duration_rejected() -> None:
    """负时长被拒绝。"""
    with pytest.raises(ValueError, match="不能为负"):
        Deadline.after(-1.0)


def test_remaining_never_negative() -> None:
    """remaining_seconds 永不返回负值。"""
    d = Deadline.after(0.0)
    time.sleep(0.02)
    assert d.remaining_seconds >= 0.0


def test_expired() -> None:
    """已过去的 deadline 正确报告过期。"""
    d = Deadline.after(0.01)
    time.sleep(0.03)
    assert d.expired


def test_clamp_timeout() -> None:
    """clamp_timeout 将请求限制在剩余时间以内。"""
    d = Deadline.after(1.0)
    clamped = d.clamp_timeout(10.0)
    assert clamped <= 1.0


def test_clamp_timeout_negative_rejected() -> None:
    """clamp_timeout 拒绝负值。"""
    d = Deadline.after(1.0)
    with pytest.raises(ValueError, match="不能为负"):
        d.clamp_timeout(-0.1)


def test_absolute_monotonic_deadline() -> None:
    """使用绝对 monotonic 时间创建 deadline。"""
    target = time.monotonic() + 5.0
    d = Deadline.at(target)
    assert d.remaining_seconds >= 0.0
    assert not d.expired


def test_sub_operation_cannot_reset() -> None:
    """子操作不能重置总 budget。"""
    d = Deadline.after(0.2)
    time.sleep(0.05)
    r1 = d.remaining_seconds
    time.sleep(0.05)
    r2 = d.remaining_seconds
    # remaining 单调递减
    assert r2 <= r1
