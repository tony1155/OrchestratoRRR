# Phase 6C2A——MuMu ADB 空白分隔兼容修复

## 真实失败证据

2026-07-30 经批准执行的第一次 external 真实完整工作流只运行了一次，退出码为 3，并在 `ENSURE_MUMU_RUNNING` 以 `READINESS_FAILED` 安全停止。后续只读脱敏探针确认：ADB 命令退出码为 0，标题有效，存在一个合法状态设备行；该行只使用空格分隔，而旧解析器要求 Tab，因而错误映射为 `ADB_OUTPUT_INVALID`。

本记录不包含真实 serial、端口、路径、设备属性、命令、输出、配置、RunReport 或 JSONL。第一次运行未到达 StarRail、MAA 或 AALC，三者均未启动；external 计划没有调用 MuMu start、stop 或 restart。

## 修复边界

`parse_adb_devices()` 现在使用 Python 的连续空白切分语义，兼容单空格、多个空格、Tab 及混合空白。token 仍严格解释为 serial、state 和后续 attributes；少于两个 token 仍返回 `ADB_OUTPUT_INVALID`。标题、空列表、重复 serial、精确选择、多设备拒绝、offline、unauthorized、未知状态、CRLF 和 attribute 首个冒号分割语义均保持。

MuMu status 结果增加固定 `probe_status`、`probe_error` 和 `probe_step` 分类。状态和错误来自稳定枚举，step 只允许 `tcp_probe`、`adb_devices`、`select_device`、`adb_get_state`、`adb_boot_completed` 或 `none`。生产 Stage 投影再次执行枚举与白名单校验，不转发 detail、serial、host、port、路径、命令或 stdout/stderr。

## 验收结论

本阶段只完成解析兼容与安全诊断增强，没有增加 ADB connect、server restart、readiness 重试、轮询或 sleep，也没有改变 external 11 阶段计划或授权 managed MuMu。

自动验收新增 45 项专项测试；ADB parser 既有文件 17 项、probes 73 项、runtime 125 项、production workflow 166 项均通过。Phase 6A 75 项、external MuMu 90 项和 Phase 6C1 86 项保持通过，完整套件连续两次均为 1177 项通过。

修复后只读 readiness 尚未复验，记录为 Phase 6C2B；修复后 external 真实完整工作流尚未执行，记录为 Phase 6C2C。新的验收运行必须基于后续新提交和新批准基线，不属于同一代码基线的自动重试。Phase 6 尚未完成。
