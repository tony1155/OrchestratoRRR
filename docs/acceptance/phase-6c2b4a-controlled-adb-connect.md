# Phase 6C2B4A——受控 external 本地 TCP ADB 自动连接

## 范围

Phase 6C2B3 只证明操作者手工执行一次目标 ADB connect 后，生产 readiness 可以正确选择配置
serial，并完成 get-state 与 sys.boot_completed 复验。它没有证明自动连接恢复。

Phase 6C2B4A 增加显式的 external ensure 路径。普通 MumuAdapter.status() 和
MumuReadinessProbe.probe() 仍然是只读操作；只有 external 工作流的
ENSURE_MUMU_RUNNING 阶段才调用显式 ensure。

## 受控连接契约

ensure 最多执行一次初始完整只读 readiness、一次本地 TCP adb connect 和一次完整只读
readiness 复验。三者共享同一个 Deadline 和 CancellationToken，不循环、不轮询、不
sleep、不自动重试，也不重置截止时间。

ADB server 是 adb 客户端使用的默认服务入口；MuMu Android ADB endpoint 是被连接的目标。
OrchestratoRRR 不独占 MuMu endpoint，也不拥有 ADB server 生命周期：不会显式调用
adb start-server、adb kill-server 或 adb disconnect。普通 ADB 客户端命令仍可能按 ADB
自身行为使用或拉起默认 server。

只有以下条件同时成立时才允许连接：

- 初始失败稳定分类为设备选择阶段的 DEVICE_NOT_FOUND；
- TCP probe 已通过；
- expected serial 严格等于配置 host/port 构造的目标；
- host 严格为 127.0.0.1，port 在 1..65535；
- Deadline 未耗尽且 CancellationToken 未取消。

精确目标已经 ready、offline 或 unauthorized，TCP 端口关闭或超时，serial 不一致，以及
emulator/localhost/其他 host 均不会触发 connect。实现不扫描端口、不选择第一个设备、
不根据 emulator transport 推断目标。

ensure 内部最多两次 readiness（初始探测和 connect 后复验）。完整 external workflow
在 ensure 成功后仍会进入 WAIT_MUMU_ADB_READY，并额外执行一次独立的只读 readiness；
因此完整 workflow 在发生 connect 时最多可能有三次 readiness 调用，WAIT 阶段不会 connect。

连接输出只在内存中分类为固定成功/失败状态；StageReport、RunReport 和 JSONL 只允许固定
布尔值或枚举字段，不保存 serial、host、port、stdout、stderr、命令或路径。

## 验收状态

本轮只使用 Fake 程序、monkeypatch、内存 Fake 和自动测试；生产 AdbClient 的
ProcessSupervisor 接线通过 Fake 程序验证。覆盖了 AdbClient 连接结果、输入校验、取消/
超时、ensure 操作次数、精确设备选择、多 transport、生产 external dispatch、managed
回归和安全投影。

本轮尚未进行真实冷连接自动恢复验收，也没有执行真实 ADB、MuMu、StarRail、MAA、AALC、
UAC 或完整 external workflow。Phase 6C2C 仍未获准，Phase 6 尚未完成。
