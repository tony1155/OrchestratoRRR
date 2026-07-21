"""ADB devices 输出解析器。

纯函数，无 I/O。解析 ``adb devices -l`` 的输出。
"""

from __future__ import annotations

from autogame_orchestrator.probes.models import AdbDevice, AdbDeviceState, ProbeErrorCode


class AdbParseError(ValueError):
    """ADB 输出解析错误，携带 ProbeErrorCode。"""

    def __init__(self, message: str, error_code: ProbeErrorCode) -> None:
        super().__init__(message)
        self.error_code = error_code


def _parse_state(raw: str) -> AdbDeviceState:
    raw = raw.strip()
    if raw == "device":
        return AdbDeviceState.DEVICE
    if raw == "offline":
        return AdbDeviceState.OFFLINE
    if raw == "unauthorized":
        return AdbDeviceState.UNAUTHORIZED
    return AdbDeviceState.UNKNOWN


def _parse_attributes(tokens: list[str]) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for token in tokens:
        if ":" in token:
            key, _, value = token.partition(":")
            attrs[key.strip()] = value.strip()
    return attrs


def parse_adb_devices(output: str) -> tuple[AdbDevice, ...]:
    """解析 ``adb devices -l`` 输出。

    Raises:
        AdbParseError: 格式错误或重复 serial 时。
    """
    lines = output.replace("\r\n", "\n").split("\n")

    # 验证标题行
    if not lines or not lines[0].strip().startswith("List of devices"):
        msg = "ADB devices 输出缺少标题行"
        raise AdbParseError(msg, ProbeErrorCode.ADB_OUTPUT_INVALID)

    devices: list[AdbDevice] = []
    seen_serials: set[str] = set()

    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue

        # 格式：{serial}\t{state} [key:val ...]
        parts = stripped.split("\t")
        if len(parts) < 2:
            msg = f"无法解析的设备行: {stripped!r}"
            raise AdbParseError(msg, ProbeErrorCode.ADB_OUTPUT_INVALID)

        serial = parts[0].strip()
        if not serial:
            msg = f"设备行缺少 serial: {stripped!r}"
            raise AdbParseError(msg, ProbeErrorCode.ADB_OUTPUT_INVALID)

        # 第二个 tab 字段可能包含 state + 空格分隔的属性
        tail_parts = parts[1].split()
        if not tail_parts:
            msg = f"设备行缺少 state: {stripped!r}"
            raise AdbParseError(msg, ProbeErrorCode.ADB_OUTPUT_INVALID)

        state = _parse_state(tail_parts[0])

        # 检查重复 serial
        if serial in seen_serials:
            msg = f"重复的 serial: {serial}"
            raise AdbParseError(msg, ProbeErrorCode.ADB_OUTPUT_INVALID)
        seen_serials.add(serial)

        # 解析属性（剩余 tab 字段 + 第二个 tab 字段中的空格分词）
        attr_tokens = tail_parts[1:] + list(parts[2:])
        attrs = _parse_attributes(attr_tokens)

        devices.append(AdbDevice(serial=serial, state=state, attributes=attrs))

    return tuple(devices)


def select_adb_device(
    devices: tuple[AdbDevice, ...],
    expected_serial: str | None,
) -> AdbDevice:
    """从设备列表中选择目标设备。

    Raises:
        AdbParseError: 无匹配设备、多设备、offline 或 unauthorized 时。
    """
    if expected_serial is not None:
        for d in devices:
            if d.serial == expected_serial:
                _check_device_state(d)
                return d
        msg = f"未找到设备: {expected_serial}"
        raise AdbParseError(msg, ProbeErrorCode.DEVICE_NOT_FOUND)

    if len(devices) == 0:
        msg = "未找到任何 ADB 设备"
        raise AdbParseError(msg, ProbeErrorCode.DEVICE_NOT_FOUND)

    if len(devices) > 1:
        msg = f"发现 {len(devices)} 个设备，但未指定 serial"
        raise AdbParseError(msg, ProbeErrorCode.MULTIPLE_DEVICES)

    device = devices[0]
    _check_device_state(device)
    return device


def _check_device_state(device: AdbDevice) -> None:
    if device.state == AdbDeviceState.OFFLINE:
        msg = f"设备不在线: {device.serial}"
        raise AdbParseError(msg, ProbeErrorCode.DEVICE_OFFLINE)
    if device.state == AdbDeviceState.UNAUTHORIZED:
        msg = f"设备未授权: {device.serial}"
        raise AdbParseError(msg, ProbeErrorCode.DEVICE_UNAUTHORIZED)
