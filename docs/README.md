# 文档索引

本目录混合了两类文档：**活文档**（随代码演进，发现过时就地更新）与
**历史记录**（固定时间的证据/快照，不改写原文，只追加状态标注）。
改动前先确认你在改哪一类。

## 活文档（随代码更新）

| 文档 | 内容 |
| --- | --- |
| [../README.md](../README.md) | 产品概览、安装、配置边界、能力清单 |
| [architecture.md](architecture.md) | 分层架构与当前验证状态（顶部为活摘要） |
| [maafgo-full-workflow.md](maafgo-full-workflow.md) | FGO（MaaFgo）链路设计：计划、完成证据契约、BBC 安全、teardown 矩阵 |
| [decisions/](decisions/) | 架构决策记录（ADR）：0001 语言选型、0002 进程约束、0003 BBC-free 私有分发 |
| [../config/orchestrator.example.toml](../config/orchestrator.example.toml) | 配置项权威示例（含注释） |

## 手册（按需执行）

| 手册 | 场景 |
| --- | --- |
| [manual/maafgo-real-acceptance.md](manual/maafgo-real-acceptance.md) | FGO 链路真机验收 Gate 0–8（真机验收待用户） |
| [manual/local-source-entry.md](manual/local-source-entry.md) | 源码运行入口与数据目录 |
| [manual/bettergi-integration.md](manual/bettergi-integration.md) | BetterGI 一条龙接入 |
| [manual/adapter-real-smoke-gate.md](manual/adapter-real-smoke-gate.md) | 单 Adapter 真实 smoke 门禁（历史门禁，已关闭） |
| [manual/phase-*.md](manual/) | 各阶段真机 smoke 的分步操作记录 |

## 调查记录（只读快照，不改写）

[investigations/](investigations/) 保存固定 revision 的只读调查；每篇顶部的
"状态更新"块标注其结论后来的去向。MaaFgo 相关六篇（BBC 所有权/无 BBC 路径/
Agent import 安全/MaaPiCli Windows/Phase 2A/2A.1）与 2026-10-29 upstream
inventory 是 Phase 2 决策的证据链。

## 验收证据账本（只追加，不删除）

[acceptance/](acceptance/) 按 phase 编号与日期记录每个阶段的真实/合成验收
证据。它们被 architecture、phase-plan 与维护日志交叉引用，是项目的审计边界；
**不做过期清理**——过时的是"当前状态"类陈述，那类内容只出现在活文档里。

## 阶段规划

[phase-plan.md](phase-plan.md) 顶部段落是活的路线状态；正文表格与分节是
历史路线的叙事记录（截至 6B2B2B）。MaaFgo Phase 2 的分解不在此表内，
见分支 `feat/maafgo-full-workflow` 与 `docs/maafgo-full-workflow.md`。
