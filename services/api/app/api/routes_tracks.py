"""Upload, inspect, separate, and delete tracks."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.deps import get_config, get_jobs, get_registry, get_storage
from app.api.schemas import (
    JobResponse,
    SeparationResponse,
    StemInfo,
    TrackResponse,
)
from app.config import Settings
from app.jobs.store import JobHandle, JobState, JobStore
from app.services import pipeline
from app.services.audio.probe import UnreadableAudioError, probe
from app.services.registry import TrackRecord, TrackRegistry
from app.services.storage import TrackStorage, UnsupportedAudioError

router = APIRouter(prefix="/api/v1/tracks", tags=["tracks"])

# Fraction of the separation job spent decoding before the model starts.
DECODE_SHARE = 0.05


@router.post("", response_model=TrackResponse, status_code=status.HTTP_201_CREATED)
async def upload_track(
    file: Annotated[UploadFile, File(description="The audio file to process")],
    owns_or_licensed: Annotated[bool, Form()] = False,
    personal_use_only: Annotated[bool, Form()] = False,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
) -> TrackResponse:
    # The rights attestation is a gate, not a checkbox we log and ignore.
    if settings.require_rights_attestation and not (owns_or_licensed and personal_use_only):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You must confirm you hold the rights to this audio and will use the "
            "output for personal purposes before Extract0r will process it.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file was empty.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds the {settings.max_upload_mb} MB limit.",
        )

    try:
        stored = storage.save_upload(file.filename or "upload.wav", data)
    except UnsupportedAudioError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    # Probe before accepting: a header read is cheap, and it is the only way to know
    # the file is really audio rather than something with an audio extension.
    try:
        info = probe(stored.path)
    except UnreadableAudioError as exc:
        storage.delete(stored.track_id)
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    if not settings.min_duration_s <= info.duration_s <= settings.max_duration_s:
        storage.delete(stored.track_id)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Track is {info.duration_s:.1f}s. Extract0r accepts "
            f"{settings.min_duration_s:.0f}s to {settings.max_duration_s / 60:.0f} minutes.",
        )

    registry.add(
        TrackRecord(
            stored=stored,
            attestation={
                "owns_or_licensed": owns_or_licensed,
                "personal_use_only": personal_use_only,
            },
            audio=info,
        )
    )
    return TrackResponse(
        track_id=stored.track_id,
        original_filename=stored.original_filename,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        duration_s=round(info.duration_s, 2),
        sample_rate=info.sample_rate,
        channels=info.channels,
        format=info.format,
    )


@router.post(
    "/{track_id}/separate",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_separation(
    track_id: str,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    try:
        registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    def work(handle: JobHandle) -> dict:
        handle.update(JobState.RUNNING, 0.02, "decoding audio")
        audio = pipeline.normalize_source(track_id, storage)

        # Decoding is a small, roughly fixed slice of the job; the model is the rest.
        def report(fraction: float) -> None:
            handle.update(None, DECODE_SHARE + fraction * (1.0 - DECODE_SHARE),
                          f"separating ({fraction:.0%})")

        handle.update(JobState.RUNNING, DECODE_SHARE, "loading model")
        result = pipeline.separate(track_id, storage, settings, on_progress=report)
        registry.set_separation(track_id, result)
        handle.update(JobState.RUNNING, 0.99, "writing stems")
        return {
            "backend": result.backend,
            "model": result.model,
            "duration_s": round(audio.duration_s, 2),
            "stems": [s.kind.value for s in result.stems],
        }

    return _as_job_response(jobs.submit("separate", track_id, work))


@router.get("/{track_id}/stems", response_model=SeparationResponse)
def list_stems(
    track_id: str,
    registry: TrackRegistry = Depends(get_registry),
) -> SeparationResponse:
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if record.separation is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Separation has not finished for this track yet."
        )
    return SeparationResponse(
        track_id=track_id,
        backend=record.separation.backend,
        model=record.separation.model,
        stems=[
            StemInfo(
                stem=s.kind,
                filename=s.path.name,
                bytes=s.path.stat().st_size if s.path.exists() else 0,
                duration_s=round(s.duration_s, 2),
                sample_rate=s.sample_rate,
            )
            for s in record.separation.stems
        ],
    )


@router.delete("/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_track(
    track_id: str,
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
) -> None:
    """Immediate, unconditional delete - the user's stated right in the privacy policy."""
    storage.delete(track_id)
    registry.remove(track_id)


def _as_job_response(job) -> JobResponse:
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
