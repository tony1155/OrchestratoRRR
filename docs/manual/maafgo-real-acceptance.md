# MaaFgo 完整 FGO 自动化 — 真机验收手册

状态：**REAL DEVICE ACCEPTANCE: PENDING USER**
适用分支：`feat/maafgo-full-workflow`（基线 `ce6d743`，见 Gate 0）
读者：在真实 Windows 机器上有 MuMu / FGO / MaaFgo 条件的验收人。

原则：**一步一验证**。每个 Gate 通过才进入下一个；不要用任何脚本一次性跑完
真实动作。所有命令在 PowerShell 中执行，工作目录为 OrchestratoRRR 仓库根。

约定：`<…>` 为占位符，按你的机器替换；不要把输出中的本机路径粘贴到公开渠道。

---

## Gate 0 — Git / artifact identity

逐条执行并记录输出：

```powershell
git branch --show-current
git rev-parse HEAD
git status --short
```

- `git branch --show-current` 必须输出 `feat/maafgo-full-workflow`；
- 工作区必须干净（无未预期修改）。

记录以下身份（后续 Gate 要复核）：

```powershell
Get-FileHash "<MaaFgo-ORR>\MaaPiCli.exe" -Algorithm SHA256
Get-FileHash "<MaaFgo-ORR>\distribution-manifest.json" -Algorithm SHA256
```

并打开 `<MaaFgo-ORR>\distribution-manifest.json`，记录：
`maafgo_commit`（应为 `d7f3a474f50b9a0631ee9acd6df67998c1933f2b`）、
`maaframework_version`（`v5.13.0`）、`orr_transform.transform_id`
（`orr-bbc-free-native-reporter`）、`orr_transform.bbc_listener_registered`
（`false`）、`orr_transform.reporter_registered`（`true`）。

不通过：不得继续。

## Gate 1 — 隔离的 MaaFgo 私有分发

确认以下路径都存在且属于**同一个私有根目录**（下称 `<MaaFgo-ORR>`），并且
它不是你其他 MaaFgo/MXU 安装目录：

```powershell
Test-Path "<MaaFgo-ORR>\MaaPiCli.exe"
Test-Path "<MaaFgo-ORR>\interface.json"
Test-Path "<MaaFgo-ORR>\agent\main.py"
Test-Path "<MaaFgo-ORR>\agent\orr_reporter.py"
Test-Path "<MaaFgo-ORR>\agent\custom\bbc_stop_listener.py"
Test-Path "<MaaFgo-ORR>\python\python.exe"
Test-Path "<MaaFgo-ORR>\config"
```

- `agent\orr_reporter.py` 必须**存在**；
- `agent\custom\bbc_stop_listener.py` 必须**不存在**
  （`False` 才通过：BBC 模块已从私有分发移除）；
- `agent\main.py` 中不得出现 `import bbc_`：

```powershell
Select-String -Path "<MaaFgo-ORR>\agent\main.py" -Pattern "import bbc_"
```

（无输出 = 通过。）

禁止：修改你的其他 MaaFgo/MXU 安装；把 `<MaaFgo-ORR>` 指向任何共享目录。

## Gate 2 — profile review（只读，不运行）

在 MaaFgo GUI 或直接检查 `<MaaFgo-ORR>\config\maa_pi_config.json`，确认：

1. `adb.address` == 你的 MuMu ADB 端点，即 OrchestratoRRR 配置里的
   `[mumu] adb_serial`（例如 `127.0.0.1:16384`）；
2. `adb.name` 形如 `<address>-<adb.exe 绝对路径>`（上游手工绑定命名）；
3. `adb.adb_path` 指向真实存在的 `adb.exe`；
4. `resource` 与你的实际服务器一致；
5. task 列表**第一个**是 `登录`；其后是你要跑的业务任务（例如 `日常战斗`）；
6. 业务战斗任务的 option 中 `battle_mode` 已显式选为 `native`；
7. 不包含 `启动bbc`、`关闭游戏`、`直接bbc战斗`；
8. 战斗次数建议 `battle_count = 1`（或原生自动战斗次数=1），便于首轮验收。

同时准备 OrchestratoRRR 的 `orchestrator.local.toml`：

```toml
game = "fgo"

[mumu]
lifecycle_mode = "external"   # Gate 4 先用 external；Gate 5 改回 "managed"
adb_executable = "C:/path/to/adb.exe"
adb_serial = "127.0.0.1:16384"
# managed 模式还需要 start_arguments / stop_arguments（见既有示例配置）

[fgo]
provider = "maafgo"
package_name = "<FGO Android 包名>"
stop_game_on_exit = true

[maafgo]
enabled = true
executable = "C:/path/to/MaaFgo-ORR/MaaPiCli.exe"
working_directory = "C:/path/to/MaaFgo-ORR"
timeout_seconds = 10800
stop_timeout_seconds = 20
```

先 review，不运行。

## Gate 3 — 独立 MaaPiCli 真实运行（不经 OrchestratoRRR）

1. 手工启动 MuMu，等待进入桌面。**FGO 保持未运行**（设置→应用里确认没有
   FGO 进程；或重启模拟器后直接开始）。
2. 用 PowerShell 为本次手工 run 生成证据契约（模拟 ORR 注入的环境变量）：

```powershell
$runId = [guid]::NewGuid().ToString()
$runDir = "<MaaFgo-ORR>\..\orr-standalone-runs\$runId"
New-Item -ItemType Directory -Path $runDir | Force
Copy-Item "<MaaFgo-ORR>\config\maa_pi_config.json" "$runDir\profile-copy.json"
# expected-tasks.json：把 profile 的 task 名与 interface entry 配对
# （登录 -> 登录识别；日常战斗 -> 日常战斗；可在 <MaaFgo-ORR>\tasks\*.json 里查 entry）
@([ordered]@{ name = "登录"; entry = "登录识别" },
  [ordered]@{ name = "日常战斗"; entry = "日常战斗" }) |
  ConvertTo-Json -Depth 4 | Set-Content "$runDir\expected-tasks.json" -Encoding UTF8
$env:ORR_MAAFGO_RUN_ID = $runId
$env:ORR_MAAFGO_PLAN_DIGEST = (Get-FileHash "$runDir\expected-tasks.json" -Algorithm SHA256).Hash.ToLower()
$env:ORR_MAAFGO_RESULT_PATH = "$runDir\maafgo-result.json"
$env:ORR_MAAFGO_EXPECTED_TASKS_PATH = "$runDir\expected-tasks.json"
$env:ORR_MAAFGO_RESULT_SCHEMA_VERSION = "1"
```

3. 运行并**全程观察**：

```powershell
Set-Location "<MaaFgo-ORR>"
.\MaaPiCli.exe -d
```

必须依次看到（不要求你预置任何页面）：

```text
FGO 被启动 → 登录/进入主界面 → 自动导航到指定关卡 → 助战/编队
→ native 战斗 1 次 → 结算 → MaaPiCli 退出
```

4. 验证证据 artifact（**不能只看 console 退出码**）：

```powershell
Get-Content $env:ORR_MAAFGO_RESULT_PATH
```

`outcome` 必须是 `success`，两个任务 `terminal` 均为 `success`，
`run_id` 与 `$runId` 一致，`unexpected_entries` 为空。
失败时记录 `outcome/tasks/unexpected_entries` 原文并停止。

## Gate 4 — OrchestratoRRR external MuMu

1. 手工启动 MuMu；FGO 不运行；MaaPiCli/Agent/BBC 均不运行。
2. `orchestrator.local.toml` 保持 `lifecycle_mode = "external"`。
3. 执行（受控 run 入口，需要显式确认字符串）：

```powershell
Set-Location "<OrchestratoRRR 根>"
.\.venv\Scripts\python.exe -m autogame_orchestrator run `
  --config .\orchestrator.local.toml `
  --deadline-seconds 14400 `
  --confirm-real-execution I_UNDERSTAND_THIS_RUNS_REAL_PROGRAMS
```

4. 观察并验证：

```text
不启动 MuMu（日志/行为均无 start）
→ ADB ready 确认 → PREPARE → RUN_MAAFGO（FGO 全流程）
→ STOP_FGO（FGO 被 force-stop）
→ MuMu 仍在运行（不被关闭）
→ 退出码 0；run-results/ 下生成 RunReport
```

RunReport 中 `validate_config/ensure_mumu_running/wait_mumu_adb_ready/
prepare_maafgo_run/run_maafgo/stop_fgo` 均 `success`，`shutdown_mumu` 不存在；
`run_maafgo.diagnostics.completion_confirmed == true`。

## Gate 5 — managed 冷启动（最终核心验收）

验收起点（全部为“否”）：

```text
MuMu 完全关闭
FGO 不运行
MaaPiCli / Agent 不运行
BBC 不运行
```

把 `orchestrator.local.toml` 改为 `lifecycle_mode = "managed"`（并配置
`start_arguments` / `stop_arguments`），再次执行 Gate 4 第 3 步的同一条命令。

必须完整看到：

```text
启动 MuMu → ADB ready → MaaFgo → FGO 启动 → 自动导航关卡
→ native 战斗 1 次 → completion confirmed → FGO 被 force-stop
→ MuMu 被关闭 → RunReport success（退出码 0）
```

如果任何一步需要你人工把 FGO 摆到助战页/编队页/战斗页：**Gate 失败**。
检查 MuMu 确实在 run 结束后被关闭（进程列表/窗口）。

## Gate 6 — failure

制造一个安全的确定性失败（推荐：把 profile 中业务任务改名，或临时把
`[maafgo] working_directory` 指向缺 manifest 的副本），重跑 managed 命令：

```text
必须：run != success；RunReport FAILURE
必须：无 MaaPiCli.exe / python Agent 孤儿进程残留（任务管理器确认）
必须：managed 模式下 MuMu 被安全关闭（若 MuMu 已被启动）
必须：FGO 从未启动时 STOP_FGO 被跳过
```

## Gate 7 — timeout

安全方式：临时把 `[maafgo] timeout_seconds` 改为 `180`，并在 Gate 3 的
expected-tasks 中放入一个不会完成的任务组合，或断开 MuMu 网络使任务卡住。
（不要用真实长关卡制造超时。）

```text
必须：RunReport TIMEOUT（WORKFLOW_STAGE_TIMEOUT）
必须：MaaPiCli + Agent owned 进程树被终止（任务管理器确认无残留）
必须：timeout 不能被 exit 0 / 晚到 success artifact 覆盖
必须：managed MuMu 按上一节 policy 被关闭
```

## Gate 8 — cancellation

在 RUN_MAAFGO 阶段（FGO 已在自动战斗中）对 OrchestratoRRR 进程按 Ctrl+C：

记录四件事并与本手册声明的策略比对：

```text
1. run status == cancelled（RunReport 或退出码 5）
2. owned MaaFgo 进程树（MaaPiCli + python Agent）已终止
3. FGO 状态：保留运行（不 force-stop）
4. MuMu 状态：保留运行（不关闭）
```

这是文档声明的取消语义（取消不破坏用户环境；owned 进程必须终止）。
如果实现与之不一致，记录实际行为 —— 那是缺陷。

---

## 通过标准

Gate 0–8 全部按上述断言通过，且 RunReport 证据齐全，才算
**REAL DEVICE ACCEPTED**。任何一步不符，请携带：

- Gate 0 记录的身份信息；
- 对应 Gate 的 console 全文；
- `run-results/` 下的 RunReport JSON；
- `distribution-manifest.json`（脱敏后）

提交反馈。不要在未通过全部 Gate 的情况下宣称接入完成。
