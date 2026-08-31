"""In-process job store and runner.

Deliberately the simplest thing that supports a progress bar: a thread pool plus a
dict. It is single-node and forgets everything on restart, which is fine for the MVP
and is the seam where Redis/RQ drops in later (see ADR-0003).
"""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

log = logging.getLogger(__name__)


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True)
class Job:
    id: str
    kind: str
    track_id: str
    state: JobState = JobState.QUEUED
    progress: float = 0.0
    message: str = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )


class JobStore:
    def __init__(self, max_workers: int = 2) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="x0r")

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def for_track(self, track_id: str) -> list[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.track_id == track_id]

    def submit(
        self,
        kind: str,
        track_id: str,
        work: Callable[[JobHandle], dict[str, Any]],
    ) -> Job:
        job = Job(id=uuid.uuid4().hex, kind=kind, track_id=track_id)
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job, work)
        return job

    def _run(self, job: Job, work: Callable[[JobHandle], dict[str, Any]]) -> None:
        handle = JobHandle(job, self._lock)
        handle.update(JobState.RUNNING, 0.01, f"{job.kind} started")
        try:
            result = work(handle)
        except Exception as exc:  # noqa: BLE001 - the job boundary is where we catch
            log.exception("job %s (%s) failed", job.id, job.kind)
            with self._lock:
                job.state = JobState.FAILED
                job.error = f"{type(exc).__name__}: {exc}"
                job.message = "failed"
                job.progress = 1.0
            log.debug(traceback.format_exc())
            return
        with self._lock:
            job.state = JobState.SUCCEEDED
            job.progress = 1.0
            job.message = "complete"
            job.result = result


@dataclass(slots=True)
class JobHandle:
    """Handed to the worker so it can report progress without touching the store."""

    job: Job
    _lock: threading.Lock

    def update(self, state: JobState | None, progress: float, message: str) -> None:
        with self._lock:
            if state is not None:
                self.job.state = state
            self.job.progress = max(0.0, min(1.0, progress))
            self.job.message = message
