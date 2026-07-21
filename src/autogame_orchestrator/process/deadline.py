"""单调时钟 Deadline，用于进程超时控制。

基于 ``time.monotonic()``，不受系统时钟调整影响。
"""

from __future__ import annotations

import time


class Deadline:
    """基于 ``time.monotonic()`` 的硬截止时间。

    ``remaining_seconds`` 单调递减，无法重置。
    ``clamp_timeout()`` 确保子操作不会超出总预算。
    """

    def __init__(self, target_monotonic: float) -> None:
        self._target = target_monotonic

    @classmethod
    def after(cls, duration_seconds: float) -> Deadline:
        """从当前时刻起，*duration_seconds* 后到期。"""
        if duration_seconds < 0:
            msg = f"duration_seconds 不能为负，收到 {duration_seconds}"
            raise ValueError(msg)
        return cls(time.monotonic() + duration_seconds)

    @classmethod
    def at(cls, monotonic_target: float) -> Deadline:
        """在指定的 monotonic 时间点到期。"""
        return cls(monotonic_target)

    @property
    def remaining_seconds(self) -> float:
        """剩余秒数，永不返回负值。"""
        return max(0.0, self._target - time.monotonic())

    @property
    def expired(self) -> bool:
        """是否已到期。"""
        return time.monotonic() >= self._target

    def clamp_timeout(self, requested_seconds: float) -> float:
        """将 *requested_seconds* 限制在 ``remaining_seconds`` 以内。

        保证子操作不会超出总 deadline。
        """
        if requested_seconds < 0:
            msg = f"requested_seconds 不能为负，收到 {requested_seconds}"
            raise ValueError(msg)
        return min(requested_seconds, self.remaining_seconds)
