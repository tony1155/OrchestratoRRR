# 阶段 2A 验收标准

> **状态:** 待用户验收。请勿自行勾选。

## 功能完整性

- [ ] 本地 TCP 端口探测（127.0.0.0/8、::1、localhost）
- [ ] 外部 IP/域名被拒绝
- [ ] ADB 命令通过 ProcessSupervisor 执行
- [ ] 每条 ADB 命令使用临时输出文件，自动清理
- [ ] stdout ≤ 1 MiB，stderr 摘要 ≤ 1024 字符
- [ ] 取消通过 CancellationToken 传播到所有 ADB 方法
- [ ] ADB devices 输出解析（含 -l 属性）
- [ ] 设备选择规则：精确 serial、唯一设备、多设备拒绝
- [ ] MuMu readiness 组合探测：TCP → devices → select → state → boot
- [ ] 所有探测共享 Deadline，子操作不重置总超时
- [ ] Fake ADB 覆盖 12+ 种场景

## 自动检查

- [ ] `ruff check .` 零错误
- [ ] `ruff format --check .` 通过
- [ ] `mypy src` 零错误
- [ ] `pytest -q` 全部通过
- [ ] `pytest tests/probes` 全部通过

## 安全边界

- [ ] 未启动/停止 MuMu
- [ ] 未执行 ADB modify 命令（connect/install/uninstall/reboot）
- [ ] 未使用 subprocess.run/Popen/os.system/shell=True/PIPE
- [ ] 未使用 WMI/CIM/taskkill/psutil
- [ ] 未访问互联网
- [ ] 未修改阶段 0 Schema 或 golden sample
- [ ] 未修改 ProcessSupervisor 核心设计
- [ ] 未执行 Git commit

## 审查人签署

- [ ] 阶段 2A 实施已审查: _________________
- [ ] 日期: _________________
- [ ] 决定: [ ] 接受  [ ] 附注接受  [ ] 拒绝
