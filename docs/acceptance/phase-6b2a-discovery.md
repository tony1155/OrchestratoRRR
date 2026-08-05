# Phase 6B2A——旧流程静态契约调查

## 1. 调查范围与方法

本记录只固化旧流程中 MAA 配置同步、MAA 更新、MuMu 启停/实例选择，以及成功、失败、超时和所有权语义。调查日期为 2026-07-30，分支为 `phase/6-complete-workflow`。

调查仅使用 PowerShell Parser/AST、文本读取、文件元数据、SHA-256 和安全路径解析。旧脚本及其中任何函数均未执行或导入；未启动任何程序、网络、UAC、更新器或设备工具。

AST 解析无错误。索引覆盖变量赋值、数组、Hashtable、`Join-Path`、`Split-Path`、字符串插值、参数默认值、函数调用、进程启动调用形状、调用运算符、复制/删除/存在性检查、进程查询、文件轮询、退出码、循环及 `try/catch/finally`。没有发现 dot-source 或模块导入，因此允许读取范围止于主脚本直接引用的四个 JSON 文件。

## 2. 证据文件

| 文件名 | SHA-256 | 类型 | 引用关系 |
|---|---|---|---|
| `Invoke-LocalOrchestrator.ps1` | `BE95C1C863E5F7C1372D9442BBAE8A887E7118EDAB9FA0270C06C7FF9625EFA7` | PowerShell | 调查主证据 |
| `gui.json` | `DDF1B8D2C5452A94550A2B52D031949A2396EC4008DACE2CBE166E5DF0B71A37` | JSON | GUI 设置源 |
| `gui.new.json` | `6D662896EE96010446B9FB8C36450D6721CB933970E9FBA5346796B476E153CF` | JSON | GUI 任务源 |
| `orchestrator.json`（profile） | `C632C25E163261010D3C3A98E19A3CB5CB10EECAE7A850A4A37F960190AA88F3` | JSON | CLI profile 目标 |
| `orchestrator.json`（tasks） | `33E3DC2FB8E65871024CB5321014216AE2D5D6196E053B2EF231BA001F1710FE` | JSON | CLI tasks 目标 |

只记录文件名和哈希；未固化路径或内容。

## 3. MAA 配置同步契约

### 3.1 静态行为

`Sync-MAAConfigurationFromGui` 读取两个 GUI JSON 源，并分别从 `Current` 指定的配置块取值；`Current` 为空时使用第一个配置块。它将连接/实例选项转换为一个 CLI profile，并把受支持的任务队列转换为一个 CLI tasks 文件。启用但无法转换的任务、空任务队列、缺少当前配置或缺少源文件均抛出配置错误。

目标是两个生成的 JSON 文件，不是目录镜像，也不是原文件直拷贝。目标父目录不存在时创建。已有目标先复制到固定 `.bak` 名称并覆盖旧备份，然后直接写入最终目标；没有临时文件和原子替换。没有删除源或额外目标，没有比较时间、大小、哈希或内容，因此每次启用都会重新生成并覆盖。无变化没有特殊分支，只要转换和写入成功就视为成功。

转换可能包含账号名、设备连接地址、设备工具路径和任务偏好，隐私等级高。旧脚本日志还会记录部分连接信息；新实现不得照搬该日志行为。

### 3.2 规范化结果

```text
source_kind=generated
source_files=2
destination_kind=file
destination_files=2
profile_selection=current_or_first
copy_mode=overwrite
backup_mode=fixed_suffix_overwrite
atomicity=non_atomic
content_comparison=none
no_change_semantics=success
failure_semantics=blocking
requires_administrator=unknown
privacy_risk=high
```

目标不存在时直接创建；源不存在时阻断；已有目标覆盖前创建/覆盖固定备份；不删除旧文件。脚本没有专门的管理员检查，实际写权限取决于目标位置，故不能静态断言不需要管理员权限。

### 3.3 可实施性

状态：`PARTIAL`。转换规则、源/目标角色和失败阻断已解析，但原实现非原子、固定备份可能被覆盖，且涉及高隐私数据。6B2B 在确定隐私白名单、原子替换、备份保留和日志脱敏前不得实现。

## 4. MAA 更新契约

### 4.1 命令形状

旧流程仅在 `all` 与 `maa` 模式执行更新，并在配置同步之后、MuMu 启动之前执行。入口角色与 MAA 运行入口相同，工作目录和环境也复用 MAA 配置。按开关依次执行以下最多三条命令：

```text
self_update_arguments=[<self>, <update>, <batch>, <run-log-placeholder>]
core_update_arguments=[<update>, <channel-placeholder>, <batch>, <run-log-placeholder>]
hot_update_arguments=[<hot-update>, <batch>, <run-log-placeholder>]
```

这是脱敏参数模板，不是完整命令行。默认频道为稳定频道，单命令超时默认 1800 秒。各命令顺序执行，无更新级重试；任一启动、等待、超时或明确非零退出均抛出更新错误并阻断后续流程。超时后尝试终止该短命令进程。

成功不解析输出关键词。可读取到的退出码为 0 时成功；非零失败。旧实现若最终退出码不可读取，也没有将其判为失败，这是需要新实现收紧的缺口。没有显式取消入口。

脚本未直接调用 Git、依赖安装器或包管理器。命令名称表明更新可能访问网络，但具体传输方式和离线行为无法从脚本证明，因此网络影响只能标为 `possible`。更新之后不再次同步配置。

### 4.2 规范化结果

```text
executable_role=maa_cli
arguments=[<one-of-three-static-templates>]
working_directory_role=maa_working_directory
success_signal=exit_code
allowed_success_exit_codes=[0]
timeout_seconds=1800
retry_policy=none
cancellation=unresolved
network_effect=possible
git_invocation=none_in_script
dependency_installation=none_in_script
failure_semantics=blocking
requires_administrator=unknown
post_update_sync=false
```

### 4.3 所有权与可实施性

更新命令是由编排器直接创建并等待的短进程，命令进程本身可视为受管；但 self-update 是否派生替换进程、子进程是否应随 Job 关闭以及文件替换语义均为 `UNRESOLVED`。

状态：`PARTIAL`。命令模板、顺序、超时和明确退出码语义已解析，但网络、自更新子进程、取消和不可读取退出码的安全规则未闭合。不得据此直接实现 6B2B。

## 5. MuMu 控制契约

### 5.1 启动入口与实例选择

旧脚本没有调用独立的管理命令短进程。`Start-MuMuSafely` 直接启动 MuMu 长期 GUI 主进程，参数数组默认为空。启动前按主程序文件名和路径查找已运行进程；存在时复用候选，不创建新实例。候选按主窗口、启动时间和进程标识排序，但没有显式实例选择器。

新启动的 readiness 依次参考：主进程存活、可选主窗口、指定日志中的默认实例完成关键词、稳定等待和最终存活。复用既有进程时跳过新启动日志，只验证进程/窗口与稳定等待。后续 ADB readiness 使用配置的设备目标直接探测状态与系统启动完成值；空设备目标会落入另一个默认设备名。旧证据因此只支持“隐式默认实例”，不支持精确实例选择。

脱敏模板只能写为：

```text
start_arguments=[]
stop_arguments=UNRESOLVED
instance_selector=UNRESOLVED
instance_source=implicit_default_log_and_device_target
```

### 5.2 停止语义

旧脚本保存启动或复用的主进程对象。停止时以该根进程为锚，通过 WMI 枚举后代，并将同安装根、允许名称的相关进程加入候选。先对有窗口的候选发送优雅关闭，再轮询候选是否全部消失；默认允许在超时后强制停止，且有系统进程终止工具的树终止回退。

该逻辑不是实例化管理命令，可能覆盖同一安装根下名称匹配的其他实例。没有“只针对目标实例”的充分静态证据。候选为空被视为停止成功；候选全部消失也成功；超时且禁止强制停止时失败；强制阶段结束仍有候选时失败。

### 5.3 时间与取消

```text
process_poll_interval_ms=1000
main_process_wait_seconds=20
ready_log_timeout_seconds=120
startup_fallback_wait_seconds=45
stabilization_seconds=10
stop_timeout_seconds=30
force_stop_timeout_seconds=max(stop_timeout,15)
cancellation=not_implemented
```

进程启动调用返回只表示创建请求成功，不能单独表示模拟器 ready；旧脚本在额外 readiness 后才完成 Stage。停止也不是短管理命令退出语义，而是候选进程集合消失语义。

### 5.4 所有权判断

| 对象 | owned_by_orchestrator | job_object_safe | command_process_short_lived | long_lived_child_expected | cleanup_strategy |
|---|---|---|---|---|---|
| MAA 更新命令 | `true`（命令本身） | `unknown`（self-update 子进程未解析） | `true` | `unknown` | 超时终止命令；正常等待退出 |
| MuMu 管理命令 | `false`（旧流程不存在独立管理命令） | `unknown` | `false` | `true` | 不适用；旧流程直接启动长期主进程 |
| MuMu 长期进程 | `partial` | `false`（若直接置于 kill-on-close Job） | `false` | `true` | 根进程、后代、同安装根名称集合的优雅关闭与可选强制停止 |

当前 `MumuAdapter` 的“短管理命令受管、模拟器仅 readiness 验证”模型与旧脚本不直接兼容。把旧脚本的长期 GUI 入口当作短管理命令交给 `ProcessSupervisor`，在 Job 关闭时存在终止刚启动模拟器的风险。没有可据以填充生产 `start_arguments`/`stop_arguments`/实例选择器的静态证据。

结论：MuMu start 为 `UNSAFE`，stop 为 `UNSAFE`，实例选择为 `BLOCKED`，所有权为 `PARTIAL`。

## 6. 冻结工作流顺序核对

| 当前 Stage | 旧脚本等价 | 顺序匹配 | 前置条件 | 成功条件 | 失败行为 | 证据状态 |
|---|---|---|---|---|---|---|
| `VALIDATE_CONFIG` | 分散的配置/可执行文件检查 | 部分 | 脚本配置已加载 | 检查未抛错 | 阻断 | `PARTIAL` |
| `SYNC_MAA_CONFIG` | `Sync-MAAConfigurationFromGui` | 是 | 两个源 JSON 可读 | 两个目标生成成功 | 阻断 | `PARTIAL` |
| `UPDATE_MAA` | `Invoke-MAAPreUpdate` | 是 | 同步完成、入口存在 | 所有启用命令完成 | 阻断 | `PARTIAL` |
| `ENSURE_MUMU_RUNNING` | `Start-MuMuSafely` 前半 | 是 | 长期入口存在 | 复用或创建主进程 | 阻断 | `UNSAFE` |
| `WAIT_MUMU_ADB_READY` | MuMu 日志 readiness；程序前另有 ADB readiness | 概念匹配 | 主进程存在 | 日志/设备探测满足 | 超时阻断 | `PARTIAL` |
| `RUN_STARRAIL` | `Invoke-ProgramFlow(StarRail)` | 是 | MuMu ready | 既有完成判定 | 阻断 | `READY` |
| `STOP_STARRAIL` | 完成监控中的受管进程清理 | 显式拆分 | StarRail 已运行 | 本次受管进程清理 | 阻断 | `PARTIAL` |
| `VERIFY_STARRAIL_STOPPED` | 无独立 Stage | 显式新增 | 清理完成 | 所有权证据成立 | 阻断 | `PARTIAL` |
| `STOP_MUMU` | `Stop-ProcessSafely` | 是 | 持有根进程对象 | 广义候选集合消失 | 阻断 | `UNSAFE` |
| `VERIFY_MUMU_STOPPED` | 停止函数内部轮询 | 显式拆分 | 停止已请求 | 候选集合为空 | 阻断 | `PARTIAL` |
| `START_MUMU` | 第二次 `Start-MuMuSafely` | 是 | 旧停止成功 | 复用或创建主进程 | 阻断 | `UNSAFE` |
| `WAIT_MUMU_ADB_READY_AFTER_RESTART` | 第二次日志 readiness；MAA 前另有 ADB readiness | 概念匹配 | 主进程存在 | 日志/设备探测满足 | 超时阻断 | `PARTIAL` |
| `RUN_MAA` | `Invoke-ProgramFlow(MAA)` | 是 | 更新、MuMu、设备 ready | 既有完成判定 | 阻断 | `READY` |
| `RUN_AALC` | 有限重试 AALC flow | 是 | MuMu/设备 ready、入口已提升 | 有限尝试成功 | 阻断 | `READY` |
| `WRITE_RUN_REPORT` | 仅有运行日志和退出码 | 新增 | 前序已最终化 | RunReport 原子写入 | 写入错误 | `READY`（当前实现） |

同步与更新顺序与冻结计划一致：先同步、后更新。旧流程将 MuMu 启动与 readiness、停止与验证分别合在函数内部；冻结计划只是将这些语义拆成显式 Stage，没有重排业务顺序。总体 `workflow_order_matches=true`，但 MuMu 等价项不代表已获安全实现许可。

## 7. UAC 与权限时点

旧脚本在 `all` 或 `aalc` 模式入口处检查权限；普通权限时立即重启整个 PowerShell 入口并等待退出。提升发生在同步、更新和第一次 MuMu 操作之前，不是在 AALC Stage 到达时临时执行。`starrail` 与 `maa` 单独模式不主动提升。

因此，包含要求管理员权限的 AALC 的完整计划应在第一个 Stage 前提升整个 OrchestratoRRR，和当前 Phase 6 前置决策一致。MAA 同步、更新及 MuMu 控制本身是否必需管理员权限仍为 `UNRESOLVED`，不能从 `all` 模式的整体提升反推。

## 8. 配置模型草案（不实施）

所有路径默认值都必须为空，不得把调查机器值写入仓库。

### 8.1 `[maa_sync]`

| 字段 | 严格类型 | 默认值 | 必填 | 隐私 | 来源证据 | 校验规则 |
|---|---|---|---|---|---|---|
| `enabled` | bool | `false` | 否 | 低 | 旧同步开关 | 严格 bool |
| `gui_settings_source` | str | `""` | 启用时 | 高 | GUI 设置源 | 普通文件；不得记录内容 |
| `gui_tasks_source` | str | `""` | 启用时 | 高 | GUI 任务源 | 普通文件；不得记录内容 |
| `cli_profile_destination` | str | `""` | 启用时 | 高 | profile 目标 | 父目录受控；禁止源目标相同 |
| `cli_tasks_destination` | str | `""` | 启用时 | 高 | tasks 目标 | 父目录受控；禁止源目标相同 |
| `backup_enabled` | bool | `true` | 否 | 中 | 旧固定备份 | 严格 bool；备份策略待确认 |
| `atomic_replace` | bool | `true` | 否 | 低 | 对旧非原子写入的安全修正 | 必须保持 true；`PROPOSED_NOT_CONFIRMED` |

### 8.2 `[maa_update]`

| 字段 | 严格类型 | 默认值 | 必填 | 隐私 | 来源证据 | 校验规则 |
|---|---|---|---|---|---|---|
| `enabled` | bool | `false` | 否 | 低 | 旧更新开关 | 严格 bool |
| `self_update` | bool | `false` | 否 | 低 | self 命令 | 严格 bool |
| `core_update` | bool | `false` | 否 | 低 | core 命令 | 严格 bool |
| `hot_update` | bool | `false` | 否 | 低 | hot 命令 | 严格 bool |
| `channel` | str | `"stable"` | core 启用时 | 低 | 旧频道 | 固定白名单；实际集合待确认 |
| `timeout_seconds` | int | `1800` | 否 | 低 | 旧单命令超时 | 正整数且拒绝 bool |
| `allow_network` | bool | `false` | 否 | 低 | 更新可能访问网络 | 必须显式授权；`PROPOSED_NOT_CONFIRMED` |

入口、工作目录和环境应复用现有 MAA 配置，不重复保存。

### 8.3 `[mumu]` 候选字段

| 字段 | 严格类型 | 默认值 | 必填 | 隐私 | 来源证据 | 校验规则 |
|---|---|---|---|---|---|---|
| `instance_selector` | str | `""` | 控制启用时 | 高 | 旧流程缺少明确选择器 | 非空、格式白名单；`PROPOSED_NOT_CONFIRMED` |
| `manager_executable` | str | `""` | 控制启用时 | 中 | 旧流程未提供管理 CLI | 普通文件；`PROPOSED_NOT_CONFIRMED` |
| `start_arguments` | tuple[str, ...] | `()` | 控制启用时 | 中 | 尚无静态命令证据 | 非空元素、包含实例占位符；`PROPOSED_NOT_CONFIRMED` |
| `stop_arguments` | tuple[str, ...] | `()` | 控制启用时 | 中 | 尚无静态命令证据 | 非空元素、包含实例占位符；`PROPOSED_NOT_CONFIRMED` |
| `ready_log_path` | str | `""` | 否 | 高 | 旧 readiness 日志 | 普通文件或受控模板；不得记录实际值 |

不建议把旧脚本的进程名扫描、安装根扫描或强制终止开关直接移植为生产配置；这些机制缺少实例所有权保证。

## 9. 可实施性矩阵

| Stage | 状态 | static_command_resolved | instance_selection_resolved | success_semantics_resolved | failure_semantics_resolved | timeout_resolved | ownership_resolved | privacy_risk | implementation_decision | missing_evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| `SYNC_MAA_CONFIG` | `PARTIAL` | true | 当前 GUI 配置已解析 | true | true | 不适用 | 文件写入部分 | high | 保持阻断 | 原子替换、备份保留、隐私白名单、权限 |
| `UPDATE_MAA` | `PARTIAL` | true | 不适用 | 部分 | true | true | partial | medium | 保持阻断 | self-update 子进程、网络、取消、不可读退出码 |
| `STOP_MUMU` | `UNSAFE` | false | false | 部分 | 部分 | true | false | high | 禁止实现 | 实例化 stop CLI 与专属所有权证据 |
| `START_MUMU` | `UNSAFE` | false | false | true（readiness） | true | true | false | high | 禁止把长期入口交给短命令 Job | 实例化 start CLI、长期进程脱离契约 |
| `VERIFY_MUMU_STOPPED` | `PARTIAL` | 不适用 | false | 部分 | true | true | false | high | 保持只读阻断/探测 | 不依赖全局扫描的目标实例 stopped 证据 |
| `WAIT_MUMU_ADB_READY_AFTER_RESTART` | `PARTIAL` | ADB 探测已解析 | false | true | true | true | partial | high | 只保留受控只读设计 | 明确实例到设备目标的绑定证据 |

## 10. 最终结论

```text
sync_maa_config_status=PARTIAL
update_maa_status=PARTIAL
mumu_start_status=UNSAFE
mumu_stop_status=UNSAFE
mumu_instance_selection_status=BLOCKED
mumu_ownership_status=PARTIAL
workflow_order_matches=true
elevation_timing_resolved=true
```

Phase 6B2A 静态调查完成，但关键安全证据不足，`phase_6b2b_authorized=false`。现有生产阻断必须保留；不得进入 MAA 同步/更新或 MuMu 控制实现。
