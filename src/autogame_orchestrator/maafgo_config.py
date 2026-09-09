"""Invocation-only MaaPiCli configuration and bounded, read-only PI identity checks."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from autogame_orchestrator.runtime.maafgo_models import MaaFgoErrorCode as Code

MAX_CONFIG_BYTES = 1024 * 1024


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
