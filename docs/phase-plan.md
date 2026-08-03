# OrchestratoRRR 阶段规划

Adapter 真实 smoke 门禁已于 2026-07-30 关闭。6C2A、6C2B（含真实冷连接恢复）和 6C2C 均已完成验收，6C3 已完成文档收口。6B2B2B 与 6B2B3C 仍未完成，Phase 6 按已批准的 external-only 范围完成；Phase 7A1 已完成入口契约实现与自动测试，Phase 7 尚未完成。

## Phase 5——AALC Runtime Adapter

Fake AALC 环境和真实 AALC smoke 验收均已完成。成功仅依据 exit 0，最多三次尝试，只有非零退出和单次尝试超时允许重试。未实现完整工作流、公开 run CLI，未替换旧 PowerShell。

本文档定义 Autogame Orchestrator 的阶段性路线。
各阶段严格按顺序实施，每个阶段完成前必须通过所有测试。

| 阶段 | 标题 | 范围 |
|---|---|---|
| 0 | 项目骨架与行为契约 | 包布局、数据模型、配置校验、CLI（version/validate/plan）、RunReport schema、JSONL 日志、测试套件、文档 |
| 1A | 进程基础契约与 Job Object 底座 | Deadline、CancellationToken、ProcessSpec、ManagedProcess、Win32 句柄封装、Job Object、CreateProcessW 启动器、Fake 程序扩展 |
| 1B | 通用进程监督器 | ProcessSupervisor 完整生命周期：launch/wait/run/stop/close、超时升级、取消升级、幂等关闭、进程树清理 |
| 2A | 本地运行时与 ADB 只读探测 | 本地 TCP 端口探测、ADB 命令执行（通过 ProcessSupervisor）、ADB devices 解析、设备选择、MuMu readiness 组合探测 |
| 2B | MuMu 生命周期适配器 | MumuAdapter：status/start/stop/restart、管理命令通过 ProcessSupervisor、空参数默认拒绝、真实控制尚未获准 |
| 2C | MuMu 管理命令发现 | 本机安装目录调查、候选文件元数据收集、安全性分类（B：候选存在但证据不足） |
| 2D | MuMu 候选 CLI 安全探针 | 诊断模块：固定帮助参数白名单、ProcessSupervisor 有界执行、受限输出收集；探针工具完成并完成安全收口；真实候选执行待安全窗口 |
| 3 | StarRail Adapter | 启动 StarRailCopilot、监控退出、捕获输出 |
| 4 | MAA Adapter | 启动 MAA CLI |
| 5 | AALC Adapter | 有界启动 AALC，最多三次尝试，仅非零退出和单次尝试超时允许重试 |
| 门禁 | Phase 6 前的真实 smoke | 已完成 StarRail、MAA、AALC 单 Adapter smoke 和人工评审；门禁已关闭，Phase 6 已获实施授权 |
| 6A | 工作流契约与 Fake 编排内核 | 冻结执行计划、惰性 Fake Stage、fail-fast、取消与父 Deadline 传播、RunReport 最终化和入口提权前置决策契约 |
| 6B1 | 生产 Stage 投影与安全绑定骨架 | 既有 Adapter 结果白名单投影、惰性 Runtime 绑定、单次运行状态和生产 ReportSink；默认计划在同步阶段安全阻断 |
| 6B2A | 旧流程静态契约调查 | 只读固化 MAA 同步/更新与 MuMu 控制的旧行为、顺序、超时和所有权证据；已完成 |
| 6B2B1 | 安全 MAA 配置同步 | 默认关闭；白名单转换、有界读取、原子替换/备份和双输出失败回滚；已完成 |
| 6B2B2A | 安全 MaaCore/资源更新 | 默认关闭并要求显式网络授权；固定 update 动词，复用 MAAAdapter 生命周期；已完成 |
| 6B2B2B | maa-cli 自更新决策 | CLI 自替换与包管理器所有权尚未闭合；继续阻断 |
| 6B2B3A | MuMu CLI 探针加固与否定证据 | 公开投影脱敏、模块执行警告修复；只读帮助仅证明 RPC/Shell 形状，未发现生命周期管理命令；已完成 |
| 6B2B3B | 外部管理 MuMu 生命周期模式 | 用户预先启动实例，OrchestratoRRR 只验证 readiness；动态计划安全跳过 stop/start；已完成 |
| 6B2B3C | managed 实例化生命周期控制 | start/stop 语法、实例选择和长期进程所有权尚未闭合；继续阻断 |
| 6C1 | 受控 external run CLI 与完整 Fake 验收 | 公开 external-only `run` v1、精确确认、有限 Deadline、入口提权接线与完整 Fake 验收；已完成 |
| 6C2A | ADB devices 空白分隔兼容修复 | 第一次真实 smoke 在 MuMu readiness 安全停止；修复空格、Tab 与混合分隔并增强安全诊断；已完成 |
| 6C2B | 修复后 readiness 与受控连接恢复 | 6C2B3 人工 connect 后 readiness 已验证；6C2B4A 完成显式 local TCP connect 的 Fake/自动测试；6C2B4C 完成真实冷连接自动恢复；已完成 |
| 6C2C | 修复后 external 真实完整工作流 smoke | 11 阶段 external 完整真实 smoke 已通过；AALC 在线业务 UI 因网络原因未验证；已完成 |
| 6C3 | Phase 6 最终验收、文档收口与合并准备 | 脱敏证据已固化，external-only 范围完成，等待人工审核；当前完成 |
| Phase 6 external scope | 已批准的 external-only 工作流范围 | Fake、生产 Adapter、冷连接恢复和完整真实 external workflow 均已验收；完成 |
| Phase 6 managed scope | MuMu managed 生命周期范围 | start/stop/restart 与实例自动选择继续阻断；未完成且不属于当前批准范围 |
| Phase 6 overall | Phase 6 按批准范围的状态 | 已批准的 external-only Phase 6 范围完成；不表示所有 MuMu 生命周期能力完成 |
| 7 | 打包与默认入口 | PyInstaller EXE、无缝替换旧 PS1 入口点 |

> **下一门禁：** 只有获得明确 start/stop/实例选择语法，并完成独立进程所有权验证后，才允许修改生产 start_arguments/stop_arguments。

每个阶段基于前一阶段构建，但不得退化先前阶段的测试。

Phase 6A 已固化入口权限规划契约：先构建完整计划；只要计划包含 `RUN_AALC` 且 AALC 声明 `requires_administrator=true`，就在 Runner 和任何 Stage 工厂构造前决定是否重启提升整个 OrchestratoRRR。不得在执行到 AALC 时才临时提升，也不得用 `runas` 绕过现有 ProcessSupervisor 单独启动 AALC。本阶段测试只使用 Fake gateway，未触发真实 UAC。

Phase 6B1 已完成生产投影与安全绑定骨架。默认完整生产计划在 `SYNC_MAA_CONFIG` 明确阻断，且阻断前不构造或执行任何 Runtime Adapter。MuMu 只允许只读 `status()`；start/stop 仍未获准。

Phase 6B2A 已完成旧流程静态契约调查，6B2B1 已完成安全 MAA 同步。Phase 6B2B2A 只实现固定 `maa update` 的 MaaCore/资源更新，默认关闭并要求显式网络授权；未执行真实更新。maa-cli 自更新与旧 hot-update 继续阻断于 6B2B2B。Phase 6B2B3A 的只读帮助证据仅确认 NemuShell RPC/Shell 调用形状，没有发现生命周期命令或安全实例选择器；`runtime_approved=false`。Phase 6B2B3B 提供 external 安全路径：用户预先启动正确实例，OrchestratoRRR 只验证 readiness，不调用 MuMu start/stop/restart；managed 模式仍保留静态 15 阶段，实例化控制继续阻断于 6B2B3C。

Phase 6C1 已提供受控 external-only `run` v1：精确确认、有限 Deadline、MAA Sync/Update 关闭、AALC attempts 为 1，并在 Runner/Stage factory/Adapter 前统一完成 elevation 决策。完整 Fake 验收已通过。第一次真实 external smoke 曾因旧解析器拒绝合法空格分隔的 ADB devices 记录而安全停止；6C2A 修复了解析兼容和脱敏诊断，6C2B4A 增加了受控 local TCP connect，6C2B4C 已完成真实冷连接自动恢复，6C2C 已完成 11 阶段 external 真实完整工作流 smoke。Phase 6C3 现已固化脱敏证据并完成 external-only 收口；6B2B2B、6B2B3C 仍未完成，Phase 7A1 已完成入口契约实现与自动测试，Phase 7 尚未完成，旧 PowerShell 尚不可替换。
## Phase 7A1 status

Phase 7A1 closes the source/frozen entry runtime and explicit UAC re-entry
contract with Fake/automatic tests. Source mode uses the Python module
entrypoint; frozen mode uses the executable directly. The launch specification
also carries an absolute configuration path and an explicit working directory.

Phase 7A2 now owns the completed PyInstaller onedir configuration and
RunReport schema resource collection. Phase 7D still owns the default user
entry and working-directory policy. The generated EXE is retained for the
future Phase 7B1 fixture-only smoke, and the legacy PowerShell entry remains
in place.

## Phase 7A2 status

Phase 7A2 is complete within its approved packaging/resource scope. The
version-controlled PyInstaller 6.21.0 onedir console spec and cwd-independent
build script collect only the canonical schema into the package resource
directory. Three historical attempts failed before a runnable onedir; the
fourth attempt completed after removing the invalid splash reference. The
artifact was audited statically only: no packaged CLI, UAC, ADB, or workflow
claim is made.

Phase 7B1 still owns packaged `version`, `--help`, fixture-only validate and
fixture-only plan smoke. Phase 7D still owns the default user entry and final
working-directory policy. The legacy PowerShell entry remains in place and
cannot yet be removed. Phase 7 is not complete.
## Phase 7B1 packaged CLI smoke

Phase 7B1 is complete for the approved packaged CLI smoke scope. The existing
onedir artifact passed source and packaged fixture-only `validate` and
`plan` from an external temporary working directory. The prior packaged
`version` and plain help results remain cumulative evidence from the same
committed artifact; neither was rerun in the diagnostic closure.

The packaged plan is the existing static 15-stage dry plan, with lowercase
stage values and a bundled-schema-valid RunReport. It must not be confused with
the production external 11-stage run contract. No packaged `run`, real UAC,
ADB, or business program was executed. Phase 7D remains the next blocker for
the default entry and final working-directory policy; Phase 7 is not complete.

## Phase 7B2A isolated workflow entry and build

Phase 7B2A is complete within its implementation and static-audit scope. The
hidden `_isolated-workflow-smoke` entry reuses `execute_run_request` and injects
strictly in-process synthetic Runtime factories. Its workspace must be an
existing empty directory outside the current entry/bundle boundaries, and its
generated configuration contains only inert workspace-local placeholder files.

The isolated report mode is `workflow_isolated`; the default production mode
remains `workflow_external`. Source tests and one source-only isolated smoke
covered the exact external 11-stage order, report/log privacy, and fail-closed
boundaries for default Runtime, process, TCP/ADB, and UAC paths.

The changed source was rebuilt once as a PyInstaller 6.21.0 onedir console
artifact. Static inspection confirmed the EXE, bundled canonical schema, and
isolated diagnostic module in the build analysis. The generated EXE was not
executed. Phase 7B2B owns that packaged isolated-workflow smoke; Phase 7D still
owns the default entry and final working-directory policy. The legacy
PowerShell entry remains retained and Phase 7 is not complete.

## Phase 7B2B packaged isolated workflow execution

Phase 7B2B is complete. The retained Phase 7B2A onedir artifact was not
rebuilt and its hidden `_isolated-workflow-smoke` command was started exactly
once from a separate system-temporary runner directory. The synthetic
workspace began empty and remained outside repository, build, and dist paths.

The packaged command exited zero with `workflow_isolated`, 11 successful
synthetic stages, and `forbidden_calls=0`. Its single log contained one start
event and 11 ordered stage events. Its single RunReport passed independent
validation with the bundled canonical schema. Artifact hashes and dist file
count were unchanged, and all temporary evidence and harness files were
removed.

Phase 7B2 is now complete without executing public `run`, UAC, ADB, TCP, or
business programs. Phase 7C requires separate authorization for any real
packaged external validation. Phase 7D remains responsible for the default
entry and final working-directory policy. The legacy PowerShell entry remains
retained and Phase 7 is not complete.

## Phase 7D1 default-entry implementation

Phase 7D1 is complete at the source implementation and automatic-test boundary.
The new public start command implements the Phase 7D0 shortcut-to-native-EXE
decision, canonical LOCALAPPDATA paths, interactive confirmation, report-free
external 11-stage preflight, and a single formal run request under the
canonical runtime cwd. Existing public CLI contracts remain unchanged.

The canonical installer and shortcut script was added but not executed. No
real shortcut, packaged execution, rebuild, UAC, ADB, TCP probe, or business
workflow occurred. Phase 7D2 is next and owns rebuilding plus packaged
non-business entry tests. Phase 7C remains a separate real-execution approval;
Phase 7E owns legacy replacement. Phase 7 and Phase 7D are not complete.

## Phase 7D2 rebuild and packaged non-business entry tests

Phase 7D2 is complete. The committed native start entry was rebuilt exactly
once with the formal onedir script and passed static Analysis, warning,
schema, resource, and privacy audits. The new packaged executable passed
version, root help, start help, and a non-interactive start rejection in four
total launches.

The rejection occurred before canonical path resolution or writes:
the temporary runner remained empty and synthetic LOCALAPPDATA and APPDATA
were never created. No correct confirmation, public run, validate, plan,
isolated workflow, installer, shortcut, UAC, ADB, TCP probe, or business
program was used.

Phase 7D3 is next and owns packaged default-entry synthetic preflight and
confirmation cancellation. Phase 7C remains separately authorized real
execution; Phase 7E owns legacy replacement. Phase 7D and Phase 7 remain
incomplete.

## Phase 7D3 composed-evidence closure

Phase 7D3 is complete through
`COMPOSED_EVIDENCE_NO_INTERACTIVE_PACKAGED_EXECUTION`. Source automatic tests
cover the synthetic preflight, exact external 11-stage preview, confirmation
cancellation, zero run-executor calls, pause, directory preparation, and
write-probe cleanup. Phase 7D2 proves inclusion of that committed control flow
in the formal packaged artifact and verifies its packaged CLI and
non-interactive boundaries. The attempted Phase 7D3 synthetic fixture also
passed all source-only pre-confirmation gates.

The interactive packaged run was waived after the computer-control backend
was unavailable and the transcript probe failed before any packaged launch.
No direct packaged confirmation-cancel evidence is claimed, and no product
defect was found. Phase 7D4 is next:
`PHASE_7D4_PARALLEL_DEPLOYMENT_AND_MANUAL_OPERATIONS`. Phase 7C remains the
separately authorized real packaged external workflow boundary, and Phase 7E
continues to own legacy replacement. Phase 7D and Phase 7 remain incomplete.

## Phase 7D4B authorized canonical installation

Phase 7D4B is complete. The ignored local configuration was atomically copied
to the canonical location after passing all six source-only gates. The
committed installer ran exactly once, installed the retained Phase 7D2 onedir,
and created the canonical Start Menu shortcut. Installed EXE/schema hashes and
the 106-file count match the source artifact; runtime, log, and report
directories remain empty.

No packaged executable or shortcut was run, and no UAC, ADB, TCP probe, or
business program was invoked. The legacy PowerShell entry remains available
in parallel. The next phase is
`PHASE_7D4C_MANUAL_SHORTCUT_PREFLIGHT_CANCELLATION`. Phase 7C continues to own
correctly confirmed real packaged execution, while Phase 7E owns any legacy
replacement decision. Phase 7D and Phase 7 remain incomplete.

## Phase 7D4C manual shortcut preflight cancellation

Phase 7D4C is complete from user direct observation plus a read-only static
post-audit. The installed shortcut launched packaged `start` exactly once,
displayed the ordered external 11-stage preview and warning, rejected the
fixed incorrect confirmation, displayed the close pause, and closed normally
after Enter. No automated transcript or computer capture is claimed.

The run executor was not reached. No UAC, ADB, TCP probe, real workflow, or
business program was executed, and canonical runtime, log, and report
directories remained empty. Phase 7D3 retains its composed-evidence basis;
this later observation adds direct packaged confirmation-cancel evidence.

`phase_7d4c_completed=true`, `phase_7d4_completed=true`, and
`phase_7d_completed=true`. Phase 7C and Phase 7E remain incomplete, so Phase 7
is not complete. The next phase is
`PHASE_7C_AUTHORIZED_REAL_PACKAGED_EXTERNAL_WORKFLOW`, gated by
`PHASE_7C_REAL_WORKFLOW_AUTHORIZATION`. It must not begin without separate
explicit authorization. Phase 7E must wait for the Phase 7C result, and the
legacy PowerShell entry cannot yet be removed.

## Phase 7C StarRail log-contract correction

The failure review and source correction are complete:
`phase_7c_starrail_failure_review_completed=true` and
`phase_7c_starrail_log_contract_fix_completed=true`. The first real attempt
failed at `run_starrail` because the fixed rendered log path did not discover
the external tool's same-directory dynamic time-component log.

The corrected runtime uses bounded pre-launch candidate snapshots, excludes
historical content by EOF, starts new candidates at zero, pins one active
candidate, and fails closed on ambiguity. Focused automatic tests and
file-scoped static checks passed. No package was rebuilt or installed, and no
real workflow was rerun.

`phase_7c_completed=false`, `phase_7e_completed=false`, and
`phase_7_completed=false`. The next phase is
`PHASE_7C_REBUILD_REINSTALL_FOR_RETRY`. Remaining blockers are
`PHASE_7C_UPDATED_ARTIFACT_REQUIRED` and
`PHASE_7C_REAL_WORKFLOW_RETRY_AUTHORIZATION`. The legacy PowerShell entry
remains retained.

## Phase 7C install-update implementation

The incident forensics and exact product-data recovery are complete:
`phase_7c_product_data_forensics_completed=true` and
`phase_7c_product_data_recovery_completed=true`. The recovered JSONL and
RunReport are protected by their approved hashes; the canonical runtime
directory remains absent.

The tested maintenance implementation is also complete:
`phase_7c_install_update_implementation_completed=true`. Build, backup, and
install update are independent. Backup produces an atomically finalized,
manifest-verified recovery bundle. The updater treats product data as read
only, rejects unchanged source EXE hashes, validates complete source/current/
staging manifests, uses same-parent directory exchange, restores only a true
transaction backup, and fails closed on transaction residue.

A separately authorized real product-data backup has completed exactly once.
The finalized bundle passed independent manifest, hash, privacy, source
consistency, and post-backup preservation checks. `config`, `logs`, and
`run-results` are present; `runtime` remains absent and was not created.
`phase_7c_product_data_backup_completed=true` and
`phase_7c_product_data_backup_bundle_ready=true`.

The implementation remains complete, while rebuild, reinstall, updated-artifact
readiness, real workflow retry, Phase 7C, Phase 7E, and Phase 7 remain
incomplete. The next phase is
`PHASE_7C_PRODUCT_DATA_BACKUP_COMMIT`. Remaining blockers are
`PHASE_7C_PRODUCT_DATA_BACKUP_COMMIT_REQUIRED`,
`PHASE_7C_UPDATED_ARTIFACT_REQUIRED`, and
`PHASE_7C_REAL_WORKFLOW_RETRY_AUTHORIZATION`.

Required order after the backup commit: separately authorize the formal
rebuild; statically audit the new artifact; separately authorize install
update; statically audit the installed artifact; and separately authorize the
real workflow retry. Phase 7E may begin only after Phase 7C succeeds. The
legacy PowerShell entry remains retained.

## Phase 7C rebuild retry and static artifact audit

The first formal build attempt was left unproven because its wrapper promoted
native stderr to a terminating error before capturing the child exit code and
completion marker. A separately authorized single retry used a foreground
System.Diagnostics.Process wrapper with separate asynchronous stdout/stderr
capture. It returned exit code zero and the formal completion marker, and its
static onedir artifact audit passed. The artifact is not installed and its EXE
was not executed.

Current state:

phase_7c_product_data_forensics_completed=true
phase_7c_product_data_recovery_completed=true
phase_7c_install_update_implementation_completed=true
phase_7c_product_data_backup_completed=true
phase_7c_product_data_backup_bundle_ready=true
phase_7c_rebuild_retry_completed=true
phase_7c_rebuild_completed=true
phase_7c_dist_artifact_audit_completed=true
phase_7c_updated_artifact_ready=true
phase_7c_reinstall_completed=false
phase_7c_installed_artifact_audit_completed=false
phase_7c_real_workflow_retry_completed=false
phase_7c_completed=false
phase_7e_completed=false
phase_7_completed=false
legacy_powershell_replacement_ready=false

The next phase is PHASE_7C_REBUILD_ARTIFACT_AUDIT_COMMIT. Its blockers are
PHASE_7C_REBUILD_ARTIFACT_AUDIT_COMMIT_REQUIRED,
PHASE_7C_INSTALL_UPDATE_AUTHORIZATION, and
PHASE_7C_REAL_WORKFLOW_RETRY_AUTHORIZATION. The required order is: commit
the audited documentation, separately authorize install update, statically
audit the installed artifact, separately authorize the real workflow retry,
and enter Phase 7E only after Phase 7C succeeds. The legacy PowerShell entry
remains retained.

## Phase 7C real install update and installed-artifact audit

The separately authorized real install update completed successfully with
the committed updater invoked exactly once. The audited source onedir and
verified product-data backup were used; the updater returned exit code zero,
reported success, and performed no retry. The installed artifact and its
complete manifest now match the source, while product data, the backup bundle,
the source dist, and the shortcut remain unchanged. The canonical runtime
directory remains absent and no transaction residue remains.

phase_7c_product_data_forensics_completed=true
phase_7c_product_data_recovery_completed=true
phase_7c_install_update_implementation_completed=true
phase_7c_product_data_backup_completed=true
phase_7c_product_data_backup_bundle_ready=true
phase_7c_rebuild_retry_completed=true
phase_7c_rebuild_completed=true
phase_7c_dist_artifact_audit_completed=true
phase_7c_updated_artifact_ready=true
phase_7c_reinstall_completed=true
phase_7c_installed_artifact_audit_completed=true
phase_7c_real_workflow_retry_completed=false
phase_7c_completed=false
phase_7e_completed=false
phase_7_completed=false
legacy_powershell_replacement_ready=false

The next phase is PHASE_7C_INSTALL_UPDATE_AUDIT_COMMIT. Its blockers are
PHASE_7C_INSTALL_UPDATE_AUDIT_COMMIT_REQUIRED and
PHASE_7C_REAL_WORKFLOW_RETRY_AUTHORIZATION. The required order is: review and
commit this install-update audit documentation; separately authorize the
repaired real packaged external workflow retry; audit its RunReport, JSONL,
all 11 stages, and business-program cleanup; then enter Phase 7E only after
Phase 7C succeeds. The legacy PowerShell entry remains retained.

## Phase 7C PROGRAM_PORT install update and installed-artifact audit

A separately authorized real install update promoted the rebuilt PROGRAM_PORT
onedir into the canonical installed location at baseline
`c8ea36103f8015dac194de1a334906df9386efc6`. An independent read-only precheck
passed first. The first foreground wrapper attempt failed during construction
because Windows PowerShell 5.1 does not expose
`ProcessStartInfo.ArgumentList`; that `PRE_INVOCATION_WRAPPER_ERROR` created no
child process, made no filesystem change, and was not an updater retry. After
the wrapper was corrected, the committed updater was invoked exactly once,
returned exit code zero with its success JSON and empty stderr, and performed
no rollback and no retry.

The installed artifact now matches the approved new dist exactly: 106 files,
28,636,334 bytes, EXE SHA-256
`9EEDF9FC4720BA6209439EA96F39BBE21C2E765A7386403D829707DA091A9C7C`, schema
SHA-256
`1994EB5915DA0079FD270412D48EA4562FA5EB4172F8BA7E8E98B9A17791F2CD`, and
fingerprint
`D00498B3E01938AD55DF01F89BC32EF6F5911B2B0C17825CF6D46D373E805A78`. The
PROGRAM_PORT fix code is present in the installed artifact, but its real
runtime effect remains unverified. Current product data stayed five files and
20,144 bytes with runtime present, unchanged file-by-file. The old and new
backup bundles each remained individually unchanged and are distinct bundles.
The shortcut and all transaction-residue checks were unchanged. No packaged
EXE, workflow, or business program was executed.

phase_7c_product_data_forensics_completed=true
phase_7c_product_data_recovery_completed=true
phase_7c_install_update_implementation_completed=true
phase_7c_product_data_backup_completed=true
phase_7c_product_data_backup_bundle_ready=true
phase_7c_rebuild_retry_completed=true
phase_7c_rebuild_completed=true
phase_7c_dist_artifact_audit_completed=true
phase_7c_updated_artifact_ready=true
phase_7c_reinstall_completed=true
phase_7c_installed_artifact_audit_completed=true
phase_7c_program_port_reinstall_completed=true
phase_7c_program_port_installed_artifact_audit_completed=true
phase_7c_real_workflow_retry_completed=false
phase_7c_completed=false
phase_7e_completed=false
phase_7_completed=false
legacy_powershell_replacement_ready=false

The next phase is PHASE_7C_AUTHORIZED_REAL_PACKAGED_EXTERNAL_WORKFLOW, gated by
PHASE_7C_REAL_WORKFLOW_RETRY_AUTHORIZATION. It must not begin without separate
explicit authorization. The required order is: separately authorize the
repaired real packaged external workflow retry; audit its RunReport, JSONL,
all 11 stages, and business-program cleanup; then enter Phase 7E only after
Phase 7C succeeds. The legacy PowerShell entry remains retained.
