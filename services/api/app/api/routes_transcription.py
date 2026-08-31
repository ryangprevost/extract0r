"""Transcribe selected stems to tab, and serve the resulting files."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse

from app.api.deps import get_config, get_jobs, get_registry, get_storage
from app.api.schemas import JobResponse, TabArtifact, TranscribeRequest, TranscribeResponse
from app.config import Settings
from app.domain.tab.fretboard import TUNINGS, SolverConfig
from app.jobs.store import JobHandle, JobState, JobStore
from app.services import pipeline
from app.services.registry import TrackRegistry
from app.services.storage import TrackStorage

router = APIRouter(prefix="/api/v1/tracks", tags=["transcription"])

# How much of the tab the UI shows before the user downloads the file.
PREVIEW_CHARS = 2000


@router.post(
    "/{track_id}/transcribe",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_transcription(
    track_id: str,
    body: TranscribeRequest,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if record.separation is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Separate this track before transcribing it."
        )

    unknown = [key for key in body.tunings.values() if key not in TUNINGS]
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Unknown tuning(s): {', '.join(unknown)}",
        )

    solver = SolverConfig(capo=body.capo, max_hand_span=body.max_hand_span)
    separation = record.separation

    def work(handle: JobHandle) -> dict:
        total = len(body.stems)
        handle.update(JobState.RUNNING, 0.05, f"transcribing {total} stem(s)")
        bundle = pipeline.transcribe(
            track_id=track_id,
            stems=body.stems,
            storage=storage,
            settings=settings,
            separation=separation,
            tuning_keys=body.tunings,
            solver=solver,
        )
        response = TranscribeResponse(
            track_id=track_id,
            artifacts=[
                TabArtifact(
                    stem=a.stem,
                    notation=a.notation.value,
                    note_count=a.note_count,
                    download_url=f"/api/v1/tracks/{track_id}/tabs/{a.stem.value}",
                    preview=a.tab_text[:PREVIEW_CHARS],
                    dropped_count=a.dropped_count,
                    folded_count=a.folded_count,
                )
                for a in bundle.artifacts
            ],
            x0r_url=f"/api/v1/tracks/{track_id}/x0r",
        )
        return response.model_dump()

    job = jobs.submit("transcribe", track_id, work)
    return JobResponse(
        job_id=job.id,
        kind=job.kind,
        track_id=job.track_id,
        state=job.state.value,
        progress=job.progress,
        message=job.message,
    )


@router.get("/{track_id}/tabs/{stem}", response_class=PlainTextResponse)
def download_tab(
    track_id: str, stem: str, storage: TrackStorage = Depends(get_storage)
) -> PlainTextResponse:
    path = storage.exports_dir(track_id) / f"{stem}.txt"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No tab for that stem yet.")
    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        headers={"Content-Disposition": f'attachment; filename="{stem}.txt"'},
    )


@router.get("/{track_id}/x0r")
def download_x0r(
    track_id: str, storage: TrackStorage = Depends(get_storage)
) -> FileResponse:
    path = storage.exports_dir(track_id) / f"{track_id}.x0r"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No .x0r document for this track yet.")
    return FileResponse(
        path, media_type="application/json", filename=f"{track_id}.x0r"
    )


@router.get("/tunings", tags=["reference"])
def list_tunings() -> dict[str, dict]:
    """The tunings the fretboard solver can target, for the UI's dropdown."""
    return {
        key: {
            "name": tuning.name,
            "open_pitches": list(tuning.open_pitches),
            "strings": tuning.string_count,
            "frets": tuning.fret_count,
        }
        for key, tuning in TUNINGS.items()
    }
