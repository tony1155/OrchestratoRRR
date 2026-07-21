"""TOML configuration loader with ErrorCode-based validation.

Reads a TOML file, constructs an ``AppConfig``, and runs structural validation.
By default **does not** check whether paths on disk exist; pass ``check_paths=True``
to enable that behaviour.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from autogame_orchestrator.config_model import (
    AALCConfig,
    AppConfig,
    MAAConfig,
    MuMuConfig,
    OrchestratorConfig,
    StarRailConfig,
)
from autogame_orchestrator.models import ErrorCode

if TYPE_CHECKING:
    pass


def _tolist(value: object) -> list[str] | None:
    """Convert a TOML array to a list of strings, or None on failure."""
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        result.append(item)
    return result


def _to_string_mapping(value: object) -> tuple[tuple[str, str], ...] | None:
    if not isinstance(value, dict):
        return None
    result: list[tuple[str, str]] = []
    for key, item in value.items():
        if not isinstance(key, str):
            return None
        if not isinstance(item, str):
            return None
        result.append((key, item))
    return tuple(result)


def load_config(path: Path, *, check_paths: bool = False) -> tuple[AppConfig | None, list[ErrorCode]]:
    """Load and validate the TOML configuration at *path*.

    Returns:
        ``(config, errors)`` — if *errors* is non-empty the caller SHOULD
        treat *config* as unreliable.
    """
    all_errors: list[ErrorCode] = []

    if not path.exists():
        all_errors.append(ErrorCode.CONFIG_FILE_NOT_FOUND)
        return None, all_errors

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        all_errors.append(ErrorCode.CONFIG_FILE_NOT_FOUND)
        return None, all_errors

    try:
        data = tomllib.loads(raw)
    except Exception:
        all_errors.append(ErrorCode.CONFIG_PARSE_ERROR)
        return None, all_errors

    cfg_or = _parse_orchestrator(data.get("orchestrator"))
    cfg_mu = _parse_mumu(data.get("mumu"))
    cfg_sr = _parse_starrail(data.get("starrail"))
    cfg_ma = _parse_maa(data.get("maa"))
    cfg_al = _parse_aalc(data.get("aalc"))

    all_errors.extend(cfg_or[1])
    all_errors.extend(cfg_mu[1])
    all_errors.extend(cfg_sr[1])
    all_errors.extend(cfg_ma[1])
    all_errors.extend(cfg_al[1])

    if all_errors:
        return None, all_errors

    config = AppConfig(
        orchestrator=cfg_or[0],  # type: ignore[arg-type]
        mumu=cfg_mu[0],  # type: ignore[arg-type]
        starrail=cfg_sr[0],  # type: ignore[arg-type]
        maa=cfg_ma[0],  # type: ignore[arg-type]
        aalc=cfg_al[0],  # type: ignore[arg-type]
    )

    validation_errors = config.validate()
    all_errors.extend(validation_errors)

    if check_paths:
        all_errors.extend(config.check_paths())

    if all_errors:
        return None, all_errors

    return config, []


def _parse_orchestrator(raw: object) -> tuple[OrchestratorConfig | None, list[ErrorCode]]:
    errors: list[ErrorCode] = []
    if not isinstance(raw, dict):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        return None, errors

    required_str_fields = ["log_dir", "report_dir"]
    for fld in required_str_fields:
        val = raw.get(fld)
        if not isinstance(val, str) or not val.strip():
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    heartbeat = raw.get("heartbeat_interval_seconds", 10)
    if not isinstance(heartbeat, int):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
    poll_int = raw.get("poll_interval_seconds", 1)
    if not isinstance(poll_int, int):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    if errors:
        return None, errors

    return OrchestratorConfig(
        log_dir=str(raw.get("log_dir", "logs")),
        report_dir=str(raw.get("report_dir", "run-results")),
        heartbeat_interval_seconds=int(heartbeat),
        poll_interval_seconds=int(poll_int),
    ), []


def _parse_mumu(raw: object) -> tuple[MuMuConfig | None, list[ErrorCode]]:
    errors: list[ErrorCode] = []
    if not isinstance(raw, dict):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        return None, errors

    for fld in ("executable", "adb_executable", "adb_serial"):
        val = raw.get(fld)
        if not isinstance(val, str) or not val.strip():
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    start_to = raw.get("start_timeout_seconds", 120)
    stop_to = raw.get("stop_timeout_seconds", 20)
    if not isinstance(start_to, int):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
    if not isinstance(stop_to, int):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    if errors:
        return None, errors

    return MuMuConfig(
        executable=str(raw.get("executable", "")),
        adb_executable=str(raw.get("adb_executable", "")),
        adb_serial=str(raw.get("adb_serial", "127.0.0.1:16384")),
        start_timeout_seconds=int(start_to),
        stop_timeout_seconds=int(stop_to),
    ), []


def _parse_starrail(raw: object) -> tuple[StarRailConfig | None, list[ErrorCode]]:
    errors: list[ErrorCode] = []
    if not isinstance(raw, dict):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        return None, errors

    executable = str(raw.get("executable", ""))
    working_dir = str(raw.get("working_directory", ""))
    log_path_tpl = str(raw.get("log_path_template", ""))

    if not executable.strip():
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
    if not working_dir.strip():
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
    if not log_path_tpl.strip():
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    arguments_raw = raw.get("arguments")
    arg_list = _tolist(arguments_raw)
    if arg_list is None:
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
    if arg_list is not None and not arg_list:
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    success_kw = raw.get("success_keywords")
    skw_list = _tolist(success_kw)
    if skw_list is None:
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    failure_kw = raw.get("failure_keywords")
    fkw_list = _tolist(failure_kw)
    if fkw_list is None:
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    env_val = raw.get("environment")
    env = _to_string_mapping(env_val)

    task_to = raw.get("task_timeout_seconds", 3600)
    stop_to = raw.get("stop_timeout_seconds", 10)
    if not isinstance(task_to, int):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
    if not isinstance(stop_to, int):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    if errors:
        return None, errors

    return StarRailConfig(
        executable=executable,
        working_directory=working_dir,
        arguments=tuple(arg_list) if arg_list else (),
        log_path_template=log_path_tpl,
        success_keywords=tuple(skw_list) if skw_list else (),
        failure_keywords=tuple(fkw_list) if fkw_list else (),
        environment_overrides=env if env else (),
        task_timeout_seconds=int(task_to),
        stop_timeout_seconds=int(stop_to),
    ), []


def _parse_maa(raw: object) -> tuple[MAAConfig | None, list[ErrorCode]]:
    errors: list[ErrorCode] = []
    if not isinstance(raw, dict):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        return None, errors

    for fld in ("executable", "working_directory"):
        val = raw.get(fld)
        if not isinstance(val, str) or not val.strip():
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    timeout = raw.get("timeout_seconds", 1800)
    if not isinstance(timeout, int):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    if errors:
        return None, errors

    return MAAConfig(
        executable=str(raw.get("executable", "")),
        working_directory=str(raw.get("working_directory", "")),
        timeout_seconds=int(timeout),
    ), []


def _parse_aalc(raw: object) -> tuple[AALCConfig | None, list[ErrorCode]]:
    errors: list[ErrorCode] = []
    if not isinstance(raw, dict):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)
        return None, errors

    for fld in ("executable", "working_directory"):
        val = raw.get(fld)
        if not isinstance(val, str) or not val.strip():
            errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    attempts = raw.get("attempts", 3)
    if not isinstance(attempts, int):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    att_to = raw.get("attempt_timeout_seconds", 7200)
    if not isinstance(att_to, int):
        errors.append(ErrorCode.CONFIG_SCHEMA_ERROR)

    if errors:
        return None, errors

    return AALCConfig(
        executable=str(raw.get("executable", "")),
        working_directory=str(raw.get("working_directory", "")),
        attempts=int(attempts),
        attempt_timeout_seconds=int(att_to),
    ), []
