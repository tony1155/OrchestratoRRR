# Phase 4 MAA smoke 手册

经用户批准后，使用正式的 `load_config()` 读取本机配置，并以 `MAAAdapter` 执行一次受控调用。实施代理不得执行真实 smoke。

成功仅由退出码 0 决定；不得根据输出关键词判定成功。
