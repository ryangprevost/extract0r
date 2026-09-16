"""Phase 2: reference mastering and export.

Runs on numpy and lameenc rather than ffmpeg, so it works wherever Phase 1 does.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import get_config, get_jobs, get_registry, get_storage
from app.api.routes_jobs import to_response
from app.api.schemas import JobResponse
from app.config import Settings
from app.domain.notes import StemKind
from app.jobs.store import JobHandle, JobState, JobStore
from app.services.mastering import pipeline as master_pipeline
from app.services.mastering.pipeline import MasterRequest, StemSetting
from app.services.mastering.polish import (
    DEFAULT_AIR_HZ,
    DEFAULT_WARMTH_HZ,
    DEFAULT_WIDTH_FLOOR_HZ,
    MAX_AIR_DB,
    MAX_WARMTH_DB,
    MAX_WIDTH,
    MIN_WIDTH,
    Polish,
)
from app.services.mastering.vocals import VocalPresence
from app.services.registry import TrackRegistry
from app.services.storage import TrackStorage, UnsupportedAudioError
from app.services.waveform import (
    DEFAULT_PEAK_BUCKETS,
    MAX_PEAK_BUCKETS,
    difference_db,
    measure,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tracks", tags=["mastering"])


class StemMixSetting(BaseModel):
    stem: StemKind
    gain_db: float = Field(default=0.0, ge=-60, le=12)
    pan: float = Field(default=0.0, ge=-1, le=1)
    #: 1.0 leaves stereo alone, 0 collapses to mono, >1 widens.
    width: float = Field(default=1.0, ge=0.0, le=3.0)
    muted: bool = False
    solo: bool = False


class MasterJobRequest(BaseModel):
    stems: list[StemMixSetting] = Field(min_length=1)
    #: Track id of an already-uploaded reference. Omit to export without matching.
    reference_track_id: str | None = None
    #: 0 leaves the tone alone, 1 applies the full clamped correction curve.
    match_strength: float = Field(default=1.0, ge=0.0, le=1.0)
    #: Match each stem to its counterpart in the reference. Requires the reference to
    #: have been separated first; ignored when it has not.
    per_stem_match: bool = False
    match_stem_levels: bool = True
    match_stem_tone: bool = True
    match_stem_width: bool = True
    #: Where the lead vocal should sit: back, natural, forward - or null to leave it
    #: entirely to the reference.
    vocal_presence: str | None = "natural"
    #: How far competing stems duck inside the vocal band while the vocal sings.
    vocal_duck_db: float = Field(default=3.0, ge=0.0, le=8.0)

    # --- finishing: what the reference cannot decide for you -------------------
    #: High-shelf lift. Set `brightness_from_hz` low (~3 kHz) for clarity and presence,
    #: high (~10 kHz) for air.
    brightness_db: float = Field(default=0.0, ge=-MAX_AIR_DB, le=MAX_AIR_DB)
    brightness_from_hz: float = Field(default=DEFAULT_AIR_HZ, ge=1500.0, le=14000.0)
    #: Low-shelf lift for body and weight. Not the same request as less brightness.
    warmth_db: float = Field(default=0.0, ge=-MAX_WARMTH_DB, le=MAX_WARMTH_DB)
    warmth_from_hz: float = Field(default=DEFAULT_WARMTH_HZ, ge=100.0, le=600.0)
    #: Side-channel scale above `width_floor_hz`; the low end is never widened.
    width: float = Field(default=1.0, ge=MIN_WIDTH, le=MAX_WIDTH)
    width_floor_hz: float = Field(default=DEFAULT_WIDTH_FLOOR_HZ, ge=80.0, le=600.0)
    #: Extra dB to sit under the reference, on top of whatever the guard decides.
    headroom_db: float = Field(default=0.0, ge=0.0, le=6.0)
    #: Refuse to squash the master past the reference's own dynamic range.
    protect_dynamics: bool = True

    bitrate_kbps: int = Field(default=320)
    export_wav: bool = False


class ReferenceStemsResponse(BaseModel):
    separated: bool
    stems: list[StemKind] = Field(default_factory=list)


class ReferenceResponse(BaseModel):
    reference_id: str
    filename: str
    duration_s: float
    integrated_lufs: float | None = None
    #: Present when the reference came from a URL rather than an upload.
    source_url: str | None = None


class ReferenceUrlRequest(BaseModel):
    url: str = Field(min_length=4, max_length=2048)
    owns_or_licensed: bool = False


@router.post(
    "/{track_id}/reference",
    response_model=ReferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_reference(
    track_id: str,
    file: Annotated[UploadFile, File(description="A commercial track to match against")],
    owns_or_licensed: Annotated[bool, Form()] = False,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
) -> ReferenceResponse:
    """Store a reference track for tonal and loudness matching.

    The reference is **analysed, never sampled**: nothing from this file ends up in the
    output, only measurements of it. That distinction matters legally, and the rights
    gate applies here too — uploading a commercial master is still an upload.
    """
    try:
        registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    if settings.require_rights_attestation and not owns_or_licensed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Confirm you have the right to use this reference recording. It is analysed "
            "only - no audio from it is copied into your master - but it is still an "
            "upload.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reference file was empty.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Reference exceeds the {settings.max_upload_mb} MB limit.",
        )

    return _store_reference(track_id, file.filename or "reference.wav", data, storage)


def _store_reference(
    track_id: str, filename: str, data: bytes, storage: TrackStorage
) -> ReferenceResponse:
    """Save, probe and meter a reference, however the bytes arrived.

    Shared by the upload and the URL route on purpose: where the audio came from should
    not change what is checked about it, and two copies of this would drift.
    """
    try:
        stored = storage.save_reference(track_id, filename, data)
    except UnsupportedAudioError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    from app.services.audio.probe import UnreadableAudioError, probe

    try:
        info = probe(stored)
    except UnreadableAudioError as exc:
        stored.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    loudness = None
    try:
        from app.services.mastering.loudness_meter import integrated_loudness
        from app.services.mixdown.encode import read_audio

        buffer = read_audio(stored)
        value, _ = integrated_loudness(buffer.samples, buffer.sample_rate)
        loudness = round(float(value), 2)
    except Exception:
        log.debug("could not measure reference loudness", exc_info=True)

    return ReferenceResponse(
        reference_id=track_id,
        filename=stored.name,
        duration_s=round(info.duration_s, 2),
        integrated_lufs=loudness,
    )


@router.post(
    "/{track_id}/reference/url",
    response_model=ReferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reference_from_url(
    track_id: str,
    body: ReferenceUrlRequest,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
) -> ReferenceResponse:
    """Fetch a reference from a direct link instead of uploading it.

    The same rights gate, size limit and probing as an upload - this is a different way to
    get the bytes, not a different set of rules about them. What a URL is allowed to point
    at, and why the answer is narrow, is in `app.services.fetch`.

    Streaming sites are refused rather than supported. Extract0r's own terms say it will
    not process audio ripped from a streaming service in breach of that service's terms,
    and building the downloader in would make that sentence false.
    """
    try:
        registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    if settings.require_rights_attestation and not body.owns_or_licensed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Confirm you have the right to use this reference recording. It is analysed "
            "only - no audio from it is copied into your master - but fetching it is "
            "still obtaining a copy.",
        )

    from app.services.fetch import (
        BlockedHostError,
        FetchError,
        StreamingSiteError,
        fetch_audio,
    )

    try:
        fetched = await fetch_audio(body.url, settings.max_upload_mb * 1024 * 1024)
    except StreamingSiteError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except BlockedHostError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except FetchError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    response = _store_reference(track_id, fetched.filename, fetched.data, storage)
    response.source_url = fetched.source_url
    return response


@router.post(
    "/{track_id}/reference/separate",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def separate_reference(
    track_id: str,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    """Split the reference into stems so matching can work per instrument.

    Costs a second separation pass - roughly as long as the first - which is why it is a
    separate, explicit step rather than something the reference upload does for you.
    """
    try:
        registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    reference = storage.reference_path(track_id)
    if reference is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Upload a reference before separating it."
        )

    out_dir = storage.reference_stems_dir(track_id)

    def work(handle: JobHandle) -> dict:
        from app.services.factory import make_separator

        def progress(fraction: float) -> None:
            handle.update(JobState.RUNNING, fraction, f"separating reference ({fraction:.0%})")

        handle.update(JobState.RUNNING, 0.02, "loading model")
        result = make_separator(settings).separate(reference, out_dir, on_progress=progress)
        registry.set_reference_stems(
            track_id, {s.kind: s.path for s in result.stems}
        )
        return {"stems": [s.kind.value for s in result.stems], "model": result.model}

    return to_response(jobs.submit("separate-reference", track_id, work))


@router.get("/{track_id}/reference/stems", response_model=ReferenceStemsResponse)
def reference_stems(
    track_id: str, registry: TrackRegistry = Depends(get_registry)
) -> ReferenceStemsResponse:
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    stems = record.reference_stems or {}
    return ReferenceStemsResponse(separated=bool(stems), stems=list(stems))


@router.post(
    "/{track_id}/master", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED
)
def start_master(
    track_id: str,
    body: MasterJobRequest,
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    """Mix the chosen stems, optionally match a reference, and encode an MP3."""
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if record.separation is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Separate this track first.")

    if body.bitrate_kbps not in (128, 192, 256, 320):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "bitrate must be 128, 192, 256 or 320."
        )

    available = {s.kind: s.path for s in record.separation.stems}
    missing = [s.stem.value for s in body.stems if s.stem not in available]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"This track has no stem(s): {', '.join(missing)}",
        )

    reference = None
    if body.reference_track_id:
        reference = storage.reference_path(body.reference_track_id)
        if reference is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "No reference has been uploaded for that track.",
            )

    reference_stems: dict = {}
    if body.per_stem_match:
        reference_stems = record.reference_stems or {}
        if not reference_stems:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Per-instrument matching needs the reference separated first. "
                "POST /reference/separate, then try again.",
            )

    presence = None
    if body.vocal_presence:
        try:
            presence = VocalPresence(body.vocal_presence)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"vocal_presence must be one of "
                f"{', '.join(p.value for p in VocalPresence)}",
            ) from exc

    request = MasterRequest(
        stems=available,
        settings=[
            StemSetting(
                stem=s.stem,
                gain_db=s.gain_db,
                pan=s.pan,
                width=s.width,
                muted=s.muted,
                solo=s.solo,
            )
            for s in body.stems
        ],
        reference=reference,
        reference_stems=reference_stems,
        bitrate_kbps=body.bitrate_kbps,
        match_strength=body.match_strength,
        match_stem_levels=body.match_stem_levels,
        match_stem_tone=body.match_stem_tone,
        match_stem_width=body.match_stem_width,
        vocal_presence=presence,
        vocal_duck_db=body.vocal_duck_db,
        polish=Polish(
            air_db=body.brightness_db,
            air_hz=body.brightness_from_hz,
            warmth_db=body.warmth_db,
            warmth_hz=body.warmth_from_hz,
            width=body.width,
            width_floor_hz=body.width_floor_hz,
            headroom_db=body.headroom_db,
            protect_dynamics=body.protect_dynamics,
        ),
        export_wav=body.export_wav,
    )
    work_dir = storage.exports_dir(track_id)

    def work(handle: JobHandle) -> dict:
        def progress(fraction: float, message: str) -> None:
            handle.update(JobState.RUNNING, fraction, message)

        result = master_pipeline.run(request, work_dir, on_progress=progress)
        payload = {
            "download_url": f"/api/v1/tracks/{track_id}/master/download",
            "bytes": result.mp3_path.stat().st_size,
            "duration_s": round(result.duration_s, 2),
            "stems": [s.value for s in result.included],
            "matched": result.report is not None,
            "vocals": (
                {
                    "measured_lu": result.vocals.measured_lu,
                    "target_lu": result.vocals.target_lu,
                    "lift_db": result.vocals.lift_db,
                    "user_gain_db": result.vocals.user_gain_db,
                    "ducked_stems": result.vocals.ducked_stems,
                    "duck_depth_db": result.vocals.duck_depth_db,
                    "notes": result.vocals.notes,
                }
                if result.vocals
                else None
            ),
            "finishing": _finishing(result.report),
            "per_stem": [
                {
                    "stem": a.stem.value,
                    "gain_db": a.gain_db,
                    "width_factor": a.width_factor,
                    "eq_bands": a.eq_bands,
                    "notes": a.notes,
                    "matched": a.matched,
                    "proportional": a.proportional,
                    "user_gain_db": a.user_gain_db,
                }
                for a in result.stem_adjustments
            ],
        }
        if result.report:
            payload["mastering"] = {
                "backend": result.report.backend,
                "gain_applied_db": result.report.gain_applied_db,
                "eq_curve_db": result.report.eq_curve_db,
                "warnings": result.report.warnings,
                "source": _stats(result.report.source),
                "reference": _stats(result.report.reference),
                "result": _stats(result.report.result),
            }
        return payload

    return to_response(jobs.submit("master", track_id, work))


def _finishing(report) -> dict | None:
    """The finishing stage and the limiter, flattened for the browser."""
    if report is None:
        return None
    polish, limiter = report.polish, report.limiter
    if polish is None and limiter is None:
        return None
    payload: dict = {}
    if polish is not None:
        payload |= {
            "brightness_db": polish.air_db,
            "warmth_db": polish.warmth_db,
            "width_factor": polish.width_factor,
            "width_before": polish.width_before,
            "width_after": polish.width_after,
            "headroom_db": polish.headroom_db,
            "ceiling_headroom_db": polish.ceiling_headroom_db,
            "reference_crest_db": polish.reference_crest_db,
            "result_crest_db": polish.result_crest_db,
            "notes": polish.notes,
        }
    if limiter is not None:
        payload |= {
            "limiter_max_db": limiter.max_reduction_db,
            "limiter_mean_db": limiter.mean_reduction_db,
            "limiter_active": limiter.active_fraction,
        }
    return payload


def _stats(stats) -> dict | None:
    if stats is None:
        return None
    return {
        "integrated_lufs": stats.integrated_lufs,
        "true_peak_dbfs": stats.true_peak_dbtp,
    }


@router.get("/{track_id}/master/download")
def download_master(
    track_id: str, storage: TrackStorage = Depends(get_storage)
) -> FileResponse:
    path = storage.exports_dir(track_id) / "master.mp3"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No master rendered for this track.")
    return FileResponse(path, media_type="audio/mpeg", filename="extract0r-master.mp3")


@router.get("/{track_id}/master/peaks")
def master_peaks(
    track_id: str,
    buckets: int = Query(DEFAULT_PEAK_BUCKETS, ge=50, le=MAX_PEAK_BUCKETS),
    storage: TrackStorage = Depends(get_storage),
) -> dict:
    """The mix and the master as two envelopes on one time axis, plus their difference.

    Numbers in a report say what mastering decided. Seeing the same four minutes twice is
    what makes it land: where the limiter shaved a chorus, where a quiet verse was pulled
    up, whether the whole thing simply got louder.

    `mix.wav` is the mix as you balanced it - stems matched, vocal placed, faders applied -
    and `mastered.wav` is that mix after the reference match. Without a reference the
    pipeline never writes the second file, and there is nothing to compare.
    """
    exports = storage.exports_dir(track_id)
    before_path = exports / "mix.wav"
    after_path = exports / "mastered.wav"

    if not before_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No master rendered for this track.")
    if not after_path.exists():
        return {"matched": False, "buckets": buckets}

    # The files are overwritten on every render, so the cache key has to change when they
    # do. Naming it after the buckets alone would serve the previous run's picture next to
    # the current run's numbers.
    stamp = "-".join(
        f"{p.stat().st_mtime_ns}x{p.stat().st_size}" for p in (before_path, after_path)
    )
    cache = exports / f"peaks-{buckets}-{stamp}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.debug("discarding unreadable master peak cache %s", cache.name)

    try:
        before = measure(before_path, buckets)
        after = measure(after_path, buckets)
    except ImportError as exc:  # pragma: no cover - numpy/soundfile are hard requirements
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "numpy/soundfile are required for waveforms."
        ) from exc

    payload = {
        "matched": True,
        "buckets": buckets,
        "before": before.as_payload(),
        "after": after.as_payload(),
        "delta_db": difference_db(before, after),
    }

    for stale in exports.glob(f"peaks-{buckets}-*.json"):
        if stale != cache:
            stale.unlink(missing_ok=True)
    try:
        cache.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        log.debug("could not cache master peaks for %s", track_id)

    return payload


@router.get("/{track_id}/master/suggest")
def suggest_settings(
    track_id: str,
    registry: TrackRegistry = Depends(get_registry),
    storage: TrackStorage = Depends(get_storage),
) -> dict:
    """Where this mix differs from its reference, and which dial closes the gap.

    Compares the uploaded track against the uploaded reference directly - no separation
    and no mastering run, so it answers in a couple of seconds and can be called the
    moment a reference lands.

    Every suggested value comes back with the sentence explaining it and the measurement
    behind it. A dial that moves on its own without saying why is worse than one that
    stays put.
    """
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    reference = storage.reference_path(track_id)
    if reference is None or not reference.exists():
        return {"available": False, "why": "No reference uploaded for this track yet."}

    try:
        from app.services.mastering.critique import critique
        from app.services.mastering.suggest import suggest
        from app.services.mixdown.encode import read_audio

        # The normalised copy is written at the start of separation, so it is only
        # there once a track has been split; before that the upload itself is the
        # source. Reaching for record.path - which does not exist - is what made this
        # endpoint 500 on every real request while passing every test that called
        # suggest() directly.
        normalised = storage.normalized_path(track_id)
        source_file = normalised if normalised.exists() else storage.source_path(track_id)
        if source_file is None or not source_file.exists():
            return {"available": False, "why": "The source audio for this track is gone."}

        source = read_audio(source_file)
        target = read_audio(reference)
    except ImportError as exc:  # pragma: no cover - numpy/soundfile are hard requirements
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "numpy/soundfile are required."
        ) from exc

    result = suggest(source.samples, target.samples, source.sample_rate)

    # The mix-balance findings need both sides separated. They are the most useful part of
    # the comparison, so they are included whenever they can be, and simply absent
    # otherwise rather than gated behind a separate call.
    source_stems = (
        {st.kind: st.path for st in record.separation.stems}
        if record.separation is not None
        else None
    )
    summary = critique(result, source_stems, record.reference_stems or None)

    polish = result.polish
    return {
        "summary": {
            "verdict": summary.verdict,
            "findings": [
                {
                    "area": f.area,
                    "severity": f.severity,
                    "headline": f.headline,
                    "detail": f.detail,
                    "delta_db": f.delta_db,
                }
                for f in summary.findings
            ],
        },
        "available": True,
        "settings": {
            "brightness_db": polish.air_db,
            "brightness_from_hz": polish.air_hz,
            "warmth_db": polish.warmth_db,
            "warmth_from_hz": polish.warmth_hz,
            "width": polish.width,
            "headroom_db": polish.headroom_db,
        },
        "reasons": {r.control: r.text for r in result.reasons},
        "measured": {
            "bands": {
                name: {"yours": mine, "reference": theirs, "gap": round(gap, 2)}
                for name, (mine, theirs, gap) in result.bands.items()
            },
            "source_width": result.source_width,
            "reference_width": result.reference_width,
            "reference_crest_db": result.reference_crest_db,
        },
    }
