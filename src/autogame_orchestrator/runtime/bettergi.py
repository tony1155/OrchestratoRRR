"""Owned BetterGI WPF invocation, with instance-scoped log evidence and bounded cleanup."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from autogame_orchestrator.bettergi_config import BetterGIConfig
from autogame_orchestrator.process import CancellationToken, Deadline, ManagedProcess, ProcessSpec, ProcessSupervisor
from autogame_orchestrator.process.errors import TerminationReason
from autogame_orchestrator.runtime.bettergi_log import BetterGILog, Evidence
from autogame_orchestrator.runtime.bettergi_models import BetterGIErrorCode as Code
from autogame_orchestrator.runtime.bettergi_models import BetterGIRunResult
from autogame_orchestrator.runtime.bettergi_models import BetterGIRunStatus as Status
from autogame_orchestrator.runtime.bettergi_process import bettergi_is_running, stop_owned_job


class BetterGIAdapter:
    def __init__(
        self,
        config: BetterGIConfig,
        *,
        instance_check: Callable[[], bool] = bettergi_is_running,
        supervisor_factory: Callable[[], ProcessSupervisor] = ProcessSupervisor,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self.config = config
        self.instance_check = instance_check
        self.supervisor_factory = supervisor_factory
        self.poll_interval = poll_interval_seconds

    def run(self, deadline: Deadline | None = None, cancel: CancellationToken | None = None) -> BetterGIRunResult:
        started = datetime.now(UTC)
        mono = time.monotonic()
        status, code = Status.FAILED, Code.INTERNAL_ERROR
        process: ManagedProcess | None = None
        supervisor: ProcessSupervisor | None = None
        evidence: Evidence | None = None
        exit_code: int | None = None
        cleaned = True

        def result() -> BetterGIRunResult:
            return BetterGIRunResult(
                status,
                code,
                started,
                datetime.now(UTC),
                max(0, int((time.monotonic() - mono) * 1000)),
                exit_code,
                cleaned,
                evidence.configuration_confirmed if evidence else False,
                evidence.completion_confirmed if evidence else False,
            )

        if cancel is not None and cancel.is_cancelled:
            status, code = Status.CANCELLED, Code.CANCELLED
            return result()
        if self.config.validate() or not self.config.enabled or self.config.check_paths():
            code = Code.INVALID_CONFIGURATION
            return result()
        effective = Deadline.after(
            min(
                float(self.config.timeout_seconds),
                deadline.remaining_seconds if deadline is not None else float(self.config.timeout_seconds),
            )
        )
        if effective.expired:
            status, code = Status.TIMEOUT, Code.TASK_TIMEOUT
            return result()
        try:
            conflict = self.instance_check()
        except Exception:
            code = Code.INSTANCE_CHECK_FAILED
            return result()
        if conflict:
            code = Code.INSTANCE_CONFLICT
            return result()
        try:
            log = BetterGILog(Path(self.config.working_directory) / "log")
        except (OSError, ValueError):
            code = Code.LOG_CONTRACT_FAILED
            return result()
        try:
            supervisor = self.supervisor_factory()
            try:
                if cancel is not None and cancel.is_cancelled:
                    status, code = Status.CANCELLED, Code.CANCELLED
                elif effective.expired:
                    status, code = Status.TIMEOUT, Code.TASK_TIMEOUT
                else:
                    process = supervisor.launch(
                        ProcessSpec(
                            name="bettergi",
                            executable=Path(self.config.executable),
                            working_directory=Path(self.config.working_directory),
                            arguments=self.config.arguments,
                        )
                    )
            except Exception:
                code = Code.PROCESS_START_FAILED
            if process is not None:
                cleaned = False
                evidence = Evidence(process.pid, self.config.config_name, int(started.timestamp() * 1000) - 5000)
                while True:
                    if cancel is not None and cancel.is_cancelled:
                        status, code = Status.CANCELLED, Code.CANCELLED
                        break
                    if effective.expired:
                        status, code = Status.TIMEOUT, Code.TASK_TIMEOUT
                        break
                    exit_code = process.poll()
                    log.read(evidence, final=exit_code is not None)
                    if evidence.cancelled:
                        status, code = Status.CANCELLED, Code.CANCELLED
                        break
                    if evidence.failed:
                        code = Code.TASK_FAILED
                        break
                    if exit_code is not None:
                        if exit_code != 0:
                            code = Code.PROCESS_EXIT_NONZERO
                        elif evidence.configuration_confirmed and evidence.completion_confirmed:
                            status, code = Status.COMPLETED, Code.OK
                        else:
                            code = Code.COMPLETION_UNCONFIRMED
                        break
                    seconds = min(self.poll_interval, effective.remaining_seconds)
                    if cancel is None:
                        time.sleep(seconds)
                    else:
                        cancel.wait(timeout_seconds=seconds)
        except (OSError, ValueError):
            status, code = Status.FAILED, Code.LOG_CONTRACT_FAILED
        except Exception:
            status, code = Status.FAILED, Code.INTERNAL_ERROR
        finally:
            if supervisor is not None:
                if process is not None:
                    cleanup_deadline = Deadline.after(float(self.config.stop_timeout_seconds))
                    job_empty = False
                    try:
                        job_empty = stop_owned_job(process, cleanup_deadline)
                    except Exception:
                        pass
                    try:
                        stopped = supervisor.stop(process, confirmation_deadline=cleanup_deadline)
                        cleaned = job_empty and stopped.termination_reason in {
                            TerminationReason.NORMAL_EXIT,
                            TerminationReason.NONZERO_EXIT,
                            TerminationReason.STOPPED,
                        }
                    except Exception:
                        cleaned = False
                try:
                    supervisor.close()
                except Exception:
                    cleaned = False
        if not cleaned and status == Status.COMPLETED:
            status, code = Status.FAILED, Code.CLEANUP_FAILED
        return result()
