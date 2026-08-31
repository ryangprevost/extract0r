"""Phase 2: reference mastering and stem mixdown to a single MP3."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.api.deps import get_config, get_jobs, get_registry, get_storage
from app.api.routes_jobs import to_response
from app.api.schemas import JobResponse, MasterRequest, MixRequest
from app.config import Settings
from app.jobs.store import JobHandle, JobState, JobStore
from app.services.factory import make_mastering_engine
from app.services.mixdown.mixspec import (
    Compressor,
    EqBand,
    MixSpec,
    Reverb,
    StemSettings,
)
from app.services.mixdown.renderer import MixdownRenderer
from app.services.registry import TrackRegistry
from app.services.storage import TrackStorage

router = APIRouter(prefix="/api/v1/tracks", tags=["mix"])


def _to_domain(body: MixRequest) -> MixSpec:
    return MixSpec(
        stems=[
            StemSettings(
                stem=s.stem.value,
                gain_db=s.gain_db,
                pan=s.pan,
                muted=s.muted,
                solo=s.solo,
                eq=[EqBand(b.kind, b.frequency_hz, b.gain_db, b.q) for b in s.eq],
                compressor=(
                    Compressor(
                        s.compressor.threshold_db,
                        s.compressor.ratio,
                        s.compressor.attack_ms,
                        s.compressor.release_ms,
                        s.compressor.makeup_db,
                    )
                    if s.compressor
                    else None
                ),
                reverb=(
                    Reverb(s.reverb.wet, s.reverb.delay_ms, s.reverb.decay)
                    if s.reverb
                    else None
                ),
            )
            for s in body.stems
        ],
        master_gain_db=body.master_gain_db,
        normalize_lufs=body.normalize_lufs,
        bitrate_kbps=body.bitrate_kbps,
    )


@router.post("/{track_id}/mix", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def start_mixdown(
    track_id: str,
    body: MixRequest,
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if record.separation is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Separate this track first.")

    available = {s.kind.value: s.path for s in record.separation.stems}
    missing = [s.stem.value for s in body.stems if s.stem.value not in available]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"This track has no stem(s): {', '.join(missing)}",
        )

    spec = _to_domain(body)
    wanted = {s.stem: available[s.stem] for s in spec.stems}
    out_path = storage.exports_dir(track_id) / "mixdown.mp3"

    def work(handle: JobHandle) -> dict:
        handle.update(JobState.RUNNING, 0.2, "building filter graph")
        renderer = MixdownRenderer()
        result = renderer.render(spec, wanted, out_path)
        handle.update(JobState.RUNNING, 0.9, "encoding mp3")
        return {
            "download_url": f"/api/v1/tracks/{track_id}/mixdown",
            "bytes": out_path.stat().st_size,
            "ffmpeg": " ".join(result.command),
        }

    return to_response(jobs.submit("mix", track_id, work))


@router.post("/{track_id}/master", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def start_mastering(
    track_id: str,
    body: MasterRequest,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    """Match this track's mixdown to a reference track uploaded the same way."""
    try:
        registry.require(track_id)
        registry.require(body.reference_track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    target = storage.exports_dir(track_id) / "mixdown.mp3"
    if not target.exists():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Render a mixdown before mastering it."
        )
    reference = storage.source_path(body.reference_track_id)
    if reference is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reference audio is missing.")

    out_path = storage.exports_dir(track_id) / "mastered.wav"

    def work(handle: JobHandle) -> dict:
        handle.update(JobState.RUNNING, 0.2, "measuring reference")
        report = make_mastering_engine(settings).match(target, reference, out_path)
        return {
            "backend": report.backend,
            "gain_applied_db": round(report.gain_applied_db, 2),
            "warnings": report.warnings,
            "download_url": f"/api/v1/tracks/{track_id}/mastered",
        }

    return to_response(jobs.submit("master", track_id, work))


@router.get("/{track_id}/mixdown")
def download_mixdown(
    track_id: str, storage: TrackStorage = Depends(get_storage)
) -> FileResponse:
    path = storage.exports_dir(track_id) / "mixdown.mp3"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No mixdown for this track yet.")
    return FileResponse(path, media_type="audio/mpeg", filename="extract0r-mix.mp3")


@router.get("/{track_id}/mastered")
def download_mastered(
    track_id: str, storage: TrackStorage = Depends(get_storage)
) -> FileResponse:
    path = storage.exports_dir(track_id) / "mastered.wav"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No mastered file for this track yet.")
    return FileResponse(path, media_type="audio/wav", filename="extract0r-master.wav")
