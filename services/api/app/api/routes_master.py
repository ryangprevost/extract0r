"""Phase 2: reference mastering and export.

Runs on numpy and lameenc rather than ffmpeg, so it works wherever Phase 1 does.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
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
    DEFAULT_BASS_HZ,
    DEFAULT_WARMTH_HZ,
    DEFAULT_WIDTH_FLOOR_HZ,
    MAX_AIR_DB,
    MAX_BASS_DB,
    MAX_WARMTH_DB,
    MAX_WIDTH,
    MIN_WIDTH,
    Polish,
)
from app.services.mastering.exciter import (
    DEFAULT_FROM_HZ as DEFAULT_SPARKLE_FROM_HZ,
    MAX_FROM_HZ as MAX_SPARKLE_FROM_HZ,
    MAX_SPARKLE_DB,
    MIN_FROM_HZ as MIN_SPARKLE_FROM_HZ,
)
from app.services.mastering.depth import (
    MAX_AMBIENCE_MIX,
    MAX_PARALLEL_MIX,
    MAX_SIDE_AIR_DB,
)
from app.services.mastering.dynamics import MAX_COMPRESSION_DB
from app.services.mastering.instrument import MAX_APPLIED_BAND_DB
from app.services.mastering.lowend import MAX_CENTRE_HZ, MAX_SUBSONIC_HZ
from app.services.mastering.saturation import MAX_SATURATION_DB
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
    #: Tail length in seconds, and how much of it to blend in. 0 mix leaves it dry.
    reverb_s: float = Field(default=1.2, ge=0.15, le=4.0)
    reverb_mix: float = Field(default=0.0, ge=0.0, le=0.6)
    #: Harmonics made from this stem alone. Driving one instrument lifts it against the
    #: others, which driving the whole mix cannot do.
    sparkle_db: float = Field(default=0.0, ge=0.0, le=MAX_SPARKLE_DB)
    sparkle_from_hz: float = Field(
        default=DEFAULT_SPARKLE_FROM_HZ, ge=MIN_SPARKLE_FROM_HZ, le=MAX_SPARKLE_FROM_HZ
    )
    #: The five tone bands the per-instrument comparison speaks in. Each one is a row on
    #: the comparison screen that can be taken or left on its own, which is the whole
    #: reason they are separate fields rather than one matching curve.
    #:
    #: Bounded by what a user may ask for, not by what the comparison will suggest - the
    #: two are different numbers on purpose. See `instrument.MAX_APPLIED_BAND_DB`.
    tone_low_db: float = Field(default=0.0, ge=-MAX_APPLIED_BAND_DB, le=MAX_APPLIED_BAND_DB)
    tone_low_mid_db: float = Field(
        default=0.0, ge=-MAX_APPLIED_BAND_DB, le=MAX_APPLIED_BAND_DB
    )
    tone_high_mid_db: float = Field(
        default=0.0, ge=-MAX_APPLIED_BAND_DB, le=MAX_APPLIED_BAND_DB
    )
    tone_presence_db: float = Field(
        default=0.0, ge=-MAX_APPLIED_BAND_DB, le=MAX_APPLIED_BAND_DB
    )
    tone_air_db: float = Field(default=0.0, ge=-MAX_APPLIED_BAND_DB, le=MAX_APPLIED_BAND_DB)
    #: dB of dynamic range removed from this stem, level-matched afterwards.
    compress_db: float = Field(default=0.0, ge=0.0, le=MAX_COMPRESSION_DB)
    #: Drive on this stem alone. Never suggested - see `instrument` for why a saturation
    #: measurement would have to be invented rather than measured.
    saturation_db: float = Field(default=0.0, ge=0.0, le=MAX_SATURATION_DB)
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
    #: Low-shelf lift for weight under the body range.
    bass_db: float = Field(default=0.0, ge=-MAX_BASS_DB, le=MAX_BASS_DB)
    bass_from_hz: float = Field(default=DEFAULT_BASS_HZ, ge=40.0, le=200.0)
    #: Side-channel scale above `width_floor_hz`; the low end is never widened.
    width: float = Field(default=1.0, ge=MIN_WIDTH, le=MAX_WIDTH)
    width_floor_hz: float = Field(default=DEFAULT_WIDTH_FLOOR_HZ, ge=80.0, le=600.0)
    #: How much of the reference stereo image to take, band by band. Records are usually
    #: tighter than a home mix below 250 Hz and much wider above it, which one factor
    #: over a crossover cannot express. 0 turns it off.
    width_profile: float = Field(default=1.0, ge=0.0, le=1.0)
    #: Harmonics made from the mix's own upper mids and added above them. A shelf can
    #: only lift what is there; this makes top end that was never recorded, which is the
    #: case for anything DI'd or played from a synth patch.
    sparkle_db: float = Field(default=0.0, ge=0.0, le=MAX_SPARKLE_DB)
    #: Where the harmonics start. Low (3-5 kHz) reads as clearer and more present; high
    #: (8-10 kHz) reads as brighter, and is sheen rather than definition.
    sparkle_from_hz: float = Field(
        default=DEFAULT_SPARKLE_FROM_HZ, ge=MIN_SPARKLE_FROM_HZ, le=MAX_SPARKLE_FROM_HZ
    )
    #: Pull the low end towards the centre. 0 leaves it alone.
    centre_bass_hz: float = Field(default=0.0, ge=0.0, le=MAX_CENTRE_HZ)
    centre_bass_amount: float = Field(default=1.0, ge=0.0, le=1.0)
    #: Cut below this, where there are no notes - only rumble. 0 leaves it alone.
    subsonic_hz: float = Field(default=0.0, ge=0.0, le=MAX_SUBSONIC_HZ)
    #: A band-limited tail, in fractions of a percent. Filtered to 200 Hz - 10 kHz before
    #: blending, so it cannot muddy the bottom or wash the cymbals.
    ambience_mix: float = Field(default=0.0, ge=0.0, le=MAX_AMBIENCE_MIX)
    #: A heavily compressed copy blended underneath, lifting what is quiet.
    parallel_mix: float = Field(default=0.0, ge=0.0, le=MAX_PARALLEL_MIX)
    #: A high shelf on the side channel only.
    side_air_db: float = Field(default=0.0, ge=0.0, le=MAX_SIDE_AIR_DB)
    #: Harmonics through the body rather than above it - the other end of the spectrum
    #: from sparkle, and what is usually meant by glue.
    saturation_db: float = Field(default=0.0, ge=0.0, le=MAX_SATURATION_DB)
    #: Extra dB to sit under the reference, on top of whatever the guard decides.
    headroom_db: float = Field(default=0.0, ge=0.0, le=6.0)
    #: Refuse to squash the master past the reference's own dynamic range.
    protect_dynamics: bool = True

    # --- drums: lay a kit over the ones that were recorded --------------------
    #: Build the mix by applying the stems' changes to the original rather than by
    #: summing the stems, which keeps separation artefacts out of whatever was not
    #: changed. Off reproduces the old behaviour.
    preserve_source: bool = True
    #: Kit name, or null to leave the drums alone.
    drum_kit: str | None = None
    drum_targets: list[str] = Field(default_factory=lambda: ["kick", "snare"])
    drum_blend: float = Field(default=0.5, ge=0.0, le=1.0)

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
        record = registry.require(track_id)
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

    return _store_reference(
        track_id, file.filename or "reference.wav", data, storage, record
    )


def _store_reference(
    track_id: str,
    filename: str,
    data: bytes,
    storage: TrackStorage,
    record=None,
) -> ReferenceResponse:
    """Save, probe and meter a reference, however the bytes arrived.

    Shared by the upload and the URL route on purpose: where the audio came from should
    not change what is checked about it, and two copies of this would drift.
    """
    try:
        stored = storage.save_reference(track_id, filename, data)
    except UnsupportedAudioError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    if record is not None:
        record.reference_name = filename

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

    response = _store_reference(
        track_id, fetched.filename, fetched.data, storage, registry.get(track_id)
    )
    response.source_url = fetched.source_url
    return response


class LibraryReferenceRequest(BaseModel):
    #: Path to a file inside the configured library. Validated against it - see the route.
    path: str


@router.get("/{track_id}/reference/library")
def library_status(
    track_id: str,
    settings: Settings = Depends(get_config),
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """Whether a reference library is configured, and where.

    Separate from the scan so the page can explain itself before anyone waits on a job:
    "no library configured, here is the setting" is a different screen from "scanning
    2000 files", and finding out which one you are on should not cost a minute.
    """
    try:
        registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    root = settings.library_dir
    if root is None:
        return {
            "configured": False,
            "why": "No reference library is set. Point EXTRACT0R_LIBRARY_DIR at a folder "
            "of music you own and restart the API.",
        }
    if not Path(root).is_dir():
        return {
            "configured": False,
            "path": str(root),
            "why": f"{root} is not a folder.",
        }
    return {"configured": True, "path": str(root), "max_tracks": settings.library_max_tracks}


@router.post(
    "/{track_id}/reference/from-library",
    response_model=ReferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
def reference_from_library(
    track_id: str,
    body: LibraryReferenceRequest,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
) -> ReferenceResponse:
    """Adopt a file from the configured library as this track's reference.

    The ranking endpoint can say which of your own records would make a good target, and
    until this existed there was no way to act on the answer - you had to go and find the
    file yourself and upload it back.

    No rights gate here, unlike the upload and the URL routes, and the reason is worth
    stating: the library is a folder the operator configured on the server. Nothing the
    browser says can widen it, and a file already sitting in it was not obtained by this
    request. What *is* checked is that the path really is inside that folder.
    """
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    root = settings.library_dir
    if root is None or not Path(root).is_dir():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No reference library is configured."
        )

    # Resolve both sides before comparing. The path arrives from the browser, so without
    # this it is an arbitrary file read wearing a library's name: "../../.ssh/id_rsa"
    # resolves to somewhere very different from where it appears to point, and symlinks
    # inside the folder do the same thing without any suspicious-looking characters.
    root_real = Path(root).resolve(strict=True)
    try:
        wanted = Path(body.path).resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such file.") from exc

    if not wanted.is_relative_to(root_real) or not wanted.is_file():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "That path is outside the configured reference library.",
        )

    try:
        data = wanted.read_bytes()
    except OSError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Could not read that file.") from exc

    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"That file is larger than the {settings.max_upload_mb} MB limit.",
        )

    return _store_reference(track_id, wanted.name, data, storage, record)


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


@router.get("/{track_id}/reference/stems/{stem}/audio")
def stream_reference_stem(
    track_id: str,
    stem: str,
    request: Request,
    registry: TrackRegistry = Depends(get_registry),
):
    """Stream one separated reference stem, so it can be played against yours.

    The point of the whole per-instrument screen is putting your snare next to that
    record's snare, and a number next to a number only gets you so far - at some point you
    have to hear both. Range requests are honoured for the same reason they are on your
    own stems: without them a browser re-downloads the file on every seek.

    This serves audio from the reference, which nothing else in extract0r does. It is
    playback only: the reference is analysed, never sampled, and no path exists from these
    bytes into a master. The rights attestation collected at upload is what makes playing
    it back the user's own recording to play.
    """
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    try:
        kind = StemKind(stem)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown stem {stem!r}.") from exc

    path = (record.reference_stems or {}).get(kind)
    if path is None or not Path(path).exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "The reference has not been separated, or has no such stem.",
        )

    from app.api.routes_audio import ranged_file

    return ranged_file(Path(path), request)


@router.post("/{track_id}/reference/instruments", response_model=JobResponse)
def compare_instruments(
    track_id: str,
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    """Your instruments against the reference's, one at a time, with a dial per difference.

    The whole-mix comparison can only ever move the sum: it knows the reference has more
    low end and cannot know whether that means the bass should come up or the kick needs
    weight. This one knows, because it compares bass with bass.

    Six dimensions per instrument - level, tone in five bands, dynamics, transients,
    position and width - and each difference comes back as its own row with the control
    that closes it, so a user can take the air on the drums and decline everything else.
    What does not come back is saturation: added harmonics cannot be told from played ones
    without the dry signal, and a number invented for the sake of a full table would be
    worse than an honest gap in it.

    A job rather than a plain response because it reads twelve stems in full - both sides,
    end to end, around 25 seconds. Windowing them was tried in `stem_match` and put the
    parts that come and go several dB out, which is enough to invent a finding.
    """
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    if record.separation is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Separate this track first.")
    if not record.reference_stems:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Comparing instrument by instrument needs the reference separated too. "
            "POST /reference/separate, then try again.",
        )

    mine_paths = {s.kind: s.path for s in record.separation.stems}
    theirs_paths = dict(record.reference_stems)

    def work(handle: JobHandle) -> dict:
        from app.services.mastering.critique import STEM_WORDS
        from app.services.mastering.instrument import compare, profile_all

        handle.update(JobState.RUNNING, 0.05, "measuring your instruments")
        mine = profile_all(mine_paths)
        handle.update(JobState.RUNNING, 0.55, "measuring the reference's")
        theirs = profile_all(theirs_paths)
        handle.update(JobState.RUNNING, 0.9, "comparing them")

        instruments = []
        for kind in StemKind:
            a, b = mine.get(kind), theirs.get(kind)
            if a is None:
                continue
            words = STEM_WORDS.get(kind, (kind.value, False))
            moves = compare(kind, a, b, words) if b is not None else []
            instruments.append(
                {
                    "stem": kind.value,
                    "label": words[0],
                    # Whether the reference actually plays this instrument. A record with
                    # no piano still yields a piano stem; saying so is more use than
                    # quietly dropping the row.
                    "in_reference": bool(b is not None and b.present),
                    "yours": _profile_json(a),
                    "reference": _profile_json(b) if b is not None else None,
                    # The precomputed band-to-filter solve, so the monitor runs the same
                    # EQ the render will. Sent already solved rather than as the raw
                    # matrix: the page used to invert it itself, which was correct right
                    # up until the server started damping the solve and the page did not.
                    "tone_solver": _tone_solver_json(a),
                    "moves": [
                        {
                            "dimension": m.dimension,
                            "band": m.band,
                            "headline": m.headline,
                            "detail": m.detail,
                            "severity": m.severity,
                            "yours": round(m.yours, 3),
                            "reference": round(m.reference, 3),
                            "suggested": m.suggested,
                            "control": m.control,
                            "confident": m.confident,
                        }
                        for m in moves
                    ],
                }
            )

        from app.services.mastering.instrument import BANDS, BASIS

        return {
            "available": True,
            "instruments": instruments,
            # The five filters the tone controls are built from, so the page can build the
            # same ones. Biquads in the browser are not the same shape as the zero-phase
            # curves used for the render - a Web Audio peaking filter is not a Gaussian in
            # log frequency - so the monitor is close rather than identical, and the page
            # says so where the user can read it.
            "tone_basis": [
                {"band": band, "kind": kind, "hz": hz} for band, kind, hz in BASIS
            ],
            "bands": [
                {"band": name, "low_hz": low, "high_hz": high} for name, low, high in BANDS
            ],
        }

    return to_response(jobs.submit("compare-instruments", track_id, work))


def _tone_solver_json(one) -> list[list[float]] | None:
    """The band-to-filter solve for this stem, as five rows of five.

    `gains = solver @ wanted` - a matrix-vector product, nothing for the page to solve.
    """
    from app.services.mastering.instrument import tone_solver

    if one.spectrum is None:
        return None
    try:
        return [
            [round(float(value), 6) for value in row]
            for row in tone_solver(one.sample_rate, one.spectrum)
        ]
    except Exception:  # pragma: no cover - a bad spectrum should not fail the comparison
        log.debug("could not build the tone solver", exc_info=True)
        return None


def _profile_json(one) -> dict:
    """One instrument's measurements, in the shape the comparison screen draws."""
    return {
        "relative_lufs": round(one.relative_lufs, 2),
        "bands": one.bands,
        "dynamic_range_db": one.dynamic_range_db,
        "crest_db": one.crest_db,
        "pan": one.pan,
        "width": one.width,
        "present": one.present,
        # Where to start an audition of this stem, so the preview opens on the part the
        # comparison is about rather than on the intro.
        "preview_start_s": one.preview_start_s,
    }


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
        # Copied by name rather than field by field, and the two models are kept in step
        # by a test rather than by hand. The hand-written version was seventeen lines of
        # `x=s.x`, and the failure it invites is silent: a new control reaches the request
        # model, reaches the pipeline, and is dropped in between, so the slider moves and
        # the master does not change. That has already shipped once here.
        settings=[StemSetting(**s.model_dump()) for s in body.stems],
        reference=reference,
        reference_stems=reference_stems,
        source=(
            storage.normalized_path(track_id)
            if storage.normalized_path(track_id).exists()
            else storage.source_path(track_id)
        ),
        preserve_source=body.preserve_source,
        tags=_export_tags(record),
        bitrate_kbps=body.bitrate_kbps,
        match_strength=body.match_strength,
        match_stem_levels=body.match_stem_levels,
        match_stem_tone=body.match_stem_tone,
        match_stem_width=body.match_stem_width,
        vocal_presence=presence,
        vocal_duck_db=body.vocal_duck_db,
        drum_kit=body.drum_kit,
        drum_targets=tuple(body.drum_targets),
        drum_blend=body.drum_blend,
        polish=Polish(
            air_db=body.brightness_db,
            air_hz=body.brightness_from_hz,
            warmth_db=body.warmth_db,
            warmth_hz=body.warmth_from_hz,
            bass_db=body.bass_db,
            bass_hz=body.bass_from_hz,
            width=body.width,
            width_floor_hz=body.width_floor_hz,
            width_profile=body.width_profile,
            sparkle_db=body.sparkle_db,
            sparkle_from_hz=body.sparkle_from_hz,
            centre_bass_hz=body.centre_bass_hz,
            centre_bass_amount=body.centre_bass_amount,
            subsonic_hz=body.subsonic_hz,
            ambience_mix=body.ambience_mix,
            parallel_mix=body.parallel_mix,
            side_air_db=body.side_air_db,
            saturation_db=body.saturation_db,
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
            "per_stem": [_adjustment_json(a) for a in result.stem_adjustments],
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


def _adjustment_json(adjustment) -> dict:
    """What per-instrument matching did to one stem.

    Built from the dataclass rather than field by field, because the hand-written version
    had drifted badly: it read fifteen names off a StemAdjustment that only exist on
    PolishReport - `width_bands`, `ambience_mix`, `saturation_db` and the rest, which are
    master-bus measurements and were never per-stem at all. It raised AttributeError on
    the first name it reached, so every export with per-instrument matching turned on
    died at the point of writing the response, after all the work was done.

    It survived that long because the list is empty unless per-stem matching actually
    ran, so every test and every manual export that left the box unticked passed straight
    over it.
    """
    from dataclasses import fields

    out: dict = {}
    for spec in fields(adjustment):
        value = getattr(adjustment, spec.name)
        out[spec.name] = value.value if isinstance(value, StemKind) else value
    return out


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
            "bass_db": polish.bass_db,
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


def _export_name(record) -> str:
    """What the download should be called: the song's own name, marked as ours.

    Everything downloaded from here used to arrive as "extract0r-master.mp3", so a
    folder of masters was a folder of identical names, each overwriting the last.
    """
    original = getattr(getattr(record, "stored", None), "original_filename", "") or ""
    stem = Path(original).stem.strip() or "master"
    # Windows and macOS both object to these, and a download that cannot be saved is
    # worse than one with a dull name.
    cleaned = "".join(" " if c in r'<>:"/\|?*' else c for c in stem).strip()
    return f"{cleaned or 'master'} [extract0r].mp3"


def _export_tags(record) -> dict[str, str]:
    """ID3 fields for the export, including which reference it was matched against.

    The reference belongs in the tag rather than the filename. A master is the product of
    two recordings but only one of them is the song, and putting both names in the
    filename makes it unreadable at exactly the moment it should be scannable.
    """
    original = getattr(getattr(record, "stored", None), "original_filename", "") or ""
    reference = getattr(record, "reference_name", "") or ""
    comment = "Mastered with extract0r"
    if reference:
        comment += f" against {Path(reference).stem}"
    return {
        "TIT2": Path(original).stem or "master",
        "TENC": "extract0r",
        "COMM": comment,
    }


@router.post("/{track_id}/reference/suggestions", response_model=JobResponse)
def suggest_references(
    track_id: str,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    """Find tracks in your own library that would make good references for this one.

    The version of this feature everybody asks for reads a streaming link and suggests
    similar songs. It cannot be built: Spotify withdrew the audio-features, analysis and
    recommendations endpoints for any application created after 27 November 2024, with no
    replacement, and metadata alone says nothing about how a record was mastered.

    Measuring a local folder is better anyway. These files are already owned, and they can
    be compared on tonal balance, loudness and stereo image rather than on a genre tag.
    Nothing is copied: only measurements leave the folder, and no audio from a candidate
    can reach a master - the same guarantee the reference upload makes.

    A job rather than a plain response because the first scan of a large library is
    minutes of decoding. After that it is cached against size and modification time, and
    returns immediately.
    """
    try:
        registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    root = settings.library_dir
    if root is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No reference library is configured. Set library_dir (or EXTRACT0R_LIBRARY_DIR) "
            "to a folder of music to search.",
        )
    if not Path(root).is_dir():
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"The configured reference library {root} is not a folder."
        )

    normalised = storage.normalized_path(track_id)
    source_file = normalised if normalised.exists() else storage.source_path(track_id)
    if source_file is None or not source_file.exists():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The source audio for this track is gone."
        )

    def work(handle: JobHandle) -> dict:
        from dataclasses import asdict

        from app.services.mastering.library import profile_of, rank, scan

        handle.update(JobState.RUNNING, 0.02, "measuring your track")
        source = profile_of(source_file)
        if source is None:
            return {"available": False, "why": "Could not measure this track."}

        def progress(fraction: float, message: str) -> None:
            # Scanning is nearly all of the work, so it owns nearly all of the bar.
            handle.update(JobState.RUNNING, 0.05 + fraction * 0.9, message)

        profiles = scan(
            Path(root), limit=settings.library_max_tracks, progress=progress
        )
        handle.update(JobState.RUNNING, 0.97, "ranking candidates")
        candidates = rank(source, profiles)
        return {
            "available": True,
            "library": str(root),
            "scanned": len(profiles),
            "source": {"name": source.name, "lufs": source.lufs},
            "candidates": [
                {
                    "name": c.profile.name,
                    "path": c.profile.path,
                    "lufs": c.profile.lufs,
                    "tonal_distance_db": c.tonal_distance_db,
                    "louder_by_db": c.louder_by_db,
                    "wider_above_1k_by_db": c.wider_above_1k_by_db,
                    "tighter_below_250_by_db": c.tighter_below_250_by_db,
                    "mono": c.mono,
                    "why": c.why,
                }
                for c in candidates
            ],
        }

    return to_response(jobs.submit("suggest-references", track_id, work))


@router.get("/{track_id}/master/download")
def download_master(
    track_id: str,
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
) -> FileResponse:
    path = storage.exports_dir(track_id) / "master.mp3"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No master rendered for this track.")
    return FileResponse(
        path, media_type="audio/mpeg", filename=_export_name(registry.get(track_id))
    )


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
    stems: bool = Query(
        False,
        description="Also compare instrument by instrument. Accurate but slow: it reads "
        "every stem on both sides in full, so it is a second call rather than a "
        "slower first one.",
    ),
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

    # The per-instrument findings need both sides separated, and reading twelve stems in
    # full costs around 25 seconds against 5 for everything else. Rather than make every
    # analysis wait for them, or sample the stems and get them wrong, they are a second
    # call: the page shows the whole-mix findings immediately and fills the rest in.
    source_stems = (
        {st.kind: st.path for st in record.separation.stems}
        if stems and record.separation is not None
        else None
    )
    reference_stems = (record.reference_stems or None) if stems else None

    # Clarity needs the source separated to say which instruments crowd which band. The
    # reference does not have to be: without its stems the congestion findings still
    # work, and only "nothing of yours reaches up here" goes quiet.
    clarity: list[dict] = []
    if source_stems:
        from app.services.mastering.clarity import compare

        clarity = compare(source_file, reference, source_stems, reference_stems)

    # These need only the two summed files, so they run whether or not stems were asked
    # for - the finishing advice arrives with the first, fast half of the comparison.
    finishing: list[dict] = []
    try:
        from app.services.mastering.finishing import suggest as suggest_finishing

        # The stems are optional here and only sharpen the continuity finding, which can
        # then name the sustained part that is turned down rather than describing the
        # problem in the abstract.
        loaded_stems = None
        if source_stems:
            loaded_stems = {}
            for kind, stem_path in source_stems.items():
                try:
                    loaded_stems[getattr(kind, "value", str(kind))] = read_audio(
                        stem_path
                    ).samples
                except Exception:
                    continue

        finishing = suggest_finishing(
            source.samples,
            target.samples,
            source.sample_rate,
            target.sample_rate,
            loaded_stems or None,
        )
    except Exception:
        log.debug("could not measure the finishing moves", exc_info=True)

    summary = critique(
        result, source_stems, reference_stems, clarity=clarity, finishing=finishing
    )

    polish = result.polish
    return {
        "summary": {
            # Whether the per-instrument half of the comparison is in this response, so
            # the page knows there is more to ask for rather than guessing.
            "includes_stems": bool(source_stems and reference_stems),
            "stems_available": bool(
                record.separation is not None and record.reference_stems
            ),
            "verdict": summary.verdict,
            "findings": [
                {
                    "area": f.area,
                    "severity": f.severity,
                    "headline": f.headline,
                    "detail": f.detail,
                    "delta_db": f.delta_db,
                    "action": f.action,
                    "handled_by_match": f.handled_by_match,
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
            "bass_db": polish.bass_db,
            "bass_from_hz": polish.bass_hz,
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


@router.get("/drum-kits")
def drum_kits() -> dict:
    """The kits available to lay over a drum track, and what they are.

    Synthesised rather than sampled, for the same reason a reference is analysed and never
    sampled: shipping recorded hits would mean shipping someone's recordings.
    """
    from app.services.drums.kit import DRUMS, KITS

    descriptions = {
        "tight": "Short and controlled. Modern rock and pop.",
        "roomy": "Longer decays, more air around each hit.",
        "punchy": "Fast and forward, with more attack.",
    }
    return {
        "drums": list(DRUMS),
        "kits": [
            {
                "name": name,
                "description": descriptions.get(name, ""),
                "drums": sorted(voices),
            }
            for name, voices in KITS.items()
        ],
    }
