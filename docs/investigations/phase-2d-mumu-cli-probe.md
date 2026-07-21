# 阶段 2D——MuMu 候选 CLI 安全探针调查

## 调查日期

2026-07-21

## 候选路径

| 候选 | 路径 |
|---|---|
| MuMuManager.exe | `D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuManager.exe` |
| NemuShell.exe | `D:\Program Files\Netease\MuMu Player 12\nx_device\12.0\shell\NemuShell.exe` |

## 门禁检查

| 进程 | PID | 状态 |
|---|---|---|
| MuMuNxDevice | 34804 | 运行中 |
| MuMuNxMain | 27832 | 运行中 |
| MuMuRemoteBackend | 8272 | 运行中 |

**真实候选探测因 MuMu 用户进程仍在运行而安全跳过。** 不结束进程，不要求管理员权限，不执行候选 exe。

## 实际是否执行

**否。** 因安全门禁未通过，真实 `--help`/`-h`/`/?` 均未执行。

## 探针工具状态

探针代码、Fake CLI 测试、CLI 入口均已完成并通过自动验收（260 项全量测试，22 项 diagnostics 测试）。

Fake CLI 覆盖场景：help_stdout、help_stderr_nonzero、no_output、unrelated_output、utf16_help、large_output、sleep_forever。

测试通过 ProcessSupervisor 真实执行，验证了：
- 帮助证据识别（英文/中文/UTF-16）
- 超大输出截断拒绝
- timeout 后进程 PID 清理
- cancellation 精确映射
- 总 Deadline 不被子操作重置
- 第一个参数发现帮助后停止后续参数

## 最终证据分类

**D：因安全门禁未执行真实候选。**

真实帮助探测需要 MuMu 用户进程完全退出（非服务进程）后才能安全执行。

## 下一步

1. 安全窗口出现时（MuMuNxMain/NxDevice 退出），可执行：
   ```powershell
   python -m autogame_orchestrator.diagnostics.mumu_cli_probe `
     --candidate 'D:\...\MuMuManager.exe' `
     --candidate 'D:\...\NemuShell.exe'
   ```
2. 即使发现帮助证据，仍需独立验证 start/stop 命令语法和进程所有权后才能解除生产阻塞。
3. 当前 `start_arguments` 和 `stop_arguments` 继续为空。
