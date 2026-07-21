# 阶段 3——StarRailCopilot 手工验收说明

> **实施代理不得执行本文件中的任何真实命令。**
> 只有用户明确批准后，才允许执行真实 StarRailCopilot smoke。

## 前提条件

1. StarRailCopilot 已正确安装。
2. 已确认系统中没有旧 StarRailCopilot 实例（例如通过任务管理器查看 `python.exe`）。
3. MuMu 模拟器已启动且 ADB 就绪。
4. 已有本机 `toolkit\python.exe` 的完整路径。

## 步骤

### 1. 复制本地配置

```powershell
Copy-Item config/orchestrator.example.toml config/orchestrator.local.toml
```

### 2. 填入真实路径

编辑 `config/orchestrator.local.toml` 的 `[starrail]` 节。

### 3. 保持 MuMu 真实 start/stop 禁用

不得修改 `start_arguments` 和 `stop_arguments`。

### 4. 使用正式加载器执行

```python
from pathlib import Path

from autogame_orchestrator.config_loader import load_config
from autogame_orchestrator.process import Deadline
from autogame_orchestrator.runtime import StarRailAdapter

config_path = Path("config/orchestrator.local.toml")
config, errors = load_config(config_path, check_paths=True)

if errors or config is None:
    raise RuntimeError(f"配置验证失败: {[e.value for e in errors]}")

adapter = StarRailAdapter(config.starrail)
result = adapter.run(deadline=Deadline.after(600.0))

print(f"status={result.status.value}")
print(f"error_code={result.error_code.value}")
print(f"matched_keyword={result.matched_keyword}")
print(f"owned_process_cleaned={result.owned_process_cleaned}")
```

### 5. 核对结果

- `COMPLETED`：任务完成，匹配到 success 关键词
- `FAILED` + `FAILURE_KEYWORD`：匹配到 failure 关键词
- `TIMEOUT`：任务超时
- `owned_process_cleaned=True`：进程树已清理

### 6. 失败时手工恢复

1. 查看 StarRailCopilot 日志（`log\YYYY-MM-DD_src.txt`）。
2. 通过任务管理器确认没有残留 `python.exe`。
3. 调整配置后重试。

### 7. 确认未启动 MAA 或 AALC

start/stop/restart 都不应启动 MAA 或 AALC。
