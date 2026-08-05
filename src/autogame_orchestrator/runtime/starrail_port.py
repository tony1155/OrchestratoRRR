"""StarRailCopilot 启动参数端口占位符契约。

复刻旧 PowerShell ``Resolve-LaunchArguments`` 的替换语义：在启动前
把启动参数中的字面量占位符 ``__PROGRAM_PORT__`` 替换为一个有效的
本地 TCP 端口。仅在 StarRail 启动边界使用。

契约要点：

* 零占位符：参数原样返回，不分配端口。
* 一个或多个占位符（跨参数或同一参数内）：分配单个端口，
  并把所有出现处替换为同一端口值。
* 端口分配失败：抛出 :class:`PortAllocationError`（fail-closed），
  调用方不得启动外部程序。
* 分配的实际端口不得进入日志、RunReport、JSONL、异常或诊断。
"""

from __future__ import annotations

import socket

PROGRAM_PORT_PLACEHOLDER = "__PROGRAM_PORT__"

# 有效的动态/临时 TCP 端口下界，避免落入知名端口区间。
_MIN_DYNAMIC_PORT = 1
_MAX_TCP_PORT = 65535


class PortAllocationError(RuntimeError):
    """无法取得可用的本地 TCP 端口。

    消息稳定、可诊断，且不包含任何实际端口值。
    """


def contains_program_port_placeholder(arguments: tuple[str, ...]) -> bool:
    """判断参数序列中是否存在字面量端口占位符。"""
    return any(PROGRAM_PORT_PLACEHOLDER in arg for arg in arguments)


def allocate_local_tcp_port() -> int:
    """取得一个有效的本地回环 TCP 端口。

    绑定到 ``127.0.0.1:0`` 让操作系统分配一个空闲端口，读取其编号后
    立即释放。返回的端口一定落在有效的 TCP 端口范围内。

    失败时抛出 :class:`PortAllocationError`，且异常消息不含端口值。
    """
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    except OSError as exc:
        raise PortAllocationError("无法取得可用的本地 TCP 端口") from exc
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    if not isinstance(port, int) or not (_MIN_DYNAMIC_PORT <= port <= _MAX_TCP_PORT):
        raise PortAllocationError("分配的本地 TCP 端口无效")

    return port


def resolve_launch_arguments(arguments: tuple[str, ...]) -> tuple[str, ...]:
    """替换启动参数中的端口占位符契约。

    * 无占位符时原样返回（同一元组内容），不分配端口。
    * 存在一个或多个占位符时，分配单个本地 TCP 端口，并把每个参数中
      所有出现的 ``__PROGRAM_PORT__`` 替换为该端口的十进制字符串。

    端口分配失败时抛出 :class:`PortAllocationError`；调用方必须据此
    fail-closed，不得启动外部程序。
    """
    if not contains_program_port_placeholder(arguments):
        return arguments

    port = allocate_local_tcp_port()
    port_text = str(port)
    return tuple(arg.replace(PROGRAM_PORT_PLACEHOLDER, port_text) for arg in arguments)
