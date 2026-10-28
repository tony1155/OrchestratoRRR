"""Invocation-only MaaPiCli configuration and bounded, read-only PI identity checks."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from autogame_orchestrator.runtime.maafgo_models import MaaFgoErrorCode as Code

MAX_CONFIG_BYTES = 1024 * 1024

# ── ORR 生产分发身份 ────────────────────────────────────────────────────────
# 与 scripts/prepare_maafgo_cli_smoke.py 的常量保持一致；
# tests/tools/test_prepare_maafgo_cli_smoke.py 防止两者漂移。
ORR_PINNED_FGO_COMMIT = "d7f3a474f50b9a0631ee9acd6df67998c1933f2b"
ORR_TRANSFORM_ID = "orr-bbc-free-native-reporter"
ORR_TRANSFORM_VERSION = 1
DISTRIBUTION_MANIFEST_FILENAME = "distribution-manifest.json"
MAX_MANIFEST_BYTES = 256 * 1024

# ── 生产 profile policy（只读，绑定 pinned revision 的 task 语义） ──────────
# 证据：docs/investigations/maafgo-bbc-free-paths.md（pinned d7f3a474）。
# 启动bbc：自定义 action start_bbc；关闭游戏：StopApp -> 关闭bbc -> stop_bbc，
# 即使本 run 从未启动 BBC 也会枚举强杀外部 BBC；直接bbc战斗 / Chaldea 一键战斗：
# BBC-required。原生自动战斗 / 直接战斗：要求人工预置到战斗页。
FORBIDDEN_TASK_NAMES = frozenset({"启动bbc", "关闭游戏", "直接bbc战斗", "Chaldea 一键战斗"})
MANUAL_PRESET_TASK_NAMES = frozenset({"原生自动战斗", "直接战斗"})
# 这些任务走共享战斗调度，options/战斗方式.json 默认 case 是 bbc；生产 profile
# 必须为它们显式选择 native。
COMBAT_TASK_NAMES = frozenset({"日常战斗", "冠位戴冠战", "迦勒底之门", "通用大活动", "通用小活动"})
REQUIRED_ENTRY_TASK_NAME = "登录"
BATTLE_MODE_OPTION_NAME = "battle_mode"
NATIVE_BATTLE_MODE = "native"
MAX_INTERFACE_IMPORT_FILES = 128


class MaaFgoConfigurationError(ValueError):
    def __init__(self, code: Code = Code.INVALID_CONFIGURATION) -> None:
        super().__init__(code.value)
        self.code = code


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MaaFgoConfigurationError()
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise MaaFgoConfigurationError()


def _read_object(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        raw = stream.read(MAX_CONFIG_BYTES + 1)
    if len(raw) > MAX_CONFIG_BYTES:
        raise MaaFgoConfigurationError()
    value: object = json.loads(
        raw.decode("utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=_reject_constant
    )
    if not isinstance(value, dict):
        raise MaaFgoConfigurationError()
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or any(ord(c) < 32 for c in value):
        raise MaaFgoConfigurationError()
    return value


def normalize_adb_endpoint(value: str) -> str:
    """Only canonical 127.0.0.1:port; no DNS, aliases or instance substitution."""
    host, separator, port = _text(value).partition(":")
    if not separator or not port.isascii() or not port.isdecimal() or len(port) > 5:
        raise MaaFgoConfigurationError()
    if host != "127.0.0.1" or not 1 <= int(port) <= 65535 or port != str(int(port)):
        raise MaaFgoConfigurationError()
    return f"{host}:{int(port)}"


@dataclass(frozen=True)
class MaaFgoAdbIdentity:
    controller_name: str
    device_name: str
    adb_path: str
    address: str


@dataclass(frozen=True)
class MaaFgoProfileTask:
    """Profile 侧的任务选择：名字、解析出的 PI entry、显式 battle_mode。"""

    name: str
    entry: str
    battle_mode: str | None


def read_profile_tasks(profile_path: Path) -> list[tuple[str, list[dict[str, object]]]]:
    """严格读取 profile 的 task 选择（名字 + 原始 option 列表），不改写文件。"""
    profile = _read_object(profile_path)
    tasks = profile.get("task")
    if not isinstance(tasks, list) or not tasks:
        raise MaaFgoConfigurationError()
    selection: list[tuple[str, list[dict[str, object]]]] = []
    for task in tasks:
        if not isinstance(task, dict):
            raise MaaFgoConfigurationError()
        name = _text(task.get("name"))
        raw_options = task.get("option", [])
        if raw_options is None:
            raw_options = []
        if not isinstance(raw_options, list):
            raise MaaFgoConfigurationError()
        options: list[dict[str, object]] = []
        for option in raw_options:
            if not isinstance(option, dict):
                raise MaaFgoConfigurationError()
            _text(option.get("name"))
            options.append(option)
        selection.append((name, options))
    return selection


def read_interface_task_entries(interface_path: Path) -> dict[str, str]:
    """沿 PI import 链收集 ``task name -> entry``（entry 缺省为任务名）。

    只提取名字映射，不复刻 PI 的 option/override 语义。import 必须相对
    interface 根且不越界，文件数与大小有界，冲突定义 fail closed。
    """
    mapping: dict[str, str] = {}
    try:
        interface_root = interface_path.parent.resolve()
    except OSError:
        raise MaaFgoConfigurationError() from None
    pending = [interface_path]
    seen: set[Path] = set()
    while pending:
        if len(seen) >= MAX_INTERFACE_IMPORT_FILES:
            raise MaaFgoConfigurationError()
        path = pending.pop(0)
        try:
            resolved = path.resolve()
        except OSError:
            raise MaaFgoConfigurationError() from None
        if resolved in seen:
            continue
        seen.add(resolved)
        document = _read_object(path)
        tasks = document.get("task")
        if isinstance(tasks, list):
            for task in tasks:
                if not isinstance(task, dict):
                    raise MaaFgoConfigurationError()
                name = _text(task.get("name"))
                raw_entry = task.get("entry")
                entry = _text(raw_entry) if raw_entry is not None else name
                if name in mapping and mapping[name] != entry:
                    raise MaaFgoConfigurationError()
                mapping[name] = entry
        imports = document.get("import")
        if isinstance(imports, list):
            for imported in imports:
                imported_file = _text(imported)
                if (
                    "\\" in imported_file
                    or ":" in imported_file
                    or imported_file.startswith("/")
                    or ".." in imported_file
                ):
                    raise MaaFgoConfigurationError()
                candidate = interface_path.parent / imported_file
                try:
                    if not candidate.resolve().is_relative_to(interface_root):
                        raise MaaFgoConfigurationError()
                except OSError:
                    raise MaaFgoConfigurationError() from None
                if candidate.is_file():
                    pending.append(candidate)
    return mapping


def read_expected_task_pairs(interface_path: Path, profile_path: Path) -> tuple[tuple[str, str], ...]:
    """把 profile 任务名解析为 (name, entry) 对，供完成证据契约绑定通知。"""
    try:
        entries = read_interface_task_entries(interface_path)
        selection = read_profile_tasks(profile_path)
    except MaaFgoConfigurationError:
        raise
    pairs: list[tuple[str, str]] = []
    for name, _options in selection:
        pairs.append((name, entries.get(name, name)))
    return tuple(pairs)


def read_adb_identity(profile_path: Path) -> MaaFgoAdbIdentity:
    """Parse the upstream Configuration envelope, not FGO task/option semantics."""
    try:
        profile = _read_object(profile_path)
        controller, adb = profile.get("controller"), profile.get("adb")
        if not isinstance(controller, dict) or not isinstance(adb, dict):
            raise MaaFgoConfigurationError()
        _text(profile.get("resource"))
        tasks = profile.get("task")
        if not isinstance(tasks, list) or not tasks:
            raise MaaFgoConfigurationError()
        for task in tasks:
            if not isinstance(task, dict):
                raise MaaFgoConfigurationError()
            _text(task.get("name"))
        return MaaFgoAdbIdentity(
            _text(controller.get("name")),
            _text(adb.get("name")),
            _text(adb.get("adb_path")),
            normalize_adb_endpoint(_text(adb.get("address"))),
        )
    except (OSError, ValueError, RecursionError):
        raise MaaFgoConfigurationError() from None


@dataclass(frozen=True)
class MaaFgoConfig:
    enabled: bool = False
    executable: str = ""
    working_directory: str = ""
    timeout_seconds: int = 10800
    stop_timeout_seconds: int = 20

    @property
    def arguments(self) -> tuple[str, ...]:
        return ("-d",)

    @property
    def interface_path(self) -> Path:
        return Path(self.working_directory) / "interface.json"

    @property
    def profile_path(self) -> Path:
        return Path(self.working_directory) / "config" / "maa_pi_config.json"

    def validate(self) -> list[Code]:
        if (
            type(self.enabled) is not bool
            or any(type(v) is not int or v <= 0 for v in (self.timeout_seconds, self.stop_timeout_seconds))
            or not all(isinstance(v, str) for v in (self.executable, self.working_directory))
        ):
            return [Code.INVALID_CONFIGURATION]
        if not self.enabled:
            return []
        if sys.platform != "win32":
            return [Code.UNSUPPORTED_PLATFORM]
        try:
            executable = Path(_text(self.executable))
            directory = Path(_text(self.working_directory))
            if (
                not executable.is_absolute()
                or not directory.is_absolute()
                or executable.name.casefold() != "maapicli.exe"
                or executable.parent.resolve() != directory.resolve()
                or executable.resolve().parent != directory.resolve()
            ):
                return [Code.INVALID_CONFIGURATION]
        except (OSError, ValueError, RuntimeError):
            return [Code.INVALID_CONFIGURATION]
        return []

    def check_paths(self) -> list[Code]:
        errors = self.validate()
        if errors or not self.enabled:
            return errors
        try:
            for path, predicate, code in (
                (Path(self.working_directory), Path.is_dir, Code.WORKING_DIRECTORY_NOT_FOUND),
                (Path(self.executable), Path.is_file, Code.EXECUTABLE_NOT_FOUND),
                (self.interface_path, Path.is_file, Code.PROJECT_INTERFACE_NOT_FOUND),
                (self.profile_path, Path.is_file, Code.PROFILE_NOT_FOUND),
            ):
                if not predicate(path):
                    return [code]
        except OSError:
            return [Code.INVALID_CONFIGURATION]
        return []

    def check_profile(self, expected_adb_serial: str) -> None:
        """Fail closed before invocation; never save, normalize or repair user files."""
        errors = self.check_paths()
        if errors or not self.enabled:
            raise MaaFgoConfigurationError(errors[0] if errors else Code.INVALID_CONFIGURATION)
        try:
            interface = _read_object(self.interface_path)
            if type(interface.get("interface_version")) is not int or interface.get("interface_version") != 2:
                raise MaaFgoConfigurationError()
            if interface.get("name") != "MaaFgo":
                raise MaaFgoConfigurationError()
            identity = read_adb_identity(self.profile_path)
            controllers = interface.get("controller")
            if not isinstance(controllers, list) or any(not isinstance(c, dict) for c in controllers):
                raise MaaFgoConfigurationError()
            selected = [c for c in controllers if c.get("name") == identity.controller_name]
            if len(selected) != 1 or selected[0].get("type") != "Adb":
                raise MaaFgoConfigurationError()
            # ShellExecute(runas) may escape the owned Job. Do not permit that path.
            if selected[0].get("permission_required", False) is not False:
                raise MaaFgoConfigurationError()
            if identity.address != normalize_adb_endpoint(expected_adb_serial):
                raise MaaFgoConfigurationError(Code.ADB_CONFIGURATION_MISMATCH)
            adb_path = Path(identity.adb_path)
            if not adb_path.is_absolute() or not adb_path.is_file() or adb_path.name.casefold() != "adb.exe":
                raise MaaFgoConfigurationError()
            # Upstream manual-input naming; detected names allow reconfig_adb to select another address.
            if identity.device_name != f"{identity.address}-{identity.adb_path}":
                raise MaaFgoConfigurationError(Code.ADB_AUTODETECT_UNSUPPORTED)
        except MaaFgoConfigurationError:
            raise
        except (OSError, ValueError, RecursionError):
            raise MaaFgoConfigurationError() from None

    def read_expected_task_pairs(self) -> tuple[tuple[str, str], ...]:
        """把当前 profile 的任务选择解析为完成证据契约所需的 (name, entry) 对。"""
        try:
            return read_expected_task_pairs(self.interface_path, self.profile_path)
        except MaaFgoConfigurationError:
            raise
        except (OSError, ValueError, RecursionError):
            raise MaaFgoConfigurationError() from None

    def check_profile_policy(self) -> None:
        """只读生产 profile policy（绑定 pinned revision 的任务语义）。

        保证这是一次完整 FGO 流程（从游戏未运行状态开始），而不是单独战斗：
        必须以 ``登录`` 开头；拒绝 BBC-only / BBC-launch / 关闭游戏；战斗任务
        必须显式 native；游戏关闭职责交给 OrchestratoRRR（拒绝 MaaFgo 的
        ``关闭游戏``）。绝不改写用户 profile。
        """
        try:
            pairs = self.read_expected_task_pairs()
            selection = read_profile_tasks(self.profile_path)
        except MaaFgoConfigurationError:
            raise
        except (OSError, ValueError, RecursionError):
            raise MaaFgoConfigurationError(Code.PROFILE_POLICY_REJECTED) from None
        battle_modes = {name: _option_value(options, BATTLE_MODE_OPTION_NAME) for name, options in selection}
        names = [name for name, _ in pairs]
        if not names or names[0] != REQUIRED_ENTRY_TASK_NAME:
            raise MaaFgoConfigurationError(Code.PROFILE_POLICY_REJECTED)
        if len(set(names)) != len(names) or any(name in FORBIDDEN_TASK_NAMES for name in names):
            raise MaaFgoConfigurationError(Code.PROFILE_POLICY_REJECTED)
        business = names[1:]
        if not business or all(name in MANUAL_PRESET_TASK_NAMES for name in business):
            raise MaaFgoConfigurationError(Code.PROFILE_POLICY_REJECTED)
        for name in business:
            if name in COMBAT_TASK_NAMES and battle_modes.get(name) != NATIVE_BATTLE_MODE:
                raise MaaFgoConfigurationError(Code.PROFILE_POLICY_REJECTED)

    def check_distribution(self) -> None:
        """生产 FGO 运行只允许 ORR 私有装配的 BBC-free 分发。

        ``distribution-manifest.json`` 必须证明：pinned MaaFgo revision、
        ORR transform 已应用（BBC stop listener 不再注册、reporter 已注册）。
        指向未验证安装一律 fail closed（DISTRIBUTION_UNVERIFIED）。
        """
        manifest_path = Path(self.working_directory) / DISTRIBUTION_MANIFEST_FILENAME
        try:
            raw = manifest_path.read_bytes()
        except OSError:
            raise MaaFgoConfigurationError(Code.DISTRIBUTION_UNVERIFIED) from None
        if len(raw) > MAX_MANIFEST_BYTES:
            raise MaaFgoConfigurationError(Code.DISTRIBUTION_UNVERIFIED)
        try:
            manifest = _read_object(manifest_path)
        except (MaaFgoConfigurationError, OSError, ValueError, RecursionError):
            raise MaaFgoConfigurationError(Code.DISTRIBUTION_UNVERIFIED) from None
        transform = manifest.get("orr_transform")
        if (
            manifest.get("schema_version") != 1
            or manifest.get("maafgo_commit") != ORR_PINNED_FGO_COMMIT
            or not isinstance(transform, dict)
            or transform.get("transform_id") != ORR_TRANSFORM_ID
            or transform.get("transform_version") != ORR_TRANSFORM_VERSION
            or transform.get("bbc_listener_registered") is not False
            or transform.get("reporter_registered") is not True
        ):
            raise MaaFgoConfigurationError(Code.DISTRIBUTION_UNVERIFIED)


def _option_value(options: list[dict[str, object]], name: str) -> str | None:
    for option in options:
        if option.get("name") == name:
            value = option.get("value")
            if isinstance(value, str) and value:
                return value
            return None
    return None
