"""Run-scoped MaaFgo task completion evidence: contract creation and strict verification.

OrchestratoRRR creates a fresh private run directory per invocation and passes
a run identity, a plan digest and the expected task list to the child via the
environment (see ``MaaFgoRunContract``). The ORR private MaaFgo distribution's
reporter (``scripts/maafgo-orr-agent/orr_reporter.py``) observes task
notifications through the official MaaFramework AgentServer ``tasker_sink()``
API and writes the artifact atomically to the ORR-provided path.

This module owns the artifact schema and rejects everything else: stale run
ids, digest drift, missing/duplicate/unknown tasks, non-terminal tasks and any
process-level anomaly. Process exit code alone is never business success.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from autogame_orchestrator.runtime.maafgo_models import MaaFgoErrorCode as Code

ARTIFACT_SCHEMA_VERSION = 1
MAX_ARTIFACT_BYTES = 64 * 1024
MAX_EXPECTED_TASKS = 32
MAX_TASK_NAME_CHARS = 200
MAX_UNEXPECTED_ENTRIES = 16

ENV_RUN_ID = "ORR_MAAFGO_RUN_ID"
ENV_PLAN_DIGEST = "ORR_MAAFGO_PLAN_DIGEST"
ENV_RESULT_PATH = "ORR_MAAFGO_RESULT_PATH"
ENV_EXPECTED_TASKS_PATH = "ORR_MAAFGO_EXPECTED_TASKS_PATH"
ENV_SCHEMA_VERSION = "ORR_MAAFGO_RESULT_SCHEMA_VERSION"

RESULT_FILENAME = "maafgo-result.json"
EXPECTED_TASKS_FILENAME = "expected-tasks.json"

_TERMINAL_STATES = ("pending", "success", "failed")
_OUTCOMES = ("success", "failed", "incomplete")

# PI v2 posts each profile task by its interface ``entry``（登录 -> 登录识别），
# 而身份校验、policy 与报告都以 profile 任务名为准，因此期望任务同时绑定两者。
ExpectedTask = tuple[str, str]


class MaaFgoEvidenceError(ValueError):
    def __init__(self, code: Code = Code.RESULT_INVALID) -> None:
        super().__init__(code.value)
        self.code = code


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MaaFgoEvidenceError()
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise MaaFgoEvidenceError()


def _clean_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_TASK_NAME_CHARS
        or value != value.strip()
        or any(ord(c) < 32 for c in value)
    ):
        raise MaaFgoEvidenceError()
    return value


def validate_expected_tasks(tasks: Sequence[ExpectedTask]) -> tuple[ExpectedTask, ...]:
    pairs = tuple((_clean_name(name), _clean_name(entry)) for name, entry in tasks)
    if not 1 <= len(pairs) <= MAX_EXPECTED_TASKS or len(set(pairs)) != len(pairs):
        raise MaaFgoEvidenceError()
    if len({name for name, _ in pairs}) != len(pairs):
        raise MaaFgoEvidenceError()
    return pairs


@dataclass(frozen=True)
class MaaFgoRunContract:
    """Caller-owned run identity passed to the MaaFgo child via the environment.

    ``run_id`` is a fresh unpredictable UUID4 per invocation; the run directory
    is freshly created and never reused, so stale artifacts from earlier runs
    cannot be mistaken for this run's evidence.
    """

    run_id: str
    plan_digest: str
    run_directory: Path
    expected_tasks: tuple[ExpectedTask, ...]
    result_path: Path
    expected_tasks_path: Path

    @classmethod
    def create(cls, parent: Path, expected_tasks: Sequence[ExpectedTask]) -> MaaFgoRunContract:
        pairs = validate_expected_tasks(expected_tasks)
        run_id = str(uuid.uuid4())
        run_directory = parent / run_id
        run_directory.mkdir(parents=True, exist_ok=False)
        payload = (
            json.dumps(
                [{"name": name, "entry": entry} for name, entry in pairs], ensure_ascii=False, indent=2
            )
            + "\n"
        ).encode("utf-8")
        expected_tasks_path = run_directory / EXPECTED_TASKS_FILENAME
        _atomic_write(expected_tasks_path, payload)
        return cls(
            run_id=run_id,
            plan_digest=hashlib.sha256(payload).hexdigest(),
            run_directory=run_directory,
            expected_tasks=pairs,
            result_path=run_directory / RESULT_FILENAME,
            expected_tasks_path=expected_tasks_path,
        )

    def environment_overrides(self) -> dict[str, str]:
        return {
            ENV_RUN_ID: self.run_id,
            ENV_PLAN_DIGEST: self.plan_digest,
            ENV_RESULT_PATH: str(self.result_path),
            ENV_EXPECTED_TASKS_PATH: str(self.expected_tasks_path),
            ENV_SCHEMA_VERSION: str(ARTIFACT_SCHEMA_VERSION),
        }


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + f".tmp-{uuid.uuid4().hex[:8]}")
    try:
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def read_completion_artifact(path: Path) -> dict[str, object]:
    """Read and strictly parse the artifact; every failure is a stable code."""
    try:
        raw = path.read_bytes()
    except OSError:
        raise MaaFgoEvidenceError(Code.RESULT_MISSING) from None
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise MaaFgoEvidenceError()
    try:
        value: object = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise MaaFgoEvidenceError() from None
    if not isinstance(value, dict):
        raise MaaFgoEvidenceError()
    return value


def verify_completion_artifact(
    artifact: dict[str, object],
    *,
    run_id: str,
    plan_digest: str,
    expected_tasks: tuple[ExpectedTask, ...],
) -> int:
    """Validate identity, task set and terminal states; return confirmed count.

    Raises ``MaaFgoEvidenceError`` with a stable code on any mismatch. A later
    success can never resurrect an earlier failure: overall success requires
    every expected task to reach terminal ``success`` in this artifact.
    """
    if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise MaaFgoEvidenceError()
    if artifact.get("run_id") != run_id or artifact.get("plan_digest") != plan_digest:
        raise MaaFgoEvidenceError(Code.RESULT_ID_MISMATCH)
    outcome = artifact.get("outcome")
    if outcome not in _OUTCOMES:
        raise MaaFgoEvidenceError()
    tasks = artifact.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != len(expected_tasks):
        raise MaaFgoEvidenceError()
    terminals: list[str] = []
    for task, (expected_name, expected_entry) in zip(tasks, expected_tasks, strict=True):
        if not isinstance(task, dict) or set(task) != {"name", "entry", "terminal"}:
            raise MaaFgoEvidenceError()
        if task["name"] != expected_name or task["entry"] != expected_entry:
            raise MaaFgoEvidenceError()
        terminal = task["terminal"]
        if terminal not in _TERMINAL_STATES:
            raise MaaFgoEvidenceError()
        terminals.append(terminal)
    unexpected = artifact.get("unexpected_entries")
    if not isinstance(unexpected, list) or any(not isinstance(entry, str) for entry in unexpected):
        raise MaaFgoEvidenceError()
    if unexpected:
        # Any entry outside the expected task set means the run did not match
        # the prepared plan; fail closed instead of guessing.
        raise MaaFgoEvidenceError()
    stop_signal = artifact.get("stop_signal_observed")
    if type(stop_signal) is not bool:
        raise MaaFgoEvidenceError()
    failed = terminals.count("failed")
    pending = terminals.count("pending")
    confirmed = terminals.count("success")
    if failed and outcome != "failed":
        raise MaaFgoEvidenceError()
    if pending and failed == 0 and outcome != "incomplete":
        raise MaaFgoEvidenceError()
    if not failed and not pending and outcome != "success":
        raise MaaFgoEvidenceError()
    if failed:
        raise MaaFgoEvidenceError(Code.TASK_FAILED)
    if pending:
        raise MaaFgoEvidenceError(Code.COMPLETION_UNCONFIRMED)
    return confirmed
