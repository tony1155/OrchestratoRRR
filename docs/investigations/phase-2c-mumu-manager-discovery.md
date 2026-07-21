# 阶段 2C——MuMu 管理命令发现与安全性判定

## 调查日期

2026-07-21

## 调查范围

1. 仓库内现有 MuMu 配置、脚本和文档证据。
2. 本机 MuMu Player 12 安装目录（`D:\Program Files\Netease\MuMu Player 12\`）中的可执行文件元数据。
3. MuMuVMM 虚拟机管理器（`C:\Program Files\MuMuVMMVbox\`）中的 CLI 工具。
4. Windows 服务、进程和快捷方式中的参数证据。

未执行任何 MuMu 可执行文件。未运行 `--help`、`version` 或任何其他命令。未访问网络。

## 仓库证据

| 文件 | 行号 | 内容 | 结论 |
|---|---|---|---|
| `config/orchestrator.example.toml` | 13 | `executable = "C:\\path\\to\\MuMuNxDevice.exe"` | 占位符路径。未填写真实值。 |
| `config/orchestrator.example.toml` | 24-25 | `start_arguments = []` `stop_arguments = []`（Phase 2B 手工说明） | 默认空参数。 |
| `docs/manual/phase-2b-mumu-smoke.md` | 21-25 | 同上，均为占位符 | 手工验收说明要求用户自行填写。 |
| `tests/fixtures/valid-config.toml` | 8 | `executable = "C:/path/to/MuMuNxDevice.exe"` | 测试占位符。 |

**仓库中不存在任何包含真实 MuMu 命令调用的 `.ps1`、`.bat`、`.cmd` 或其他脚本。**

## 本机候选文件

### MuMu Player 12 安装目录（nx_main）

| 文件 | 大小 | 文件描述 | 产品名 | 版本 | 签名 | 推测用途 |
|---|---|---|---|---|---|---|
| `MuMuManager.exe` | 18 MB | （无） | （无） | （无） | Valid | 候选管理工具。无 CLI 证据，18MB 偏大，可能为 GUI。当前未运行。 |
| `MuMuNxMain.exe` | 25 MB | （无） | （无） | （无） | Valid | GUI 主程序。开始菜单快捷方式指向该程序。MuMu 运行期间同时存在多个相关组件，但该程序是否直接派生或仅协调这些组件尚未验证。不批准交给 ProcessSupervisor.run()。 |
| `MuMuNxUpdater.exe` | 18 MB | （无） | （无） | （无） | Valid | 更新器。 |

### MuMu Player 12 安装目录（shell）

| 文件 | 大小 | 文件描述 | 产品名 | 版本 | 签名 | 推测用途 |
|---|---|---|---|---|---|---|
| `MuMuNxDevice.exe` | 30 MB | （无） | （无） | （无） | Valid | **当前正在运行**（PID 34804）。MuMu 运行期间长期存在的设备组件，具体职责未经验证。长期进程，**不可**作为短生命周期管理命令交给 ProcessSupervisor。 |
| `NemuShell.exe` | 233 KB | （无） | （无） | （无） | Valid | 小型可执行文件。可能为 CLI helper。但无版本信息，无参数证据。当前未运行。 |

### MuMuVMM 虚拟机管理器

| 文件 | 大小 | 文件描述 | 产品名 | 版本 | 签名 | 推测用途 |
|---|---|---|---|---|---|---|
| `MuMuVMMManage.exe` | 1.4 MB | MuMuVMM Command Line Tool | NetEase VM MuMuVMM | 6.1.36.152435 | Valid | **已确认为 CLI**。但属于底层虚拟机管理层，尚无证据证明它是正确的 MuMu Player 生命周期控制入口。其命令语义、子进程行为、MuMu Player 实例映射以及是否会启动长期 VM 进程均未验证。 |
| `MuMuVMMHeadless.exe` | 220 KB | MuMuVMM Headless Frontend | NetEase VM MuMuVMM | 6.1.36.152435 | Valid | VM 进程。长期进程。 |
| `MuMuVMMSVC.exe` | 5.7 MB | MuMuVMM Interface | NetEase VM MuMuVMM | 6.1.36.152435 | Valid | 服务。 |

### 正在运行的 MuMu 进程

| PID | 进程名 | 路径 |
|---|---|---|
| 34804 | MuMuNxDevice | `D:\Program Files\Netease\MuMu Player 12\nx_device\12.0\shell\MuMuNxDevice.exe` |
| 27832 | MuMuNxMain | （无路径 — 已提升权限） |
| 8272 | MuMuRemoteBackend | （无路径） |
| 5556 | MuMuRemoteService | `D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuRemoteService.exe --service` |

## 参数证据

### start 参数

**未找到。** 无脚本、无配置文件、无文档显示任何 MuMu 可执行文件的 start 参数。

### stop 参数

**未找到。** 同上。

### 实例选择

**部分。** `log/fcount.data` 中包含 `device_id=aeawjbblgqaavom6`。`configs/install_config.json` 中包含 `series: "12.0"` 和 `fchannel: "nochannel-mumu12"`。但无命令行参数格式证据。

### CLI 帮助文档

**未找到。** 未执行任何可执行文件（包含 `--help`），因此未验证是否有内置帮助。

## Job Object 风险分析

| 可执行文件 | 是否可以安全交给 `ProcessSupervisor.run()` | 理由 |
|---|---|---|---|
| `MuMuNxDevice.exe` | **否** | 长期运行进程（调查时 PID 34804），具体职责未经验证。作为长期进程不能由 ProcessSupervisor 管理。 |
| `MuMuNxMain.exe` | **否** | GUI 主程序。可能启动或协调其他 MuMu 组件；进程所有权与生命周期未经验证，不批准交给 ProcessSupervisor.run()。 |
| `MuMuManager.exe` | **未知** | 未验证其行为。18MB 大小暗示可能不是简单 CLI。如为 GUI 或长期进程，不可安全交给 ProcessSupervisor。如为短 CLI，可能安全。但未验证。 |
| `NemuShell.exe` | **未知** | 小型（233KB），可能为 CLI。但无参数证据，未验证。 |
| `MuMuVMMManage.exe` | **未知，不批准** | CLI 身份已确认，但其命令语义、子进程行为、MuMu Player 实例映射以及是否会启动长期 VM 进程均未验证。不批准接入。 |

## 最终分类

**B：候选存在但证据不足**

理由：

1. `MuMuManager.exe` 名称暗示管理功能，但 18MB 大小、无版本元数据、无 CLI 参数证据，不足以确认是短生命周期 CLI。
2. `NemuShell.exe` 体量符合 CLI（233KB），但同样无参数证据。
3. `MuMuVMMManage.exe` 是 CLI，但面向底层 VM 管理，可能不是正确的 MuMu Player 控制层。
4. 无脚本、无配置、无文档证明 start/stop 命令的具体参数格式。
5. `MuMuNxDevice.exe` 是长期运行设备组件（具体职责未验证），**确认不可**交给 ProcessSupervisor。

需要手工测试来补充的证据：
- `MuMuManager.exe` 是否有 `--help` 或 `/h` 输出
- `MuMuManager.exe` 是否接受 `start`/`stop`/`status` 命令
- `MuMuManager.exe` 执行 start 后是否立即退出（短生命周期）
- 实例 ID（如 `device_id`）如何传入

## 是否允许手工 smoke

**否。** 在补充上述证据前，不更新手工 smoke 文档。当前生产配置应保持 `start_arguments=()` 和 `stop_arguments=()`，即默认拒绝执行任何管理命令。

## 尚缺少的证据

1. `MuMuManager.exe` 是否接受命令行参数（需 `--help`）
2. start/stop 命令的具体语法
3. 实例标识参数（index 或 id）
4. 命令执行后是否为短进程（立即退出 vs 持续运行）
5. 它创建的 ADB 端口和 serial 是否可预测

## 相关文件路径（绝对路径，不含用户目录）

| 路径 | 说明 |
|---|---|
| `D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuManager.exe` | 候选管理工具 |
| `D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuNxMain.exe` | GUI 主程序（排除） |
| `D:\Program Files\Netease\MuMu Player 12\nx_device\12.0\shell\MuMuNxDevice.exe` | 长期运行设备组件，职责未验证（排除） |
| `D:\Program Files\Netease\MuMu Player 12\nx_device\12.0\shell\NemuShell.exe` | 候选 CLI helper |
| `D:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe` | ADB 可执行文件 |
| `C:\Program Files\MuMuVMMVbox\Hypervisor\MuMuVMMManage.exe` | VBox CLI（面向底层 VM） |
| `D:\Program Files\Netease\MuMu Player 12\configs\install_config.json` | 产品配置 |
| `D:\Program Files\Netease\MuMu Player 12\configs\vm_config.json` | VM 配置 |
