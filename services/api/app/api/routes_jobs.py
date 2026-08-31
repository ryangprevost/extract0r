"""Job polling. The front end long-polls these while a separation or render runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_jobs
from app.api.schemas import JobResponse
from app.jobs.store import Job, JobStore

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, jobs: JobStore = Depends(get_jobs)) -> JobResponse:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job.")
    return to_response(job)


def to_response(job: Job) -> JobResponse:
    return JobResponse(
        job_id=job.id,
        kind=job.kind,
        track_id=job.track_id,
        state=job.state.value,
        progress=job.progress,
        message=job.message,
        result=job.result,
        error=job.error,
    )
