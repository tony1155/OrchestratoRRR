# 累积维护与修复日志

本文件记录已经进入生产代码的缺陷修复。它是按时间持续追加的维护账本，不替代
<code>docs/acceptance/</code> 中的详细验收证据，也不把尚未执行的真实验证写成已完成。

## 记录规则

- 新记录按时间倒序追加，使用稳定 ID：<code>MNT-YYYY-MM-DD-NN</code>。
- 每条记录固定使用下列字段，不为单次事故另造格式。
- 状态只允许：<code>已实现</code>、<code>自动验证完成</code>、<code>真实验证完成</code>、<code>已回退</code>。
- 真实验证必须明确写出是否运行过真实 workflow。
- 日志、RunReport、确认字符串、ADB serial、PID 和原始 stdout/stderr 不写入本文件。

固定字段：

| 字段 | 含义 |
| --- | --- |
| ID / 日期 / 状态 | 稳定索引与当前验证等级 |
| 影响范围 | 用户可见影响和失败边界 |
| 事故证据 | 经过脱敏的稳定错误码、阶段和时序 |
| 根因 | 环境触发与代码缺陷分层 |
| 修复 | 实际进入源码的行为变化 |
| 安全边界 | 明确没有放宽的权限、地址和预算约束 |
| 自动验证 | focused/full pytest、Ruff、mypy、format、diff check |
| 制品 | 是否重建及 hash 变化 |
| 真实验证 | 是否重新运行真实业务流程 |
| 提交 | 对应 commit 或提交标题 |
| 剩余风险 | 本次修复刻意没有覆盖的边界 |

---

## MNT-2026-09-05-02 — MAA MaaResource 覆盖合并阶段

| 字段 | 记录 |
| --- | --- |
| ID / 日期 / 状态 | <code>MNT-2026-09-05-02</code> / 2026-09-05 / 真实验证完成 |
| 影响范围 | <code>maa update</code> 只更新 <code>MaaResource</code> 仓库而不覆盖 MaaCore 共用 <code>resource</code> 时，MAA CLI 可能因资源叠加顺序和旧技能表残留而加载失败；此前生产计划没有自动修复步骤。 |
| 事故证据 | 资源更新后 CLI 侧连续加载 <code>resource</code> 与 <code>MaaResource/resource</code>；已知失败表现为资源加载失败和非零退出。新增报告 marker 可识别资源仓库 pull、MaaCore 初始化和资源加载等稳定原因，但不会输出原始日志。 |
| 根因 | CLI 与 GUI 的资源更新语义不同：GUI 将增量资源就地 DirectoryMerge 到单一 <code>resource</code>，CLI 仍保留两份目录并由 MaaCore 连续加载；同名技能使用 <code>emplace</code> 时旧值不会覆盖，后续新技能组引用可能触发查找失败。 |
| 修复 | 新增默认关闭的 <code>maa_resource_merge</code> 配置、不可变结果模型、资源合并器和生产阶段 <code>MERGE_MAA_RESOURCE</code>。该阶段紧跟 <code>UPDATE_MAA</code>，仅将源目录文件覆盖合并到目标目录；同内容文件跳过，新目录按需创建，目标独有文件保留，单文件使用同目录临时文件、flush/fsync 和 <code>os.replace</code>。新增文件数、字节数、跳过数和错误码诊断。MAA 输出投影同时增加安全的固定 failure markers。 |
| 安全边界 | 默认关闭；不联网、不删除目标独有文件、不跟随源符号链接；源/目标相同或互为祖先时拒绝；最大文件数、单文件大小和 deadline 可配置且必须为正数；公开结果不包含路径和原始 stdout/stderr。external 与 managed 仅执行资源阶段，不改变 MuMu 所有权边界。 |
| 自动验证 | 资源合并、配置、工作流、报告投影、ADB server 持久化及原有回归测试均通过；full pytest：1512 passed, 1 skipped；Ruff：passed；strict mypy：passed（72 source files）；<code>git diff --check</code>：passed。 |
| 制品 | 未重建 onedir；本次新增功能尚未执行正式打包构建。 |
| 真实验证 | 已从正式安装目录的脱敏生产 RunReport 确认 external workflow 多次实际执行资源合并。2026-09-05 最近一次成功扫描 5215 个真实资源文件，覆盖 4206 个文件、跳过 1009 个相同文件，复制约 91.5 MiB，随后完整 external workflow 成功；此前 2026-09-03、2026-08-31、2026-08-29 等运行也确认合并成功或资源完全一致。未执行 managed 模式真实复验。 |
| 提交 | 待本次变更提交：<code>feat(maa): add safe resource merge stage</code> |
| 剩余风险 | 真实 external workflow 已验证资源合并在当前安装目录、当前真实资源规模和 MAA 运行链路下正常工作。合并过程按阶段和文件批次检查控制信号，单个大文件读写本身不是可中断的；目标目录若被外部 MAA GUI 同时修改，仍可能出现竞态。managed 模式和更换机器/安装目录仍需独立验证。 |


| 字段 | 记录 |
| --- | --- |
| ID / 日期 / 状态 | <code>MNT-2026-09-05-01</code> / 2026-09-05 / 自动验证完成 |
| 影响范围 | 安装更新前的产品数据 backup 在 Windows PowerShell 5.1 环境中统一失败为 <code>BACKUP_COPY_FAILED</code>，导致后续 onedir update、参数校验与回滚测试全部无法执行。 |
| 事故证据 | backup 在扫描产品数据并计算文件摘要阶段失败；实际宿主为 Windows PowerShell 5.1，未提供 <code>Get-FileHash</code> cmdlet。修复前 focused packaging 为 7 个基础失败并产生 29 个级联失败。 |
| 根因 | <code>scripts/lib/DefaultEntryMaintenance.psm1</code> 依赖 PowerShell 7 可用的 <code>Get-FileHash</code>，但项目文档同时支持 Windows PowerShell 5.1；顶层脚本为保护内部细节将该命令缺失折叠为稳定错误码。 |
| 修复 | 将 <code>Get-FileSha256</code> 改为使用 <code>System.Security.Cryptography.SHA256</code> 和只读 .NET 文件流计算 SHA-256，保持原有大写摘要格式、文件共享模式、manifest 校验和错误码契约；不再依赖 <code>Get-FileHash</code>。 |
| 安全边界 | 仅替换摘要实现，未放宽路径、reparse point、manifest、原子写入、事务回滚或安装目录策略；文件仍以只读共享方式打开，backup/update 的内容校验逻辑不变。 |
| 自动验证 | packaging focused：36 passed；full pytest：1512 passed, 1 skipped；Ruff：passed；strict mypy：passed（72 source files）；<code>git diff --check</code>：passed。 |
| 制品 | 未重建 onedir；本次修复只修改维护脚本，尚未执行打包制品构建。 |
| 真实验证 | 未运行真实 MuMu、StarRail 或 MAA workflow；已在当前 Windows PowerShell 5.1 宿主完成安装更新脚本自动验证。 |
| 提交 | 待本次修复提交：<code>fix(packaging): support backup hashing on PowerShell 5.1</code> |
| 剩余风险 | 尚未在 PowerShell 7、非英文路径、超大文件和真实安装目录上分别执行现场验证；这些边界仍由现有自动测试和后续真实安装验收覆盖。 |


| 字段 | 记录 |
| --- | --- |
| ID / 日期 / 状态 | <code>MNT-2026-08-17-03</code> / 2026-08-17 / 自动验证完成 |
| 影响范围 | managed workflow 在 <code>ensure_mumu_running</code> 连续两次用满约 120 秒后退出；StarRail 与 MAA 未进入。 |
| 事故证据 | 两次最新运行均为 <code>WORKFLOW_STAGE_TIMEOUT / START_TIMEOUT</code>，最后 probe 为 <code>DEVICE_OFFLINE / select_device</code>；一次 managed MuMu restart 已完成，但 restart 后目标 transport 仍 offline，失败 cleanup 与 RunReport 均成功。 |
| 根因 | 前一版恢复只重启 MuMu 实例，没有清理宿主 ADB server 中精确目标的 stale/offline transport；普通 controlled connect 又只允许 <code>DEVICE_NOT_FOUND</code>，所以 restart 后持续 offline 只能等到 operation deadline。旧成功测试在 manager start 返回时直接把 fake probe 推进为 READY，没有覆盖“restart 完成但宿主 transport 仍 offline”。 |
| 修复 | <code>AdbClient</code> 增加仅面向精确 localhost endpoint 的 <code>disconnect</code> 与 <code>recycle_local_endpoint</code>。持续 offline 经过 grace 后先执行一次 <code>disconnect → connect → readonly recheck</code>；若仍 offline，再执行已有的最多一次 managed restart；restart 后仍 offline 时允许第二次且最后一次 endpoint recycle。 |
| 安全边界 | 未把 <code>DEVICE_OFFLINE</code> 加入普通 <code>_connect_is_allowed()</code>；不执行 <code>adb kill-server/start-server</code>，不扫描、不操作或断开其他设备。endpoint recycle 最多 2 次、MuMu restart 最多 1 次；全部共享原 start-operation Deadline，每条 ADB 命令仍受 5 秒 child deadline 和父预算共同约束。external mode 不进入该恢复状态机。 |
| 自动验证 | endpoint/client/runtime/projection focused：107 passed；probes/runtime/workflow：600 passed；full pytest：1456 passed, 1 skipped；<code>ruff check .</code>：passed；<code>mypy src</code>：passed（69 source files）；changed-file format 与 <code>git diff --check</code>：passed。 |
| 制品 | 使用 <code>scripts/build-package.ps1</code> 与正式 spec 重建 onedir；EXE SHA256：<code>1AB5DDDB2D15745882BECCEBA811410105E5D25DBAAE698B9B285A09B7C38A82</code> → <code>0C82694DE15B42C1C3FB8199CEBDD4BF8CC7C29D74BE75727D9C8ECE88B10986</code>；<code>_internal</code> 与 RunReport schema 存在；Desktop shortcut target 未修改。 |
| 真实验证 | 未运行真实 workflow、MuMu、StarRail 或 MAA；本条状态不得解读为真实业务复验完成。 |
| 提交 | 本条记录所在提交：<code>fix(runtime): recycle stale MuMu ADB endpoint</code>。 |
| 剩余风险 | 若精确 disconnect/connect、一次 MuMu restart 和第二次 recycle 后仍无法恢复，workflow 仍按原 120 秒边界 fail closed。全局 ADB server 重置因会影响其他设备，仍明确不在自动恢复范围。 |

---

## MNT-2026-08-17-02 — managed DEVICE_OFFLINE restart、失败 cleanup 与交互通知

| 字段 | 记录 |
| --- | --- |
| ID / 日期 / 状态 | <code>MNT-2026-08-17-02</code> / 2026-08-17 / 自动验证完成 |
| 影响范围 | MuMu UI 可用但宿主到精确 ADB endpoint 长期 offline 时，旧实现没有 managed 恢复策略；失败后窗口直接关闭且上游失败可能跳过 MuMu 收尾。 |
| 事故证据 | <code>ensure_mumu_running</code> 约 120 秒后 <code>START_TIMEOUT</code>；最后安全诊断为 <code>DEVICE_OFFLINE / select_device</code>。 |
| 根因 | managed 生命周期只对 <code>DEVICE_NOT_FOUND</code> 提供受控 connect，对持续 offline 只有只读轮询；普通 pipeline 的 fail-fast 还会跳过后续 shutdown。 |
| 修复 | 三秒 offline grace 后，managed start 最多执行一次共享原预算的 MuMu stop/start；取得 managed ownership 后的 failure/timeout 在写报告前执行一次 bounded shutdown cleanup；打包交互运行在报告写入后显示脱敏失败对话框并保留原始非零退出码。 |
| 安全边界 | external mode 不启停 MuMu；普通 controlled connect 契约未放宽；restart 最多一次且不刷新 start deadline；cleanup failure 只能作为 secondary failure，不能覆盖原始失败。 |
| 自动验证 | focused：198 passed；full pytest：1442 passed, 1 skipped；Ruff 与 mypy passed；详细证据见 [managed DEVICE_OFFLINE recovery](acceptance/2026-08-17-managed-mumu-device-offline-recovery.md)。 |
| 制品 | onedir 已重建；EXE SHA256：<code>AB63BDE14D3E2C728DF9DC9C9AEC5D0888E987D7AA4E91B0B9255A5C3419C9F0</code> → <code>1AB5DDDB2D15745882BECCEBA811410105E5D25DBAAE698B9B285A09B7C38A82</code>。 |
| 真实验证 | 未运行真实 workflow；后续真实事故证明“只重启 MuMu”不足以清除宿主 stale/offline transport，由 <code>MNT-2026-08-17-03</code> 继续修复。 |
| 提交 | <code>46d3af9 fix(runtime): recover managed MuMu offline failures</code> |
| 剩余风险 | 本记录当时未覆盖 restart 后宿主 ADB transport 仍 offline；该缺口已转入 <code>MNT-2026-08-17-03</code>。顶层 cancelled cleanup 仍是独立边界。 |

---

## MNT-2026-08-17-01 — 单条 ADB 命令 child deadline

| 字段 | 记录 |
| --- | --- |
| ID / 日期 / 状态 | <code>MNT-2026-08-17-01</code> / 2026-08-17 / 自动验证完成 |
| 影响范围 | 单条 <code>adb devices/get-state/getprop/connect</code> 异常阻塞时，可独占整个 MuMu start operation deadline，使 readiness loop 无法继续。 |
| 事故证据 | <code>ensure_mumu_running</code> 用满 120 秒；最后安全 probe 为 <code>ADB_TIMEOUT / adb_devices</code>，MuMu 进程和 TCP 端口存在，但 StarRail 未进入。 |
| 根因 | <code>AdbClient._run_adb_command()</code> 直接把 MuMu operation deadline 交给单个 ADB 子进程，没有命令级上界。 |
| 修复 | 每条 ADB 命令创建一次固定 child deadline：不超过 5 秒且不超过父 operation 剩余预算；命令超时后 readiness 可在原 operation deadline 内继续下一轮 probe。 |
| 安全边界 | child deadline 只收紧、不刷新父预算；未增加全局 ADB server 操作、设备扫描或 MuMu restart；<code>DEVICE_NOT_FOUND</code> connect 条件保持不变。 |
| 自动验证 | full pytest：1425 passed, 1 skipped；Ruff 与 mypy passed；详细证据见 [ADB 子命令 timeout](acceptance/2026-08-17-mumu-adb-command-timeout-recovery.md)。 |
| 制品 | onedir 已重建；EXE SHA256：<code>CEBA40DE19A9558228273E704ED64B0E1796DE1AA7375B016201F52AF5595FDC</code> → <code>AB63BDE14D3E2C728DF9DC9C9AEC5D0888E987D7AA4E91B0B9255A5C3419C9F0</code>。 |
| 真实验证 | 未运行真实 workflow；后续事故确认 5 秒 child deadline 生效，并把最后诊断推进为更准确的 <code>DEVICE_OFFLINE</code>。 |
| 提交 | <code>80e0835 fix(runtime): bound individual ADB commands</code> |
| 剩余风险 | child deadline 不能自行修复 offline transport；后续恢复策略见 <code>MNT-2026-08-17-02</code> 与 <code>MNT-2026-08-17-03</code>。 |
