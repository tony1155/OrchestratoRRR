"""Invocation-only configuration; BetterGI owns its task JSON."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from autogame_orchestrator.models import ErrorCode


@dataclass(frozen=True)
class BetterGIConfig:
    enabled: bool = False
    executable: str = ""
    working_directory: str = ""
    mode: str = "one_dragon"
    config_name: str = "Orchestrator-Daily"
    timeout_seconds: int = 7200
    stop_timeout_seconds: int = 15

    @property
    def arguments(self) -> tuple[str, ...]:
        return ("startOneDragon", self.config_name)

    def validate(self) -> list[ErrorCode]:
        valid = isinstance(self.enabled, bool) and all(
            isinstance(value, int) and not isinstance(value, bool) and value > 0
            for value in (self.timeout_seconds, self.stop_timeout_seconds)
        )
        valid = valid and all(
            isinstance(value, str) for value in (self.executable, self.working_directory, self.mode, self.config_name)
        )
        if not valid:
            return [ErrorCode.CONFIG_SCHEMA_ERROR]
        if not self.enabled:
            return []
        if (
            self.mode != "one_dragon"
            or not self.config_name.strip()
            or self.config_name != self.config_name.strip()
            or len(self.config_name) > 100
            or any(c in '<>:"/\\|?*' or ord(c) < 32 for c in self.config_name)
            or self.config_name.endswith(".")
            or not Path(self.executable).is_absolute()
            or not Path(self.working_directory).is_absolute()
            or Path(self.executable).name.casefold() != "bettergi.exe"
            or any(ord(c) < 32 for c in self.executable + self.working_directory)
            or os.path.normcase(os.path.abspath(Path(self.executable).parent))
            != os.path.normcase(os.path.abspath(self.working_directory))
        ):
            return [ErrorCode.CONFIG_SCHEMA_ERROR]
        return []

    def check_paths(self) -> list[ErrorCode]:
        if not self.enabled:
            return []
        if self.validate():
            return [ErrorCode.CONFIG_SCHEMA_ERROR]
        if not Path(self.executable).is_file():
            return [ErrorCode.CONFIG_PATH_NOT_FOUND]
        try:
            self.check_profile()
        except (OSError, ValueError):
            return [ErrorCode.CONFIG_SCHEMA_ERROR]
        return []

    def check_profile(self) -> None:
        """Reject fallback selection, empty runs, resume markers and shutdown actions."""
        path = Path(self.working_directory) / "User" / "OneDragon" / f"{self.config_name}.json"
        with path.open("rb") as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError("Profile too large")
        profile = json.loads(data.decode("utf-8-sig"))
        if not isinstance(profile, dict) or profile.get("Name") != self.config_name:
            raise ValueError("Profile name mismatch")
        if profile.get("CompletionAction") != "关闭软件":
            raise ValueError("Completion action must be 关闭软件")
        tasks = profile.get("TaskEnabledList")
        if not isinstance(tasks, dict) or not tasks or not all(type(v) is bool for v in tasks.values()):
            raise ValueError("Invalid task selection")
        if not any(tasks.values()) or profile.get("NextTaskId"):
            raise ValueError("An enabled task and a full run are required")
