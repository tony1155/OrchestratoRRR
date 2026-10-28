"""Windows MaaPiCli invocation with run-scoped completion evidence.

Without a contract (phase-one standalone use), exit 0 maps to
COMPLETION_UNCONFIRMED. With a ``MaaFgoRunContract``, the ORR private
distribution's reporter writes the run-scoped artifact; only its strict
verification can produce SUCCESS. Timeout/cancellation always dominate any
late artifact.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from autogame_orchestrator.maafgo_config import MaaFgoConfig, MaaFgoConfigurationError
from autogame_orchestrator.maafgo_evidence import (
    MaaFgoEvidenceError,
    MaaFgoRunContract,
    read_completion_artifact,
    verify_completion_artifact,
)
from autogame_orchestrator.process import CancellationToken, Deadline, ProcessSpec, ProcessSupervisor
from autogame_orchestrator.process.errors import TerminationReason
from autogame_orchestrator.runtime.maafgo_models import MaaFgoErrorCode as Code
from autogame_orchestrator.runtime.maafgo_models import MaaFgoRunResult
from autogame_orchestrator.runtime.maafgo_models import MaaFgoRunStatus as Status


class MaaFgoAdapter:
    def __init__(
        self,
        config: MaaFgoConfig,
        *,
        expected_adb_serial: str,
        supervisor_factory: Callable[[], ProcessSupervisor] | None = None,
        contract: MaaFgoRunContract | None = None,
    ) -> None:
        self.config = config
        self.expected_adb_serial = expected_adb_serial
        self.supervisor_factory = supervisor_factory
        self.contract = contract

    def run(self, deadline: Deadline | None = None, cancel: CancellationToken | None = None) -> MaaFgoRunResult:
        started, mono = datetime.now(UTC), time.monotonic()
        status, code = Status.FAILED, Code.INTERNAL_ERROR
        reason: TerminationReason | None = None
        exit_code: int | None = None
        cleaned, confirmed = True, False
        expected_count, confirmed_count = 0, 0

        def result() -> MaaFgoRunResult:
            return MaaFgoRunResult(
                status,
                code,
                started,
                datetime.now(UTC),
                max(0, int((time.monotonic() - mono) * 1000)),
                exit_code,
                reason,
                cleaned,
                confirmed,
                status is Status.SUCCESS,
                expected_count,
                confirmed_count,
            )

        def control_requested(effective: Deadline | None) -> bool:
            nonlocal status, code, reason
            if cancel is not None and cancel.is_cancelled:
                status, code, reason = Status.CANCELLED, Code.CANCELLED, TerminationReason.CANCELLED
                return True
            if effective is not None and effective.expired:
                status, code, reason = Status.TIMEOUT, Code.TASK_TIMEOUT, TerminationReason.TIMEOUT
                return True
            return False

        if control_requested(deadline):
            return result()
        errors = self.config.validate()
        if errors or not self.config.enabled:
            code = errors[0] if errors else Code.INVALID_CONFIGURATION
            return result()
        effective = Deadline.after(
            min(float(self.config.timeout_seconds), deadline.remaining_seconds if deadline else float("inf"))
        )
        try:
            self.config.check_profile(self.expected_adb_serial)
        except MaaFgoConfigurationError as exc:
            code = exc.code
            return result()
        confirmed = True
        if self.contract is not None:
            expected_count = len(self.contract.expected_tasks)
        if control_requested(effective):
            return result()
        supervisor: ProcessSupervisor | None = None
        try:
            supervisor = (
                self.supervisor_factory()
                if self.supervisor_factory
                else ProcessSupervisor(kill_confirmation_seconds=float(self.config.stop_timeout_seconds))
            )
            if not control_requested(effective):
                process_result = supervisor.run(
                    ProcessSpec(
                        name="maafgo",
                        executable=Path(self.config.executable),
                        arguments=self.config.arguments,
                        working_directory=Path(self.config.working_directory),
                        environment_overrides=(
                            self.contract.environment_overrides() if self.contract is not None else {}
                        ),
                        # DEVNULL: retain zero raw bytes; no unbounded disk capture or path leakage.
                        stdout_path=None,
                        stderr_path=None,
                        descendants_survive_close=False,
                    ),
                    effective,
                    cancel,
                )
                reason, exit_code = process_result.termination_reason, process_result.exit_code
                status, code, cleaned = {
                    TerminationReason.NORMAL_EXIT: (Status.FAILED, Code.COMPLETION_UNCONFIRMED, True),
                    TerminationReason.NONZERO_EXIT: (Status.FAILED, Code.PROCESS_EXIT_NONZERO, True),
                    TerminationReason.START_FAILED: (Status.FAILED, Code.PROCESS_START_FAILED, True),
                    TerminationReason.TIMEOUT: (Status.TIMEOUT, Code.TASK_TIMEOUT, True),
                    TerminationReason.CANCELLED: (Status.CANCELLED, Code.CANCELLED, True),
                    TerminationReason.WAIT_FAILED: (Status.FAILED, Code.WAIT_FAILED, False),
                    TerminationReason.TERMINATION_FAILED: (Status.FAILED, Code.CLEANUP_FAILED, False),
                    TerminationReason.STOPPED: (Status.FAILED, Code.INTERNAL_ERROR, False),
                }[reason]
                if reason == TerminationReason.TERMINATION_FAILED:
                    if cancel is not None and cancel.is_cancelled:
                        status = Status.CANCELLED
                    elif effective.expired:
                        status = Status.TIMEOUT
                if reason == TerminationReason.NORMAL_EXIT and exit_code == 0 and self.contract is not None:
                    # Control-plane results already dominate; this branch only runs
                    # on a clean normal exit, so a verified artifact is the sole
                    # remaining success path.
                    confirmed_count = verify_evidence(self.contract)
                    status, code = Status.SUCCESS, Code.OK
        except MaaFgoEvidenceError as exc:
            status, code = Status.FAILED, exc.code
            confirmed_count = 0
        except Exception:
            code = Code.INTERNAL_ERROR
            cleaned = False
            confirmed_count = 0
        finally:
            if supervisor is not None:
                try:
                    supervisor.close()
                except Exception:
                    code, reason, cleaned = Code.CLEANUP_FAILED, TerminationReason.TERMINATION_FAILED, False
                    confirmed_count = 0
                    if status is Status.SUCCESS:
                        # A success whose owned tree could not be confirmed dead is not success.
                        status = Status.FAILED
        return result()


def verify_evidence(contract: MaaFgoRunContract) -> int:
    artifact = read_completion_artifact(contract.result_path)
    return verify_completion_artifact(
        artifact,
        run_id=contract.run_id,
        plan_digest=contract.plan_digest,
        expected_tasks=contract.expected_tasks,
    )
