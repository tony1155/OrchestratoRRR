# FGO 链路验收指引（给有游戏环境的验收人）

> 交付物：两个分支。本文从零开始，在**装有 MuMu + FGO 的 Windows 机器**上完成验收。
> 预计耗时：环境准备 20–40 分钟（含 Mash 下载资源），实际验收 30–60 分钟。
> 全程不需要 Rust 工具链；OrchestratoRRR 侧需要 Python 3.11+。

## 0. 你会拿到什么

| 交付物 | 仓库 / 分支 | 内容 |
|---|---|---|
| mash-cli（headless 接口） | [tony1155/mash-app](https://github.com/tony1155/mash-app) fork，分支 [`feat/headless-cli`](https://github.com/tony1155/mash-app/tree/feat/headless-cli) | mash-app 上游 + 无窗口 CLI 入口（对上游净改 ~60 行） |
| FGO 编排链路 | [tony1155/OrchestratoRRR](https://github.com/tony1155/OrchestratoRRR)，分支 [`feat/fgo-mash-workflow`](https://github.com/tony1155/OrchestratoRRR/tree/feat/fgo-mash-workflow) | MashAdapter + `game="fgo"` 计划 + 配置段 + 32 个新测试 |
| 预编译 exe | mash-app 分支的 `dist-headless/mash-cli.exe` | 免装 Rust 直接用（对应分支的 release 构建） |

契约文档：mash-cli 接口规范见 [tony1155/mash-app 分支 docs/headless-cli-spec.md](https://github.com/tony1155/mash-app/blob/feat/headless-cli/docs/headless-cli-spec.md)；编排侧设计见本分支 `docs/fgo-mash-workflow.md`。

## 1. 准备 Mash（一次性，需要图形界面）

1. 安装 [Mash](https://github.com/ZaiZheTingDun/mash-app) 正式版（v0.23.0+，Windows x64）。
2. 打开 Mash GUI，按官方文档：连接 MuMu 设备、**下载 CV 运行时**、下载资源包、
   创建一个 FGO 周回项目（选好从者/礼装/周回数），在 GUI 里手动跑通至少一次战斗。
   —— 这一步确保 `%APPDATA%\com.xiaotongx.mash` 里有可用配置与运行时，mash-cli 与 GUI 共享它。
3. 拿到项目 id：记下或运行第 2 步的 `mash-cli projects`。

## 2. 验收 mash-cli（可独立于 OrchestratoRRR 进行）

**安装**：从 mash-app fork 的 `feat/headless-cli` 分支下载
[`dist-headless/mash-cli.exe`](https://github.com/tony1155/mash-app/raw/feat/headless-cli/dist-headless/mash-cli.exe)，
放进 Mash 安装目录（与 `Mash.exe` 同级）。
（或自行构建：clone fork 分支 → `pnpm install --frozen-lockfile` → `cd src-tauri && cargo build --release --bin mash-cli`）

按顺序执行，每步给出预期：

```powershell
cd <Mash 安装目录>

# ① 列项目：能看到第 1 步建的项目
.\mash-cli.exe projects --json

# ② 列设备：MuMu 开着时应看到 127.0.0.1:<端口> 的 device
.\mash-cli.exe devices --json

# ③ 前置自检：期望 ok=true（cvRuntime/scrcpyJar/templates/servantAssets 全绿）
.\mash-cli.exe validate --project <项目id> --json

# ④ 冒烟 dry-run：不指定 --device，故意用一个不存在的 serial
#    预期：exit code 1，stdout 最后一条 result 事件 outcome="error"，
#    message 含 "no device found"，且生成了 result JSON 文件
.\mash-cli.exe run --project <项目id> --device 127.0.0.1:1 --server cn --result-file smoke.json --watchdog 60
echo $LASTEXITCODE   # 期望 1
type smoke.json

# ⑤ 真机短跑：repeat 限制 1 轮，FGO 停在可开始战斗的界面后执行
#    预期：exit code 0，result JSON outcome="finished"、completedRuns=1
.\mash-cli.exe run --project <项目id> --repeat count:1 --result-file real.json
echo $LASTEXITCODE   # 期望 0

# ⑥ 优雅取消（另开一个终端，趁 ⑤ 换成 count:5 长跑时）：
.\mash-cli.exe cancel            # 立即取消；预期 ⑤ 侧 exit code 2、outcome="cancelled"
.\mash-cli.exe cancel --after-current   # 当前局收尾后停；预期 exit code 0
```

验收通过标准：①–④ 全部符合预期，⑤ 至少一次 exit 0，⑥ 两种取消各自得到对应退出码。

## 3. 验收 OrchestratoRRR FGO 链路

```powershell
git clone -b feat/fgo-mash-workflow https://github.com/tony1155/OrchestratoRRR.git
cd OrchestratoRRR
python -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

# ① 静态与单元回归（不需要游戏）
python -m pytest -q          # 预期 1545 passed
python -m ruff check src tests config
python -m mypy src/autogame_orchestrator

# ② 配置
Copy-Item config\orchestrator.example.toml config\orchestrator.local.toml
# 编辑 orchestrator.local.toml：
#   顶部 game = "fgo"
#   [mumu] 按机器实际填（沿用原有 StarRail 配置的写法即可）
#   [mash] executable = "<Mash安装目录>\mash-cli.exe"，working_directory/resource_dir 指向安装目录，
#         project_id 填第 1 步的项目，result_file 填一个绝对路径

# ③ 干跑计划（不执行任何外部程序），确认 6 阶段 FGO 计划
python -m autogame_orchestrator <dry-plan 入口，见 README"当前生产流程">

# ④ 真实运行（managed 模式需要管理员/UAC；与既有 StarRail run 相同入口）
#    预期：按 VALIDATE → ENSURE_MUMU_RUNNING → WAIT_MUMU_ADB_READY → RUN_MASH → SHUTDOWN_MUMU → WRITE_RUN_REPORT
#    顺序执行，run-results 下生成 RunReport，RUN_MASH 阶段 diagnostics 含
#    mash_outcome="finished"、mash_completed_runs、owned_process_cleaned=true
```

验收通过标准：① 全绿；③ 计划与文档一致；④ 一次完整成功 + 一次中途 Ctrl+C/取消
（预期 run 状态 cancelled、MuMu 被清理关闭）。

## 4. 出问题时的取证清单

把以下内容发回即可定位：

1. 对应的 `run-results` RunReport JSON（OrchestratoRRR 侧）或 result JSON（mash-cli 侧）；
2. `<Mash安装目录>` 下 mash-cli 的完整 stdout/stderr 复制；
3. `mash-cli validate --json` 的完整输出；
4. `%APPDATA%\com.xiaotongx.mash\cli\runs\` 下最新的 JSON（含事件计数）。

## 5. 已知边界（不算验收失败）

- FGO 与 StarRail 不能并发（共享 MuMu），串行编排即可。
- mash-cli `run` 期间不要同时用 Mash GUI 开自动化（会抢设备/sidecar）。
- 服务器切换（cn/jp）以 `[mash].server` 为准，且项目内的识别配置需与服务器匹配。
