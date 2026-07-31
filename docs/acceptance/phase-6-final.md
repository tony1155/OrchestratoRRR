# Phase 6 最终验收

## 验收范围

本阶段按批准范围定义为 external-only 工作流收口。Phase 6 完成的含义是：已批准的
external-only 生产路径完成 Fake、Adapter、冷连接恢复和完整真实 workflow 验收；不表示
所有 MuMu 生命周期能力已经完成。

批准基线提交：`3a63f949ccc7effc42e09252633e4a39c4a94f2c`。

## Phase 6A：工作流内核

- 冻结执行计划和阶段顺序。
- 通过 Fake Stage 验证编排行为。
- fail-fast 在首个失败、取消、超时或非法结果后阻断后续业务阶段。
- Deadline 和 CancellationToken 沿同一次运行传播，不由子阶段重置。
- RunReport/StageReport 使用稳定 schema 和脱敏投影。
- 在 Runner、Stage factory 和 Runtime Adapter 构造前完成入口级 UAC 决策。

## Phase 6B：生产绑定与安全边界

- 完成生产 Stage 投影、Runtime binding 和 ReportSink。
- MAA Sync 默认关闭。
- MAA Update 默认关闭。
- external MuMu 模式由外部操作者管理实例，OrchestratoRRR 只执行 readiness/受控
  external ensure。
- managed 模式继续显式阻断；没有把未经批准的 MuMu start/stop/restart 纳入发布范围。

## Phase 6C：external-only 生产验收

- 完成 external-only `run` v1、入口级 UAC、精确确认、有限 Deadline 和 Fake 编排验收。
- 完成真实 ADB parser 的空白分隔兼容修复及脱敏诊断。
- 完成受控 local TCP connect：仅由显式 external ensure 在严格 `DEVICE_NOT_FOUND`
  条件下最多连接一次，status/probe/WAIT 保持只读。
- 完成 Phase 6C2B4C 真实冷连接自动恢复：生产 ENSURE 自动 connect，readiness 复验
  恢复 ready，连接保留。
- 完成 Phase 6C2C external 11 阶段真实完整 workflow smoke，RunReport schema=1、
  status=success、error_code=OK，所有阶段为 success/OK。
- MAA Sync/Update 未执行；MuMu start/stop/restart、ADB server restart、额外 disconnect、
  emulator 自动选择和自动重试均未发生。

## AALC 限定结论

```text
aalc_process_lifecycle_validation=PASS
aalc_adapter_contract_validation=PASS
aalc_online_business_ui_validation=NOT_VERIFIED
aalc_business_task_completion_claimed=false
aalc_network_issue_blocking_phase_6=false
```

AALC 真实进程启动一次，由操作者通过自身界面正常关闭，exit code=0 且 cleanup 成功。
网络原因导致在线业务 UI 未打开，因此不能声称 AALC 在线流程或业务任务已验证。

## Phase 6 完成判定

```text
phase_6_external_scope_completed=true
phase_6_managed_scope_completed=false
phase_6_completed=true
```

解释为：已批准的 external-only Phase 6 范围完成。以下能力仍不属于完成范围：

- managed MuMu start/stop/restart；
- MuMu 实例自动选择；
- 6B2B2B maa-cli 自更新决策；
- 6B2B3C managed 实例生命周期控制；
- AALC 在线业务 UI（因网络原因未验证）；
- Phase 7 打包和默认入口。

6B2B2B 和 6B2B3C 必须继续保留为未完成的未来阻断项，不得为了标记 external-only
Phase 6 完成而删除或弱化。

## 旧 PowerShell 替换判断

```text
legacy_powershell_replacement_ready=false
replacement_blocker=PHASE_7_PACKAGING_AND_DEFAULT_ENTRY
```

核心 external 工作流已经具备替换能力，但 Phase 7 打包和用户默认入口尚未完成。因此
旧 PowerShell 入口暂不可移除；待 Phase 7 提供可部署的默认入口后再进行替换评审。

## 下一阶段

```text
next_phase=PHASE_7_PACKAGING_AND_DEFAULT_ENTRY
```

提交前仍需人工审核本轮文档差异和脱敏边界。本轮不提交、不推送，也不执行任何真实
程序或再次验收。
