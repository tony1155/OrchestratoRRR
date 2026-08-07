# OrchestratoRRR 阶段规划

Adapter 真实 smoke 门禁已于 2026-07-30 关闭。6C2A、6C2B（含真实冷连接恢复）和 6C2C 均已完成验收，6C3 已完成文档收口。6B2B3C 已完成 managed 生命周期实现与 15 阶段真实端到端验收，同时解除 MAA 配置同步在 `run` v1 的闸门。6B2B2B 已解除 MAA 自更新闸门（`run` 不再以 maa_update_not_allowed_in_run_v1 阻断），真实打包工作流验收留待 Phase 7C。Phase 7A1 已完成入口契约实现与自动测试，Phase 7C 的真实重试目标已从 external 11 阶段改为 managed 16 阶段（新增 SHUTDOWN_MUMU 收尾关闭），Phase 7 尚未完成。

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
| 6B2B3C | managed 实例化生命周期控制 | start/stop 语法与实例选择已确认，执行器接线、契约分层与 run 闸门均已完成；15 阶段真实端到端验收通过；当前完成 |
| 6C1 | 受控 external run CLI 与完整 Fake 验收 | 公开 external-only `run` v1、精确确认、有限 Deadline、入口提权接线与完整 Fake 验收；已完成 |
| 6C2A | ADB devices 空白分隔兼容修复 | 第一次真实 smoke 在 MuMu readiness 安全停止；修复空格、Tab 与混合分隔并增强安全诊断；已完成 |
| 6C2B | 修复后 readiness 与受控连接恢复 | 6C2B3 人工 connect 后 readiness 已验证；6C2B4A 完成显式 local TCP connect 的 Fake/自动测试；6C2B4C 完成真实冷连接自动恢复；已完成 |
| 6C2C | 修复后 external 真实完整工作流 smoke | 11 阶段 external 完整真实 smoke 已通过；AALC 在线业务 UI 因网络原因未验证；已完成 |
| 6C3 | Phase 6 最终验收、文档收口与合并准备 | 脱敏证据已固化，external-only 范围完成，等待人工审核；当前完成 |
| Phase 6 external scope | 已批准的 external-only 工作流范围 | Fake、生产 Adapter、冷连接恢复和完整真实 external workflow 均已验收；完成 |
| Phase 6 managed scope | MuMu managed 生命周期范围 | start/stop/restart 与实例自动选择已获批准并完成真实验收；收尾关闭模拟器阶段尚未纳入计划 |
| Phase 6 overall | Phase 6 按批准范围的状态 | 已批准的 external-only Phase 6 范围完成；不表示所有 MuMu 生命周期能力完成 |
| 7 | 打包与默认入口 | PyInstaller EXE、无缝替换旧 PS1 入口点 |

> **下一门禁：** 只有获得明确 start/stop/实例选择语法，并完成独立进程所有权验证后，才允许修改生产 start_arguments/stop_arguments。

每个阶段基于前一阶段构建，但不得退化先前阶段的测试。

Phase 6A 已固化入口权限规划契约：先构建完整计划；只要计划包含 `RUN_AALC` 且 AALC 声明 `requires_administrator=true`，就在 Runner 和任何 Stage 工厂构造前决定是否重启提升整个 OrchestratoRRR。不得在执行到 AALC 时才临时提升，也不得用 `runas` 绕过现有 ProcessSupervisor 单独启动 AALC。本阶段测试只使用 Fake gateway，未触发真实 UAC。

Phase 6B1 已完成生产投影与安全绑定骨架。默认完整生产计划在 `SYNC_MAA_CONFIG` 明确阻断，且阻断前不构造或执行任何 Runtime Adapter。MuMu 只允许只读 `status()`；start/stop 仍未获准。

Phase 6B2A 已完成旧流程静态契约调查，6B2B1 已完成安全 MAA 同步。Phase 6B2B2A 只实现固定 `maa update` 的 MaaCore/资源更新，默认关闭并要求显式网络授权；未执行真实更新。maa-cli 自更新与旧 hot-update 继续阻断于 6B2B2B。Phase 6B2B3A 的只读帮助证据仅确认 NemuShell RPC/Shell 调用形状，没有发现生命周期命令或安全实例选择器；`runtime_approved=false`。Phase 6B2B3B 提供 external 安全路径：用户预先启动正确实例，OrchestratoRRR 只验证 readiness，不调用 MuMu start/stop/restart。Phase 6B2B3C 已通过 `MuMuManager.exe control -v <index> launch/shutdown` 确认启停语法与实例选择，完成执行器接线、`ManagedMumuRuntimePort` 契约分层与 run 闸门放开，并修复四个仅在真实执行时暴露的缺陷（Job 句柄关闭连带终止模拟器、readiness 缺少受控 adb connect、投影层不认 STARTED/RESTARTED、停止阶段不认 STOPPED）；详见 `docs/acceptance/phase-6b2b3c-managed-mumu-lifecycle.md`。

Phase 6C1 已提供受控 `run` v1：精确确认、有限 Deadline、MAA Update 关闭、AALC attempts 为 1，并在 Runner/Stage factory/Adapter 前统一完成 elevation 决策。完整 Fake 验收已通过。第一次真实 external smoke 曾因旧解析器拒绝合法空格分隔的 ADB devices 记录而安全停止；6C2A 修复了解析兼容和脱敏诊断，6C2B4A 增加了受控 local TCP connect，6C2B4C 已完成真实冷连接自动恢复，6C2C 已完成 11 阶段 external 真实完整工作流 smoke。Phase 6C3 已固化脱敏证据并完成 external-only 收口。此后 6B2B3C 解除 managed 阻断并完成 15 阶段真实验收，MAA 配置同步亦已放行；6B2B2B 仍未完成，Phase 7A1 已完成入口契约实现与自动测试，Phase 7 尚未完成，旧 PowerShell 尚不可替换。
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
phase_7c_managed_target_rebuild_completed=true
phase_7c_managed_target_artifact_audit_completed=true
phase_7c_managed16_rebuild_completed=true
phase_7c_managed16_artifact_audit_completed=true
phase_7c_real_workflow_retry_completed=false
phase_7c_completed=false
phase_7e_completed=false
phase_7_completed=false
legacy_powershell_replacement_ready=false

## Phase 7C managed 16-stage rebuild and artifact audit

新增 `SHUTDOWN_MUMU` 收尾阶段（`a4eaab3`）后重建制品，基线为 `main` 的
`a4eaab3`，工作区干净，仍用受版本控制的 `scripts/build-package.ps1` 与
`packaging/OrchestratoRRR.spec`（PyInstaller 6.21.0）。构建脚本自带的三项后置
校验（EXE、`_internal`、内置 RunReport schema）均通过。

制品审计：

- `dist/OrchestratoRRR/OrchestratoRRR.exe`，7,507,985 字节，
  sha256 `266c00a378cc3864c53937f226c599eba10fc8ac4f1d56dc6f963bd7111ddfde`
- `_internal`：105 个文件，21,133,235 字节
- 内置 `run-report-v1.schema.json` 的 stage 枚举已含 `shutdown_mumu`。该枚举是
  硬编码的，未修正时 RunReport 无法通过 schema 校验，且因 schema 会被打包
  进 EXE（见 spec 的 datas），影响不限于测试

打包态非业务检查（针对真实 local 配置，managed 模式）：

- `version` 返回 `OrchestratoRRR 0.1.0`
- `validate --check-paths` 返回 `Validation OK.`
- `plan` 投影出 managed 16 阶段，`shutdown_mumu` 位于第 15 位、`write_run_report`
  仍为最后一位

本次审计未执行任何业务程序、未提权、未触发 ADB 或 TCP 连接。
`phase_7c_managed16_rebuild_completed=true` 与
`phase_7c_managed16_artifact_audit_completed=true`。

## Phase 7C managed-target rebuild and artifact audit

The onedir artifact was rebuilt from `main` at `de04a35` with a clean working
tree, using the version-controlled `scripts/build-package.ps1` and
`packaging/OrchestratoRRR.spec` (PyInstaller 6.21.0). The build script's own
post-conditions passed: the EXE, `_internal`, and the bundled RunReport schema
were all generated.

Artifact audit:

- `dist/OrchestratoRRR/OrchestratoRRR.exe`, 7,507,690 bytes,
  sha256 `9e26b5c635c5edc29614192260e35ad4658bd441015396e7f4ced98b2eaa6bde`
- `_internal`: 105 files, 21,133,209 bytes
- `_internal/autogame_orchestrator/_resources/run-report-v1.schema.json` present
  (3,936 bytes)
- The string `maa_update_not_allowed_in_run_v1` is absent from the bundle,
  confirming the lifted gate is present in the artifact rather than only in
  source

Packaged non-business checks against the real local configuration
(`maa_update.enabled = true`):

- `version` returns `OrchestratoRRR 0.1.0`
- `validate --check-paths` returns `Validation OK.`, which the previous artifact
  would have rejected at the run gate
- `plan` projects the managed 15-stage plan with `update_maa` at position 3

No business program, UAC elevation, ADB, or TCP connection was exercised by
this audit. `phase_7c_managed_target_rebuild_completed=true` and
`phase_7c_managed_target_artifact_audit_completed=true`. The real packaged
managed workflow retry remains gated by
PHASE_7C_REAL_WORKFLOW_RETRY_AUTHORIZATION.

## Phase 7C scope change: managed 15-stage retry

The Phase 7C real-workflow retry now targets the managed 15-stage plan instead
of the external 11-stage plan. The earlier external-only wording predates
Phase 6B2B3C, which unlocked the managed MuMu lifecycle and passed a real
15-stage end-to-end acceptance from source. The local configuration has used
`lifecycle_mode = "managed"` since then, and Phase 7E will replace the legacy
PowerShell entry with an entry that also runs managed. Auditing an external
run would therefore validate a configuration that is no longer the operational
one.

The MAA self-update gate was also lifted, so `UPDATE_MAA` now executes for
real rather than returning an immediate `executed=false` success. Installed
MaaCore is v6.14.2 while the MAA GUI is v6.16.2, so this retry is expected to
perform an actual download and extraction.

Audit scope for the retry: RunReport, JSONL, all 16 stages, real `UPDATE_MAA`
execution, `SHUTDOWN_MUMU` teardown (no emulator left running), and
business-program cleanup. The external 11-stage plan remains supported in code
and covered by automatic tests; only the real packaged retry target changed.

The stage count changed from 15 to 16 on 2026-08-06 (`a4eaab3`) with the new
`SHUTDOWN_MUMU` teardown. The motivation was empirical: after run `f4be5315`
LimbusCompany was still running, because AALC cannot close the game in emulator
mode. Its `exit_game` targets the Windows process `LimbusCompany.exe` while the
actual game is the Android app `com.ProjectMoon.LimbusCompany` inside MuMu, so
the action was a silent no-op. Teardown therefore belongs to the orchestrator,
which already owns the emulator lifecycle and whose `MuMuManager control -v 0
shutdown` is verified working.

The next phase is PHASE_7C_AUTHORIZED_REAL_PACKAGED_MANAGED_WORKFLOW, gated by
PHASE_7C_REAL_WORKFLOW_RETRY_AUTHORIZATION. It must not begin without separate
explicit authorization. The required order is: separately authorize the
repaired real packaged managed workflow retry; audit its RunReport, JSONL,
all 16 stages, real UPDATE_MAA execution, SHUTDOWN_MUMU teardown, and
business-program cleanup; then enter Phase 7E only after Phase 7C succeeds.
The legacy PowerShell entry remains retained.

## Phase 7C 首次真实 16 阶段运行：报告成功但收尾未生效

首次授权的真实打包 managed 16 阶段运行（run_id `8f96fb14-2576-454c-9bef-e6a625d5cb74`，
2026-08-07 09:03:50Z 起，历时 43 分 48 秒）RunReport 报 `status=success`、
`error_code=OK`，16 个阶段全部 `success`。但运行结束后 MuMu 仍在运行：
TCP 16384 为 OPEN，`MuMuVMMHeadless` 常驻，`MuMuManager info -v 0` 甚至 60 秒超时。
因此本次运行不足以翻转 `phase_7c_real_workflow_retry_completed`。

定位依据是阶段耗时与 `changed` 标志的对照：

| 阶段 | duration_ms | changed | 含义 |
|---|---|---|---|
| 9 `stop_mumu` | 3157 | true | 真的执行了停止命令 |
| 15 `shutdown_mumu` | 78 | false | 走了幂等短路，命令从未执行 |

`stop()` 中返回 `changed=false` 且 `error_code=OK` 的只有开头的「已 stopped → 幂等」
分支，故 `MuMuManager control -v 0 shutdown` 根本没有被调用。

根因是 `status()` 把 `PORT_CLOSED` 与 `DEVICE_NOT_FOUND` 一同映射为 `STOPPED`。
MuMu 的 ADB 是网络设备（`127.0.0.1:16384`），不像 USB 设备会自动出现；宿主 ADB
server 一旦重启就会忘掉网络设备注册，必须重新 `adb connect` 才能列出。AALC 退出时
重启了 ADB server，于是 readiness probe 的 TCP 探测通过（端口 OPEN），但
`adb devices -l` 返回空列表，`select_adb_device` 在 `select_device` 步骤抛出
`DEVICE_NOT_FOUND`，被误判成「已停止」。实测复现：TCP 16384 为 OPEN 而
`adb devices` 列不出目标 serial，手动 `adb connect` 后设备才出现。

修复（`243d061`）改动三处：

- `status()` 只以 `PORT_CLOSED` 作为 `STOPPED` 的证据。`DEVICE_NOT_FOUND` 落到方法
  末尾的 `NOT_READY` 分支，因为端口开着恰恰说明进程还活着，只是 ADB 未注册
- `_wait_stopped()` 的停止确认同样只接受 `PORT_CLOSED`。否则执行 shutdown 命令后若
  ADB server 恰好为空，会立刻误判成功返回，而 VM 其实还在；只认 `PORT_CLOSED` 时
  这种情况会诚实地等到 `STOP_TIMEOUT`
- `stop()` 的幂等返回补上 `diagnostics=st.diagnostics`。事故报告第 15 阶段缺少
  `probe_error` / `probe_step` 字段正是因为该分支丢弃了内层 probe 诊断

影响面已核对：`start()` 仅在 `READY` 时短路，不受影响；`ensure_external_ready()` 有
独立映射，`DEVICE_NOT_FOUND` 走 fallthrough 返回 `NOT_READY`，不经过 `STOPPED`，
故 EXTERNAL 路径行为不变。该缺陷能通过 1390 个测试是因为 `_FakeProbe(refused=True)`
只产生 `PORT_CLOSED`，`DEVICE_NOT_FOUND` 路径此前无任何覆盖；现补三个回归测试并逐项
验证「移除修复即变红」。

修复在真实事故态下验证：`status()` 返回 `not_ready` / `READINESS_FAILED`，诊断为
`probe_error=DEVICE_NOT_FOUND`、`probe_step=select_device`；`stop()` 返回
`changed=true`、耗时 2.70 秒，随后 TCP 16384 转为 CLOSED，`MuMuVMMHeadless`
（事故时占 1702 MB）在 20 秒内的三次采样中均已消失，`is_process_started` 与
`is_android_started` 双双为 false，`MuMuManager info -v 0` 恢复为即时响应。

## Phase 7C 修复后重建与制品审计

制品自 `main` 的 `243d061` 干净工作区重建，仍用受版本控制的
`scripts/build-package.ps1` 与 `packaging/OrchestratoRRR.spec`（PyInstaller 6.21.0），
构建脚本自带的三项后置校验均通过。

- `dist/OrchestratoRRR/OrchestratoRRR.exe`，7,507,942 字节，
  sha256 `e3fc7f29ad04a89210680fdc7624b6342a312668441bbca87de6c87c633a6028`
- `_internal`：105 个文件，21,133,235 字节

字节码级核验（从 PYZ 取出 `runtime.mumu` 后反汇编，而非只看源码）：
`MumuAdapter.status` 与 `MumuAdapter._wait_stopped` 均只引用 `PORT_CLOSED`，
`DEVICE_NOT_FOUND` 引用数为 0，确认修复进入了制品而非仅存在于源码。

打包态非业务检查：`version` 返回 `OrchestratoRRR 0.1.0`；
`validate --check-paths` 返回 `Validation OK.`；`plan` 投影出 managed 16 阶段，
`shutdown_mumu` 位于第 15 位、`write_run_report` 仍为最后一位。本次审计未执行任何
业务程序、未提权、未触发 ADB 或 TCP 连接。

下一步需要重跑一次真实 16 阶段运行。判定收尾是否真正生效的判据不是阶段
`outcome=success`（事故运行同样全绿），而是第 15 阶段的
`changed=true` 且 `duration_ms` 在秒级；若再次出现 `changed=false` 加毫秒级耗时，
说明仍有未堵住的误判路径。`phase_7c_real_workflow_retry_completed` 保持 false。
