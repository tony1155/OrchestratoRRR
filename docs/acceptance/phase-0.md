# 阶段 0 验收记录

## 一、基线信息

* 项目：Autogame Orchestrator
* 阶段：阶段 0——项目骨架与行为契约
* 分支：`phase/0-bootstrap-contracts`
* 父提交：`f0a753c`
* 验收日期：`2026-07-21`
* 验收时间：`2026-07-21 18:56:38`
* Python 版本：`Python 3.12.4`
* Python 解释器：`E:\Program Files\Games\Autogame\orchestrator-src\.venv\Scripts\python.exe`
* 操作系统：Windows
* 验收人：shiki

## 二、阶段目标

阶段 0 的目标是在不改变现有生产行为的前提下，建立新编排器的工程基础、稳定接口和测试保护网。

本阶段交付内容包括：

1. 独立 Python 项目；
2. 标准 `src` 目录结构；
3. TOML 配置模型、解析和静态校验；
4. 稳定的 `ErrorCode`、`OutcomeKind`、`RunStatus` 和 `StageName`；
5. `StageReport` 和 `RunReport` 数据模型；
6. RunReport v1 JSON Schema；
7. RunReport v1 golden sample；
8. JSONL 结构化日志 writer；
9. RunReport 原子文件写入；
10. `version`、`validate`、`plan` 三个安全 CLI 命令；
11. Fake Program 测试资产；
12. 单元测试、CLI 测试和 Schema 合约测试；
13. 架构文档、阶段计划和架构决策记录。

本阶段不包含任何真实程序的启动、停止、探测或控制。

## 三、变更范围

本阶段暂存文件总数为 36 个。

其中：

* 修改已追踪文件：2 个；
* 新增文件：34 个；
* 删除文件：0 个。

允许的变更范围包括：

* `.gitignore`
* `README.md`
* `pyproject.toml`
* `config/`
* `schemas/`
* `src/`
* `tests/`
* `docs/`

实际暂存内容全部位于上述批准范围内，未发现阶段 0 范围外的文件。

### 3.1 修改文件

* `.gitignore`

  * 移除错误写入的 PowerShell heredoc 内容；
  * 恢复为纯文本 Git 忽略规则。

* `README.md`

  * 增加项目目标；
  * 增加开发环境初始化方法；
  * 增加安全 CLI 命令说明；
  * 增加测试和阶段限制说明。

### 3.2 新增生产代码

* `pyproject.toml`
* `src/autogame_orchestrator/__init__.py`
* `src/autogame_orchestrator/__main__.py`
* `src/autogame_orchestrator/cli.py`
* `src/autogame_orchestrator/config_loader.py`
* `src/autogame_orchestrator/config_model.py`
* `src/autogame_orchestrator/log_writer.py`
* `src/autogame_orchestrator/models.py`
* `src/autogame_orchestrator/planning.py`
* `src/autogame_orchestrator/reporter.py`

### 3.3 新增配置和 Schema

* `config/orchestrator.example.toml`
* `schemas/run-report-v1.schema.json`
* `schemas/golden/run-report-v1.golden.json`

### 3.4 新增测试

* `tests/__init__.py`
* `tests/conftest.py`
* `tests/cli/__init__.py`
* `tests/cli/test_cli.py`
* `tests/contract/__init__.py`
* `tests/contract/test_run_report_schema.py`
* `tests/fakes/fake_stage.py`
* `tests/fixtures/valid-config.toml`
* `tests/fixtures/invalid-toml.toml`
* `tests/fixtures/invalid-values-config.toml`
* `tests/fixtures/missing-fields-config.toml`
* `tests/unit/__init__.py`
* `tests/unit/test_config_loader.py`
* `tests/unit/test_config_model.py`
* `tests/unit/test_log_writer.py`
* `tests/unit/test_models.py`
* `tests/unit/test_reporter.py`

### 3.5 新增文档

* `docs/architecture.md`
* `docs/phase-plan.md`
* `docs/decisions/ADR-0001-python-orchestrator.md`
* `docs/acceptance/phase-0.md`

## 四、开发环境检查

使用项目虚拟环境执行：

```powershell
$Python = '.\.venv\Scripts\python.exe'

& $Python --version
& $Python -c "import typer, pytest, ruff, mypy, jsonschema; print('dev dependencies OK')"
```

实际结果：

```text
Python 3.12.4
dev dependencies OK
```

检查结论：

* [x] 使用项目独立 `.venv`。
* [x] 未使用 Anaconda base Python 执行最终验收。
* [x] Typer 可导入。
* [x] Pytest 可导入。
* [x] Ruff 可导入。
* [x] Mypy 可导入。
* [x] jsonschema 可导入。

## 五、完整自动验收结果

### 5.1 Ruff 静态检查

执行命令：

```powershell
& $Python -m ruff check .
```

实际输出：

```text
All checks passed!
```

退出码：

```text
0
```

结论：

* [x] Ruff 静态检查通过。

### 5.2 Ruff 格式检查

执行命令：

```powershell
& $Python -m ruff format --check .
```

实际输出：

```text
22 files already formatted
```

退出码：

```text
0
```

结论：

* [x] 全部 Python 文件符合格式要求。

### 5.3 Mypy 类型检查

执行命令：

```powershell
& $Python -m mypy src
```

实际输出：

```text
Success: no issues found in 9 source files
```

退出码：

```text
0
```

结论：

* [x] 9 个生产源文件通过类型检查。
* [x] 未发现无效或未使用的 mypy 配置段。

### 5.4 Pytest 全量测试

执行命令：

```powershell
& $Python -m pytest -q
```

最终结果：

```text
86 passed
```

退出码：

```text
0
```

测试统计：

* Passed：86
* Failed：0
* Skipped：0
* Errors：0

结论：

* [x] 全量测试通过。
* [x] 未通过跳过测试获得绿色结果。
* [x] 测试不依赖真实安装路径。
* [x] 测试未启动真实外部程序。
* [x] 测试未访问网络。

### 5.5 日期时间专项测试

执行命令：

```powershell
& $Python -m pytest -q -k 'datetime or date_time or calendar'
```

最终结果：

```text
9 passed
```

退出码：

```text
0
```

结论：

* [x] 日期时间专项测试通过。
* [x] 合法带时区日期时间被接受。
* [x] 非法日期时间字符串被拒绝。
* [x] 无 `T` 分隔符的日期时间被拒绝。
* [x] 非法日历日期被拒绝。
* [x] 模型层拒绝无时区 `datetime`。

### 5.6 Reporter 与 Schema 专项测试

执行命令：

```powershell
& $Python -m pytest `
    tests/unit/test_reporter.py `
    tests/contract/test_run_report_schema.py `
    -q
```

结果：

```text
全部通过
```

退出码：

```text
0
```

结论：

* [x] Reporter 真实校验入口通过测试。
* [x] Schema 合约测试通过。
* [x] Golden sample 通过 Schema。
* [x] Python 生成的 RunReport 通过同一 Schema。
* [x] 非法数据会被 Schema 拒绝。

### 5.7 Git 空白检查

执行命令：

```powershell
git diff --cached --check
```

实际输出：

```text
无输出
```

退出码：

```text
0
```

结论：

* [x] 未发现尾随空格。
* [x] 未发现空白错误。
* [x] 暂存 diff 格式有效。

### 5.8 自动验收退出码汇总

```text
deps=0
ruff=0
format=0
mypy=0
pytest=0
datetime=0
diff=0
```

结论：

* [x] 所有自动门禁退出码均为 0。

## 六、日期时间语义验证

本阶段使用 JSON Schema 和 `jsonschema.FormatChecker` 对 RunReport 日期时间执行实际格式及语义校验。

已验证合法值：

```text
2026-07-21T08:30:00+00:00
```

已验证非法值：

```text
not-a-date
2026-07-21 08:30:00
2026-13-40T25:61:61+00:00
```

其中：

```text
2026-13-40T25:61:61+00:00
```

符合日期时间字符串的基本外形，但月份、日期、小时、分钟和秒均为非法值。

该测试用于证明系统不是只依赖正则表达式，而是实际执行日期时间语义校验。

检查结论：

* [x] Reporter 校验入口拒绝非法日历日期。
* [x] Schema 合约测试拒绝非法日历日期。
* [x] 合法带时区日期时间可以通过。
* [x] 无时区 `datetime` 被模型层拒绝。
* [x] Schema 校验未访问网络。
* [x] Schema 资源从本地读取。

## 七、CLI 手工验收

### 7.1 查看版本

执行命令：

```powershell
& $Python -m autogame_orchestrator version
```

实际输出：

```text
autogame-orchestrator 0.1.0
```

退出码：

```text
0
```

检查结果：

* [x] 版本命令退出码为 0。
* [x] 版本命令未读取配置。
* [x] 版本命令未创建日志。
* [x] 版本命令未创建 RunReport。
* [x] 版本命令未执行外部程序。

### 7.2 验证有效配置

执行命令：

```powershell
& $Python -m autogame_orchestrator validate `
    --config 'tests/fixtures/valid-config.toml'
```

实际输出：

```text
Validation OK.
```

退出码：

```text
0
```

检查结果：

* [x] 有效 TOML 解析成功。
* [x] 配置结构校验成功。
* [x] 默认未检查示例路径是否存在。
* [x] 生成 JSONL 日志。
* [x] 生成成功 RunReport。
* [x] 未启动任何外部程序。

### 7.3 查看静态计划

执行命令：

```powershell
& $Python -m autogame_orchestrator plan `
    --config 'tests/fixtures/valid-config.toml'
```

实际输出：

```text
DRY PLAN — no external programs will be executed

   1. validate_config
   2. sync_maa_config
   3. update_maa
   4. ensure_mumu_running
   5. wait_mumu_adb_ready
   6. run_starrail
   7. stop_starrail
   8. verify_starrail_stopped
   9. stop_mumu
  10. verify_mumu_stopped
  11. start_mumu
  12. wait_mumu_adb_ready_after_restart
  13. run_maa
  14. run_aalc
  15. write_run_report

End of plan.
```

退出码：

```text
0
```

检查结果：

* [x] 输出明确的安全提示。
* [x] 只展示静态计划。
* [x] 未执行任何计划阶段。
* [x] 未查询真实进程。
* [x] 未探测端口。
* [x] 未执行 ADB。
* [x] 未启动外部程序。

### 7.4 验证无效 TOML

执行命令：

```powershell
& $Python -m autogame_orchestrator validate `
    --config 'tests/fixtures/invalid-toml.toml'
```

实际输出：

```text
Validation FAILED [CONFIG_PARSE_ERROR]
```

退出码：

```text
1
```

检查结果：

* [x] 无效 TOML 返回非零退出码。
* [x] 返回稳定错误码 `CONFIG_PARSE_ERROR`。
* [x] 默认未显示完整 traceback。
* [x] 生成失败 RunReport。
* [x] 失败结果未被错误标记为成功。

### 7.5 CLI 退出码汇总

```text
version=0
valid=0
plan=0
invalid=1
```

结论：

* [x] CLI 行为符合阶段 0 契约。

## 八、静态生命周期顺序

静态计划按以下顺序定义：

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

关键生命周期顺序为：

```text
run_starrail
→ stop_starrail
→ verify_starrail_stopped
→ stop_mumu
→ verify_mumu_stopped
→ start_mumu
```

该顺序确保未来工作流不会在 StarRail 仍使用模拟器时提前关闭 MuMu。

阶段 0 只定义此顺序，不执行任何阶段。

## 九、模型和稳定契约检查

* [x] `schema_version` 使用整数 `1`。
* [x] `run_id` 使用合法 UUID 字符串。
* [x] 模型内部使用带时区的 `datetime`。
* [x] 结束时间不得早于开始时间。
* [x] `duration_ms` 不得为负数。
* [x] `SUCCESS` 必须使用 `ErrorCode.OK`。
* [x] 非成功结果不得使用 `ErrorCode.OK`。
* [x] `SKIPPED` 使用 `ErrorCode.SKIPPED`。
* [x] 错误码使用稳定且可读的机器名称。
* [x] 未知异常不得映射为成功。
* [x] diagnostics 必须可以 JSON 序列化。
* [x] Schema 使用明确 ErrorCode 枚举。
* [x] Schema 使用明确 StageName 枚举。
* [x] Schema 使用明确 RunStatus 枚举。
* [x] Schema 使用明确 OutcomeKind 枚举。
* [x] 顶层和嵌套对象禁止未声明字段。
* [x] Python 模型序列化结果通过同一个 Schema。
* [x] Golden sample 通过同一个 Schema。

## 十、RunReport 验收

* [x] RunReport 写入前执行 Schema 校验。
* [x] Schema 校验失败使用 `RUN_REPORT_VALIDATION_ERROR`。
* [x] 序列化失败使用 `RUN_REPORT_SERIALIZATION_ERROR`。
* [x] 写盘失败使用 `RUN_REPORT_WRITE_ERROR`。
* [x] 写入过程使用同目录临时文件。
* [x] 写入后执行 flush。
* [x] 尽可能执行 `os.fsync`。
* [x] 最终文件通过 `os.replace` 原子替换。
* [x] 写入失败不会留下半写入的最终报告。
* [x] 临时文件清理行为有测试覆盖。
* [x] 报告写入失败不会被视为业务成功。

## 十一、JSONL 日志验收

* [x] Writer 具有明确生命周期。
* [x] Writer 支持上下文管理器。
* [x] 初始化时打开日志文件。
* [x] 每条记录写入单独一行。
* [x] 每一行均为合法 JSON。
* [x] 时间戳包含时区。
* [x] 每条记录包含 `timestamp`。
* [x] 每条记录包含 `level`。
* [x] 每条记录包含 `event`。
* [x] 每条记录包含 `run_id`。
* [x] 每条记录包含 `message`。
* [x] 每条记录包含 `details`。
* [x] close 时执行 flush 并关闭文件。
* [x] 不可序列化 details 会被拒绝。
* [x] 日志写入错误使用 `LOG_WRITE_ERROR`。
* [x] 未静默忽略日志写入错误。
* [x] 未实现网络日志 sink。
* [x] 未实现后台日志线程。
* [x] 未实现 telemetry 上传。

## 十二、配置验收

* [x] 使用 Python 标准库 `tomllib`。
* [x] 使用 dataclass 和显式校验。
* [x] 未引入 Pydantic。
* [x] 配置文件不存在时返回 `CONFIG_FILE_NOT_FOUND`。
* [x] TOML 解析失败时返回 `CONFIG_PARSE_ERROR`。
* [x] 配置结构错误时返回 `CONFIG_SCHEMA_ERROR`。
* [x] timeout 必须为正整数。
* [x] AALC attempts 限制在 1 至 3。
* [x] arguments 必须为字符串列表。
* [x] heartbeat interval 不得小于 poll interval。
* [x] 默认验证不检查示例路径是否存在。
* [x] 只有指定 `--check-paths` 时才检查路径。
* [x] 路径检查只使用本地文件系统 API。
* [x] 路径检查不会启动目标文件。
* [x] 路径检查不会执行 ADB。
* [x] 路径检查不会探测端口。
* [x] 路径检查不会访问网络。

## 十三、Fake Program 边界

* [x] Fake Program 位于 `tests/fakes/`。
* [x] 生产代码未导入 Fake Program。
* [x] Fake Program支持正常退出。
* [x] Fake Program支持指定退出码。
* [x] Fake Program支持 stdout 输出。
* [x] Fake Program支持 stderr 输出。
* [x] Fake Program支持向指定文件写入文本。
* [x] 本阶段未实现无限挂起模拟。
* [x] 本阶段未实现子进程树模拟。
* [x] 本阶段未实现 Job Object。
* [x] 本阶段未实现真实进程监督。

## 十四、安全边界验收

* [x] 未启动或停止真实 MuMu。
* [x] 未执行真实 ADB。
* [x] 未启动 StarRailCopilot。
* [x] 未执行 MAA。
* [x] 未执行 AALC。
* [x] 未探测 TCP 端口。
* [x] 未查询真实系统进程。
* [x] 未使用 WMI 或 CIM。
* [x] 未实现 ProcessSupervisor。
* [x] 未实现 Windows Job Object。
* [x] 未实现 MuMu Adapter。
* [x] 未实现 StarRail Adapter。
* [x] 未实现 MAA Adapter。
* [x] 未实现 AALC Adapter。
* [x] 未实现可执行完整工作流。
* [x] 未实现 `run` 命令。
* [x] 未实现 `all` 命令。
* [x] 未实现 `start` 命令。
* [x] 未实现 `stop` 命令。
* [x] 未实现 `restart` 命令。
* [x] 未实现 `probe` 命令。
* [x] 未修改旧 PowerShell 编排器。
* [x] 未复制旧 PS1 流程。
* [x] 未添加网络访问。
* [x] 未创建 EXE 打包配置。
* [x] 实施代理未执行 Git commit。
* [x] 未实现阶段 1 或后续阶段功能。

## 十五、仓库和暂存区验收

* [x] `.gitignore` 已恢复为纯文本规则。
* [x] `.gitignore` 不包含 PowerShell heredoc。
* [x] `.venv/` 未被暂存。
* [x] `logs/` 未被暂存。
* [x] `run-results/` 未被暂存。
* [x] 本地配置文件未被暂存。
* [x] `__pycache__/` 未被暂存。
* [x] Pytest 缓存未被暂存。
* [x] Ruff 缓存未被暂存。
* [x] Mypy 缓存未被暂存。
* [x] 暂存文件总数为 36。
* [x] 全部暂存文件属于阶段 0 批准范围。
* [x] 暂存区不包含旧 PS1。
* [x] 暂存区不包含运行日志。
* [x] 暂存区不包含 RunReport 运行产物。
* [x] 暂存区不包含凭据或令牌。
* [x] 暂存区不包含环境变量值。
* [x] 暂存区不包含用户专属真实绝对路径。
* [x] `git diff --cached --check` 通过。

## 十六、已知限制

以下功能明确不属于阶段 0：

1. 通用进程监督器将在阶段 1 实现；
2. Windows Job Object 集成将在阶段 1 实现；
3. Fake Program 的超时、子进程和拒绝退出场景将在阶段 1 实现；
4. ADB、端口和日志探针将在阶段 2 实现；
5. MuMu Adapter 将在阶段 3 实现；
6. StarRail Adapter 将在阶段 4 实现；
7. MAA Adapter 将在阶段 5 实现；
8. AALC Adapter 将在阶段 6 实现；
9. 完整工作流将在阶段 7 实现；
10. EXE 打包和默认入口切换将在阶段 8 实现。

上述内容不是阶段 0 缺陷，不阻塞阶段 0 验收。

## 十七、验收结论

自动检查结果：

* Ruff：通过；
* Ruff 格式检查：通过；
* Mypy：通过；
* Pytest 全量测试：通过；
* 日期时间语义测试：通过；
* Reporter 与 Schema 专项测试：通过；
* CLI 手工验证：通过；
* Git 空白检查：通过；
* 暂存文件范围检查：通过；
* 安全边界检查：通过。

验收决定：

* [x] 已验收
* [ ] 未通过
* [ ] 有条件通过

验收说明：

> 阶段 0 已通过静态检查、格式检查、类型检查、全量自动测试、日期时间语义校验、CLI 手工验证、RunReport Schema 合约检查、安全边界检查和完整暂存区审查。未发现真实程序执行、后续阶段越界实现、生产路径污染或敏感信息泄露，批准提交阶段 0。

遗留问题：

> 无阶段 0 阻塞问题。后续能力按照既定阶段计划继续实施。

## 十八、提交信息

建议提交信息：

```text
chore(orchestrator): bootstrap project and contracts
```

本验收记录由用户在完成全部自动检查和人工审查后确认。
