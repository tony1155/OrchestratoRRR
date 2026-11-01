# MaaFgo GUI 配置与 CLI 执行

状态（2026-11-01）：**本机 CLI 已完成登录、关卡导航、助战选择与编队检查；完整战斗验收未通过。**
最后一次运行在进本时遇到游戏的“该支援角色不存在”弹窗，最终正确记录为失败。
自动退出、重新登录、刷新助战并重试的恢复分支尚未实现；不能把本轮接入描述为全流程可用。

## 两种安装身份

- 原始固定提交装配：`scripts/prepare_maafgo_cli_smoke.py` 生成 schema 1 清单，
  约束见 [真机验收手册](maafgo-real-acceptance.md)。
- 本机安装适配：`scripts/adapt_installed_fgo.py` 针对 MaaFgo **v2.0.17**、嵌入式 Python
  入口生成 schema 2 清单。本机已将 CLI 和根目录 DLL 统一为 MaaFramework **v5.14.3**，
  与 GUI/Python SDK 对齐。适配器本身不会下载或升级框架，不能只换一个 CLI 可执行文件。

schema 2 记录被守卫文件的实际 SHA-256，防止更新覆盖入口、报告器或框架后误用旧契约；
它不是官方签名，也不覆盖整个上游资源目录。不要给未知安装手工重算清单来绕过检查。

## 配置与启动

以下命令均在仓库根目录的 PowerShell 中执行，路径按本机安装修改。游戏和模拟器应停止自动运行，
配置 GUI 在执行前关闭，避免同时控制同一个模拟器。

1. 在独立安装目录准备 MaaFgo，确认 GUI 的原生战斗可用。不要在其他自动化工具共用的目录上试验。
2. 核对 CLI、根目录框架 DLL 与 Python SDK 版本。针对上述已验证安装执行一次适配：

   ```powershell
   .\.venv\Scripts\python.exe scripts\adapt_installed_fgo.py "C:\path\to\MaaFgo-ORR"
   ```

   该操作备份受影响文件到安装目录旁的 `_config-backups/fgo-workflow-*`，
   包装任务入口并加入资源不足处理层，同时移除 GUI 的 `mirrorchyan_rid` 自动更新入口。
   第三方更新后需重新核对安装，不能假定私有补丁仍然存在。

3. 在运行配置中启用 GUI 同步：

   ```toml
   game = "fgo" # 独立 FGO 计划；其他配置段参照 orchestrator.example.toml

   [fgo]
   provider = "maafgo"
   package_name = "com.bilibili.fatego" # 按区服选择
   stop_game_on_exit = true
   append_to_workflow = false

   [maafgo]
   enabled = true
   executable = "C:/path/to/MaaFgo-ORR/MaaPiCli.exe"
   working_directory = "C:/path/to/MaaFgo-ORR"
   gui_config_source = "C:/path/to/MaaFgo-ORR/config/mxu-MaaFgo.json"
   gui_instance_id = "orr-daily" # 替换为自己的 MXU 实例 ID
   timeout_seconds = 10800
   stop_timeout_seconds = 20
   ```

4. 在 GUI 中把“登录”放在第一项，勾选业务任务，使用“原生自动战斗”，确认区服、关卡、队伍及次数。
   首次验收建议 **1 次、不食用苹果**。需要刷到资源不足时可用 999 次作为上限；此版本 0 会被当作 1。
   “启动bbc”“直接bbc战斗”“Chaldea 一键战斗”“关闭游戏”不属于受支持的生产任务。
5. 保存并关闭 GUI，再执行转换检查（会更新 CLI 配置，但不启动游戏）：

   ```powershell
   .\.venv\Scripts\python.exe scripts\configure_fgo.py check --config "C:\path\to\orchestrator.local.toml"
   ```

6. 对符合源码入口路径约定的配置进行只读预检，再由用户选择是否运行：

   ```powershell
   .\scripts\run-local.ps1 -Config "C:\path\to\orchestrator.local.toml" -CheckOnly -NoPause
   # 下一条会启动真实游戏；仅在人工确认后执行。
   .\scripts\run-local.ps1 -Config "C:\path\to\orchestrator.local.toml" -DeadlineSeconds 14400
   ```

`game = "fgo"` 只运行 FGO，不运行星铁、MAA、BetterGI；managed 模式最终关闭 FGO 和 MuMu，
external 模式不管理模拟器启停。主动取消与失败的收尾差异见真机验收手册。

某些本机安装在仓库父目录提供 `Configure-FGO.cmd`、`Check-FGO.cmd`、`Run-FGO.cmd` 等快捷入口。
它们及 `local-config/`、MaaFgo 安装、战斗 JSON 均属于**仓库外本机数据**，clone 本仓库不会自动获得它们。
`scripts/open-fgo-gui.ps1` 也仅适用于仓库和 `MaaFgo-ORR` 并列的本机目录布局。

## 接入已有日常流程

在默认星铁工作流中设置 `[fgo] append_to_workflow = true`，把 FGO 放在 MAA 后、模拟器收尾前。
也可运行 `scripts/configure_fgo.py enable --config <配置路径>`；它先验证 GUI 任务再启用开关。
`disable` 只关闭接入开关，不删除游戏配置。

- `[orchestrator] skip_maa = true`：暂时跳过 MAA 同步、更新、资源合并和执行，保留配置便于恢复。
- `[orchestrator] continue_on_failure = true`：记录失败并继续后续独立游戏，整次报告仍保留失败状态。
- 准备条件失败会跳过依赖它的游戏；前一个脚本未清理干净时阻止后续游戏抢占共享模拟器。
- 手动停止、全局超时或主配置无效仍终止流程。当前尚不支持自由选择游戏及任意排序。

这两个开关在示例配置中默认关闭。2026-11-01 本机因 MAA 上游适配问题临时启用了 `skip_maa`；
这只是本机运行选择，不应把“永久停用 MAA”写入公共默认配置。

## GUI → CLI 转换边界

源文件是指定 MXU 实例的 `config/mxu-MaaFgo.json`；目标是 `config/maa_pi_config.json`。
转换保留任务顺序、勾选状态、当前分支的嵌套选项、输入值和默认值；变化时备份旧 CLI 配置为 `.json.bak`。
GUI 文件及本地战斗方案不会被转换器改写。

- 输入映射为 PI 的 `inputs`，多选为 `values`，开关按 MXU 的 Yes/No 命名转换。
- 设备端点必须与编排器一致；实际启动前按保存的设备名、ADB 路径和端口再次核对设备。
- 加密输入及 GUI 自定义前置程序不属于转换契约；未知或不支持的任务选项会拒绝转换。
- 适配脚本把 MXU 的 `scan_select` 转成 CLI 支持的标准选择列表。目前是**适配时的文件快照**，
  不会自动追踪之后新增/删除的方案文件；新增本地方案后需核对选项列表，不能宣称热刷新已实现。

没有单独的“领取奖励”任务，登录后的奖励弹窗处理由上游登录流程决定；友情召唤等消耗性任务不等同领奖。
本机选关偏移曾通过固定 MuMu **60 FPS** 解决；试验性替代导航没有部署，也不包含在本轮正式修复中。

## 执行与结果回传

`orr_cli_runner.py` 关闭 CLI 标准输入，避免“按回车继续”无人处理；输出写入本次
`run-results/maafgo/<run-id>/maafgo-cli.log`，每份 1 MiB、保留两份备份。Agent 未写就绪报告的启动等待上限为 120 秒。

本机 MaaPiCli v5.14.3 未转发原报告器依赖的 Tasker 通知，故 schema 2 安装将任务入口包装为
`orr_run_task`，按 `Context.run_task()` 的实际状态报告成功/失败，不能用 CLI 的退出码代替任务结果。
报告器在 GUI 中也会导入，但没有 ORR 运行契约时不写报告，只调用原入口；ORR 运行时不导入 BBC 进程处理器。

`resource/orr-workflow` 在已有体力检查分支中补充风暴罐不足识别，只有明确不足弹窗才正常结束。
这些分支已有离线验证，**真实资源不足弹窗尚未验收**。关卡导航、战斗技能及队伍 JSON 保持上游/用户设置。

## 本轮真实证据与未完成事项

2026-11-01 18:46–18:52（UTC+8）的独立 FGO 运行：

- 登录成功，进入所选关卡，选中符合方案的助战，完成编队检查。
- 18:49:45 点击开始，随后加载界面出现“该支援角色不存在”；目前没有足够证据断定根因。
- 原生进本等待链没有接入该异常的恢复，18:52:25 任务失败。
- CLI 退出码为 0，但任务报告为登录 `success`、日常战斗 `failed`；编排器正确记录失败并执行 FGO/MuMu 收尾。

下一步仍需验证单场战斗成功、资源耗尽正常结束、助战异常的有界恢复，以及超时/取消的真实清理行为。
本轮收口仅保存已有代码与证据，不启动游戏，不添加未经验证的助战重试实现。
