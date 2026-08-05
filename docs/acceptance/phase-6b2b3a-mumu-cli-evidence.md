# Phase 6B2B3A——MuMu CLI 探针加固与否定证据

## 验收范围

本阶段只加固 MuMu 候选 CLI 诊断入口的路径隐私、公开结果投影和模块执行行为，并固化已经由用户提供的只读帮助探针结论。执行日期为 2026-07-30，执行分支为 `phase/6-complete-workflow`。

本阶段没有再次执行真实候选，没有执行 MuMu、ADB、NemuShell RPC 命令或任何生命周期管理命令，也没有读取 `.nemu` 文件。

## 脱敏真实证据

受控只读探针只发现一个候选，文件名为 `NemuShell.exe`。探针使用固定参数 `--help`，退出码为 0，状态为 `help_discovered`；单次尝试状态为 `help_evidence`，stdout 和 stderr 均未截断，固定白名单 marker 为 `usage` 与 `instance`。探针本身退出码为 0，仓库未被修改，`runtime_approved=false`。

帮助信息只能规范化为以下调用形状：

```text
NemuShell.exe <HOST_NAME> <RPC_INSTANCE> <CMD>
```

帮助提示 `RPC_INSTANCE` 来源与 `.nemu` 文件有关。这只能证明该入口面向已有实例发送 RPC/Shell 命令，不能证明它具备模拟器生命周期管理能力。

## 否定结论

- 帮助没有提供启动、关闭或重启模拟器实例的命令。
- 没有获得可验证的 MuMu 管理实例索引或安全实例选择器。
- `RPC_INSTANCE` 不得推断为生命周期管理实例编号。
- 不得据此填充生产 `start_arguments` 或 `stop_arguments`。
- MuMu start 与 stop 继续为 `UNSAFE`，实例选择继续为 `BLOCKED`。
- `runtime_approved=false`，MuMu 生命周期生产门禁继续保持。

## 诊断加固

公开 JSON 不再包含候选路径、stdout excerpt 或 stderr excerpt，只投影候选文件名、固定帮助参数、稳定状态、退出码、耗时、输出存在性、截断标志和白名单 marker。候选验证失败只返回稳定错误码，不复制输入路径；内部异常不复制异常文本。

诊断包初始化不再提前导入 `mumu_cli_probe`，因此 `python -m autogame_orchestrator.diagnostics.mumu_cli_probe` 不再产生模块已提前进入 `sys.modules` 的 RuntimeWarning。成功执行时 stdout 只包含一个 JSON document。

内部模型仍可有界保留输出 excerpt 以判定帮助证据，但这些原文不进入公开 JSON、文档、日志或 RunReport，临时输出文件继续在 finally 中清理。

## 验收结论

Phase 6B2B3A 的诊断加固与否定证据固化完成。真实只读证据不足以授权 MuMu 生命周期管理：MuMu start/stop 未实现，实例选择未解析，Phase 6B2B3B 未获授权。Phase 6B2 与 Phase 6 整体仍未完成。
