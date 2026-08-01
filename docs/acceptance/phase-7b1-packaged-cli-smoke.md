# Phase 7B1——packaged CLI smoke 验收

## 结论

Phase 7B1 已完成。验收使用基线提交
`9c943b2d27b42dbc317fabbf565111aa3daf8b11` 上已经保留的同一份
PyInstaller onedir 产物，未重新构建，也未执行 EXE 的 `version`（该证据沿用此前累计通过结果）。

本轮先在仓库外系统临时工作区使用同一份纯合成 fixture 完成 source
`validate -> plan` 对照，再执行 packaged `validate -> plan`。source 与
packaged 的 plan 均以 `StageName.value` 的小写稳定值输出，并生成通过
对应 schema 校验的 15 阶段 plan RunReport。

## 累计与本轮证据

- packaged `version`：此前累计 PASS，本轮未重复执行。
- packaged plain root `--help`：此前累计 PASS；四个公开命令存在，隐藏 elevation marker 未暴露。
- source `validate`：exit 0，报告 schema 校验 PASS。
- source `plan`：exit 0，输出和报告均为 15 阶段，顺序及 schema 校验 PASS。
- packaged `validate`：exit 0，报告 schema 校验 PASS。
- packaged `plan`：本轮带有限 debug 环境执行一次，exit 0，输出、顺序、报告和 bundled schema 校验全部 PASS。
- 本轮 packaged 新启动次数为 2，未重试。

此前 packaged plan 的 `PACKAGED_PLAN_FAILED` 未在本轮复现；诊断轮未发现稳定产品异常，因此没有修改生产代码，也没有把此前的驱动失败归因于产品。

## Plan 与报告契约

公开 `plan` 命令继续是静态 15 阶段 dry plan，不等同于 production
external run 的 11 阶段计划。阶段顺序为：

1. `validate_config`
2. `sync_maa_config`
3. `update_maa`
4. `ensure_mumu_running`
5. `wait_mumu_adb_ready`
6. `run_starrail`
7. `stop_starrail`
8. `verify_starrail_stopped`
9. `stop_mumu`
10. `verify_mumu_stopped`
11. `start_mumu`
12. `wait_mumu_adb_ready_after_restart`
13. `run_maa`
14. `run_aalc`
15. `write_run_report`

首阶段为 `success/OK`，其余阶段为 `skipped/SKIPPED`。validate 和 plan
报告均使用 bundled RunReport schema 独立离线校验通过。报告和日志只写入
临时工作区，未写入仓库或 dist。

## 安全边界

- 只使用纯合成 fixture；未读取真实配置。
- 所有命令从仓库和 dist 之外的系统临时 cwd 执行。
- 未使用 `--check-paths`，未执行任何 fixture executable。
- 未执行 `run`、UAC、ADB、MuMu、StarRail、MAA 或 AALC。
- 未重新构建，产物保持完整；临时工作区和 Git-ignored 诊断驱动已删除。
- 没有修改生产代码、测试、依赖、spec、构建脚本或 schema。

Phase 7B1 仅证明 packaged CLI 的受限 fixture-only smoke。它不证明冻结
UAC、packaged real workflow 或默认用户入口。Phase 7D blocker 仍然存在，
旧 PowerShell 入口仍不可删除，Phase 7 尚未完成。下一步为 Phase 7B2
packaged isolated workflow。
