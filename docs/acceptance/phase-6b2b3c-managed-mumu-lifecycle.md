# Phase 6B2B3C——managed MuMu 生命周期与 MAA 配置同步验收

## 基线与执行范围

- 分支：`phase/7-packaging-default-entry`
- 起始基线提交：`165de11`
- 验收基线提交：`7ee8c1a`
- 模式：`workflow_external`（RunReport mode 枚举值，非 MuMu lifecycle_mode）
- MuMu lifecycle_mode：`managed`
- 完整 workflow 执行次数：`1`（最终验收轮）
- 运行退出码：`0`
- 脱敏耗时：`1677` 秒

本阶段解除 6B2B3C 的 managed 实例化生命周期阻断，并解除 MAA 配置同步在
`run` v1 的闸门。配置使用仓库外的本机 local 配置，通过公开 `run` CLI 进入
生产工作流。

## 解除阻断前的实际状态

managed 路径此前从未端到端执行过，阻断分布在五个层次，其中三处此前未被记录：

1. `run_application.validate_run_v1_config` 以 `managed_mumu_not_supported` 拒绝。
2. `run_application.validate_external_plan` 仅接受精确的 11 阶段 external 计划。
3. `executors._execute` 对 `STOP_MUMU`/`START_MUMU` 无条件硬阻断。
4. `executors._run_mumu` 在所有非 external 路径上只调用 `status()`；
   `MumuAdapter.start()`/`stop()` 仅被 `restart()` 内部引用，生产工作流从未触达。
5. `MumuRuntimePort` 契约未声明生命周期方法。

`runtime_bindings.build_mumu()` 是唯一本就正确的一层：managed 时返回完整
`MumuAdapter` 并传入 executable 与启停参数，external 时包裹为
`_ExternalMumuStatusPort`。

## 已确认的 MuMuManager 命令契约

本机 MuMu Player 12（product_version `5.23.0.3181`）经只读 `--help` 与受控
执行确认：

```text
control -v 0 launch      短命令，errcode 0 后立即退出，模拟器异步启动
control -v 0 shutdown    短命令，errcode 0 后立即退出
info -v 0                只读，暴露 is_android_started/is_process_started/adb_port
adb -v 0 -c connect      建立 adb 连接
control -v 0 app close -pkg <package>   关闭指定 App，实测 0.236 秒返回
```

实例选择为 `-v <index>`，本机仅一个主实例 `index=0`。adb 端点为
`127.0.0.1:16384`，与 `MumuAdapter` 默认值一致。冷启动 `launch_time` 实测
约 15.7 秒。

结论：2C 调查文档遗留的五项待补证据（是否有 CLI、start/stop 语法、实例
标识、是否短进程、adb 端点可否预测）已全部确认。

## 解除阻断过程中发现并修复的四个缺陷

四者均只在真实端到端执行时暴露，单元测试与只读干跑均无法发现。

### 一、Job Object 的 KILL_ON_JOB_CLOSE 连带终止模拟器

`MuMuManager.exe control -v 0 launch` 是引信型短命令，其派生的模拟器进程
需长期存活。这些后代自动加入同一 Job；命令退出后 `close_handles()` 关闭
Job 句柄，`KILL_ON_JOB_CLOSE` 随即终止箱内全部进程。

实测对照：

| 执行方式 | 命令结果 | Job 句柄关闭后模拟器 |
|---|---|---|
| 无 Job 的 shell | exit 0 | 存活至 `start_finished` |
| `ProcessSupervisor` | exit 0 | `is_process_started` 转为 false |

修复：`ProcessSpec` 新增 `descendants_survive_close`（默认 `False`，现有调用方
行为不变），为真时不配置 `KILL_ON_JOB_CLOSE`。仍然创建 Job 并加入进程，
因此超时或取消时 `terminate_job()` 依旧可一次性终止整棵进程树；未采用
「不装箱」方案，避免退化为后代逃逸。

### 二、readiness 等待缺少受控 adb connect

新启动的模拟器需经一次 `adb connect` 才出现在设备列表中，而
`_wait_readiness` 只调用只读 `probe()`，导致模拟器已 `start_finished` 仍
永远等不到 ready，最终 `START_TIMEOUT`。

修复：`_wait_readiness` 改用 `ensure_ready()`（内部执行受控 connect 并复检）。
`_wait_stopped` 保持只读 `probe()`——判定停止不应建立连接。

### 三、投影层不认生命周期动作的成功状态

`MumuAdapter.start()` 成功返回 `STARTED`、`restart()` 返回 `RESTARTED`，而
`project_mumu` 仅将只读探测的 `READY` 归为成功，两者落入兜底分支判为
`WORKFLOW_STAGE_FAILED`。诊断可见 `source_error_code=OK`、`action=start`、
`changed=true`，即适配器已成功而投影误判。

修复：`STARTED`/`RESTARTED` 与 `READY` 一并视为就绪成功。

### 四、停止阶段的 STOPPED 未被判为成功

同类缺陷的对称面。`STOPPED` 原本仅在旧 `verify_stopped` 标志为真时归为
成功，而执行器只对 `VERIFY_MUMU_STOPPED` 传该标志，导致 `stop()` 成功
返回 `STOPPED` 的 `STOP_MUMU` 阶段被判失败。

修复：标志更名为 `expect_stopped`，语义由「这是验证阶段」变为「本阶段期望
模拟器处于已停止状态」，`STOP_MUMU` 与 `VERIFY_MUMU_STOPPED` 均适用。停止
阶段拿到 `READY` 仍判失败，因此该阶段自身即可捕获「未停止」。

## MAA 配置同步

启用动机：GUI 中 `Fight` 关卡已改为 `TO-8`，而 maa-cli 侧仍为手工快照的
`1-7`，导致代理反复刷低级本。

以真实 GUI 配置只读干跑转换器时发现一个会造成回归的缺陷：转换器只读旧版
扁平 `Connect.*` 键，而本机 MAA 使用新版布局，连接配置位于 tasks 侧
`Gui.ConnectSettings`。旧代码对新版布局产出空的 adb_path/address/config，
若直接启用同步会覆盖可用连接配置并使 MAA 完全无法连接模拟器。

修复：

- 连接配置优先旧版扁平键，缺失时回退新版 `Gui.ConnectSettings`
  （含 `EnableAdbLite` 与 `AdbLiteEnabled` 的命名差异）。已验证的旧布局行为不变。
- 新版 `Gui.PostActions` 或旧版 `MainFunction.ActionAfterCompleted` 表达退出
  明日方舟时，追加 `CloseDown` 任务。此前转换器不产出 CloseDown，启用同步
  会抹掉手工添加的该任务；现由 GUI 作为唯一事实来源自动推导。
- `validate_run_v1_config` 不再拒绝同步。路径约束仍由 `MAASyncConfig` 保证
  （四路径非空、源与目标不得重叠），写入仍为原子替换并具备备份与双目标回滚。

只读干跑结果：profile 与当前可用 CLI 配置逐项一致（连接配置零退化），
tasks 仅 `Fight[4]` 由 `1-7` 变为 `TO-8`，`CloseDown` 保留。随后以临时目标
执行真实同步器：`completed/OK`，写出任务链为
`StartUp/Recruit/Infrast/Mall/Fight(TO-8)/Fight(1-7)/Award/CloseDown`。

真实同步已在验收前一轮生效，故最终验收轮 `sync_maa_config` 为
`changed=false`（内容一致不重写，幂等行为正确）。

## 执行计划与 RunReport

managed 执行计划精确包含 15 个阶段，与 `build_plan()` 逐项一致：

1. `VALIDATE_CONFIG`
2. `SYNC_MAA_CONFIG`
3. `UPDATE_MAA`
4. `ENSURE_MUMU_RUNNING`
5. `WAIT_MUMU_ADB_READY`
6. `RUN_STARRAIL`
7. `STOP_STARRAIL`
8. `VERIFY_STARRAIL_STOPPED`
9. `STOP_MUMU`
10. `VERIFY_MUMU_STOPPED`
11. `START_MUMU`
12. `WAIT_MUMU_ADB_READY_AFTER_RESTART`
13. `RUN_MAA`
14. `RUN_AALC`
15. `WRITE_RUN_REPORT`

RunReport 脱敏结果：

```text
report_found=true
report_schema_version=1
report_mode=workflow_external
report_status=success
report_error_code=OK
report_stage_count=15
report_stage_order_matches=true
requires_administrator=true
```

全部阶段均为 `success/OK`，脱敏耗时（秒）：

```text
validate_config                      0.0
sync_maa_config                      0.0
update_maa                           0.0
ensure_mumu_running                 48.0
wait_mumu_adb_ready                  0.2
run_starrail                         1.9
stop_starrail                        0.0
verify_starrail_stopped              0.0
stop_mumu                            2.9
verify_mumu_stopped                  2.0
start_mumu                          13.9
wait_mumu_adb_ready_after_restart    0.2
run_maa                            393.5
run_aalc                          1214.2
write_run_report                     0.0
```

`run_maa` 与 `run_aalc` 均为 `exit_code=0`、`termination_reason=normal_exit`、
`owned_process_cleaned=true`；`run_aalc` 为 `configured_attempts=1`、
`attempts_started=1`、`completion_mode=normal_exit`。

`run_starrail` 耗时 1.9 秒并判成功，因 StarRailCopilot 当日任务已完成，输出
`No task pending` 与 `Wait until <next> for task Restart`，命中配置的成功关键词；
该短路属预期行为，非跳过。

## 阶段性组件的独立真实验证

除完整轮外，另以真实模拟器逐阶段执行六个 MuMu 生命周期阶段，全部
`success/OK`：

```text
ensure_mumu_running                13172ms
wait_mumu_adb_ready                  218ms
stop_mumu                           2891ms
verify_mumu_stopped                 2045ms
start_mumu                         13844ms
wait_mumu_adb_ready_after_restart    266ms
```

适配器层单独验证：冷启动 `start()` 14.0 秒返回 `started/OK`；已就绪时重复
`start()` 为 0.2 秒且 `changed=false`（幂等正确）；`stop()` 2.9 秒返回
`stopped/OK`，`info` 确认 `is_android_started=false`。

## 自动化测试

`1380 passed, 1 skipped`；`mypy src` 无错误；改动文件 `ruff check` 与
`ruff format --check` 通过。

新增回归用例均已通过「移除修复后转为失败」的有效性验证：

- launcher 对照用例：相同引信型父进程，仅 `descendants_survive_close` 不同
  则后代结局相反；另一用例证明标志为真时 `terminate_job()` 仍可清空进程树。
- mumu 用例：`_wait_readiness` 未走 `ensure_ready` 时 `start()` 转为 timeout。
- 投影用例：`STARTED`/`RESTARTED` 与停止阶段 `STOPPED` 的成功映射。
- 执行器用例：managed `STOP_MUMU` 调用 `stop()` 且 `STOPPED` 判成功；
  `VERIFY_MUMU_STOPPED` 仍只读 `status()`。投影级用例无法覆盖执行器侧传参
  回退，故补执行器级用例。
- maa_sync 用例：新版布局连接配置、旧键优先、`PostActions` 追加与不追加
  `CloseDown`、旧版 `ActionAfterCompleted`；另有「启用同步但路径为空仍被配置
  校验拒绝」作为闸门放开后的底线。

`tests/runtime/test_maa_runtime.py::test_child_is_cleaned_after_parent_exit_zero`
存在既有偶发性（基线 1/12、本次改动 1/8 失败），与本阶段改动无因果关系。

## 契约与安全边界

- `MumuRuntimePort` 保持只读（status/ensure_external_ready）；新增
  `ManagedMumuRuntimePort` 扩展 start/stop 并标记 `runtime_checkable`。
  已验证：真实 `MumuAdapter` 满足后者，`_ExternalMumuStatusPort` 不满足且
  不具备 `start`/`stop` 属性，external 纵深防御未被削弱。
- `_run_mumu` 在配置声明 managed 但端口不具备生命周期能力时返回
  `mumu_lifecycle_port_unavailable` 阻断，避免静默降级。
- `STOP_MUMU`/`START_MUMU` 的硬阻断收窄为仅 external 模式生效。
- managed 要求显式配置启停命令，否则闸门以
  `managed_mumu_arguments_required` 尽早失败。
- 本阶段只放开 `run`。`default_entry`（交互式 `start` 命令）仍硬校验
  `EXTERNAL_RUN_STAGES`，保持 external-only。
- MAA 自更新（6B2B2B）与 AALC 重试的既有限制不变。

## 未完成项与已知问题

1. ~~**收尾不关闭模拟器。**~~ **已修（`a4eaab3`，2026-08-07）。** 新增
   `SHUTDOWN_MUMU` 收尾阶段（第 16 阶段）。run `7f524e53` 与 `faabbcef`
   两轮真实验收均报告 `shutdown_mumu diagnostics: changed=True`，ADB 端口
   16384 物理核实 CLOSED，player 进程消失。**已关闭。**
2. ~~**收尾出现半开状态。**~~ **已修（`243d061`，2026-08-07）。** 根因定位为
   `_wait_stopped()` 将 `DEVICE_NOT_FOUND` 误映射为 `STOPPED`（ADB 服务重启
   后设备注册丢失，不代表模拟器已停止）。修复后停止路径只认 `PORT_CLOSED`；
   新增三条回归用例，移除修复均变红。**已关闭。**
3. **`MuMuNxDevice` 孤儿泄漏——根因已查清，操作纪律已确定（2026-08-08）。**

   **根因**：`MuMuNxMain`（监工）负责回收 player，回收时需调用 `OpenProcess`
   请求含 `PROCESS_QUERY_INFORMATION(0x400)` 的权限。Windows 完整性策略
   对「MEDIUM 请求者 → HIGH 目标」全有或全无地拒绝，监工失去管理能力，
   player 留存为孤儿。

   **2×2 实证矩阵**（全部通过直接测试填完）：

   | 监工完整性 | player 完整性 | 结果 |
   | --- | --- | --- |
   | MEDIUM | MEDIUM | 不漏 |
   | HIGH | HIGH | 不漏 |
   | **MEDIUM** | **HIGH** | **漏（直接测试确认）** |

   混搭仅在「桌面开 MuMu UI（MEDIUM 监工在场）+ 运行提权编排器（HIGH player）」
   组合下出现，即历史 40 个孤儿产生的实际路径。

   **操作纪律（零代码改动）**：跑编排器前不从桌面开 MuMu UI。让
   `MuMuManager` 自己拉起监工，监工与 player 完整性一致，回收正常。
   run `faabbcef` 干净基线验收已证实（players born 2 / reaped 2 / leaked 0）。

   **清杀孤儿方式**：只申请 `PROCESS_TERMINATE(0x0001)` 直调
   `TerminateProcess()`，无需提权。`Stop-Process` / `taskkill /F` 均含
   `0x400` 位，对 HIGH 孤儿一律失败。

   判定：编排器命令用法正确（`MuMuManager control -v 0 shutdown`），
   不写孤儿清理逻辑进编排器（越界操作别人进程树）。**根因已关闭，
   操作纪律文档化。**
4. **提权子进程使用了非 venv 解释器。** 进程链显示提权重启使用
   `D:\Anaconda\python.exe` 而非 venv 解释器，尽管 `detect_entry_runtime()`
   经验证返回正确的 `sys.executable`。打包 EXE 不受影响；源码模式现象
   原因已知（venv stub + 真实解释器父子关系），不影响功能，待独立排查。
5. ~~**AALC 无重试余量。**~~ **已修（`d922782` / `de04a35`，2026-08-07）。**
   解除 managed 16 阶段闸门，`configured_attempts` 可在配置中设置。
   run `faabbcef` 验收确认 `attempts_started=1 successful_attempt_number=1`
   正常完成。**已关闭。**
6. **`plan` CLI 输出与实际执行计划不一致。** `plan` 命令使用静态
   `build_plan()`，恒显示 15 阶段；`run` 使用 `build_execution_plan(config)`
   按 lifecycle_mode 动态生成，external 配置下两者不同，易误导。未修。
7. **`shutdown_mumu` 上游失败时被跳过（`always_run` 缺口）。** 若
   `run_maa` 或 `run_aalc` 失败，`SHUTDOWN_MUMU` 会被 SKIP，模拟器留着
   不关。三条候选修法已记录在 `2bd4e1c` commit message，未实施。正常
   流程不触发，但属已知真实风险。

## 结论

managed MuMu 生命周期与 MAA 配置同步均已完成实现与真实端到端验收，
15 阶段完整工作流一次通过且无重试。6B2B3C 阻断解除。
