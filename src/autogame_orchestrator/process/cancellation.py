"""CancellationToken：线程安全的一次性取消信号。

基于 ``threading.Event``，用于在多线程环境中通知操作停止。
阶段 1A 只实现 token 本身，不与进程等待组合。
"""

from __future__ import annotations

import threading


class CancellationToken:
    """线程安全的一次性取消令牌。

    ``cancel()`` 幂等。``is_cancelled`` 多线程可见。
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        """是否已被取消。"""
        return self._event.is_set()

    def cancel(self) -> None:
        """设置取消信号（幂等）。"""
        self._event.set()

    def wait(self, timeout_seconds: float | None = None) -> bool:
        """等待直到取消或超时。

        Args:
            timeout_seconds: 最长等待秒数。``None`` 表示无限等待。

        Returns:
            ``True`` 如果在超时前被取消，``False`` 表示超时。
        """
        if timeout_seconds is not None and timeout_seconds < 0:
            msg = f"timeout_seconds 不能为负，收到 {timeout_seconds}"
            raise ValueError(msg)
        return self._event.wait(timeout=timeout_seconds)
