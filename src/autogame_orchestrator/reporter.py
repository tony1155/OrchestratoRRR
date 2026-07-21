"""RunReport atomic writer with JSON Schema validation.

Writes a ``RunReport`` to disk atomically:
1. Validate in-memory model constraints (already done by ``__post_init__``).
2. Serialize to JSON.
3. Validate JSON against the RunReport v1 schema.
4. Write to a temp file in the target directory.
5. Flush + fsync.
6. Atomically replace the final file with ``os.replace``.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import jsonschema.validators
from jsonschema import Draft7Validator, FormatChecker, ValidationError

from autogame_orchestrator.models import ErrorCode, RunReport

if TYPE_CHECKING:
    from collections.abc import Iterator

_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "schemas" / "run-report-v1.schema.json"


def _load_schema() -> dict[str, object]:
    raw = _SCHEMA_PATH.read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


def _format_validator(
    validator: Draft7Validator,
    fmt: str,
    instance: object,
    schema: object,
) -> Iterator[ValidationError]:
    if validator.format_checker is not None:
        try:
            validator.format_checker.check(instance, fmt)
        except Exception:
            yield ValidationError(f"'{instance}' is not a valid '{fmt}' format")


_AssertingFormatValidator = jsonschema.validators.extend(
    Draft7Validator,
    validators={"format": _format_validator},
)


def _is_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


_CHECKER = FormatChecker()
_CHECKER.checkers["date-time"] = (_is_datetime, ValueError)

_VALIDATOR = _AssertingFormatValidator(_load_schema(), format_checker=_CHECKER)


def validate_run_report_json(data: object) -> tuple[bool, str]:
    """Validate *data* against the RunReport v1 schema.

    Returns ``(valid, error_message)``.
    """
    errors = sorted(_VALIDATOR.iter_errors(data), key=lambda e: str(e.path))
    if errors:
        return False, "; ".join(e.message for e in errors)
    return True, ""


def write_report_atomic(
    report: RunReport, target_dir: Path, filename: str | None = None
) -> tuple[Path | None, list[ErrorCode]]:
    """Serialize *report* and write it atomically to *target_dir*.

    Args:
        report: The validated ``RunReport`` to persist.
        target_dir: Directory where the report should live.
        filename: Optional explicit file name; defaults to
            ``run-report-{run_id}.json``.

    Returns:
        ``(path, errors)``.  On success *path* points to the written file.
    """
    errors: list[ErrorCode] = []

    try:
        json_str = report.to_json()
    except Exception:
        errors.append(ErrorCode.RUN_REPORT_SERIALIZATION_ERROR)
        return None, errors

    try:
        parsed = json.loads(json_str)
    except Exception:
        errors.append(ErrorCode.RUN_REPORT_SERIALIZATION_ERROR)
        return None, errors

    valid, msg = validate_run_report_json(parsed)
    if not valid:
        errors.append(ErrorCode.RUN_REPORT_VALIDATION_ERROR)
        return None, errors

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        errors.append(ErrorCode.RUN_REPORT_WRITE_ERROR)
        return None, errors

    final_name = filename or f"run-report-{report.run_id}.json"
    final_path = target_dir / final_name

    fd = -1
    tmp_path = ""
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix=".tmp-report-", dir=str(target_dir), text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json_str)
            fh.flush()
            os.fsync(fh.fileno())
        fd = -1

        os.replace(tmp_path, str(final_path))
    except OSError:
        errors.append(ErrorCode.RUN_REPORT_WRITE_ERROR)
        _clean_tmp(tmp_path, fd)
        return None, errors
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
            _clean_tmp(tmp_path, -1)

    return final_path, []


def _clean_tmp(path: str, fd: int) -> None:
    if fd >= 0:
        try:
            os.close(fd)
        except OSError:
            pass
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass
