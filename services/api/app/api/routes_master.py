"""Phase 2: reference mastering and export.

Runs on numpy and lameenc rather than ffmpeg, so it works wherever Phase 1 does.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Annotated, Literal

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
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator

from app.api.deps import get_config, get_jobs, get_registry, get_storage
from app.api.routes_jobs import to_response
from app.api.schemas import JobResponse
from app.config import Settings
from app.domain.notes import StemKind
from app.jobs.stages import GROOVE_BOTH_SIDES, GROOVE_ONE_SIDE
from app.jobs.store import JobHandle, JobState, JobStore
from app.services.mastering import pipeline as master_pipeline
from app.services.mastering.depth import (
    MAX_AMBIENCE_MIX,
    MAX_PARALLEL_MIX,
    MAX_SIDE_AIR_DB,
)
from app.services.mastering.dynamics import MAX_COMPRESSION_DB
from app.services.mastering.exciter import (
    DEFAULT_FROM_HZ as DEFAULT_SPARKLE_FROM_HZ,
)
from app.services.mastering.exciter import (
    MAX_FROM_HZ as MAX_SPARKLE_FROM_HZ,
)
from app.services.mastering.exciter import (
    MAX_SPARKLE_DB,
)
from app.services.mastering.exciter import (
    MIN_FROM_HZ as MIN_SPARKLE_FROM_HZ,
)
from app.services.mastering.instrument import BANDS as _BANDS_FOR_DISPLAY
from app.services.mastering.instrument import MAX_APPLIED_BAND_DB
from app.services.mastering.lowend import MAX_CENTRE_HZ, MAX_SUBSONIC_HZ
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
from app.services.mastering.saturation import MAX_SATURATION_DB
from app.services.mastering.sidechain import MAX_APPLIED_DB as MAX_SIDECHAIN_APPLIED_DB
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
    #: Gain reduction keyed to the kick. Meaningful on the bass and ignored elsewhere,
    #: because that is the only pair this measures. Bounded by the hardest the solver will
    #: ever ask for - past that it is an effect rather than a match.
    sidechain_db: float = Field(default=0.0, ge=0.0, le=MAX_SIDECHAIN_APPLIED_DB)
    #: Drive on this stem alone. Never suggested - see `instrument` for why a saturation
    #: measurement would have to be invented rather than measured.
    saturation_db: float = Field(default=0.0, ge=0.0, le=MAX_SATURATION_DB)
    muted: bool = False
    solo: bool = False


class DrumMixSetting(BaseModel):
    """A move taken on one drum inside the drums stem.

    Four fewer fields than `StemMixSetting`, and the four that are missing are missing on
    purpose. There is no mute or solo because a sub-drum is not a lane - the mixer's
    faders are per stem and a kick has no fader of its own. There is no reverb or
    sparkle because those are stem moves the comparison never suggests per drum.

    `pan` and `width` are accepted for cymbals and toms and refused for a kick and a
    snare, by the same rule that governs whether the comparison offers them at all. The
    check is in the route rather than here, because a field cannot know which drum it is
    on.
    """

    drum: str
    gain_db: float = Field(default=0.0, ge=-12, le=12)
    pan: float = Field(default=0.0, ge=-1, le=1)
    width: float = Field(default=1.0, ge=0.0, le=3.0)
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
    compress_db: float = Field(default=0.0, ge=0.0, le=MAX_COMPRESSION_DB)


class MasterJobRequest(BaseModel):
    stems: list[StemMixSetting] = Field(min_length=1)
    #: How far this run may move anything: "nudge", "further", "closest". Unlike
    #: `match_strength` below, this one has a measured effect - see `mastering.budget`.
    #: An unknown name falls back to the default rather than 422ing, so an older client
    #: keeps working.
    budget: str = "nudge"
    #: Moves taken on the four drums inside the drums stem. Ignored unless that stem has
    #: been split, which only the per-drum comparison does.
    drums: list[DrumMixSetting] = Field(default_factory=list)
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
    #: Stems to play on a synthesised voice instead of as recorded, as {stem: voice}.
    #: X0R-1328. Each named stem must already have been rendered by `/revoice`; one that
    #: has not is left as recorded rather than silenced.
    revoice: dict[str, str] = Field(default_factory=dict)
    #: Kit name, or null to leave the drums alone.
    drum_kit: str | None = None
    drum_targets: list[str] = Field(default_factory=lambda: ["kick", "snare"])
    drum_blend: float = Field(default=0.5, ge=0.0, le=1.0)

    bitrate_kbps: int = Field(default=320)
    export_wav: bool = False
    #: "16", "24" or "32f" for the exported WAV. Nothing to do with the MP3: LAME takes
    #: 16-bit PCM and `lameenc` has no setter for anything else, so there is no bit depth
    #: on that path to choose. See `encode.WAV_SUBTYPES`.
    wav_depth: Literal["16", "24", "32f"] = "24"


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

    The reference is **analyzed, never sampled**: nothing from this file ends up in the
    output, only measurements of it. That distinction matters legally, and the rights
    gate applies here too — uploading a commercial master is still an upload. The one
    exception is a sound the person chooses to sample from it in pr0ducer (Sprint 15,
    `sample_reference`), which they must say they may do, and which is named as such.
    """
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    if settings.require_rights_attestation and not owns_or_licensed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Confirm you have the right to use this reference recording. It is analyzed "
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


def _forget_the_previous_reference(track_id: str, record, storage) -> None:
    """Everything derived from the reference that has just been replaced.

    X0R-1420. `save_reference` replaces the bytes correctly, and for a long time that
    looked like the whole job. It is not: three things outlive the file they came from,
    and all three are read by name afterwards.

    * `reference_stems` - the six stems the old reference was separated into. Left in
      place, the instrument comparison measures the new record on one side and the old one
      on the other, and a profile saved from it carries the old record's instruments under
      the new record's name.
    * `drum_stems["reference"]` - the four drums inside those. Same fault, one level in.
      The source's own drums are untouched, because they have nothing to do with the
      reference and throwing away a separation the user paid for would be its own bug.
    * `reference_profile` - a saved profile this track was aimed at before. A file and a
      profile are two answers to the same question; leaving both set makes which one wins
      depend on the order some other function happens to check them in.

    This survived from September because a profile is six kilobytes of numbers with no
    audio behind it: there is no way to look at one afterwards and tell which record it
    describes. It was found when two of them turned out to be byte-identical.

    The stale directories go too, not only the registry entries. Keeping them would leave
    the next separation writing into a folder that already holds another record's stems.
    """
    import shutil

    record.reference_stems = {}
    record.reference_profile = None
    if record.drum_stems:
        record.drum_stems = {
            side: stems for side, stems in record.drum_stems.items() if side != "reference"
        }

    for directory in (
        storage.reference_stems_dir(track_id),
        storage.drum_stems_dir(track_id, "reference"),
    ):
        try:
            if Path(directory).is_dir():
                shutil.rmtree(directory)
        except OSError:
            # A stale folder is untidy; failing the upload over it would be worse, and
            # the registry no longer points at it either way.
            log.info("could not remove %s after a reference swap", directory, exc_info=True)



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
        _forget_the_previous_reference(track_id, record, storage)

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
            "Confirm you have the right to use this reference recording. It is analyzed "
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


class SaveProfileRequest(BaseModel):
    #: What to call it. Becomes the filename, sanitised - see `profile.safe_filename`.
    name: str = Field(min_length=1, max_length=120)


class UseProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.get("/reference/profiles")
def list_profiles(settings: Settings = Depends(get_config)) -> dict:
    """Every saved reference profile: what a record teaches, without the record.

    Not scoped to a track. A profile is the point of the feature precisely because it
    outlives the track it was captured from - measure a song once, aim at it for years.
    """
    from app.services.mastering.profile import listing

    return {
        "directory": str(settings.profile_dir),
        "profiles": [
            {
                "name": p.name,
                "captured_from": p.captured_from,
                "captured_at": p.captured_at,
                "seconds": p.seconds,
                "lufs": p.lufs,
                "true_peak_db": p.true_peak_db,
                # So a chooser can say which profiles carry the instrument half before
                # anyone commits to one and finds out on the comparison screen.
                "per_stem": p.has_instruments,
                "instruments": sorted(p.instruments),
                # And whether it carries the four drums inside the drums stem, which is
                # a second, rarer thing a profile may hold.
                "per_drum": p.has_drums,
                "drums": sorted(p.drums),
            }
            for p in listing(settings.profile_dir)
        ],
    }


@router.post("/{track_id}/reference/profile", status_code=status.HTTP_201_CREATED)
def save_reference_profile(
    track_id: str,
    body: SaveProfileRequest,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """Measure this track's reference once and keep the numbers.

    What gets written is a spectrum, a width profile, a loudness and two peaks - the whole
    of what the match ever reads from a reference. No audio, and nothing that can be turned
    back into audio.

    If this track's reference has been separated, the per-instrument half is measured and
    kept as well: seven numbers per stem, which is everything `instrument.compare` reads
    from the reference side. That makes the profile able to drive the instrument-by-
    instrument stage on any future song, with no second separation to wait for. It is
    skipped silently when there are no reference stems - a whole-mix profile is worth
    having on its own, and the response says which kind was written.
    """
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    reference = storage.reference_path(track_id)
    if reference is None or not reference.exists():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "There is no reference on this track to measure."
        )

    from app.services.mastering import subdrum
    from app.services.mastering.instrument import profile_all, snapshot_all
    from app.services.mastering.profile import capture, save
    from app.services.mixdown.encode import read_audio

    instruments: dict[str, dict] = {}
    if record.reference_stems:
        try:
            instruments = snapshot_all(profile_all(dict(record.reference_stems)))
        except Exception:
            # A whole-mix profile is still worth writing. Failing the whole save because
            # one stem would not read loses the part that was working.
            log.warning("could not measure the reference stems for a profile", exc_info=True)

    # One level further in, and only when the reference's drums have already been split -
    # this never *starts* a separation. Saving a profile should cost what it has always
    # cost; the per-drum pass is a thing the user chose to run on the comparison screen,
    # and what is written here is the measurements it already produced.
    drums: dict[str, dict] = {}
    sub_stems = (record.drum_stems or {}).get("reference") or {}
    if sub_stems:
        try:
            drums = subdrum.snapshot_all(subdrum.profile_all(dict(sub_stems)))
        except Exception:
            log.warning("could not measure the reference's drums for a profile", exc_info=True)

    audio = read_audio(reference)
    captured = capture(
        audio.samples,
        audio.sample_rate,
        body.name,
        getattr(record, "reference_name", "") or reference.name,
        instruments=instruments,
        drums=drums,
    )
    path = save(captured, settings.profile_dir)
    return {
        "name": captured.name,
        "captured_from": captured.captured_from,
        "lufs": captured.lufs,
        "seconds": captured.seconds,
        "bytes": path.stat().st_size,
        "instruments": sorted(captured.instruments),
        "per_stem": captured.has_instruments,
        "drums": sorted(captured.drums),
        "per_drum": captured.has_drums,
    }


@router.post(
    "/{track_id}/reference/use-profile", status_code=status.HTTP_200_OK
)
def use_reference_profile(
    track_id: str,
    body: UseProfileRequest,
    settings: Settings = Depends(get_config),
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """Aim this track at a saved profile instead of at a reference file.

    Covers the whole-mix stage completely - the tonal curve, the width match, the level
    and the headroom guard all read measurements and nothing else. It covers the
    per-instrument stage too when the profile was captured from a separated reference,
    because that comparison reads measurements as well. The response says which, rather
    than leaving someone to discover it by finding an empty screen.
    """
    try:
        registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    from app.services.mastering.profile import find

    profile = find(settings.profile_dir, body.name)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No saved profile {body.name!r}.")

    registry.set_reference_profile(track_id, profile)
    return {
        "name": profile.name,
        "captured_from": profile.captured_from,
        "lufs": profile.lufs,
        "seconds": profile.seconds,
        "per_stem_available": profile.has_instruments,
        "instruments": sorted(profile.instruments),
        # And whether it also carries the four drums inside the drums stem, which is the
        # difference between reaching the per-drum comparison instantly and paying for a
        # second separation of a reference that no longer exists here as audio.
        "per_drum_available": profile.has_drums,
        "drums": sorted(profile.drums),
        "note": (
            "Matched on the whole mix and instrument by instrument. The reference was "
            "separated when this profile was saved, so its stems are already measured - "
            "your song is the only one that needs splitting."
            if profile.has_instruments
            else "Whole-mix matching only. This profile was saved from a reference that "
            "had not been separated, so there are no reference instruments to compare "
            "yours against. Load that song as a reference with instrument-by-instrument "
            "matching on, and save the profile again to include them."
        ),
    }


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
    playback only: the reference is analyzed, never sampled, and no path exists from these
    bytes into a master. (pr0ducer can sample a note from a stem when the person asks - see
    `sample_reference` - but never from here.) The rights attestation collected at upload is
    what makes playing it back the user's own recording to play.
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


# --- Sprint 15: a sound sampled from the reference ---------------------------------------------


def _sampled_dir(storage: TrackStorage, track_id: str, stem: str) -> Path:
    return storage.exports_dir(track_id) / "sampled" / stem


@router.post("/{track_id}/reference/notes", response_model=JobResponse)
def find_reference_notes(
    track_id: str,
    stem: str = Query("other", description="the reference stem to look in"),
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    """Find the clean notes in one of the reference's parts - candidates to sample. Sprint 15.

    Nothing is sampled yet: each candidate is cut so it can be heard, kept with the track,
    and becomes an instrument only when the person picks it and says they may sample it."""
    from app.services.synth.sampled import SAMPLEABLE

    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if stem not in SAMPLEABLE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Sounds are sampled from {', '.join(SAMPLEABLE)} - not {stem}.")
    path = (record.reference_stems or {}).get(StemKind(stem))
    if path is None or not Path(path).exists():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Split the reference first, so there is a part to sample from.")

    def work(handle: JobHandle) -> dict:
        import soundfile as sf

        from app.services.synth import sampled

        handle.update(JobState.RUNNING, 0.1, f"reading the notes in the reference's {stem}")
        notes = _transcribe(settings, StemKind(stem), Path(path)).notes
        handle.update(JobState.RUNNING, 0.6, "listening for clean ones")
        audio, rate = sf.read(str(path), dtype="float64", always_2d=True)
        found = sampled.find_candidates(audio, rate, notes)
        out = _sampled_dir(storage, track_id, stem)
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("*.wav"):
            old.unlink()
        held = {}
        for c in found:
            note = sampled.cut(audio, rate, c)
            held[c.n] = round(len(note) / rate, 2)
            sf.write(str(out / f"{c.n}.wav"), note, rate, subtype="PCM_16")
        (out / "candidates.json").write_text(
            json.dumps({"rate": rate, "candidates": [c.to_dict() for c in found]}), "utf-8")
        return {
            "stem": stem,
            # `sample_s`: how long the sample can hold a note, looped or not.
            "candidates": [dict(c.to_dict(), sample_s=held[c.n],
                                url=f"/api/v1/tracks/{track_id}/reference/notes/"
                                f"{stem}/{c.n}.wav") for c in found],
            "note": "Best first. A clean note is one pitch at a time, held steady, with most of "
            "its sound on its own harmonics." if found else
            f"No clean notes in the reference's {stem} - it is chords, noise or another "
            "part's leakage throughout. Try another part.",
        }

    return to_response(jobs.submit("reference-notes", track_id, work))


@router.get("/{track_id}/reference/notes/{stem}/{n}.wav")
def hear_reference_note(
    track_id: str, stem: str, n: int,
    storage: TrackStorage = Depends(get_storage),
) -> FileResponse:
    """One candidate, as it would be sampled: cut, tuned and held. Sprint 15."""
    path = _sampled_dir(storage, track_id, stem) / f"{int(n)}.wav"
    if not re.fullmatch(r"[a-z]+", stem) or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such candidate - find notes first.")
    return FileResponse(path, media_type="audio/wav")


class SampleRequest(BaseModel):
    stem: str
    picks: list[int] = Field(min_length=1, max_length=24)
    name: str = Field("", max_length=40)
    #: The person says they may sample this recording - see `legal.SAMPLING_NOTICE`.
    may_sample: bool = False


@router.post("/{track_id}/reference/sampled")
def sample_reference(
    track_id: str,
    body: SampleRequest,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """Make an instrument of the picked notes, to play any part on. Sprint 15.

    The one place extract0r samples a reference, and only when asked: `may_sample` must be
    true. The instrument goes to the samples folder, never the repository, is named for the
    reference, and is deleted with this track."""
    import soundfile as sf

    from app.legal import SAMPLING_NOTICE
    from app.services.synth import sampled

    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if not body.may_sample:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, SAMPLING_NOTICE + " Tick the box to "
                            "say you may sample this recording.")
    if settings.sample_dir is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No samples folder is configured.")
    folder = _sampled_dir(storage, track_id, body.stem)
    try:
        saved = json.loads((folder / "candidates.json").read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Find the notes first.") from exc
    by_n = {c["n"]: sampled.Candidate.from_dict(c) for c in saved["candidates"]}
    missing = [n for n in body.picks if n not in by_n or not (folder / f"{n}.wav").exists()]
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No candidate {missing[0]}.")
    picks = []
    for n in dict.fromkeys(body.picks):
        audio, _ = sf.read(str(folder / f"{n}.wav"), dtype="float64")
        picks.append((by_n[n], audio))
    reference = getattr(record, "reference_name", "") or "the reference"
    names = "/".join(sampled.note_name(c.pitch) for c, _ in picks[:3])
    name = body.name.strip() or f"{Path(reference).stem[:24]} {body.stem} {names}"
    made = sampled.make_instrument(settings.sample_dir, name, body.stem, reference, picks,
                                   int(saved["rate"]), SAMPLING_NOTICE, track_id,
                                   storage.root)
    from app.services.synth import instruments

    instrument = instruments.find(made, settings.sample_dir)
    return {"id": made, "name": instrument.name if instrument else name,
            "label": f"{name} (from your reference)",
            "instrument": instrument.to_dict() if instrument else None,
            "notice": SAMPLING_NOTICE}


@router.post("/{track_id}/reference/instruments", response_model=JobResponse)
def compare_instruments(
    track_id: str,
    budget: str = Query("nudge", description="nudge | further | closest"),
    settings: Settings = Depends(get_config),
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
    # Two ways to have a reference to compare against, and the second is why this route
    # no longer insists on stems: a saved profile carries the reference's instruments as
    # measurements, which is all the comparison ever reads from that side. Stems win when
    # both are present, because they came from the song the user just chose.
    saved = getattr(record, "reference_profile", None)
    from_profile = not record.reference_stems and saved is not None and saved.has_instruments

    if not record.reference_stems and not from_profile:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Comparing instrument by instrument needs the reference separated too, or a "
            "saved profile that was. POST /reference/separate, then try again.",
        )

    mine_paths = {s.kind: s.path for s in record.separation.stems}
    theirs_paths = dict(record.reference_stems)
    theirs_saved = dict(saved.instruments) if from_profile else {}
    reference_name = saved.name if from_profile else ""

    def work(handle: JobHandle) -> dict:
        from app.jobs.stages import COMPARE_BOTH_SIDES, COMPARE_FROM_PROFILE
        from app.services.mastering.budget import limits_for
        from app.services.mastering.critique import STEM_WORDS
        from app.services.mastering.instrument import (
            compare,
            from_snapshot_all,
            profile_all,
        )

        ceilings = limits_for(budget)

        # Fractions from measured stage costs rather than chosen by hand. This job used
        # to report 0.9 immediately before the character pass, which is half of it, so
        # the bar reached ninety per cent and then appeared to hang. See `jobs.stages`.
        plan = COMPARE_FROM_PROFILE if from_profile else COMPARE_BOTH_SIDES

        plan.report(handle, "mine")
        mine = profile_all(mine_paths)
        plan.report(handle, "theirs")
        # From a profile this is already measured, once, whenever the profile was
        # saved - which is the whole point of the feature: the half of the work that used
        # to take longer than the user's own song did is now a dictionary lookup.
        theirs = (
            from_snapshot_all(theirs_saved) if from_profile else profile_all(theirs_paths)
        )
        # Named for the work, not for the step. "Comparing them" was measured at 0.00 s
        # across six instruments; what the user is waiting for here is the pitch tracker.
        plan.report(handle, "character")

        instruments = []
        for kind in StemKind:
            a, b = mine.get(kind), theirs.get(kind)
            if a is None:
                continue
            words = STEM_WORDS.get(kind, (kind.value, False))
            moves = compare(kind, a, b, words, limits=ceilings) if b is not None else []
            # Two observations with no dial: how close to the grid a vocal sits, and how
            # often each part plays. They need the audio rather than the profile, so a
            # comparison drawn from a saved profile has the source half only and emits
            # nothing - a profile keeps measurements, not music.
            moves = moves + _character(kind, words, mine_paths, theirs_paths)
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
                    # No audio behind a saved profile, so there is nothing to solo. Said
                    # per row rather than inferred, so the page never renders a play
                    # button that cannot do anything.
                    "reference_audio": not from_profile,
                    # The precomputed band-to-filter solve, so the monitor runs the same
                    # EQ the render will. Sent already solved rather than as the raw
                    # matrix: the page used to invert it itself, which was correct right
                    # up until the server started damping the solve and the page did not.
                    "tone_solver": _tone_solver_json(a),
                    "moves": [_move_json(m) for m in moves],
                }
            )

        from app.services.mastering.instrument import BANDS, BASIS

        return {
            "available": True,
            # Whether the drums card can offer a second level, and what it would cost.
            # Sent with the comparison rather than fetched separately so the card can be
            # drawn in one pass - and sent even when it is unavailable, because
            # "unavailable, and here is how to get it" is the whole of criterion 9.
            "per_drum": _per_drum_capability(record, settings),
            # Where the reference half came from, so the page can explain a comparison
            # with no audio behind it instead of appearing to lose a feature.
            "reference_kind": "profile" if from_profile else "stems",
            "reference_name": reference_name,
            # Which notch produced these suggestions. On the response rather than assumed
            # by the page, so a comparison cached from before a budget change cannot be
            # drawn under the new label.
            "budget": budget,
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


def _drum_shapes(wanted, available: dict[str, Path]) -> dict:
    """The per-drum moves, as shapes, refusing the ones that cannot mean anything.

    Two refusals, both 422 rather than a silent drop, because a dial that reports success
    and does nothing is worse than one that says no:

    * a drum that was never split out of this track's drums - there is nothing to apply
      it to, and guessing which file was meant is how a kick move lands on a snare;
    * a sideways move on a kick or a snare, by the same rule that stops the comparison
      offering one. A separated kick is the most mono signal in the application, so a pan
      on it is moving separation bleed around.
    """
    from app.services.mastering import subdrum
    from app.services.mastering.instrument import NEVER_MOVE_SIDEWAYS, StemShape

    shapes: dict[str, StemShape] = {}
    for one in wanted or []:
        if one.drum not in subdrum.DRUMS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{one.drum!r} is not one of {', '.join(subdrum.DRUMS)}.",
            )
        if one.drum not in available:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"This track's drums have not been split into a {one.drum}. Run the "
                "drum-by-drum comparison first.",
            )
        if one.drum in NEVER_MOVE_SIDEWAYS and (one.pan or one.width != 1.0):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"A {one.drum} is not moved sideways: a separated {one.drum} is "
                "effectively mono, so a pan or a width on it moves separation bleed "
                "rather than the drum.",
            )
        fields = one.model_dump()
        fields.pop("drum")
        shapes[one.drum] = StemShape(**fields)
    return shapes


def _character(kind, words, mine_paths, theirs_paths) -> list:
    """The contour and onset observations for one stem, or nothing.

    Wrapped in its own try: these read audio a second time and are the newest code on
    this path, and a comparison that lost its six instrument cards because a pitch
    tracker raised would be a bad trade for two extra rows.
    """
    from app.services.mastering.character import observations
    from app.services.mixdown.encode import read_audio

    def audio(paths):
        path = paths.get(kind)
        if path is None or not Path(path).exists():
            return None, 0
        buffer = read_audio(Path(path))
        return buffer.samples, buffer.sample_rate

    try:
        mine, rate = audio(mine_paths)
        if mine is None:
            return []
        theirs, _ = audio(theirs_paths)
        return observations(kind, words[0], words[1], mine, theirs, rate)
    except Exception:
        log.info("could not read the character of %s", kind, exc_info=True)
        return []


def _move_json(move) -> dict:
    """One finding, in the shape the comparison screen draws.

    Named once because there are two levels of comparison now - stems and the four drums
    inside one of them - and a field added to one and not the other is a row that renders
    differently depending on how far in you are.
    """
    return {
        "dimension": move.dimension,
        "band": move.band,
        "headline": move.headline,
        "detail": move.detail,
        "severity": move.severity,
        "yours": round(move.yours, 3),
        "reference": round(move.reference, 3),
        "measured": move.measured,
        "suggested": move.suggested,
        "control": move.control,
        "confident": move.confident,
    }



def _bleed_for(path, drum: str) -> float | None:
    """How loud the content that does not belong in one drum stem is, or None.

    Wrapped and swallowed: this is a caveat on a row, and losing four drum cards because
    a filter raised on an odd file would be a bad trade for a sentence.
    """
    from app.services.mastering import subdrum
    from app.services.mixdown.encode import read_audio

    if not path or not Path(path).exists():
        return None
    try:
        buffer = read_audio(Path(path))
        return subdrum.bleed_db(buffer.samples, buffer.sample_rate, drum)
    except Exception:
        log.info("could not measure bleed in the %s stem", drum, exc_info=True)
        return None



def _duck_measurement(kick_path, bass_path):
    """How far one side's bass gets out of its own kick's way, or None.

    Lives here rather than in `sidechain` because it is the plumbing - finding a grid,
    reading two files - and `sidechain` is the part worth testing without any of that.

    The kick times come from the separated kick sub-stem rather than from a classifier on
    the drum bus. X0R-414 is why: a stroke in the kick file *is* a kick, while the
    classifier puts about a quarter of them within a few decibels of the snare line, and a
    duck keyed to a mis-detected kick measures as noise.
    """
    import numpy as np

    from app.services.analysis.fingerprint import BeatGrid, envelope_db, kick_duck
    from app.services.analysis.timing import TimingAnalyser
    from app.services.mixdown.encode import read_audio

    if not kick_path or not bass_path:
        return None
    kick_path, bass_path = Path(kick_path), Path(bass_path)
    if not kick_path.exists() or not bass_path.exists():
        return None

    try:
        import librosa

        y, sr = librosa.load(str(kick_path), sr=None, mono=True)
        kicks = [float(t) for t in librosa.onset.onset_detect(y=y, sr=sr, units="time")]
        if not kicks:
            return None

        bass = read_audio(bass_path)
        duration = len(bass.samples) / bass.sample_rate
        grid = BeatGrid.from_timing(TimingAnalyser().analyse(bass_path), duration)

        env, times = envelope_db(np.asarray(bass.samples, dtype=np.float64), bass.sample_rate)
        return kick_duck(env, times, kicks, grid)
    except Exception:
        # One optional figure. A comparison that lost its four drum cards because a beat
        # tracker raised would be a bad trade for one row.
        log.info("could not measure the bass duck", exc_info=True)
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


# --- the four drums inside the drums stem ------------------------------------------------
#
# A second level, not six more stems. `subdrum`'s docstring has the reasoning; the short
# version is that `pipeline.run` sums every separated stem and subtracts that sum from the
# original, so sub-drums as `StemKind` members would put the drums into the mix twice.
#
# A route of its own rather than a flag on the comparison, for three reasons that all
# point the same way. The pass costs about half the audio's length again *per side*, so
# folding it in would make every comparison several times slower for a feature most runs
# do not want. It is the only honest way to state the cost before it is paid. And it makes
# the "no weights installed" case free: the comparison is untouched, and the drums card
# gets one line saying what is missing.


def _stem_path(stems, kind: StemKind) -> Path | None:
    """One stem out of a separation result or a reference's stem map.

    Two shapes, because the two sides are stored differently: the source keeps a
    `SeparationResult` and the reference keeps a plain dict. Callers should not have to
    know which they are holding.
    """
    if isinstance(stems, dict):
        path = stems.get(kind)
        return Path(path) if path else None
    for stem in getattr(stems, "stems", []) or []:
        if stem.kind is kind:
            return Path(stem.path)
    return None


def _drums_path(stems) -> Path | None:
    """The drums stem out of a separation result or a reference's stem map."""
    return _stem_path(stems, StemKind.DRUMS)


def _per_drum_capability(record, settings: Settings) -> dict:
    """Whether the drums card can offer a second level, and what pressing it would cost.

    Sent with every comparison, including when the answer is no, because "not available,
    and here is the one command that makes it available" is more use than an expander that
    silently is not there. Deliberately **not** gated on `drumsep_enabled`: that flag
    exists to keep an unasked-for second pass out of a master render, and this is a button
    with its price written on it. Gating an explicit, costed action behind an environment
    variable as well would ship a feature nobody can find.
    """
    from app.services.drums import separate as drumsep
    from app.services.mastering import subdrum

    saved = getattr(record, "reference_profile", None)
    cached = (record.drum_stems or {})

    mine = _drums_path(record.separation) if record.separation else None
    theirs = _drums_path(record.reference_stems or {})
    # Stems win when both are there, which is the rule the stem-level comparison already
    # follows: separated stems came from the song the user just chose, and a profile is
    # whatever they saved some other evening. Only when there are no stems does the
    # profile's copy stand in - which is the case it exists for.
    from_profile = theirs is None and bool(
        saved is not None and getattr(saved, "has_drums", False)
    )

    if mine is None:
        return {
            "available": False,
            "reason": "This track has no drums stem to split - separate it first.",
        }
    if theirs is None and not from_profile:
        return {
            "available": False,
            "reason": (
                "Comparing drum by drum needs the reference's drums as well. Separate "
                "the reference, or aim at a saved profile that carries them."
            ),
        }
    if not drumsep.available(settings.models_dir):
        return {
            "available": False,
            "reason": drumsep.why_unavailable(settings.models_dir),
        }

    seconds = getattr(record.audio, "duration_s", 0.0) or 0.0
    sides = 0 if "source" in cached else 1
    if not from_profile and "reference" not in cached:
        sides += 1

    return {
        "available": True,
        "reason": "",
        "drums": list(subdrum.DRUMS),
        # Zero once both sides are cached, which is what makes opening the expander a
        # second time instant.
        "sides": sides,
        "estimate_s": subdrum.estimate_seconds(seconds, sides),
        "reference_kind": "profile" if from_profile else "stems",
        # No audio behind a profile, so there is no "their kick" to play. Said here rather
        # than inferred on the page, same rule the stem rows already follow.
        "reference_audio": not from_profile,
        "cached": sides == 0,
    }


@router.get("")
def list_tracks(registry: TrackRegistry = Depends(get_registry)) -> dict:
    """Every track the server is holding, so the page can offer them again.

    X0R-1423 taught the server to read `storage/` back on boot, and the page still could
    not reach any of it: `state.trackId` is written in exactly one place, the upload
    handler, so a reload left finished separations addressable only by someone who knew
    the id and had curl. The audio survived; the pointer to it did not, which is the
    complaint that card was written about one layer down.

    What each entry carries is what the page needs to decide whether resuming is worth
    anything: which stems exist, whether a reference was split, and whether the per-drum
    pass has run on each side. A row that cannot be resumed usefully should say so before
    the user clicks it, not after.
    """
    out = []
    for record in registry.all():
        drums = record.drum_stems or {}
        out.append(
            {
                "track_id": record.stored.track_id,
                "name": record.stored.original_filename,
                "uploaded_at": record.uploaded_at,
                "adopted": bool(record.attestation.get("adopted")),
                "stems": sorted(s.kind.value for s in record.separation.stems)
                if record.separation
                else [],
                "reference_name": record.reference_name,
                "reference_stems": sorted(
                    k.value if hasattr(k, "value") else str(k) for k in record.reference_stems
                ),
                "drums": {side: sorted(found) for side, found in drums.items()},
            }
        )
    return {"tracks": out}


@router.get("/voices")
def list_voices(settings: Settings = Depends(get_config)) -> dict:
    """What a transcribed part can be played on. X0R-1325.

    Parameters rather than recordings, which is `kit.py`'s argument reused: nothing here is
    anyone else's audio, so there is no licence and a reviewer can read a patch and disagree
    with it. None of them imitates a recorded instrument - that is what keeps this clear of
    the guitar non-goal, which is about synthesis failing to *reach* an amplified guitar.
    """
    from app.services.synth.voice import VOICES

    blurbs = {
        "supersaw": "Wide and obviously electronic — a big lead for a drop.",
        "subbass": "Fundamental-heavy and nearly clean, so it does not fight the kick.",
        "epiano": "Struck rather than blown — bright for a moment, then dark and sustaining.",
        "pluck": "Bright and short, closing fast — what strummed guitars usually become in "
        "a dance version.",
        "pad": "Slow in, wide and held — chords turned into a wash under the drop.",
        "808": "A falling, gritty sub — the bass of most modern dance and hip hop.",
        "reese": "Two detuned saws, low and growling — the moving bass of drum and bass.",
        "stab": "A short, hollow chord hit — piano house and rave offbeats.",
        "bell": "Sparse and ringing — a bell or mallet top line over the drop.",
        "square": "Hollow and bright — chiptune and old-school rave leads.",
    }
    from app.services.synth import instruments
    from app.services.synth.shape import describe, user_sounds

    real = [
        {"id": i.id,
         "label": f"{i.name} (from your reference)" if i.origin == "reference"
         else f"{i.name} (real synth)",
         "about": i.about, "real": True, "kind": i.kind, "origin": i.origin,
         "track_id": i.track_id, "tweak": dict(i.tweak)}
        for i in instruments.installed(settings.sample_dir).values()
    ]
    mine = [
        {"id": name, "label": f"{name} (yours)", "about": "Shaped: " + describe(
            "voice", sound["base"], sound.get("knobs") or {}), "yours": True}
        for name, sound in user_sounds(settings.sample_dir).items() if sound["kind"] == "voice"
    ]
    return {
        "voices": [
            {"id": name, "label": name, "about": blurbs.get(name, ""),
             "partials": len(voice.partials), "stack": voice.stack}
            for name, voice in sorted(VOICES.items())
        ] + mine + real
    }


class SoundRequest(BaseModel):
    """A sound to hear or keep: a built-in voice or kit, and knob positions (-1..1)."""

    kind: str = Field(pattern="^(voice|kit)$")
    base: str
    #: For a voice, {knob: value}. For a kit, {drum: {knob: value}}.
    knobs: dict = Field(default_factory=dict)
    name: str | None = None


def _check_sound(body: SoundRequest) -> None:
    from app.services.drums.kit import KITS
    from app.services.synth.voice import VOICES

    if body.kind == "voice" and body.base not in VOICES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"No voice called {body.base!r} to start from.")
    if body.kind == "kit" and body.base not in KITS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"No kit called {body.base!r} to start from.")


@router.get("/sounds")
def list_sounds(settings: Settings = Depends(get_config)) -> dict:
    """The knobs there are, and the sounds you have shaped. Sprint 8."""
    from app.services.drums.kit import DRUMS, KITS
    from app.services.synth import shape
    from app.services.synth.voice import VOICES

    return {
        "voice_knobs": shape.VOICE_KNOBS,
        "drum_knobs": shape.DRUM_KNOBS,
        "drums": list(DRUMS),
        "voices": sorted(VOICES),
        "kits": list(KITS),
        "yours": [{"name": n, **v, "about": shape.describe(v["kind"], v["base"],
                                                           v.get("knobs") or {})}
                  for n, v in shape.user_sounds(settings.sample_dir).items()],
    }


@router.post("/sounds/preview")
def preview_sound(body: SoundRequest) -> Response:
    """Hear a sound with these knobs, before keeping it - the phrase a voice is previewed on,
    or two bars of a beat for a kit. The exact sound a part will be played on."""
    from app.services.drums.kit import render_voice
    from app.services.synth import library, shape
    from app.services.synth.voice import VOICES

    _check_sound(body)
    rate = 44100
    if body.kind == "voice":
        patch = shape.shape_voice(VOICES[body.base], body.knobs)
        audio = library.preview_voice(body.base, rate, patch)
    else:
        kit = shape.shape_kit(body.base, body.knobs)
        audio = library.preview_kit({d: render_voice(v, rate, seed=i)
                                     for i, (d, v) in enumerate(kit.items())}, rate)
    return Response(library.wav_bytes(audio, rate), media_type="audio/wav")


@router.post("/sounds", status_code=status.HTTP_201_CREATED)
def save_sound(body: SoundRequest, settings: Settings = Depends(get_config)) -> dict:
    """Keep a shaped sound under a name. It is then in every voice or kit list."""
    from app.services.drums.kit import KITS
    from app.services.synth import library, shape
    from app.services.synth.voice import VOICES

    _check_sound(body)
    name = (body.name or "").strip()
    if not shape.SAFE_NAME.match(name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A sound's name can hold letters, numbers, spaces, hyphens and "
                            "underscores, up to 32 of them.")
    taken = (name in VOICES or name in KITS or name in library.user_kits(settings.sample_dir)
             or (settings.sample_dir / f"{name}.wav").exists())
    existing = shape.user_sounds(settings.sample_dir).get(name)
    if taken or (existing and existing["kind"] != body.kind):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{name!r} is already the name of something else. Call it "
                            f"something else.")
    shape.save_sound(settings.sample_dir, name, body.kind, body.base, body.knobs)
    return {"name": name, "kind": body.kind,
            "about": shape.describe(body.kind, body.base, body.knobs)}


@router.delete("/sounds/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sound(name: str, settings: Settings = Depends(get_config)) -> Response:
    from app.services.synth import shape

    if not shape.SAFE_NAME.match(name) or not shape.delete_sound(settings.sample_dir, name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No sound of yours called {name!r}.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class KitRequest(BaseModel):
    """A kit made of the user's own one-shots, by sample name."""

    name: str
    kick: str | None = None
    snare: str | None = None
    hihat: str | None = None


@router.get("/library")
def sound_library(settings: Settings = Depends(get_config)) -> dict:
    """Every kit and voice there is to choose from, and your one-shots sorted into drums.
    Sprint 4, X0R-1343. Previews at `/library/kits/{kit}/preview` and
    `/library/voices/{voice}/preview`. Nothing recorded ships - see `synth/library.py`."""
    import soundfile as sf

    from app.services.drums.kit import KITS
    from app.services.synth import library
    from app.services.synth.voice import VOICES

    mine = library.user_kits(settings.sample_dir)
    shots = []
    if settings.sample_dir.exists():
        for path in sorted(settings.sample_dir.glob("*.wav")):
            try:
                data, rate = sf.read(str(path), dtype="float64", always_2d=True)
            except Exception:  # noqa: BLE001 - an unreadable file is skipped, not fatal
                continue
            if len(data) / rate > 2.5:
                continue  # longer than a one-shot: a phrase or a loop, not a drum hit
            kind, why = library.classify(data, rate)
            shots.append({"name": path.stem, "sounds_like": kind, "why": why})
    blurbs = list_voices(settings)["voices"]
    from app.services.synth.shape import describe as said_shape
    from app.services.synth.shape import user_sounds

    shaped = {n: v for n, v in user_sounds(settings.sample_dir).items() if v["kind"] == "kit"}
    return {
        "kits": [{"name": k, "yours": False, "about": library.KIT_ABOUT.get(k, "")}
                 for k in KITS]
        + [{"name": k, "yours": True, "about": "Shaped: " + said_shape(
            "kit", v["base"], v.get("knobs") or {})} for k, v in shaped.items()]
        + [{"name": k, "yours": True, "about": "Your kit: " + ", ".join(
            f"{d} - {n}" for d, n in v.items())} for k, v in mine.items()],
        "voices": [{"name": v["id"], "about": v["about"], "real": bool(v.get("real"))}
                   for v in blurbs if v["id"] in VOICES or v.get("yours") or v.get("real")],
        "one_shots": shots,
        "note": "Built-in sounds are synthesised here, so nothing anybody else recorded ships. "
        "Your kits are made of samples you uploaded and stay on this machine.",
    }


class TweakIn(BaseModel):
    """Sprint 22: a sampled sound's tuning - every field optional; see `instruments.TWEAKS`."""

    semitones: float | None = None
    cents: float | None = None
    start_ms: float | None = None
    attack_ms: float | None = None
    max_s: float | None = None
    release_ms: float | None = None
    low_cut_hz: float | None = None
    high_cut_hz: float | None = None
    bass_db: float | None = None
    treble_db: float | None = None


def _instrument(name: str, settings: Settings):
    from app.services.synth import instruments

    found = instruments.find(name, settings.sample_dir)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No instrument called {name!r}.")
    return found


@router.post("/instruments/{name}/preview")
def preview_tweak(name: str, body: TweakIn, settings: Settings = Depends(get_config)) -> Response:
    """Hear a sound with these settings before keeping them. Sprint 22."""
    from dataclasses import replace

    from app.services.synth import instruments, library

    found = _instrument(name, settings)
    trial = replace(found, tweak=instruments.clean_tweak(body.model_dump(exclude_none=True)))
    rate = 44100
    return Response(library.wav_bytes(instruments.preview(trial, rate), rate),
                    media_type="audio/wav")


@router.put("/instruments/{name}/tweak")
def save_tweak(name: str, body: TweakIn, settings: Settings = Depends(get_config)) -> dict:
    """Keep a sound's tuning. The recordings are untouched; the settings are applied whenever
    it plays, so a part played on it must be played again to hear them. Sprint 22."""
    from app.services.synth import instruments

    found = _instrument(name, settings)
    tweak = instruments.clean_tweak(body.model_dump(exclude_none=True))
    meta = found.folder / "instrument.json"
    data = json.loads(meta.read_text("utf-8"))
    if tweak:
        data["tweak"] = tweak
    else:
        data.pop("tweak", None)
    meta.write_text(json.dumps(data, indent=2), "utf-8")
    return {"name": name, "tweak": tweak,
            "said": "Kept. Play the parts on it again to hear it in the version."
            if tweak else "Back to the sound as it was sampled."}


@router.get("/library/kits/{kit}/preview")
def preview_kit(kit: str, settings: Settings = Depends(get_config)) -> Response:
    """Two bars of the same plain beat on this kit, so kits are compared like for like."""
    from app.services.synth import library

    if not library.exists(kit, settings.sample_dir):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No kit called {kit!r}.")
    rate = 44100
    audio = library.preview_kit(library.sounds(kit, rate, settings.sample_dir), rate)
    return Response(library.wav_bytes(audio, rate), media_type="audio/wav")


@router.get("/library/voices/{voice}/preview")
def preview_voice(voice: str, settings: Settings = Depends(get_config)) -> Response:
    """A short phrase on this voice, in its own register."""
    from app.services.synth import instruments, library
    from app.services.synth.shape import user_sounds, voice_named

    real = instruments.find(voice, settings.sample_dir)
    if real is not None:
        rate = 44100
        return Response(library.wav_bytes(instruments.preview(real, rate), rate),
                        media_type="audio/wav")
    patch = voice_named(voice, settings.sample_dir)
    if patch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No voice called {voice!r}.")
    base = user_sounds(settings.sample_dir).get(voice, {}).get("base", voice)
    rate = 44100
    return Response(library.wav_bytes(library.preview_voice(base, rate, patch), rate),
                    media_type="audio/wav")


@router.post("/library/kits", status_code=status.HTTP_201_CREATED)
def save_kit(body: KitRequest, settings: Settings = Depends(get_config)) -> dict:
    """Save a kit made of your own one-shots. Any drum left empty plays the edm kit's."""
    from app.services.drums.kit import KITS
    from app.services.synth import library

    if not library.SAFE_NAME.match(body.name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A kit name can hold letters, numbers, spaces, hyphens and "
                            "underscores, up to 32 of them.")
    if body.name in KITS:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{body.name!r} is a built-in kit. Call yours something else.")
    drums = {d: getattr(body, d) for d in ("kick", "snare", "hihat") if getattr(body, d)}
    if not drums:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose at least one sample.")
    for drum, sample in drums.items():
        if not _sample_path(settings, sample).exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                f"No sample called {sample!r} for the {drum}.")
    library.save_kit(settings.sample_dir, body.name, drums)
    return {"name": body.name, "drums": drums}


@router.delete("/library/kits/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kit(name: str, settings: Settings = Depends(get_config)) -> Response:
    from app.services.synth import library

    if not library.SAFE_NAME.match(name) or not library.delete_kit(settings.sample_dir, name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No kit of yours called {name!r}.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


#: What a sample may be named once it is on disk. A name from a form becomes a filename,
#: and a filename from a form is a path traversal waiting to happen.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9 _-]{1,48}$")


def _sample_root(settings: Settings, name: str, detected: float | None) -> float | None:
    """The root note for a sample: the user's choice if they made one, else the detector's.

    A sidecar JSON beside the wav, which is the same answer `adopt.py` reached for tracks -
    the directory layout is the record, and one more file beats one more database. X0R-1330.
    """
    side = settings.sample_dir / f"{name}.json"
    if side.exists():
        try:
            saved = json.loads(side.read_text(encoding="utf-8")).get("root_midi")
            if saved is not None:
                return float(saved)
        except Exception:
            log.info("unreadable sidecar for sample %s", name, exc_info=True)
    return detected


def _sample_path(settings: Settings, name: str) -> Path:
    if not _SAFE_NAME.match(name):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A sample name can hold letters, numbers, spaces, hyphens and underscores.",
        )
    return settings.sample_dir / f"{name}.wav"


@router.get("/samples")
def list_samples(settings: Settings = Depends(get_config)) -> dict:
    """Samples the user has uploaded to play parts on. X0R-1326."""
    import soundfile as sf

    from app.services.synth.samples import detect_root, note_name, reach

    out = []
    directory = settings.sample_dir
    if directory.is_dir():
        for path in sorted(directory.glob("*.wav")):
            try:
                info = sf.info(str(path))
                # Two seconds is plenty to find a fundamental and keeps a long sample
                # out of memory on a listing that runs on every page load.
                data, rate = sf.read(
                    str(path), dtype="float32", always_2d=True, frames=info.samplerate * 2
                )
                root = _sample_root(settings, path.stem, detect_root(data, rate))
            except Exception:
                log.info("could not read sample %s", path.name, exc_info=True)
                continue
            out.append(
                {
                    "name": path.stem,
                    "duration_s": round(info.duration, 2),
                    "sample_rate": info.samplerate,
                    "root_midi": round(root, 1) if root is not None else None,
                    "root_name": note_name(root) if root is not None else None,
                    # What the picker needs to decide for the user: a sample with no clear
                    # pitch is triggered, not transposed, and saying so beats a dropdown
                    # that silently does one of them.
                    "pitched": root is not None,
                    # Per stem, because the same sample reaches most of a guitar part and
                    # little of a bass one. A forecast from where that instrument usually
                    # sits, not a measurement of this user's part - the wording says so.
                    "reach": {
                        stem: reach(root, stem)[2]
                        for stem in ("bass", "guitar", "piano", "vocals", "other")
                    }
                    if root is not None
                    else {},
                }
            )
    return {"samples": out}


@router.post("/samples", status_code=status.HTTP_201_CREATED)
async def upload_sample(
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()],
    owns_or_licensed: Annotated[bool, Form()] = False,
    settings: Settings = Depends(get_config),
) -> dict:
    """Take a sample to play a part on. X0R-1326.

    **Behind the same rights attestation a reference track needs**, and for the same reason.
    `kit.py` refuses to ship recorded hits because shipping a library means shipping
    someone's audio with no way to check where it came from; a user's own upload is the one
    case that was never in question, and the attestation is what makes it that case rather
    than an assumption.

    Stored outside `storage_dir` so the retention sweep cannot take it - a sample is audio
    somebody chose and may have paid for, and losing it a day later because it sat beside a
    track would be a bad surprise - and outside the repository, where `.gitignore` keeps it.
    """
    import soundfile as sf

    from app.services.synth.samples import MAX_SAMPLE_S

    if settings.require_rights_attestation and not owns_or_licensed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Confirm you own or are licensed to use this sample.",
        )

    path = _sample_path(settings, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(".staged")
    try:
        staged.write_bytes(await file.read())
        info = sf.info(str(staged))
        if info.duration > MAX_SAMPLE_S:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"That is {info.duration:.0f} seconds long. A sample over {MAX_SAMPLE_S:.0f} "
                f"is a loop or a phrase rather than an instrument, and triggering it once a "
                f"note makes a wall rather than a part.",
            )
        data, rate = sf.read(str(staged), dtype="float32", always_2d=True)
        sf.write(str(path), data, rate)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Could not read that audio: {exc}"
        ) from exc
    finally:
        staged.unlink(missing_ok=True)

    from app.services.synth.samples import detect_root

    root = detect_root(data, rate)
    return {
        "name": name,
        "duration_s": round(info.duration, 2),
        "root_midi": round(root, 1) if root is not None else None,
        "pitched": root is not None,
    }


@router.patch("/samples/{name}")
def set_sample_root(
    name: str,
    root_midi: float | None = Query(None, ge=0, le=127),
    settings: Settings = Depends(get_config),
) -> dict:
    """Tell a sample what note it is. X0R-1330.

    The control every sampler has had for forty years, and this one needed it as soon as it
    worked: a one-shot recorded at A3 chosen to play a bass part had 44 of 60 notes skipped,
    because seventeen semitones is past the cap. The detector is usually right about the
    pitch and cannot know which octave the user wants it to play in.

    `root_midi` of null clears the override and goes back to what was detected.
    """
    path = _sample_path(settings, name)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No sample called {name!r}.")

    side = settings.sample_dir / f"{name}.json"
    if root_midi is None:
        side.unlink(missing_ok=True)
    else:
        side.write_text(json.dumps({"root_midi": root_midi}), encoding="utf-8")
    return {"name": name, "root_midi": root_midi}


@router.delete("/samples/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sample(name: str, settings: Settings = Depends(get_config)) -> Response:
    path = _sample_path(settings, name)
    if path.exists():
        path.unlink()
    # The override goes with it. A sidecar outliving its sample would silently re-apply to
    # a different sample uploaded under the same name later.
    (settings.sample_dir / f"{name}.json").unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


#: One lock per track for the slow reads, so two requests that arrive together - the page
#: prefetching while it loads - wait for one answer instead of working it out twice.
_READING: dict[str, threading.Lock] = {}
_READING_GUARD = threading.Lock()


def _reading(track_id: str) -> threading.Lock:
    with _READING_GUARD:
        return _READING.setdefault(track_id, threading.Lock())


#: A target within this fraction of the song's own tempo *is* the song's own (Sprint 15).
#: The page shows the tempo to a tenth of a BPM, so a style that keeps the song at its speed
#: asked for 169.0 against a measured 169.04 - a 0.02% stretch of every part, paid for in
#: time and quality, and an added beat drifting 57 ms against the song by its end.
SAME_TEMPO = 0.002


def _as_asked(track_id: str, registry: TrackRegistry, target: float | None) -> float | None:
    """`target`, snapped to the song's exact tempo when it is within `SAME_TEMPO` of it - so
    the move is exactly 1 and nothing is stretched, while the version keeps the name asked
    for."""
    if not target:
        return target
    source = _tempo_of(track_id, registry)
    if source and abs(source / target - 1.0) <= SAME_TEMPO:
        return source
    return target


def _transcribe(settings: Settings, kind: StemKind, path: Path):
    """A stem's notes, transcribed once and kept beside it. Sprint 14.

    Every change of sound on a part used to transcribe the stem again - the same notes,
    tens of seconds each time on a full song - so trying three synths on one part paid for
    three transcriptions. The notes are kept next to the stem in the track's storage, keyed
    on the stem file and the transcriber, so a new separation or a different transcriber
    reads them afresh."""
    from app.domain.notes import NoteEvent, Transcription
    from app.services.factory import make_transcriber

    transcriber = make_transcriber(settings, kind)
    info = path.stat()
    key = [path.name, info.st_size, info.st_mtime_ns, type(transcriber).__name__, 1]
    kept = path.with_name(f"{path.stem}.notes.json")
    with _reading(str(path)):
        try:
            data = json.loads(kept.read_text("utf-8"))
            if data.get("key") == key:
                return Transcription(
                    stem=kind, backend=data["backend"], tempo_bpm=data["tempo_bpm"],
                    notes=[NoteEvent(s, e, p, v) for s, e, p, v in data["notes"]])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        found = transcriber.transcribe(path, kind)
        try:
            kept.write_text(json.dumps({
                "key": key, "backend": found.backend, "tempo_bpm": found.tempo_bpm,
                "notes": [[n.start_s, n.end_s, n.pitch, n.velocity] for n in found.notes],
            }), "utf-8")
        except OSError:
            log.info("could not keep the notes of %s", path, exc_info=True)
        return found


def _tempo_of(track_id: str, registry: TrackRegistry) -> float:
    with _reading(track_id):
        return _tempo_unlocked(track_id, registry)


def _tempo_unlocked(track_id: str, registry: TrackRegistry) -> float:
    """The track's tempo, reading it now if it has not been read yet.

    One place, called by everything that needs a tempo. Found by restarting the API: an
    adopted track - X0R-1423 - comes back with no timing on it, because reading one means
    opening the audio and adoption deliberately does not. Before this, re-voicing at a tempo
    and bouncing a version both refused with "no tempo has been read" until something
    happened to call `/tempo` first, which is an ordering rule a user cannot see.
    """
    record = registry.require(track_id)
    if record.timing is None:
        # Read before, and kept beside the track: reading it is ~9 s on a four-minute song,
        # and the registry forgets it on every restart. Sprint 11.
        kept = _load_timing(record)
        if kept is not None:
            registry.set_timing(track_id, kept)
            record = registry.require(track_id)
    if record.timing is None:
        from dataclasses import replace

        from app.services.analysis.timing import TimingAnalyser

        try:
            timing = TimingAnalyser().analyse(record.stored.path)
            # Then lock it to the kick drum when there is one. The whole-mix estimate read
            # a 170 BPM song as 168.5, and re-played parts follow the real performance - so
            # a part scaled by the estimate lands at 129.1 when 128 was asked for, and an
            # added four-on-the-floor at exactly 128 slides away from it across the song.
            # `find_beats` searches near the estimate for the comb that lands on the most
            # kick energy and measured that song at 170.01, first beat 3 ms.
            drums = _stem_path(record.separation, StemKind.DRUMS) if record.separation else None
            if drums is not None and Path(drums).exists():
                import soundfile as sf

                from app.services.synth.retempo import find_beats

                audio, rate = sf.read(str(drums), dtype="float64", always_2d=True)
                bpm, first = find_beats(audio, rate, timing.tempo_bpm)
                if bpm > 0:
                    timing = replace(timing, tempo_bpm=bpm, first_beat_s=first)
            registry.set_timing(track_id, timing)
            _save_timing(record, timing)
            record = registry.require(track_id)
        except Exception:
            log.info("could not read a tempo for %s", track_id, exc_info=True)
    return getattr(record.timing, "tempo_bpm", 0.0) or 0.0


def _timing_path(record) -> Path:
    return Path(record.stored.path).parent / "timing.json"


def _save_timing(record, timing) -> None:
    from dataclasses import asdict

    try:
        _timing_path(record).write_text(json.dumps(asdict(timing)), "utf-8")
    except Exception:  # noqa: BLE001 - a cache that cannot be written is only slower
        log.info("could not keep the timing for %s", record.stored.path, exc_info=True)


def _load_timing(record):
    from app.domain.timing import TimingEstimate

    path = _timing_path(record)
    if not path.exists():
        return None
    try:
        return TimingEstimate(**json.loads(path.read_text("utf-8")))
    except Exception:  # noqa: BLE001 - a damaged cache is read again, not trusted
        return None


def _song_shape(record, bpm: float) -> dict:
    """The song's sections and its best drops, worked out together from one read of the
    audio and kept beside the track, keyed by the grid they were read on. Sprint 11.

    Each was its own request, and each decoded the whole original and measured every bar
    again on every visit to pr0ducer - 2.6 s apiece on a four-minute song. Now once per
    track and tempo; a corrected tempo is a different key, so it is read again.
    """
    first = getattr(record.timing, "first_beat_s", 0.0) or 0.0
    # The third element versions the cache: v2 added the song's length and bar loudness.
    key = [round(bpm, 4), round(first, 5), 2]
    path = Path(record.stored.path).parent / "shape.json"
    with _reading(f"shape:{record.stored.path}"):
        return _shape_unlocked(record, bpm, first, key, path)


def _shape_unlocked(record, bpm: float, first: float, key: list, path: Path) -> dict:
    from dataclasses import asdict

    import soundfile as sf

    from app.services.synth import drop
    from app.services.synth.arrange import Section, find_sections
    from app.services.synth.retempo import beat_grid

    if path.exists():
        try:
            data = json.loads(path.read_text("utf-8"))
            if data.get("key") == key:
                data["sections"] = [Section(**x) for x in data["sections"]]
                return data
        except Exception:  # noqa: BLE001 - a damaged cache is read again
            pass
    audio, rate = sf.read(str(record.stored.path), dtype="float64", always_2d=True)
    beats = beat_grid(first, bpm, len(audio) / rate)
    sections = find_sections(audio, rate, beats)
    drops = drop.suggest_drops(audio, rate, beats)
    from app.services.synth.arrange import bar_levels

    data = {
        "key": key,
        "duration_s": len(audio) / rate,
        "bar_db": bar_levels(audio, rate, beats),
        # Full precision, not to_dict's: arrangements cut on these exact bar times, and a
        # start rounded to the millisecond can drop the beat the cut lands on.
        "sections": [asdict(x) for x in sections],
        "bars": int(drop.bar_times(beats).size),
        "drops": [{"bar": d.bar, "at_s": round(d.at_s, 2), "strength": d.strength}
                  for d in drops],
    }
    try:
        path.write_text(json.dumps(data), "utf-8")
    except Exception:  # noqa: BLE001 - a cache that cannot be written is only slower
        log.info("could not keep the song's shape for %s", record.stored.path, exc_info=True)
    data["sections"] = sections
    return data


@router.get("/{track_id}/tempo")
def track_tempo(
    track_id: str,
    settings: Settings = Depends(get_config),
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """What tempo this track is at, so a target can be set against something. Sprint 3.

    Cached on the record once measured: it is read every time the pr0ducer page opens and
    an onset-envelope pass on a four-minute song is not a thing to repeat per page load.
    """
    try:
        bpm = _tempo_of(track_id, registry)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    record = registry.require(track_id)
    return {
        "tempo_bpm": round(bpm, 1),
        "confidence": round(getattr(record.timing, "confidence", 0.0) or 0.0, 3),
        # Named out loud, because "128" means something to a person and "the target" does
        # not. These are where the styles actually sit, not a claim about any record.
        "suggestions": [
            {"label": "house / EDM", "bpm": 128},
            {"label": "techno", "bpm": 140},
            {"label": "drum and bass", "bpm": 174},
            {"label": "hip hop", "bpm": 90},
            {"label": "pop", "bpm": 120},
        ],
    }


@router.put("/{track_id}/tempo")
def correct_tempo(
    track_id: str,
    bpm: float = Query(..., gt=20, lt=300),
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """Say what tempo the track is really at. Sprint 3.

    The detector is usually right and cannot always be. X0R-1319 proved that a tempo read
    from onsets alone cannot always tell 170 from 85 or from 113 - every hit on one grid is
    also on the other - and it measured a live 3:2 disagreement between two estimators on one
    file. Building this feature turned up another: raw librosa read a 170 BPM pop punk demo as
    112 while this application's own analyser read 168.5. Either way, a wrong source tempo
    turns "make it EDM" into a speed-up instead of a slow-down.

    So the person who can hear the song gets the last word. Only the tempo is replaced; the
    first beat and the metre stay as measured.
    """
    try:
        _tempo_of(track_id, registry)
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    from dataclasses import replace

    from app.domain.timing import TimingEstimate

    timing = record.timing or TimingEstimate(tempo_bpm=bpm)
    # Full confidence, because a person said so - and the figure means "the tempo is known",
    # which is now true in a way no estimator could make it.
    registry.set_timing(track_id, replace(timing, tempo_bpm=float(bpm), confidence=1.0))
    _save_timing(registry.require(track_id), registry.require(track_id).timing)
    return {"tempo_bpm": round(float(bpm), 1), "set_by": "you"}


# --- Sprint 6: a part's notes, to edit ------------------------------------------------------


def _notes_file(out_dir: Path, stem: str, which: str) -> Path:
    return out_dir / f"{stem}.{which}.json"


def _read_notes(path: Path) -> list | None:
    from app.services.synth.edit import BeatNote

    if not path.exists():
        return None
    try:
        return [BeatNote.from_dict(n) for n in json.loads(path.read_text("utf-8"))["notes"]]
    except Exception:  # noqa: BLE001 - a damaged file is treated as absent, and logged
        log.info("unreadable notes file %s", path, exc_info=True)
        return None


def _edited_notes(out_dir: Path, stem: str) -> list | None:
    """The part's notes as the user edited them, or None for a part played as transcribed."""
    return _read_notes(_notes_file(out_dir, stem, "edited"))


def _save_played(out_dir: Path, stem: str, notes: list) -> None:
    """The part's notes as played, in beats - what the editor opens and resets to."""
    out_dir.mkdir(parents=True, exist_ok=True)
    _notes_file(out_dir, stem, "played").write_text(
        json.dumps({"notes": [n.to_dict() for n in notes]}), "utf-8")


class NoteIn(BaseModel):
    beat: float
    length: float = Field(gt=0)
    pitch: int = Field(ge=0, le=127)
    velocity: int = Field(100, ge=1, le=127)


class NotesRequest(BaseModel):
    notes: list[NoteIn] = Field(max_length=20000)


class QuantizeRequest(NotesRequest):
    #: A grid by name: "1/4", "1/8", "1/16", "1/8 triplet", "1/16 triplet".
    grid: str = "1/16"
    #: How far towards the grid, 0..1. 1 is hard quantise; 0.5 halves every distance.
    strength: float = Field(1.0, ge=0.0, le=1.0)
    #: Snap where notes end as well as where they start.
    ends: bool = False
    #: Then swing the off-sixteenths by this much, 0..1 of a triplet. Null leaves them.
    swing: float | None = Field(None, ge=0.0, le=1.0)
    #: Then move every note this many semitones.
    transpose: int = Field(0, ge=-48, le=48)
    #: Sprint 18: then hold every note this far towards the next one, 0..1.
    legato: float = Field(0.0, ge=0.0, le=1.0)
    #: Sprint 19: first take out the questionable notes - ghosts, and lone leaps in a line.
    trim: bool = False
    #: Sprint 19: then keep only the top note of each chord, as one line in G3..B4.
    top_line: bool = False
    #: Sprint 19: then re-cut the chords into short complextro stabs.
    stabs: bool = False
    #: Sprint 22: last, run every note exactly into the next one (gaps closed, overlaps cut).
    fill: bool = False


@router.get("/{track_id}/parts/{stem}/notes")
def part_notes(
    track_id: str,
    stem: StemKind,
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """A played part's notes in beats, for the editor: the edits if there are any, else as
    played. Drums come as General MIDI kick 36, snare 38, hat 42. Sprint 6."""
    from app.services.synth.edit import GRIDS

    try:
        bpm = _tempo_of(track_id, registry)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    out_dir = storage.exports_dir(track_id)
    played = _read_notes(_notes_file(out_dir, stem.value, "played"))
    if played is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Play the {stem.value} on something first - its notes are read "
                            f"when it is played, and that is what you edit.")
    edited = _edited_notes(out_dir, stem.value)
    notes = edited if edited is not None else played
    end = max((n.beat + n.length for n in notes), default=0.0)
    return {
        "stem": stem.value,
        "drums": stem is StemKind.DRUMS,
        "notes": [n.to_dict() for n in notes],
        "edited": edited is not None,
        "played_count": len(played),
        "bars": int(end // 4) + 1,
        "tempo_bpm": round(bpm, 2),
        "grids": list(GRIDS),
    }


@router.put("/{track_id}/parts/{stem}/notes")
def save_part_notes(
    track_id: str,
    stem: StemKind,
    body: NotesRequest,
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """Keep your edits to a part. Play it again to hear them. Saving notes identical to the
    played ones clears the edit, so "as you edited it" is only ever said when it is true."""
    try:
        registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    from app.services.synth.edit import BeatNote, differs

    out_dir = storage.exports_dir(track_id)
    played = _read_notes(_notes_file(out_dir, stem.value, "played"))
    if played is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Play the {stem.value} on something first.")
    notes = [BeatNote.from_dict(n.model_dump()) for n in body.notes]
    path = _notes_file(out_dir, stem.value, "edited")
    if not differs(notes, played):
        path.unlink(missing_ok=True)
        return {"edited": False, "notes": len(notes)}
    path.write_text(json.dumps({"notes": [n.to_dict() for n in notes]}), "utf-8")
    return {"edited": True, "notes": len(notes)}


@router.delete("/{track_id}/parts/{stem}/notes", status_code=status.HTTP_204_NO_CONTENT)
def reset_part_notes(
    track_id: str,
    stem: StemKind,
    storage: TrackStorage = Depends(get_storage),
) -> Response:
    """Back to as played."""
    _notes_file(storage.exports_dir(track_id), stem.value, "edited").unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class FollowRequest(BaseModel):
    #: Then hold every note this far towards the next one, stopping at the bass's changes.
    legato: float = Field(0.0, ge=0.0, le=1.0)
    #: At most this many notes sound together.
    voices: int = Field(4, ge=1, le=8)


@router.post("/{track_id}/parts/{stem}/follow-bass")
def follow_bass_notes(
    track_id: str,
    stem: StemKind,
    body: FollowRequest,
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """A part's notes made to agree with the bass's chords - and, with `legato`, held to the
    next note or chord change. Sprint 18b. Nothing is saved: the editor shows the result and
    the person saves it, so the version says the notes are theirs."""
    from app.services.synth import edit

    try:
        registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if stem in (StemKind.BASS, StemKind.DRUMS):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "The bass is what the other parts follow, and drums have no chords.")
    out_dir = storage.exports_dir(track_id)

    def current(part: str):
        found = _edited_notes(out_dir, part)
        if found is None:
            found = _read_notes(_notes_file(out_dir, part, "played"))
        return found

    bass = current(StemKind.BASS.value)
    notes = current(stem.value)
    if not bass:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Play the bass first, so there are chords to follow.")
    if not notes:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Play the {stem.value} first.")
    scale = edit.scale_of(list(notes) + list(bass))
    followed = edit.follow_bass(notes, bass, body.voices, scale)
    if body.legato:
        followed = edit.legato(followed, body.legato, stops=[b.beat for b in bass])
    kept = {(round(n.beat / 0.05), n.pitch) for n in followed}
    moved = sum(1 for n in notes if (round(n.beat / 0.05), n.pitch) not in kept)
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return {"notes": [n.to_dict() for n in followed],
            "scale": [names[p] for p in scale],
            "said": f"{len(notes)} notes became {len(followed)}, in the scale of "
                    f"{names[scale[0]]} major, every one a note of the bass's chord "
                    f"({moved} moved or merged)."}


@router.post("/notes/quantize")
def quantize_notes(body: QuantizeRequest) -> dict:
    """Quantise, swing and transpose a list of notes - the editor's tools, done here so they
    are the same every time and tested. Nothing is saved."""
    from app.services.synth import edit

    if body.grid not in edit.GRIDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"No grid called {body.grid!r}. Try one of {', '.join(edit.GRIDS)}.")
    notes = [edit.BeatNote.from_dict(n.model_dump()) for n in body.notes]
    if body.trim:
        notes = edit.trim(notes)
    notes = edit.quantize(notes, edit.GRIDS[body.grid], body.strength, body.ends)
    if body.swing is not None:
        notes = edit.groove(notes, body.swing)
    if body.transpose:
        notes = edit.transpose(notes, body.transpose)
    if body.top_line:
        notes = edit.top_line(notes)
    if body.stabs:
        notes = edit.stabs(notes)
    if body.legato:
        notes = edit.legato(notes, body.legato)
    if body.fill:
        notes = edit.fill(notes)
    return {"notes": [n.to_dict() for n in notes]}


@router.post("/{track_id}/revoice", response_model=JobResponse)
def revoice(
    track_id: str,
    stem: StemKind,
    voice: str = Query("supersaw", description="a synth voice, or 'sample' with ?sample="),
    sample: str | None = Query(None, description="an uploaded sample to play it on"),
    pitched: bool | None = Query(None, description="transpose the sample, or trigger it"),
    clean: bool = Query(True, description="merge fragments separation broke apart"),
    target_bpm: float | None = Query(None, gt=0, description="re-play it at this tempo"),
    kit: str = Query("tight", description="which kit, when the stem is drums"),
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    """Transcribe one stem and play its notes on a synthesised voice. X0R-1327.

    **What this is, measured, so the output is read for what it is.** Through demucs and
    basic-pitch on a synthetic chord part, recall is 1.000 and pitch accuracy matches a
    clean DI - the notes are right. Precision is 0.462 before cleaning and 0.727 after,
    because separation breaks held notes into pieces and each piece arrives as its own note.
    `clean` is `coalesce`, and it is on by default here while staying off on the tab path:
    a tab is a transcription of what was played, and this is not.

    Nothing is quantised, re-sequenced or re-tempoed. The notes land where they were played.
    """
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    from app.services.synth import library

    if stem is StemKind.DRUMS and not library.exists(kit, settings.sample_dir):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No kit called {kit!r}.")
    from app.services.synth import instruments
    from app.services.synth.shape import voice_named

    sample_path = None
    patch = None
    # A multisampled real synth (Sprint 12) needs nothing more checked here.
    real = None if sample else instruments.find(voice, settings.sample_dir)
    if real is None and sample:
        sample_path = _sample_path(settings, sample)
        if not sample_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No sample called {sample!r}.")
    elif real is None:
        # A built-in voice, or one you shaped. Sprint 8.
        patch = voice_named(voice, settings.sample_dir)
        if patch is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No voice called {voice!r}.")

    path = _stem_path(record.separation, stem)
    if path is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"No {stem.value} stem — separate the track first."
        )

    # Sprint 3: a tempo change is arithmetic on a list of times followed by a fresh render,
    # so it has to be settled before the job starts - a move this refuses should say so now
    # rather than after a transcription.
    move = None
    target_bpm = _as_asked(track_id, registry, target_bpm)
    if target_bpm:
        from app.services.synth.retempo import MAX_RATIO, MIN_RATIO, plan

        source_bpm = _tempo_of(track_id, registry)
        if not source_bpm:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This track's tempo could not be read, so there is nothing to move it from.",
            )
        move = plan(source_bpm, target_bpm, 0.0)
        if move is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{source_bpm:.0f} to {target_bpm:.0f} BPM is more than this can move a "
                f"part. It scales a performance between {MIN_RATIO:g}x and {MAX_RATIO:g}x "
                f"of its own tempo; past that the playing stops being the same playing.",
            )

    out_dir = storage.exports_dir(track_id)
    # Sprint 6: the grid a part's notes are kept on, so they can be edited and survive a
    # change of tempo. Without a tempo there is no grid, and the part plays as before.
    grid_bpm = _tempo_of(track_id, registry)
    grid_first = getattr(registry.require(track_id).timing, "first_beat_s", 0.0) or 0.0
    edited = _edited_notes(out_dir, stem.value) if grid_bpm else None

    def work(handle: JobHandle) -> dict:
        import numpy as np
        import soundfile as sf

        from app.domain.notes import coalesce
        from app.services.synth import edit
        from app.services.synth.voice import render_notes

        probe_in = sf.info(str(path))
        stretched = probe_in.duration * (move.scale if move else 1.0)

        # Drums are not a pitched part and do not go through a transcriber. They are
        # strokes, and `kit.py` already synthesises at whatever positions it is handed - so
        # at a new tempo they are re-struck rather than re-pitched, and nothing is stretched.
        if stem is StemKind.DRUMS:
            from app.services.synth.retempo import move_hits, rebuild_drums

            handle.update(JobState.RUNNING, 0.2, "finding every stroke in the drums")
            samples, rate = sf.read(str(path), dtype="float64", always_2d=True)
            if edited is not None:
                # Your strokes, as you edited them, at this tempo. Sprint 6.
                hits = edit.notes_to_hits(edit.to_seconds(edited, grid_first, grid_bpm))
            else:
                # Placed where each stroke really begins (X0R-412) and with every label
                # checked against the audio (Sprint 4's `read_hits`). Found while building
                # the stroke editor: the bare detector found 3 of the pop punk demo's 16
                # snares - a hat struck with the snare hid it - and 13 of 24 kicks, so the
                # re-played drummer had been missing most of the backbeat. Checked: 16 and 21.
                from app.services.synth.groove import read_hits

                hits = read_hits(samples, rate)
                if grid_bpm:
                    _save_played(out_dir, "drums", edit.to_beats(
                        edit.hits_to_notes(hits), grid_first, grid_bpm))
            if not hits:
                return {"notes": 0, "why": "no drum strokes came back from that stem."}

            handle.update(
                JobState.RUNNING, 0.7, f"re-playing {len(hits)} strokes on the {kit} kit"
            )
            from app.services.synth import library

            audio = rebuild_drums(
                move_hits(hits, move.scale if move else 1.0), rate, stretched, kit=kit,
                sounds=library.sounds(kit, rate, settings.sample_dir),
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            wav = out_dir / f"drums.{kit}.wav"
            sf.write(str(wav), audio, rate)
            return {
                "stem": "drums",
                "voice": kit,
                "notes": len(hits),
                "notes_before_cleaning": len(hits),
                "fragments_merged": 0,
                "out_of_range": 0,
                "url": f"/api/v1/tracks/{track_id}/revoiced/{wav.name}",
                "backend": "kit",
                "moved": move.describe() if move else "",
                "duration_s": round(stretched, 1),
                "edited": edited is not None,
            }

        if edited is not None:
            # Your notes, as you edited them - no transcription, no cleaning. Sprint 6.
            found = merged = edit.to_seconds(edited, grid_first, grid_bpm)
            backend = "your edits"
        else:
            handle.update(JobState.RUNNING, 0.1, f"reading the notes out of the {stem.value}")
            transcription = _transcribe(settings, stem, Path(path))
            found = list(transcription.notes)
            merged = coalesce(found) if clean else found
            backend = transcription.backend
            if grid_bpm and merged:
                _save_played(out_dir, stem.value, edit.to_beats(merged, grid_first, grid_bpm))

        if not merged:
            return {"notes": 0, "why": "nothing pitched came back from that stem."}

        probe = probe_in
        label = sample or voice
        handle.update(JobState.RUNNING, 0.7, f"playing {len(merged)} notes on the {label}")

        out_of_range = 0
        octaves = 0
        if move:
            from app.services.synth.retempo import move_notes

            merged = move_notes(merged, move.scale)

        if sample_path is not None:
            from app.services.synth.samples import Sample, detect_root, render_with_sample

            raw, rate = sf.read(str(sample_path), dtype="float64", always_2d=True)
            if rate != probe.samplerate:
                # Resampling here would move the sample's pitch, which is the one failure
                # that gets blamed on the transcription. Said rather than silently fixed.
                return {
                    "notes": 0,
                    "why": f"That sample is {rate} Hz and this track is "
                    f"{probe.samplerate} Hz. Re-save it at the track's rate.",
                }
            root = _sample_root(settings, sample, detect_root(raw, rate))
            held = Sample(sample, sample_path, rate, len(raw) / rate, root)
            audio, out_of_range = render_with_sample(
                merged, held, raw, rate, stretched, pitched
            )
        else:
            if real is not None:
                audio, out_of_range, octaves = instruments.render(
                    merged, real, probe.samplerate, stretched)
            else:
                audio = render_notes(merged, probe.samplerate, patch, duration_s=stretched)

        out_dir.mkdir(parents=True, exist_ok=True)
        wav = out_dir / f"{stem.value}.{label}.wav"
        sf.write(str(wav), np.stack([audio, audio], axis=1), probe.samplerate)

        return {
            "stem": stem.value,
            "voice": label,
            # Notes the sample could not reach without being stretched past the point where
            # it stops sounding like itself. Reported rather than hidden: a part that
            # quietly thinned out is worse than one that says it could not get there.
            "out_of_range": out_of_range,
            "notes": len(merged),
            "notes_before_cleaning": len(found),
            # Said plainly, because it is the number that decides whether what comes out is
            # worth keeping, and nobody can hear a precision figure.
            "fragments_merged": len(found) - len(merged),
            "url": f"/api/v1/tracks/{track_id}/revoiced/{wav.name}",
            "backend": backend,
            "moved": move.describe() if move else "",
            "duration_s": round(stretched, 1),
            "edited": edited is not None,
            # Sprint 12: a part moved by whole octaves to sit in a real synth's range.
            "octaves": octaves,
        }

    return to_response(jobs.submit("revoice", track_id, work))


@router.get("/{track_id}/revoiced/{name}")
def revoiced_audio(
    track_id: str,
    name: str,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
) -> FileResponse:
    """Serve one re-voiced render back for preview.

    The name is rebuilt from a stem and a voice rather than taken as given: a path from a
    URL that reaches `exports_dir` is a directory traversal, and this directory also holds
    the user's masters.
    """
    from app.services.synth.voice import VOICES

    stem, _, rest = name.partition(".")
    voice, _, extension = rest.partition(".")
    # A render is named after a built-in voice, an uploaded sample, or - for drums, which
    # are struck rather than pitched - a kit. Each of those is a closed list, which is the
    # point: the name is rebuilt from known parts rather than taken from the URL.
    from app.services.drums.kit import KITS
    from app.services.synth import library
    from app.services.synth.instruments import find as real_synth
    from app.services.synth.shape import voice_named

    known = (
        voice in VOICES
        or voice in KITS
        or (settings.sample_dir / f"{voice}.wav").exists()
        or library.exists(voice, settings.sample_dir)
        or voice_named(voice, settings.sample_dir) is not None
        or real_synth(voice, settings.sample_dir) is not None
    )
    if extension != "wav" or not known or stem not in {k.value for k in StemKind}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such render.")

    path = storage.exports_dir(track_id) / f"{stem}.{voice}.wav"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not rendered yet.")
    return FileResponse(path, media_type="audio/wav", filename=path.name)


class ArrangeItem(BaseModel):
    """One block of an arrangement: a section of the song, by id from `/sections`."""

    section: str
    #: Stems silent in this block, and "beat" for the added beat - a breakdown is
    #: ["drums", "beat"], an intro of just the beat is every stem.
    mute: list[str] = Field(default_factory=list)
    #: Build up into the start of this block and drop there.
    drop: bool = False


class ChopIn(BaseModel):
    """Sprint 19: a stutter, gate or stop at a place in the version."""

    bar: int = Field(ge=1)
    beat: float = Field(0.0, ge=0.0, lt=4.0)
    beats: float = Field(1.0, ge=0.25, le=8.0)
    kind: Literal["stutter", "gate", "stop", "rise", "tape"] = "stutter"
    #: Sprint 20: the parts it is cut into - stems and "beat" - or empty for the whole track.
    parts: list[str] = Field(default_factory=list, max_length=8)


class CustomBeat(BaseModel):
    """A beat written on the step grid. Each row is sixteen of x (plays), o (soft), . (rest)."""

    based_on: str | None = None
    rows: dict[str, str] = Field(default_factory=dict)


class BounceRequest(BaseModel):
    #: Null keeps the track's own tempo, which makes this a plain mixdown of the version.
    target_bpm: float | None = None
    #: Which parts were re-played and on what, as {stem: voice-or-kit-or-sample}.
    parts: dict[str, str] = Field(default_factory=dict)
    #: Duck every non-drum part on every beat - the sound a listener knows a dance record by.
    pump: bool = False
    #: Lay a kick on every beat and hats between, *alongside* the drummer rather than instead
    #: of him. Added, not moved: re-sequencing his hits is still out.
    four_on_the_floor: bool = False
    #: Build up into this bar and drop there, counted from 1. X0R-1335. Null for none.
    drop_bar: int | None = Field(None, ge=1)
    #: A beat to add alongside the band: a built-in name from `/grooves`, or "reference" for
    #: the one read off the reference by `/reference/recipe`. Sprint 4. Overrides
    #: `four_on_the_floor` when set.
    beat: str | None = None
    #: Which kit plays the added beat.
    beat_kit: str = "edm"
    #: Swing on the added beat's off-sixteenths, 0 straight to 1 full triplet. Null keeps the
    #: beat's own feel - which for a reference's beat is the swing it was played with.
    swing: float | None = Field(None, ge=0.0, le=1.0)
    #: How deep the pump goes, in dB, when `pump` is on. Null is the house default (8 dB);
    #: a recipe sets it to the depth measured on the reference.
    pump_db: float | None = Field(None, ge=0.0, le=12.0)
    #: Stems to leave out of this version entirely - a mute, the user's choice.
    leave_out: list[str] = Field(default_factory=list)
    #: How much the added beat is nudged off the grid and varied in level, 0..1. A built-in
    #: beat is programmed dead straight; this is what makes it sound played.
    humanize: float = Field(0.0, ge=0.0, le=1.0)
    #: Sprint 6: a beat you wrote on the step grid - {"based_on": a beat name or "reference"
    #: or null, "rows": {"kick": "x...x...", ...}}. Takes over from `beat` when set.
    custom_beat: CustomBeat | None = None
    #: Sprint 5: the song's sections in any order - repeated, left out, with parts muted and
    #: drops placed per block. Null plays the song as it was written.
    arrangement: list[ArrangeItem] | None = Field(None, max_length=64)
    #: Sprint 16: how hard to drive each part into distortion, 0 to 1, by stem.
    grit: dict[str, float] = Field(default_factory=dict)
    #: Sprint 17: how wide to spread each part in stereo, 0 to 1, by stem - mono-safe.
    width: dict[str, float] = Field(default_factory=dict)
    #: Sprint 18b: a pump depth per part in dB, in place of `pump_db` for those parts.
    pump_parts: dict[str, float] = Field(default_factory=dict)
    #: Sprint 18b: keep pumping on the beat where the arrangement mutes the beat.
    ghost_pump: bool = False
    #: Sprint 19: stutters, gates and stops cut into the version, by bar.
    chops: list[ChopIn] = Field(default_factory=list, max_length=64)

    @field_validator("pump_parts")
    @classmethod
    def _pumps_in_range(cls, value: dict[str, float]) -> dict[str, float]:
        for stem, depth in value.items():
            if not 0.0 <= depth <= 24.0:
                raise ValueError(f"the pump on {stem} must be 0 to 24 dB")
        return value

    @field_validator("grit", "width")
    @classmethod
    def _amounts_in_range(cls, value: dict[str, float]) -> dict[str, float]:
        for stem, amount in value.items():
            if not 0.0 <= amount <= 1.0:
                raise ValueError(f"{stem} must be between 0 and 1")
        return value


def _marks_path(record) -> Path:
    return Path(record.stored.path).parent / "sections.user.json"


def _user_marks(record) -> list[tuple[int, str]] | None:
    """The sections the person marked - [(bar, name)] - or None if they have not."""
    path = _marks_path(record)
    if not path.exists():
        return None
    try:
        return [(int(m["bar"]), str(m["label"])) for m in json.loads(path.read_text("utf-8"))]
    except Exception:  # noqa: BLE001 - a damaged file falls back to the detected sections
        log.info("unreadable section marks for %s", record.stored.path, exc_info=True)
        return None


def _sections_of(record, bpm: float) -> list:
    """The song's sections: the person's own marks when there are any (Sprint 13), else the
    ones read off the original mix on its own beat grid (Sprint 5, kept beside the track
    since Sprint 11 - see `_song_shape`)."""
    shape = _song_shape(record, bpm)
    marks = _user_marks(record)
    if not marks:
        return shape["sections"]
    from app.services.synth.arrange import sections_from_marks
    from app.services.synth.retempo import beat_grid

    first = getattr(record.timing, "first_beat_s", 0.0) or 0.0
    duration = shape.get("duration_s") or 0.0
    return sections_from_marks(marks, beat_grid(first, bpm, duration), duration)


def _arrangement(record, body: BounceRequest, source_bpm: float, scale: float,
                 grid_bpm: float, stems: dict) -> list | None:
    """An arrangement request turned into pieces in the version's time, every problem with
    it raised now, in words, rather than inside the job."""
    if not body.arrangement:
        return None
    from app.services.synth import drop as drops
    from app.services.synth.arrange import Piece, arranged_beats, drop_bars
    from app.services.synth.retempo import beat_grid

    if not source_bpm:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Rearranging needs to know where the bars are, and this track's "
                            "tempo could not be read.")
    sections = {s.id: s for s in _sections_of(record, source_bpm)}
    # Any part the app knows, not only the ones in this version: muting the drums in a block
    # of a version that left the drummer out is harmless, and refusing it would be a puzzle.
    allowed = {kind.value for kind in StemKind} | {"beat"}
    pieces = []
    for n, item in enumerate(body.arrangement, start=1):
        section = sections.get(item.section)
        if section is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Block {n} asks for section {item.section!r}, and the song's "
                                f"sections are {', '.join(sections)}.")
        unknown = set(item.mute) - allowed
        if unknown:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Block {n} mutes {', '.join(sorted(unknown))}, which this "
                                f"version does not have.")
        end = section.end_s
        # The song's ring-out, once, when the arrangement ends on the song's last section.
        if n == len(body.arrangement):
            end += section.tail_s
        pieces.append(Piece(section.start_s * scale, end * scale,
                            frozenset(item.mute), item.drop))

    first = getattr(record.timing, "first_beat_s", 0.0) or 0.0
    longest = max(piece.end_s for piece in pieces)
    beats = arranged_beats(beat_grid(first * scale, grid_bpm, longest + 1.0), pieces)
    for bar in drop_bars(pieces, beats):
        try:
            drops.check(beats, bar)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"A drop at bar {bar} of the arrangement has no room for its "
                f"{drops.BUILD_BARS}-bar build. Put a block before it, or untick that drop.",
            ) from exc
    return pieces


def _resolve_beat(body: BounceRequest, out_dir: Path):
    """The groove a version adds, from its name - or None. Raises the reason when there is
    none by that name, or when it is the reference's and the reference has not been read."""
    if body.custom_beat is not None:
        import re as _re

        from app.services.synth.groove import KINDS, from_rows

        rows = body.custom_beat.rows
        for kind, row in rows.items():
            if kind not in KINDS or not _re.fullmatch(r"[xo.]{1,16}", row):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"A beat row is a drum ({', '.join(KINDS)}) and up to sixteen of x, o "
                    f"and . - not {kind!r}: {row!r}.")
        base = None
        if body.custom_beat.based_on:
            base = _resolve_beat(BounceRequest(beat=body.custom_beat.based_on), out_dir)
        return from_rows(rows, base)
    if body.beat:
        from app.services.synth.groove import BUILT_IN, Groove

        if body.beat == "reference":
            saved = out_dir / "reference.recipe.json"
            if not saved.exists():
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Read the reference first (Remix like your reference), so there is a beat "
                    "to take from it.",
                )
            return Groove.from_dict(json.loads(saved.read_text("utf-8"))["groove_full"])
        if body.beat in BUILT_IN:
            return BUILT_IN[body.beat]
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No beat called {body.beat!r}.")
    return None


@router.post("/{track_id}/bounce", response_model=JobResponse)
def bounce_version(
    track_id: str,
    body: BounceRequest,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    """The whole song at the new tempo, as one file. Sprint 3.

    **Not the master pipeline, and deliberately.** That pipeline builds its output as the
    original file plus whatever the stems *changed* - which is how it keeps separation's
    artefacts out of everything untouched, and which only works at the original tempo. At a
    new tempo there is no original to correct, so a re-played part sent through it would be
    truncated to the old length and mixed against stems that no longer line up. This sums
    the version directly instead: re-played parts as rendered, everything else stretched.

    That makes it a sketch rather than a master, and the response says so. The mastering
    page is where loudness and polish are decided.
    """
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if record.separation is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Separate the track first.")

    from app.services.synth.retempo import plan

    scale = 1.0
    move = None
    body.target_bpm = _as_asked(track_id, registry, body.target_bpm)
    if body.target_bpm:
        source_bpm = _tempo_of(track_id, registry)
        if not source_bpm:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This track's tempo could not be read, so there is nothing to move it from.",
            )
        move = plan(source_bpm, body.target_bpm, 0.0)
        if move is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{source_bpm:.0f} to {body.target_bpm:.0f} BPM is further than this moves a "
                f"performance.",
            )
        scale = move.scale

    out_dir = storage.exports_dir(track_id)
    stems = {stem.kind.value: stem.path for stem in record.separation.stems}
    renders = {
        stem: out_dir / f"{stem}.{voice}.wav" for stem, voice in body.parts.items()
    }
    missing = [stem for stem, path in renders.items() if not path.exists()]
    if missing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Play these parts first, so there is something to put in the version: "
            + ", ".join(missing) + ".",
        )
    for stem in body.leave_out:
        if stem not in stems:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"There is no {stem} stem.")
        stems.pop(stem)
        renders.pop(stem, None)
    if not stems and not body.beat and not body.custom_beat and not body.four_on_the_floor:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Every part is left out, so there is nothing to put in the version.")
    added_beat = _resolve_beat(body, out_dir)
    from app.services.synth import library

    if not library.exists(body.beat_kit, settings.sample_dir):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No kit called {body.beat_kit!r}.")
    sample_dir = settings.sample_dir

    from app.services.synth.retempo import stretcher_available

    unplayed = [stem for stem in stems if stem not in renders]
    if abs(scale - 1.0) > 1e-6 and unplayed and not stretcher_available():
        # Asked before the job starts, not discovered inside it. Anything not re-played has
        # to be stretched, and both stretchers come with the ML extras.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This install has no time-stretcher, so every part has to be re-played to change "
            "the tempo. Still to re-play: " + ", ".join(unplayed) + ".",
        )
    if body.drop_bar:
        # Checked here, with the reason, rather than inside the job where it would be a log.
        import soundfile as sf

        from app.services.synth import drop
        from app.services.synth.retempo import beat_grid

        grid_bpm = body.target_bpm or _tempo_of(track_id, registry)
        if not grid_bpm:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A drop needs to know where the bars are, and this track's tempo could not "
                "be read.",
            )
        record = registry.require(track_id)
        first = getattr(record.timing, "first_beat_s", 0.0) or 0.0
        longest = max(sf.info(str(path)).duration for path in stems.values())
        try:
            drop.check(beat_grid(first * scale, grid_bpm, longest * scale), body.drop_bar)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    source_bpm = _tempo_of(track_id, registry)
    pieces = _arrangement(registry.require(track_id), body, source_bpm, scale,
                          body.target_bpm or source_bpm, stems)

    def work(handle: JobHandle) -> dict:
        import soundfile as sf

        from app.services.mixdown.encode import write_mp3, write_wav
        from app.services.synth import instruments
        from app.services.synth.chop import Chop
        from app.services.synth.retempo import StaleRender, bounce, stretcher_available

        handle.update(JobState.RUNNING, 0.1, "gathering the parts")
        audio: dict = {}
        rate = 0
        for stem, path in stems.items():
            data, rate = sf.read(str(path), dtype="float64", always_2d=True)
            audio[stem] = data
        replays = {}
        for stem, path in renders.items():
            data, _ = sf.read(str(path), dtype="float64", always_2d=True)
            label = body.parts[stem]
            sound = instruments.find(label, sample_dir)
            if sound is not None and sound.origin == "reference":
                # Sprint 15: said wherever the version describes itself.
                label = f"{sound.name}, a sound sampled from your reference"
            if _edited_notes(out_dir, stem) is not None:
                label = f"{label}, as you edited it"
            replays[stem] = (data, label)

        # Sprint 16: grit, on the part as it will be heard - its re-played render, else
        # the stem - before anything is stretched, pumped or summed.
        gritted = []
        if body.grit:
            from app.services.synth import grit as grit_

            for stem, amount in body.grit.items():
                if amount <= 0:
                    continue
                if stem in replays:
                    data, label = replays[stem]
                    replays[stem] = (grit_.drive(data, rate, amount), label)
                elif stem in audio:
                    audio[stem] = grit_.drive(audio[stem], rate, amount)
                else:
                    continue
                gritted.append(f"{stem} {round(amount * 100)}%")
        # Sprint 17: width, after grit - a distorted synth is spread, not a spread one
        # distorted, which would fold the side back into the middle.
        widened = []
        if body.width:
            from app.services.synth import width as width_

            for stem, amount in body.width.items():
                if amount <= 0:
                    continue
                if stem in replays:
                    data, label = replays[stem]
                    replays[stem] = (width_.widen(data, rate, amount), label)
                elif stem in audio:
                    audio[stem] = width_.widen(audio[stem], rate, amount)
                else:
                    continue
                widened.append(f"{stem} {round(amount * 100)}%")

        stretching = [s for s in audio if s not in replays and abs(scale - 1.0) > 1e-6]
        handle.update(
            JobState.RUNNING,
            0.3,
            f"stretching {', '.join(stretching)} with {stretcher_available()}"
            if stretching
            else "summing the parts",
        )
        # Where the beats fall at the new tempo, for the pump and the four-on-the-floor.
        # The song's own first beat, scaled - so the added kick lands on the drummer's
        # downbeats rather than on a grid of its own that happens to share a tempo.
        beats = None
        target = body.target_bpm or (getattr(record.timing, "tempo_bpm", 0.0) or 0.0)
        if (body.pump or body.four_on_the_floor or body.drop_bar or added_beat
                or pieces or body.chops) and target:
            from app.services.synth.retempo import beat_grid

            first = getattr(record.timing, "first_beat_s", 0.0) or 0.0
            longest = max(len(a) for a in audio.values()) / rate
            beats = beat_grid(first * scale, target, longest * scale)
        layers: dict = {}
        try:
            mix, account = bounce(
                audio, rate, scale, replays,
                beats=beats, bpm=target,
                pump_db=(8.0 if body.pump_db is None else body.pump_db) if body.pump else 0.0,
                floor_kick=body.four_on_the_floor,
                drop_bar=body.drop_bar or 0,
                added_beat=added_beat,
                beat_kit=body.beat_kit,
                swing=body.swing,
                left_out=tuple(body.leave_out),
                beat_sounds=library.sounds(body.beat_kit, rate, sample_dir) if added_beat else None,
                humanize=body.humanize,
                pieces=pieces,
                layers_out=layers,
                pump_parts=body.pump_parts if body.pump else None,
                ghost_pump=body.ghost_pump and body.pump,
                chops=[Chop(c.bar, c.beat, c.beats, c.kind, tuple(c.parts))
                       for c in body.chops],
            )
        except StaleRender as exc:
            return {"ok": False, "why": str(exc), "stem": exc.stem}

        handle.update(JobState.RUNNING, 0.85, "writing the file")
        bpm = round(body.target_bpm) if body.target_bpm else "same"
        wav = write_wav(out_dir / f"version.{bpm}.wav", mix, rate, "24")
        mp3 = write_mp3(out_dir / f"version.{bpm}.mp3", mix, rate)
        handle.update(JobState.RUNNING, 0.92, "keeping each part for the mixer")
        # Where the version's first beat falls, so automation drawn in bars lands on them.
        grid_first = 0.0 if pieces else (
            getattr(record.timing, "first_beat_s", 0.0) or 0.0) * scale
        mixable = _save_layers(out_dir, str(bpm), layers, mix, rate, target, grid_first)
        from app.services.synth.retempo import summarise

        said = summarise(move, account)
        if gritted:
            said["lines"].append("Driven into distortion (grit): " + ", ".join(gritted) + ".")
        if widened:
            said["lines"].append("Spread wide in stereo, low end kept centered: "
                                 + ", ".join(widened) + ".")
        return {
            "ok": True,
            # Counted, not asserted. `Move.describe()` is true of one re-played part and was
            # printed here on bounces where most parts had been stretched.
            "headline": said["headline"],
            "lines": said["lines"],
            "tip": said["tip"],
            "duration_s": round(len(mix) / rate, 1),
            "parts": [{"stem": p.stem, "how": p.how, "detail": p.detail} for p in account],
            "wav": f"/api/v1/tracks/{track_id}/version/{wav.name}",
            "mp3": f"/api/v1/tracks/{track_id}/version/{mp3.name}",
            "note": "A sketch of the version, not a master - the mastering page is where "
            "loudness is decided.",
            # Sprint 7: the layers, for the mixer.
            "label": str(bpm),
            "layers": [{"name": n, "label": lbl,
                        "url": f"/api/v1/tracks/{track_id}/version/{bpm}/layers/{n}"}
                       for n, lbl in mixable["layers"]],
            "layer_gain": mixable["layer_gain"],
            "tempo_bpm": round(target, 2) if target else None,
            "first_beat_s": round(grid_first, 6),
        }

    return to_response(jobs.submit("bounce", track_id, work))


# --- Sprint 7: mixing each part -----------------------------------------------------------

_LABEL = re.compile(r"\d{2,3}|same")


def _save_layers(out_dir: Path, label: str, layers: dict, mix, rate: int, bpm: float,
                 first_beat_s: float = 0.0) -> dict:
    """Every layer of a version as its own file, for the mixer, and how to read them back.

    Scaled by what the bounce did to the sum, so a flat mix of the layers *is* the file that
    was just written. Then, if any single layer would clip as 16-bit, all of them come down
    together and `layer_gain` says by how much - the page and the server both turn them back
    up by it.
    """
    import numpy as np
    import soundfile as sf

    from app.services.synth.mixer import LAYERS

    # A layer with nothing in it - below -80 dBFS throughout - is not a strip worth loading.
    names = [n for n in LAYERS if n in layers
             and float(np.max(np.abs(np.asarray(layers[n])))) > 1e-4]
    if not names:
        return {"layers": [], "layer_gain": 1.0}
    raw = sum(np.asarray(layers[n], dtype=np.float64) for n in names)
    raw_peak = float(np.max(np.abs(raw))) or 1.0
    bounced = float(np.max(np.abs(mix))) or raw_peak
    scale = bounced / raw_peak
    loudest = max(float(np.max(np.abs(layers[n]))) for n in names) * scale
    fit = min(1.0, 0.99 / loudest) if loudest > 0 else 1.0
    for old in [*out_dir.glob(f"layer.{label}.*.wav"), *out_dir.glob(f"layer.{label}.*.flac")]:
        old.unlink()
    for n in names:
        # FLAC: lossless, so the mixer still hears exactly what is bounced, and about a
        # tenth of the WAV on the demo - eight layers of a four-minute song as WAV were
        # some 340 MB for the page to download before it could play a note. Sprint 11.
        sf.write(str(out_dir / f"layer.{label}.{n}.flac"),
                 np.asarray(layers[n]) * scale * fit, rate, format="FLAC", subtype="PCM_16")
    meta = {"layers": names, "layer_gain": 1.0 / fit, "bpm": bpm, "rate": rate,
            "first_beat_s": first_beat_s}
    (out_dir / f"layer.{label}.json").write_text(json.dumps(meta), "utf-8")
    return {"layers": [(n, LAYERS[n]) for n in names], "layer_gain": round(1.0 / fit, 6)}


class ChannelIn(BaseModel):
    gain_db: float = Field(0.0, ge=-60.0, le=12.0)
    pan: float = Field(0.0, ge=-1.0, le=1.0)
    mute: bool = False
    solo: bool = False
    low_cut_hz: float = Field(0.0, ge=0.0, le=2000.0)
    high_cut_hz: float = Field(0.0, ge=0.0, le=20000.0)
    reverb: float = Field(0.0, ge=0.0, le=1.0)
    delay: float = Field(0.0, ge=0.0, le=1.0)
    #: Sprint 9: {setting: [[beat, value], ...]} - level, pan, low or high cut, reverb or
    #: delay, moving over the song. Values outside a setting's range are held to it.
    automation: dict[str, list[tuple[float, float]]] = Field(default_factory=dict)

    @field_validator("automation")
    @classmethod
    def _lanes(cls, lanes: dict) -> dict:
        from app.services.synth.mixer import AUTOMATABLE, MAX_POINTS

        for setting, points in lanes.items():
            if setting not in AUTOMATABLE:
                raise ValueError(f"{setting!r} cannot move. These can: {', '.join(AUTOMATABLE)}.")
            if len(points) > MAX_POINTS:
                raise ValueError(f"A lane holds up to {MAX_POINTS} points.")
            if any(b < 0 for b, _ in points):
                raise ValueError("A point cannot come before the song's first beat.")
        return lanes


class MixRequest(BaseModel):
    channels: dict[str, ChannelIn] = Field(default_factory=dict)


@router.get("/mixer/impulse")
def mixer_impulse(rate: int = Query(44100, ge=8000, le=192000)) -> Response:
    """The reverb's impulse response, for the page's ConvolverNode - the same one the server
    convolves with, so the reverb heard is the reverb bounced. 32-bit float WAV."""
    import io

    import soundfile as sf

    from app.services.synth.mixer import impulse

    buffer = io.BytesIO()
    sf.write(buffer, impulse(rate), rate, format="WAV", subtype="FLOAT")
    return Response(buffer.getvalue(), media_type="audio/wav")


@router.get("/{track_id}/version/{label}/layers/{name}")
def version_layer(track_id: str, label: str, name: str,
                  storage: TrackStorage = Depends(get_storage)) -> FileResponse:
    """One layer of a bounced version. Both parts of the name are checked against closed
    lists, because a path built from a URL is a traversal waiting to happen."""
    from app.services.synth.mixer import LAYERS

    if not _LABEL.fullmatch(label) or name not in LAYERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such layer.")
    path = _layer_path(storage.exports_dir(track_id), label, name)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Make the version first.")
    kind = "audio/flac" if path.suffix == ".flac" else "audio/wav"
    return FileResponse(path, media_type=kind, filename=path.name)


def _layer_path(out_dir: Path, label: str, name: str) -> Path | None:
    """A layer's file: FLAC since Sprint 11, WAV for versions bounced before it."""
    for suffix in (".flac", ".wav"):
        path = out_dir / f"layer.{label}.{name}{suffix}"
        if path.exists():
            return path
    return None


# --- Sprint 10: saved mixes --------------------------------------------------------------------


class SaveMixRequest(BaseModel):
    name: str
    channels: dict[str, ChannelIn] = Field(default_factory=dict)
    #: How long the version it was made on is, in beats - so its lanes can be fitted later.
    beats: float = Field(0.0, ge=0.0)
    tempo_bpm: float = Field(0.0, ge=0.0)


class ApplyMixRequest(BaseModel):
    name: str
    #: Stretch the moving settings to this version's length, rather than keep their bars.
    stretch: bool = False


def _version_meta(storage: TrackStorage, track_id: str, label: str) -> tuple[Path, dict]:
    if not _LABEL.fullmatch(label):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such version.")
    out_dir = storage.exports_dir(track_id)
    meta_path = out_dir / f"layer.{label}.json"
    if not meta_path.exists():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Make the version first - a mix is put on its parts.")
    return out_dir, json.loads(meta_path.read_text("utf-8"))


def _version_beats(out_dir: Path, label: str, meta: dict) -> float:
    """How long a version is, in beats from its first beat."""
    import soundfile as sf

    longest = max((sf.info(str(_layer_path(out_dir, label, n))).duration
                   for n in meta["layers"]), default=0.0)
    bpm = meta.get("bpm") or 0.0
    return max(0.0, (longest - (meta.get("first_beat_s") or 0.0)) * bpm / 60.0) if bpm else 0.0


@router.get("/mixes")
def list_mixes(settings: Settings = Depends(get_config)) -> dict:
    """Starter mixes, and the mixes you have saved. Sprint 10."""
    from app.services.synth import mixes

    return {
        "starters": [{"name": n, "about": m["about"]} for n, m in mixes.STARTERS.items()],
        "yours": [{"name": n, "about": mixes.describe(m["channels"]),
                   "bars": round((m.get("beats") or 0) / 4)}
                  for n, m in mixes.saved_mixes(settings.sample_dir).items()],
    }


@router.post("/mixes", status_code=status.HTTP_201_CREATED)
def save_mix(body: SaveMixRequest, settings: Settings = Depends(get_config)) -> dict:
    """Keep a mix under a name, to put on another version."""
    from app.services.synth import mixes

    name = body.name.strip()
    if not mixes.SAFE_NAME.match(name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A mix's name can hold letters, numbers, spaces, hyphens and "
                            "underscores, up to 32 of them.")
    if name in mixes.STARTERS:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{name!r} is a starter mix. Call yours something else.")
    channels = {n: c.model_dump() for n, c in body.channels.items()}
    mixes.save_mix(settings.sample_dir, name, channels, body.beats, body.tempo_bpm)
    return {"name": name, "about": mixes.describe(channels)}


@router.delete("/mixes/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mix(name: str, settings: Settings = Depends(get_config)) -> Response:
    from app.services.synth import mixes

    if not mixes.SAFE_NAME.match(name) or not mixes.delete_mix(settings.sample_dir, name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No mix of yours called {name!r}.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{track_id}/version/{label}/mix/apply")
def apply_mix(
    track_id: str,
    label: str,
    body: ApplyMixRequest,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
) -> dict:
    """A saved or starter mix, made ready for this version - its parts, its length - with a
    sentence for whatever did not carry over. Nothing is bounced: the page puts it on the
    strips, so it is heard before it is kept."""
    from app.services.synth import mixes

    out_dir, meta = _version_meta(storage, track_id, label)
    if body.name in mixes.STARTERS:
        saved = {"channels": mixes.STARTERS[body.name]["channels"], "beats": None}
    else:
        saved = mixes.saved_mixes(settings.sample_dir).get(body.name)
        if saved is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No mix called {body.name!r}.")
    beats = _version_beats(out_dir, label, meta)
    channels, notes = mixes.fit(saved["channels"], meta["layers"], beats,
                                saved.get("beats"), body.stretch)
    # Through the same validation a bounce uses, so anything out of range is held to it.
    checked = {}
    for name, channel in channels.items():
        try:
            checked[name] = ChannelIn(**{**ChannelIn().model_dump(), **channel}).model_dump()
        except Exception as exc:  # noqa: BLE001 - a damaged saved mix is reported, not raised
            notes.append(f"The {name} settings could not be read and were left out ({exc}).")
    return {"channels": checked, "notes": notes, "beats": round(beats, 2)}


class FinishRequest(BaseModel):
    """Sprint 23: how loud to finish a version, and whether to move it towards the
    reference's tone on the way."""

    #: A named target ("club", "loud", "streaming", "gentle") or a loudness in LUFS.
    target: str | float = "club"
    #: Move the tone towards the reference's - cuts anywhere, lifts only below 1.5 kHz.
    match_reference: bool = False


@router.post("/{track_id}/version/{label}/finish", response_model=JobResponse)
def finish_version(
    track_id: str,
    label: str,
    body: FinishRequest,
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    """Finish a version for a club: glued, clipped, limited and landed on a loudness, under a
    -1 dBTP ceiling. Sprint 23, see `mastering/club.py`.

    Written beside the version as `master.{label}.*`, never over it - the sketch stays, so the
    two can be compared and the finish can be run again at another target."""
    from app.services.mastering.club import TARGETS

    try:
        registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if not _LABEL.fullmatch(label):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such version.")
    out_dir = storage.exports_dir(track_id)
    source = out_dir / f"version.{label}.wav"
    if not source.exists():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Make the version first - this finishes what the bounce wrote.")
    if isinstance(body.target, str):
        if body.target not in TARGETS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"No target called {body.target!r}. Try "
                                f"{', '.join(TARGETS)}, or a loudness in LUFS.")
        target = TARGETS[body.target]
    else:
        target = float(body.target)
    if not -30.0 <= target <= -5.0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A target between -30 and -5 LUFS, please. Past -8 a master is "
                            "squashed rather than loud.")
    reference = storage.reference_path(track_id) if body.match_reference else None
    if body.match_reference and (reference is None or not Path(reference).exists()):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "There is no reference to match - upload one, or finish without it.")

    def work(handle: JobHandle) -> dict:
        import soundfile as sf

        from app.services.mastering import club
        from app.services.mixdown.encode import write_mp3, write_wav

        handle.update(JobState.RUNNING, 0.15, "reading the version")
        audio, rate = sf.read(str(source), dtype="float64", always_2d=True)
        theirs, their_rate = (None, None)
        if reference is not None:
            theirs, their_rate = sf.read(str(reference), dtype="float64", always_2d=True)
        handle.update(JobState.RUNNING, 0.35, "gluing, clipping and limiting")
        done, report = club.finish(audio, rate, target, theirs, their_rate)
        handle.update(JobState.RUNNING, 0.8, "writing the file")
        wav = write_wav(out_dir / f"master.{label}.wav", done, rate, "24")
        mp3 = write_mp3(out_dir / f"master.{label}.mp3", done, rate)
        return {
            "label": label,
            "target_lufs": target,
            "wav": f"/api/v1/tracks/{track_id}/version/{wav.name}",
            "mp3": f"/api/v1/tracks/{track_id}/version/{mp3.name}",
            "report": report.to_dict(),
            "lines": report.said(),
            "note": "Finished for playing out. The version itself is untouched beside it, so "
                    "you can compare them or finish again at another loudness.",
        }

    return to_response(jobs.submit("finish", track_id, work))


@router.get("/{track_id}/versions")
def list_versions(track_id: str, storage: TrackStorage = Depends(get_storage)) -> dict:
    """Every version this track has, newest first - enough for the mixer to pick one up
    again. Sprint 23.

    Versions have always survived a restart on disk, but only the page that made one knew
    about it: reopening a track left the mixer and the finish unavailable until it was
    bounced again, for no reason but that nothing listed them."""
    from app.services.synth.mixer import LAYERS

    out_dir = storage.exports_dir(track_id)
    found = []
    for meta_path in out_dir.glob("layer.*.json"):
        label = meta_path.name[len("layer."):-len(".json")]
        if not _LABEL.fullmatch(label):
            continue
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        names = [n for n in meta.get("layers", []) if _layer_path(out_dir, label, n).exists()]
        if not names:
            continue
        found.append({
            "label": label,
            "tempo_bpm": meta.get("bpm") or None,
            "layer_gain": meta.get("layer_gain", 1.0),
            "layers": [{"name": n, "label": LAYERS.get(n, n),
                        "url": f"/api/v1/tracks/{track_id}/version/{label}/layers/{n}"}
                       for n in names],
            "mp3": f"/api/v1/tracks/{track_id}/version/version.{label}.mp3",
            "wav": f"/api/v1/tracks/{track_id}/version/version.{label}.wav",
            "mastered": (out_dir / f"master.{label}.mp3").exists(),
            "made_at": meta_path.stat().st_mtime,
        })
    found.sort(key=lambda v: v["made_at"], reverse=True)
    return {"versions": found}


@router.get("/{track_id}/version/{label}/mix")
def version_mix(track_id: str, label: str,
                storage: TrackStorage = Depends(get_storage)) -> dict:
    """The mix this version was last bounced with, so a reload does not lose it."""
    _, meta = _version_meta(storage, track_id, label)
    return {"channels": meta.get("mix") or {}}


@router.post("/{track_id}/version/{label}/mix", response_model=JobResponse)
def mix_version(
    track_id: str,
    label: str,
    body: MixRequest,
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    """Bounce the version again with a mix: each layer's level, pan, mute, solo, tone and
    sends. Nothing is re-played or re-stretched - the layers saved by the last bounce are
    mixed - so this takes seconds. Sprint 7, see `synth/mixer.py`."""
    try:
        registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if not _LABEL.fullmatch(label):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such version.")
    out_dir = storage.exports_dir(track_id)
    meta_path = out_dir / f"layer.{label}.json"
    if not meta_path.exists():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Make the version first - the mixer mixes its parts.")
    meta = json.loads(meta_path.read_text("utf-8"))
    # "master" is the whole-mix strip, on every version. Sprint 11.
    unknown = set(body.channels) - set(meta["layers"]) - {"master"}
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"This version has no {', '.join(sorted(unknown))} to mix. Its "
                            f"parts are {', '.join(meta['layers'])}.")

    def work(handle: JobHandle) -> dict:
        import numpy as np
        import soundfile as sf

        from app.services.mixdown.encode import write_mp3, write_wav
        from app.services.synth import mixer

        handle.update(JobState.RUNNING, 0.2, "mixing")
        layers, rate = {}, meta["rate"]
        for name in meta["layers"]:
            data, rate = sf.read(str(_layer_path(out_dir, label, name)), dtype="float64",
                                 always_2d=True)
            layers[name] = data * meta["layer_gain"]
        channels = {n: mixer.Channel(**c.model_dump()) for n, c in body.channels.items()}
        mixed = mixer.mix(layers, channels, rate, meta.get("bpm") or 0.0,
                          meta.get("first_beat_s", 0.0))
        # The same ceiling the bounce uses: -1 dBFS if the mix went over, nothing otherwise.
        peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
        ceiling = 10 ** (-1.0 / 20)
        if peak > ceiling:
            mixed *= ceiling / peak
        handle.update(JobState.RUNNING, 0.8, "writing the file")
        wav = write_wav(out_dir / f"version.{label}.wav", mixed, rate, "24")
        mp3 = write_mp3(out_dir / f"version.{label}.mp3", mixed, rate)
        meta["mix"] = {n: c.model_dump() for n, c in body.channels.items()}
        meta_path.write_text(json.dumps(meta), "utf-8")
        said = mixer.describe(channels)
        return {
            "ok": True,
            "headline": "Mixed." if said else "Mixed flat - every part as it was.",
            "lines": said,
            "duration_s": round(len(mixed) / rate, 1),
            "wav": f"/api/v1/tracks/{track_id}/version/{wav.name}",
            "mp3": f"/api/v1/tracks/{track_id}/version/{mp3.name}",
        }

    return to_response(jobs.submit("mix", track_id, work))


def _have_detector() -> bool:
    """Reading strokes needs librosa's onset detector, which ships with the ML extras."""
    try:
        import librosa  # noqa: F401

        return True
    except ImportError:
        return False


NO_DETECTOR = ("Reading a beat needs the hit detector, which comes with the ML extras "
               "(requirements-ml.txt). Built-in beats still work without it.")


@router.get("/styles")
def list_styles(
    bpm: float = Query(0.0, ge=0.0, le=400.0, description="the song's tempo, to fit each style"),
    settings: Settings = Depends(get_config),
) -> dict:
    """Styles to remix into - each a tempo, a beat, a kit and a sound for every part, real
    synths where they are installed and this app's own voices where not. Sprint 12.

    Given the song's tempo (Sprint 15), each style's tempo is fitted to it and says what it
    does to the song, and `suggested` names the styles that keep it at its own speed."""
    from app.services.synth import instruments, styles

    have = set(instruments.installed(settings.sample_dir))
    return {"styles": [styles.resolve(name, have, bpm) for name in styles.STYLES],
            "suggested": styles.suggested(bpm)}


class DescribeRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    #: The track it is for, so the song's own part names ("post-chorus") can be read.
    track_id: str | None = None


@router.post("/describe")
def describe_remix(
    body: DescribeRequest,
    settings: Settings = Depends(get_config),
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """A remix in words, read into a recipe of this app's own controls. Sprint 21.

    Nothing is made here: the page sets the controls the recipe names and makes the version
    the ordinary way. Read by the vocabulary unless `PROMPT_READER=claude` and a key are set."""
    from app.services.drums.kit import KITS
    from app.services.synth import describe, library, styles
    from app.services.synth.shape import user_sounds

    labels: list[str] = []
    if body.track_id:
        try:
            record = registry.require(body.track_id)
            bpm = _tempo_of(body.track_id, registry)
            if bpm:
                labels = sorted({s.label for s in _sections_of(record, bpm)})
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    kits = [*KITS, *library.user_kits(settings.sample_dir),
            *(n for n, s in user_sounds(settings.sample_dir).items() if s["kind"] == "kit")]
    context = describe.Context(labels=labels, styles=list(styles.STYLES), kits=kits)
    reader = describe.reader_for(settings)
    try:
        reading = reader.read(body.prompt, context)
    except Exception as exc:  # noqa: BLE001 - a reader that fails says so, in words
        log.info("prompt reader %s failed", reader.name, exc_info=True)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"The {reader.name} reader could not read that: {exc}") from exc
    return reading.to_dict()


@router.post("/{track_id}/version/{label}/match-levels")
def match_reference_levels(
    track_id: str,
    label: str,
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """The fader moves that give a version the reference's balance - drums, synths and vocals
    each set against the bass as the reference sets them. Sprint 21 (X0R-1475). Nothing is
    applied here: the moves come back for the mixer, where the person can change them."""
    import soundfile as sf

    from app.services.synth import levels

    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if not record.reference_stems:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Split the reference first, so its parts can be measured.")
    out_dir, meta = _version_meta(storage, track_id, label)
    gain = float(meta.get("layer_gain", 1.0))
    layers = {}
    for name in meta.get("layers", []):
        path = out_dir / f"layer.{label}.{name}.flac"
        if path.exists():
            layers[name] = sf.read(str(path), dtype="float64", always_2d=True)[0] * gain
    stems, rate = {}, 44100
    for kind, path in record.reference_stems.items():
        data, rate = sf.read(str(path), dtype="float64", always_2d=True)
        stems[getattr(kind, "value", str(kind))] = data
    return levels.match(layers, int(meta.get("rate", 44100)), stems, rate)


@router.get("/grooves")
def list_grooves() -> dict:
    """The built-in beats, as a drum machine would show them. Sprint 4."""
    from app.services.synth.groove import BUILT_IN

    return {
        "grooves": [{"name": name, "grid": beat.grid()} for name, beat in BUILT_IN.items()],
        "note": "Each is added alongside your band, never instead of it - leave the drums out "
        "of the version if you want the beat on its own.",
    }


@router.get("/{track_id}/beat")
def track_groove(
    track_id: str,
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """How your drummer plays: the pattern, the swing, and who pushes or lays back.

    A description, not a control. Sentences like "your snare sits 11 ms behind the beat"
    are how somebody learns what their own record is doing - the confidence half of the
    brief - and nothing here moves a hit.
    """
    try:
        bpm = _tempo_of(track_id, registry)
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    drums = _stem_path(record.separation, StemKind.DRUMS) if record.separation else None
    if drums is None or not Path(drums).exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "Separate the track first.")
    if not bpm:
        raise HTTPException(status.HTTP_409_CONFLICT, "The tempo could not be read.")
    if not _have_detector():
        raise HTTPException(status.HTTP_409_CONFLICT, NO_DETECTOR)

    import soundfile as sf

    from app.services.synth import groove as g
    from app.services.synth.retempo import beat_grid

    audio, rate = sf.read(str(drums), dtype="float64", always_2d=True)
    first = getattr(record.timing, "first_beat_s", 0.0) or 0.0
    read = g.from_audio(audio, rate, beat_grid(first, bpm, len(audio) / rate),
                        "your drummer", "your drummer", bpm)
    push = {kind: read.push_ms(kind) for kind in g.KINDS}
    return {
        "grid": read.grid(),
        "swing_percent": read.swing_percent,
        "push_ms": {k: (round(v, 1) if v is not None else None) for k, v in push.items()},
        "bars": read.bars,
        "lines": g.describe(read),
    }


@router.post("/{track_id}/reference/recipe", response_model=JobResponse)
def reference_recipe(
    track_id: str,
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    """Read the essential elements of a reference remix, as a recipe for this song. Sprint 4.

    Tempo, beat, pump, kick and bass - each reduced to numbers and matched to this
    application's own sounds. Nothing of the reference's audio is used in the remix; see
    `synth/recipe.py`. Saved beside the exports so a bounce can add the reference's beat.
    """
    try:
        record = registry.require(track_id)
        source_bpm = _tempo_of(track_id, registry)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    theirs = record.reference_stems or {}
    drums = _stem_path(theirs, StemKind.DRUMS)
    if drums is None or not Path(drums).exists():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Add a reference and split it first - its drums are where the beat is read from.",
        )
    if not _have_detector():
        raise HTTPException(status.HTTP_409_CONFLICT, NO_DETECTOR)
    out_dir = storage.exports_dir(track_id)
    bass_path = _stem_path(theirs, StemKind.BASS)
    other_path = _stem_path(theirs, StemKind.OTHER)

    def work(handle: JobHandle) -> dict:
        import soundfile as sf

        from app.services.analysis.timing import TimingAnalyser
        from app.services.synth import groove as g
        from app.services.synth import recipe as r
        from app.services.synth.retempo import beat_grid, plan

        handle.update(JobState.RUNNING, 0.1, "finding their tempo")
        audio, rate = sf.read(str(drums), dtype="float64", always_2d=True)
        estimate = TimingAnalyser().analyse(Path(drums)).tempo_bpm
        # Every multiple the estimator gets wrong, checked against the kick. See dance_tempo.
        bpm, first = r.dance_tempo(audio, rate, estimate)
        if not bpm:
            bpm, first = estimate, 0.0
        beats = beat_grid(first, bpm, len(audio) / rate)

        handle.update(JobState.RUNNING, 0.35, "reading their beat")
        hits = g.read_hits(audio, rate)
        groove = g.extract(hits, beats, "your reference", "your reference", bpm)

        handle.update(JobState.RUNNING, 0.6, "measuring the pump")
        pump = 0.0
        for path in (bass_path, other_path):
            if path is not None and Path(path).exists():
                part, part_rate = sf.read(str(path), dtype="float64", always_2d=True)
                pump = max(pump, r.measure_pump(part, part_rate, beats))

        handle.update(JobState.RUNNING, 0.8, "matching their kick and bass")
        kicks = [h.time_s for h in hits if "kick" in h.kinds and "snare" not in h.kinds]
        features = r.reference_kick(audio, rate, kicks)
        kit, kit_line = (r.nearest_kit(features, rate) if features
                         else ("edm", "No clear kick to match, so the edm kit."))
        bass, bass_line = "808", "No bass stem to match, so the 808."
        if bass_path is not None and Path(bass_path).exists():
            part, part_rate = sf.read(str(bass_path), dtype="float64", always_2d=True)
            bass, bass_line = r.nearest_bass(r.bass_features(part.mean(axis=1), part_rate),
                                             part_rate)

        # Their tempo if this song can be moved there; otherwise the same groove at half or
        # double, which a dance producer would call the same tempo anyway.
        target = next((t for t in (bpm, bpm / 2, bpm * 2)
                       if source_bpm and plan(source_bpm, t, 0.0) is not None), bpm)
        lines = [r.tempo_line(bpm, source_bpm, target)]
        lines += [f"Their beat: {line}" for line in g.describe(groove)]
        lines += [r.pump_line(pump), kit_line, bass_line]
        recipe = r.Recipe(tempo_bpm=bpm, groove=groove, pump_db=pump, kit=kit,
                          bass_voice=bass, lines=lines)
        result = {**recipe.to_dict(), "target_bpm": round(target, 1)}
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "reference.recipe.json").write_text(
            json.dumps({**result, "groove_full": groove.to_dict()}), "utf-8")
        return result

    return to_response(jobs.submit("recipe", track_id, work))


@router.get("/{track_id}/sections")
def song_sections(
    track_id: str,
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """The song's sections, to rearrange. Sprint 5. See `synth/arrange.py`."""
    try:
        bpm = _tempo_of(track_id, registry)
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if not bpm:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "The tempo could not be read, so there are no bars to count.")
    return _sections_body(record, bpm)


def _sections_body(record, bpm: float) -> dict:
    shape = _song_shape(record, bpm)
    found = _sections_of(record, bpm)
    yours = _user_marks(record) is not None
    return {
        "tempo_bpm": round(bpm, 2),
        "sections": [s.to_dict() for s in found],
        "source": "yours" if yours else "detected",
        # For the marking editor: every bar's loudness, and what the detector suggested.
        "bar_db": shape.get("bar_db", []),
        "detected": [{"bar": s.start_bar, "label": s.label} for s in shape["sections"]],
        "note": "Marked by you." if yours else
        "Cut on four-bar phrases and grouped by how they sound: the same letter sounds "
        "alike. The names are guesses - mark them yourself if they are wrong.",
    }


class Mark(BaseModel):
    bar: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=24)


class MarksRequest(BaseModel):
    marks: list[Mark] = Field(min_length=1, max_length=128)


@router.put("/{track_id}/sections")
def mark_sections(
    track_id: str,
    body: MarksRequest,
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """Say where the song's parts start and what they are. Sprint 13.

    Kept beside the track and used everywhere sections are - the arrangement editor, section
    previews, bounces and the MIDI export - instead of the detector's guess."""
    try:
        bpm = _tempo_of(track_id, registry)
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if not bpm:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "The tempo could not be read, so there are no bars to mark.")
    bars = len(_song_shape(record, bpm).get("bar_db") or [])
    late = [m.bar for m in body.marks if bars and m.bar > bars]
    if late:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"The song has {bars} bars, so a section cannot start at bar "
                            f"{late[0]}.")
    seen = {}
    for m in sorted(body.marks, key=lambda m: m.bar):
        seen[m.bar] = m.label.strip()
    _marks_path(record).write_text(
        json.dumps([{"bar": b, "label": label} for b, label in seen.items()]), "utf-8")
    return _sections_body(record, bpm)


@router.delete("/{track_id}/sections", status_code=status.HTTP_204_NO_CONTENT)
def unmark_sections(track_id: str, registry: TrackRegistry = Depends(get_registry)) -> Response:
    """Back to the detected sections."""
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    _marks_path(record).unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{track_id}/listen")
def listen_from_bar(
    track_id: str,
    bar: int = Query(1, ge=1),
    bars: int = Query(4, ge=1, le=32),
    registry: TrackRegistry = Depends(get_registry),
) -> Response:
    """A few bars of the original from any bar - to hear where a part starts before marking
    it. Sprint 13."""
    try:
        bpm = _tempo_of(track_id, registry)
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if not bpm:
        raise HTTPException(status.HTTP_409_CONFLICT, "The tempo could not be read.")
    import soundfile as sf

    from app.services.synth.library import wav_bytes

    first = getattr(record.timing, "first_beat_s", 0.0) or 0.0
    bar_s = 4 * 60.0 / bpm
    info = sf.info(str(record.stored.path))
    start = int((first + (bar - 1) * bar_s) * info.samplerate)
    if start >= info.frames:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The song ends before that bar.")
    audio, rate = sf.read(str(record.stored.path), dtype="float64", always_2d=True,
                          start=start, frames=int(bars * bar_s * info.samplerate))
    return Response(wav_bytes(audio, rate), media_type="audio/wav")


@router.get("/{track_id}/sections/{section_id}/preview")
def section_preview(
    track_id: str,
    section_id: str,
    registry: TrackRegistry = Depends(get_registry),
) -> Response:
    """One section of the original song, to hear what a block is before placing it."""
    try:
        bpm = _tempo_of(track_id, registry)
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    found = {s.id: s for s in _sections_of(record, bpm)} if bpm else {}
    section = found.get(section_id)
    if section is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such section.")
    import soundfile as sf

    from app.services.synth.library import wav_bytes

    audio, rate = sf.read(str(record.stored.path), dtype="float64", always_2d=True)
    piece = audio[int(section.start_s * rate): int((section.end_s + section.tail_s) * rate)]
    return Response(wav_bytes(piece, rate), media_type="audio/wav")


@router.get("/{track_id}/drops")
def suggest_drops(
    track_id: str,
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """Where a build and drop would land best, strongest first. X0R-1335.

    Read from the original mix on the song's own grid. Bars are counted the same at any
    tempo, so a suggestion here means the same bar in a version at 128.
    """
    try:
        bpm = _tempo_of(track_id, registry)
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if not bpm:
        return {"bars": 0, "suggestions": [],
                "why": "The tempo could not be read, so there are no bars to count."}

    from app.services.synth import drop

    shape = _song_shape(record, bpm)
    found = shape["drops"]
    return {
        "bars": shape["bars"],
        "build_bars": drop.BUILD_BARS,
        "suggestions": found,
        "why": "Where the music changes most at the start of a four-bar phrase - usually a "
        "verse turning into a chorus." if found else
        "The song is too short for a build and a drop.",
    }


@router.get("/{track_id}/version/{name}")
def version_file(
    track_id: str, name: str, storage: TrackStorage = Depends(get_storage)
) -> FileResponse:
    """A bounced version. The name is checked against the only shape a bounce writes."""
    if not re.fullmatch(r"(version|master)\.(\d{2,3}|same)\.(wav|mp3|mid)", name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such version.")
    path = storage.exports_dir(track_id) / name
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not bounced yet.")
    kind = {"mp3": "audio/mpeg", "mid": "audio/midi"}.get(name.rsplit(".", 1)[1], "audio/wav")
    return FileResponse(path, media_type=kind, filename=name)


@router.post("/{track_id}/version/midi", response_model=JobResponse)
def version_midi(
    track_id: str,
    body: BounceRequest,
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    """The version as a multi-track MIDI file at its tempo. Sprint 4, X0R-1342.

    Takes the same request as a bounce, so the file is the version that was heard: the
    re-played parts as notes, the drummer's strokes, the added beat and the roll into the
    drop. Transcribes as it goes, which is why it is a job. See `synth/version_midi.py`.
    """
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if record.separation is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Separate the track first.")

    from app.services.synth.retempo import plan

    source_bpm = _tempo_of(track_id, registry)
    body.target_bpm = _as_asked(track_id, registry, body.target_bpm)
    tempo = body.target_bpm or source_bpm or 120.0
    scale = 1.0
    move = None
    if body.target_bpm and source_bpm:
        move = plan(source_bpm, body.target_bpm, 0.0)
        if move is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{source_bpm:.0f} to {body.target_bpm:.0f} BPM is further than this moves a "
                f"performance.",
            )
        scale = move.scale
    out_dir = storage.exports_dir(track_id)
    stems = {stem.kind.value: stem.path for stem in record.separation.stems}
    wanted = [s for s in body.parts if s in stems and s not in body.leave_out]
    if not wanted and not body.beat and not body.custom_beat and not body.four_on_the_floor:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Choose something to play first - a part on a voice, or a beat - so there are "
            "notes to write.",
        )
    added = _resolve_beat(body, out_dir)
    first = getattr(record.timing, "first_beat_s", 0.0) or 0.0
    pieces = _arrangement(record, body, source_bpm, scale, tempo, stems)

    def work(handle: JobHandle) -> dict:
        import soundfile as sf

        from app.domain.notes import coalesce
        from app.services.synth import drop as drops
        from app.services.synth import groove as g
        from app.services.synth import version_midi as vm
        from app.services.synth.retempo import beat_grid, move_hits, move_notes

        pitched: dict[str, list] = {}
        drummer = None
        for i, stem in enumerate(wanted):
            handle.update(JobState.RUNNING, 0.1 + 0.6 * i / max(1, len(wanted)),
                          f"reading the notes out of the {stem}")
            path = Path(stems[stem])
            if stem == StemKind.DRUMS.value:
                if not _have_detector():
                    continue
                audio, rate = sf.read(str(path), dtype="float64", always_2d=True)
                drummer = vm.drummer(move_hits(g.read_hits(audio, rate), scale))
                continue
            try:
                found = _transcribe(settings, StemKind(stem), path).notes
            except Exception:
                log.info("no notes from %s", stem, exc_info=True)
                continue
            pitched[stem] = move_notes(coalesce(list(found)), scale)

        handle.update(JobState.RUNNING, 0.8, "laying out the beat and the build")
        longest = max(sf.info(str(p)).duration for p in stems.values()) * scale
        beats = beat_grid(first * scale, tempo, longest)
        drop_at = [body.drop_bar] if body.drop_bar else []
        rest: list = []
        if pieces:
            # Every part follows the arrangement, the same cut as the audio.
            from app.services.synth import arrange

            pitched = {stem: arrange.place_notes(notes, pieces, stem)
                       for stem, notes in pitched.items()}
            if drummer is not None:
                drummer = arrange.place_notes(drummer, pieces, "drums")
            beats = arrange.arranged_beats(beats, pieces)
            drop_at = sorted({*drop_at, *arrange.drop_bars(pieces, beats)})
            rest += arrange.muted_spans(pieces, "beat")
        roll_notes = []
        for bar in drop_at:
            try:
                window = drops._window(beats, bar)
            except ValueError:
                continue
            rest.append(window)
            roll_notes += vm.build(drops.roll(beats, tempo, bar), window[1])
        roll_notes = sorted(roll_notes, key=lambda n: n.start_s) or None
        beat_notes = None
        beat_name = "beat"
        if added is not None:
            beat_notes = vm.added_beat(g.events(added, beats, rest, body.swing,
                                                humanize=body.humanize))
            beat_name = ("your reference's beat" if added.source == "your reference"
                         else f"{added.name} beat")
        elif body.four_on_the_floor:
            beat_notes = vm.added_beat(g.events(g.BUILT_IN["four on the floor"], beats, rest))
            beat_name = "four on the floor"

        data, contents = vm.write(tempo, pitched, drummer, beat_notes, beat_name, roll_notes)
        bpm = round(body.target_bpm) if body.target_bpm else "same"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"version.{bpm}.mid"
        path.write_bytes(data)
        missing = [s for s in wanted if s not in pitched and s != StemKind.DRUMS.value]
        notes = []
        if missing:
            notes.append(f"Nothing pitched came back from: {', '.join(missing)}.")
        notes.append("Not in the file because they are sounds rather than notes: the riser, "
                     "the impact and the pump - your DAW's sidechain and FX do those.")
        return {
            "ok": True,
            "tempo_bpm": round(tempo, 2),
            "tracks": [{"name": n, "notes": c} for n, c in contents],
            "midi": f"/api/v1/tracks/{track_id}/version/{path.name}",
            "notes": notes,
        }

    return to_response(jobs.submit("version-midi", track_id, work))


@router.get("/{track_id}/midi")
def download_midi(
    track_id: str,
    settings: Settings = Depends(get_config),
    registry: TrackRegistry = Depends(get_registry),
) -> Response:
    """Every transcribed part as one multi-track MIDI file. X0R-503.

    Synchronous and therefore slow on a first call - it transcribes whatever has not been
    transcribed yet. Worth it: this is the hand-off to a DAW, where the re-sequencing and
    the tempo change this application will not do are the user's own work.
    """
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc
    if record.separation is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Separate the track first.")

    from app.domain.midi import write_midi
    from app.domain.notes import coalesce

    parts: dict[str, list] = {}
    for stem in record.separation.stems:
        if stem.kind is StemKind.DRUMS:
            continue
        try:
            found = _transcribe(settings, stem.kind, Path(stem.path)).notes
        except Exception:
            log.info("no notes from %s", stem.kind.value, exc_info=True)
            continue
        if found:
            parts[stem.kind.value] = coalesce(list(found))

    if not parts:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing pitched was transcribed.")

    tempo = getattr(record.timing, "tempo_bpm", 0.0) or 120.0
    data = write_midi(parts, tempo_bpm=tempo)
    return Response(
        content=data,
        media_type="audio/midi",
        headers={"Content-Disposition": f'attachment; filename="{track_id[:8]}.mid"'},
    )


@router.post("/{track_id}/reference/drums", response_model=JobResponse)
def compare_drums(
    track_id: str,
    budget: str = Query("nudge", description="nudge | further | closest"),
    settings: Settings = Depends(get_config),
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
    jobs: JobStore = Depends(get_jobs),
) -> JobResponse:
    """Your kick against their kick, and the snare, the cymbals and the toms.

    The drums row is the one place in the six where the stem is not an instrument: told
    "the reference's drums have more weight", nobody can tell whether that is the kick's
    sub or the snare's body, and those are opposite moves. This splits both sides' drums
    again and runs the same seven-dimension comparison on each drum, so the advice arrives
    in the only form it can be taken in.

    Four dimensions on a kick and a snare, six on cymbals and toms - see
    `instrument.NEVER_MOVE_SIDEWAYS`, which kick and snare join. A separated kick is the
    most mono signal this application handles and a pan finding on it would be reporting
    separation bleed.

    Cached per side on the track, because nothing about a split changes between two
    comparisons of the same pair, and read from a saved profile when the reference came
    from one - which is the whole reason a profile carries the four drums.
    """
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    capability = _per_drum_capability(record, settings)
    if not capability["available"]:
        raise HTTPException(status.HTTP_409_CONFLICT, capability["reason"])

    saved = getattr(record, "reference_profile", None)
    from_profile = capability["reference_kind"] == "profile"
    mine_drums = _drums_path(record.separation)
    theirs_drums = _drums_path(record.reference_stems or {})
    theirs_saved = dict(saved.drums) if from_profile else {}
    reference_name = saved.name if from_profile else ""
    cached = dict(record.drum_stems or {})
    models_dir = settings.models_dir

    def split(side: str, drums_path: Path, handle: JobHandle, at: float) -> dict:
        """One side's drums, split into four - or the split that already happened."""
        have = cached.get(side)
        if have and all(Path(p).exists() for p in have.values()):
            return {k: Path(v) for k, v in have.items()}

        from app.services.drums import separate as drumsep

        handle.update(JobState.RUNNING, at, f"splitting the {side} drums into four")
        stems = drumsep.separate(
            Path(drums_path), storage.drum_stems_dir(track_id, side), models_dir
        )
        if not stems:
            raise RuntimeError(f"the {side} drums produced no sub-stems")
        registry.set_drum_stems(track_id, side, {k: str(v) for k, v in stems.items()})
        return stems

    def work(handle: JobHandle) -> dict:
        from app.services.mastering import subdrum
        from app.services.mastering.budget import limits_for

        handle.update(JobState.RUNNING, 0.05, "splitting your drums")
        mine_stems = split("source", mine_drums, handle, 0.05)
        mine = subdrum.profile_all(mine_stems)

        theirs_stems: dict = {}
        if from_profile:
            # Measured once, whenever that profile was saved. Half the cost of this
            # feature, gone, for every song ever aimed at the same record.
            handle.update(JobState.RUNNING, 0.85, "reading the saved reference's drums")
            theirs = subdrum.from_snapshot_all(theirs_saved)
        else:
            theirs_stems = split("reference", theirs_drums, handle, 0.5)
            handle.update(JobState.RUNNING, 0.85, "measuring the reference's drums")
            theirs = subdrum.profile_all(theirs_stems)

        handle.update(JobState.RUNNING, 0.95, "comparing them, drum by drum")
        moves = subdrum.compare_all(mine, theirs, limits=limits_for(budget))

        # Whether the bass gets out of the kick's way, on both sides. Measured here
        # because here is the only place both kicks already exist as their own files -
        # anywhere else it would mean a second drum separation for one row.
        from app.services.mastering import sidechain as sidechain_module

        duck_moves = sidechain_module.compare(
            _duck_measurement(
                mine_stems.get("kick"), _stem_path(record.separation, StemKind.BASS)
            ),
            _duck_measurement(
                (theirs_stems or {}).get("kick"),
                _stem_path(record.reference_stems or {}, StemKind.BASS),
            ),
            limits=limits_for(budget),
        )

        drums = []
        for name in subdrum.DRUMS:
            a = mine.get(name)
            if a is None:
                continue
            b = theirs.get(name)
            label, plural = subdrum.words(name)
            drums.append(
                {
                    "drum": name,
                    "label": label,
                    "plural": plural,
                    "in_reference": bool(b is not None and b.present),
                    "in_yours": bool(a.present),
                    # One sentence naming which side is empty and the figures behind it,
                    # or empty when both sides really play it.
                    "absent_reason": subdrum.why_absent(a, b),
                    # How much of each file is not the drum on its label. X0R-1413:
                    # Ryan soloed the reference's kick and heard snares, and nothing in
                    # the application could tell him whether that was the record or the
                    # separation. Measured per side, because on the pair that prompted
                    # this the source's kick came out 15.6 dB cleaner than the
                    # reference's - so one figure for both would have hidden the answer.
                    "bleed_db": _bleed_for(mine_stems.get(name), name),
                    "reference_bleed_db": _bleed_for((theirs_stems or {}).get(name), name),
                    "yours": _profile_json(a),
                    "reference": _profile_json(b) if b is not None else None,
                    "reference_audio": not from_profile,
                    # The band-to-filter solve for this drum, so a tone dial moved while
                    # that drum is auditioning runs the same EQ the render will.
                    "tone_solver": _tone_solver_json(a),
                    "moves": [_move_json(m) for m in moves.get(name, [])],
                }
            )

        return {
            "available": True,
            "reference_kind": "profile" if from_profile else "stems",
            "reference_name": reference_name,
            "budget": budget,
            "measured": len(drums),
            # The bass against the kick. Sent beside the four drums rather than inside
            # one of them: it is a finding about the bass, measured here only because
            # this is where both kicks exist as their own files. Always present, because
            # abstaining is the common outcome and a row that disappears when the answer
            # is "could not tell" is indistinguishable from a broken feature.
            "sidechain": [_move_json(m) for m in duck_moves],
            # Repeated here so a caveat shown on screen and a caveat written into a
            # finding's detail cannot say two different things.
            "bleed_caveat": subdrum.BLEED_CAVEAT,
            "drums": drums,
        }

    return to_response(jobs.submit("compare-drums", track_id, work))


@router.get("/{track_id}/drums/{side}/{drum}/audio")
def stream_drum_stem(
    track_id: str,
    side: str,
    drum: str,
    request: Request,
    registry: TrackRegistry = Depends(get_registry),
):
    """One separated drum, from either side, on its own.

    The point of the per-drum comparison is putting your kick next to that record's kick,
    and two numbers next to each other only get you so far. Same terms as the reference
    stem route above: playback only, the reference is analyzed and never sampled, and the
    rights attestation collected at upload is what makes playing it back the user's own
    recording to play.

    `side` and `drum` are both matched against fixed lists before either reaches a path.
    """
    from app.services.mastering import subdrum

    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    if side not in ("source", "reference") or drum not in subdrum.DRUMS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown drum.")

    path = ((record.drum_stems or {}).get(side) or {}).get(drum)
    if path is None or not Path(path).exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Those drums have not been split into four, or have no such drum.",
        )

    from app.api.routes_audio import ranged_file

    return ranged_file(Path(path), request)


@router.post(
    "/{track_id}/master", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED
)
def start_master(
    track_id: str,
    body: MasterJobRequest,
    settings: Settings = Depends(get_config),
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

    # A saved profile stands in for reference audio at the whole-mix stage, so a track
    # aimed at one masters without a reference file existing anywhere.
    reference_profile = getattr(record, "reference_profile", None)

    reference = None
    if body.reference_track_id:
        reference = storage.reference_path(body.reference_track_id)
        if reference is None and reference_profile is None:
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

    drum_stems = {
        name: Path(path)
        for name, path in ((record.drum_stems or {}).get("source") or {}).items()
    }
    drum_shapes = _drum_shapes(body.drums, drum_stems)

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
        reference_profile=reference_profile if reference is None else None,
        reference_stems=reference_stems,
        source=(
            storage.normalized_path(track_id)
            if storage.normalized_path(track_id).exists()
            else storage.source_path(track_id)
        ),
        preserve_source=body.preserve_source,
        tags=_export_tags(record),
        bitrate_kbps=body.bitrate_kbps,
        budget=body.budget,
        match_strength=body.match_strength,
        match_stem_levels=body.match_stem_levels,
        match_stem_tone=body.match_stem_tone,
        match_stem_width=body.match_stem_width,
        vocal_presence=presence,
        vocal_duck_db=body.vocal_duck_db,
        revoice=dict(body.revoice),
        # Where `/revoice` put each render. Resolved here rather than in the pipeline so
        # that a render deleted by retention since it was made is simply absent, and the
        # part comes back as recorded instead of as silence.
        revoiced_audio={
            stem: path
            for stem, voice in body.revoice.items()
            if (path := storage.exports_dir(track_id) / f"{stem}.{voice}.wav").exists()
        },
        drum_kit=body.drum_kit,
        drum_targets=tuple(body.drum_targets),
        drum_blend=body.drum_blend,
        # Per-drum separation, when the weights are installed and it is switched on.
        # `_drum_hits` falls back to the classifier rather than failing if either is
        # missing, so this is safe to pass unconditionally.
        drumsep=settings.drumsep_enabled,
        models_dir=settings.models_dir,
        # Moves taken on one drum inside the drums stem. Both empty is the usual case
        # and costs exactly nothing: `_apply_per_drum` reads no audio and returns the
        # drums it was handed, so a master with no per-drum move is the same file it
        # always was.
        drum_stems=drum_stems,
        drum_shapes=drum_shapes,
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
        wav_depth=body.wav_depth,
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
            "quantisation": result.quantisation,
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


@router.get("/{track_id}/master/spectrum")
def master_spectrum(
    track_id: str,
    storage: TrackStorage = Depends(get_storage),
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """Your song, your master and the reference as three tonal curves on one axis.

    The report above this says what the match decided and by how much. This says whether it
    worked - whether the master actually sits between where you started and where you were
    aiming, or whether it overshot, or moved the wrong band. That question was previously
    answerable only by exporting the file and opening it in something else, which is a long
    way to go to check a claim the tool is already making in prose.

    Every curve is level-matched and smoothed to a third of an octave, which is the width
    the correction engine works at - see `spectrum_view` for why both of those are what
    make the picture honest rather than merely pretty.

    Partial answers are normal and are returned as such. Before a master is rendered there
    are two curves rather than three, which is still the useful comparison: it is the gap
    you are about to close.
    """
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    from app.services.mastering import spectrum_view

    exports = storage.exports_dir(track_id)
    source_path = storage.source_path(track_id)
    mastered_path = exports / "mastered.wav"
    mix_path = exports / "mix.wav"
    reference_path = storage.reference_path(track_id)
    saved = getattr(record, "reference_profile", None)

    # `mastered.wav` is the mix after the reference match; `mix.wav` is the mix before it.
    # Without a reference the pipeline never writes the first, so the second is what "your
    # master" means, and the label says which one is on screen.
    rendered = mastered_path if mastered_path.exists() else mix_path

    curves: list[spectrum_view.Curve] = []

    if (buffer := spectrum_view.read(source_path)) is not None:
        curves.append(
            spectrum_view.measure(buffer.samples, buffer.sample_rate, "source", "Your song")
        )

    if (buffer := spectrum_view.read(rendered)) is not None:
        curves.append(
            spectrum_view.measure(
                buffer.samples,
                buffer.sample_rate,
                "master",
                "Master" if rendered is mastered_path else "Your mix (not mastered yet)",
            )
        )

    # A reference file when there is one, its saved measurements when there is not. The
    # two are the same curve by different routes, which is the premise of a profile.
    if (buffer := spectrum_view.read(reference_path)) is not None:
        label = getattr(record, "reference_name", "") or "Reference"
        curves.append(
            spectrum_view.measure(buffer.samples, buffer.sample_rate, "reference", label)
        )
    elif saved is not None:
        curves.append(spectrum_view.from_profile(saved, label=saved.name))

    if len(curves) < 2:
        return {
            "available": False,
            "why": "There is only one recording to draw. Add a reference, or render a "
            "master, and this becomes a comparison.",
            "curves": [_curve_json(c) for c in curves],
        }

    by_key = {c.key: c for c in curves}
    low, high = spectrum_view.window(curves)
    reference = by_key.get("reference")

    return {
        "available": True,
        "hz": [round(float(v), 2) for v in spectrum_view.axis()],
        "curves": [_curve_json(c) for c in curves],
        # The vertical range every curve shares. Sent rather than computed in the browser
        # so the axis labels and the lines cannot disagree about where 0 is.
        "floor_db": low,
        "ceiling_db": high,
        # The slope taken out of every curve so a mix reads roughly level and the vertical
        # range is spent on the departures. Sent so the axis can say what it is showing.
        "tilt_db_per_octave": spectrum_view.DISPLAY_TILT_DB_PER_OCTAVE,
        "tilt_pivot_hz": spectrum_view.TILT_PIVOT_HZ,
        # The band drawn, which is also the band scaled — see `spectrum_view.LOW_HZ`.
        # Sent so the page never has to hold a second opinion about where the chart ends.
        "low_hz": spectrum_view.LOW_HZ,
        "high_hz": spectrum_view.HIGH_HZ,
        # What is left between the master and the reference, per point. The number the
        # whole panel exists to show, so it is computed here rather than left to the page
        # to subtract two arrays and hope it picked the right pair.
        "remaining_db": (
            spectrum_view.difference(by_key["master"], reference)
            if reference is not None and "master" in by_key
            else []
        ),
        "started_db": (
            spectrum_view.difference(by_key["source"], reference)
            if reference is not None and "source" in by_key
            else []
        ),
        # The bands the per-instrument screen speaks in, so the two screens can be read
        # against each other instead of being two unrelated pictures of the same song.
        "bands": [
            {"band": name, "low_hz": lo, "high_hz": hi}
            for name, lo, hi in _BANDS_FOR_DISPLAY
        ],
    }


def _curve_json(curve) -> dict:
    return {
        "key": curve.key,
        "label": curve.label,
        "db": curve.db,
        "flat_db": curve.flat_db,
        "lufs": curve.lufs,
        "shifted_db": curve.shifted_db,
        "source": curve.source,
    }


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

    # A track aimed at a saved profile has no reference file, and still has everything
    # this endpoint needs: the profile carries the spectrum, width, loudness and peak.
    profile = getattr(record, "reference_profile", None)
    reference = storage.reference_path(track_id)
    if (reference is None or not reference.exists()) and profile is None:
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
        target = read_audio(reference) if reference is not None and reference.exists() else None
    except ImportError as exc:  # pragma: no cover - numpy/soundfile are hard requirements
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "numpy/soundfile are required."
        ) from exc

    result = suggest(
        source.samples,
        target.samples if target is not None else None,
        source.sample_rate,
        profile=profile,
    )

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
    if source_stems and reference is not None and reference.exists():
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

        # Needs both waveforms - it measures continuity and transients, which a profile
        # does not carry. On a profile the tonal findings still arrive; these do not.
        finishing = (
            suggest_finishing(
                source.samples,
                target.samples,
                source.sample_rate,
                target.sample_rate,
                loaded_stems or None,
            )
            if target is not None
            else []
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


@router.get("/budgets")
def budgets() -> dict:
    """The notches of the one control in this application with a measured effect.

    Worth stating plainly, because the page already has a "Match strength" slider that
    looks like it does this job. It does not: sweeping it from 0.4 to 1.0 moves the mean
    spectral distance to the reference by 0.56 dB, under half the 1.2 dB this codebase
    calls a meaningful gap, because it scales a curve that has already been clamped and
    is clipped at 1.0. The clamps behind it are worth three and a half times as much, and
    this is the control that moves them.
    """
    from app.services.mastering import budget as budgets_module

    return {
        "budgets": budgets_module.as_json(),
        "default": budgets_module.DEFAULT,
        # Said here so the page can put it next to the control rather than inventing its
        # own wording for it.
        "note": (
            "Raises the ceiling on every move, never the share of the gap taken. A big "
            "difference between the two records is allowed to move further; a small one "
            "does not move at all, and nothing ever becomes a copy - the largest move "
            "any setting can make is still half the measured gap."
        ),
    }


@router.get("/drum-kits")
def drum_kits(settings: Settings = Depends(get_config)) -> dict:
    """The kits available to lay over a drum track, and what they are.

    Synthesised rather than sampled, for the same reason a reference is analyzed and never
    sampled: shipping recorded hits would mean shipping someone's recordings.

    Also says **which of two routes this machine will take** to decide where a sample
    goes, because they are not the same feature and they fail differently. With the
    DrumSep weights installed, a stroke in the kick file is a kick and there is nothing
    to get wrong. Without them, a band-rise classifier decides, and on real material a
    quarter of the kicks sit within a few dB of the line that separates kick from snare -
    which is heard as a snare that comes and goes between consecutive kicks. The panel
    used to describe both with one sentence. (X0R-1316.)
    """
    from app.services.drums import separate as drumsep
    from app.services.drums.kit import DRUMS, KITS, VOICE_FOR_STEM

    descriptions = {
        "tight": "Short and controlled. Modern rock and pop.",
        "roomy": "Longer decays, more air around each hit.",
        "punchy": "Fast and forward, with more attack.",
    }
    per_drum = drumsep.available(settings.models_dir)
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
        "per_drum": {
            "available": per_drum,
            "reason": "" if per_drum else drumsep.why_unavailable(settings.models_dir),
            # What a separated stem is called against what it drives. The hi-hat box is
            # fed by the cymbals stem, which holds hats, rides and crashes together -
            # the model that splits them apart was rejected on its licence - so the box
            # has to say "cymbals" when this route is the one running.
            "voices": dict(VOICE_FOR_STEM),
        },
    }

class AskRequest(BaseModel):
    """One sentence, plus where every fader currently stands.

    The page owns the controls and this service does not keep any state about them - a
    deliberate consequence of EPIC-07 being a `NON-GOAL`. So the request carries them,
    and the response names absolute values rather than deltas, which is what keeps a
    clamp on this side from disagreeing with the slider on that side.
    """

    text: str = Field(max_length=400)
    #: {stem: {control: value}}, as the mixer has them right now.
    lanes: dict[str, dict[str, float]] = Field(default_factory=dict)
    #: The same, as they stood when the conversation opened. `ask.CEILING` is measured
    #: from here, so somebody who dragged a fader by hand is not refused their first ask.
    baseline: dict[str, dict[str, float]] | None = None
    #: The instrument comparison, if one has been run. Sent by the page rather than
    #: recomputed here: it costs about half the song's length to produce (X0R-1403), and
    #: asking a question must not cost that.
    comparison: dict | None = None


@router.post("/{track_id}/ask")
def ask_for_a_change(
    track_id: str,
    body: AskRequest,
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """Say what you want in words, and have it move the controls that already exist.

    The comparison, when one has been run, is passed in from the page rather than
    recomputed: it costs about half the song's length to produce (X0R-1403) and asking a
    question must not cost that. What it buys is the second sentence of every reply -
    where the measurement had you, before you asked for more of it.
    """
    from app.services.mastering import ask as ask_module

    try:
        registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    answer = ask_module.interpret(
        body.text,
        lanes=body.lanes,
        baseline=body.baseline,
        comparison=body.comparison,
    )
    return {
        "understood": answer.understood,
        "reply": answer.reply,
        "heard": answer.heard,
        "suggestions": list(answer.suggestions),
        "changes": [
            {
                "control": change.control,
                "stem": change.stem,
                "delta": change.delta,
                "to": change.to,
                "clamped": change.clamped,
            }
            for change in answer.changes
        ],
    }


@router.get("/ask/vocabulary")
def ask_vocabulary() -> dict:
    """Everything the box understands, so the page can show it instead of guessing.

    A parser with a vocabulary rather than a language model has exactly one obligation:
    to be honest about where its edges are. This is that obligation as an endpoint.
    """
    from app.services.mastering import ask as ask_module

    return {
        "examples": list(ask_module.EXAMPLES),
        # Split by what the word *is*, not by whether it is scoped to a stem. "Pump" is
        # bass-only because the bass against the kick is the only pair this measures, and
        # listing it under "parts" made the help text read "bass, vocal, drums, pump".
        "parts": [
            {"label": t.label, "words": list(t.words)}
            for t in ask_module.TARGETS
            if t.control == "gain_db"
        ],
        "tone": [
            {"label": t.label, "words": list(t.words)}
            for t in ask_module.TARGETS
            if t.control != "gain_db"
        ],
        "qualities": sorted(ask_module.QUALITIES),
        "amounts": ["a little", "(plain)", "a lot"],
        "note": (
            "It reads a vocabulary rather than English, so it will say when it has not "
            "understood rather than quietly doing nothing. Everything it moves is a "
            "control you can also drag, and every reply says what the reference "
            "comparison makes of what you asked for."
        ),
    }


class CombineProfilesRequest(BaseModel):
    """One profile for the mix, and a different one for named instruments.

    Ryan's idea: guitars from a pop-punk record, drums from a dance one. The rule it runs
    on is **character, not balance** - see `profile.combine` - so a borrowed instrument
    contributes its tone, dynamics, placement and width, and declines to suggest a level.
    """

    #: The profile the whole-mix half comes from: the curve, the loudness, the peaks, the
    #: width. Not merged with anything, because averaging finished masters invents a record
    #: nobody made.
    base: str
    #: stem name -> the profile to take that instrument from.
    instruments: dict[str, str] = Field(default_factory=dict)
    #: Keep the result under this name. Omitted, it is used for this track and not saved,
    #: which is the shape of trying one out.
    save_as: str | None = Field(default=None, max_length=120)


def _combined(settings, body: CombineProfilesRequest):
    """Resolve the named profiles and merge them, or raise with the one that was missing."""
    from app.services.mastering.profile import combine, find

    base = find(settings.profile_dir, body.base)
    if base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No saved profile {body.base!r}.")

    borrowed = {}
    for stem, name in body.instruments.items():
        if name == body.base:
            # Asking for the base's own instrument is not an error, it is the default.
            continue
        source = find(settings.profile_dir, name)
        if source is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No saved profile {name!r}.")
        borrowed[stem] = source

    made = combine(body.save_as or f"{base.name} + borrowed", base, borrowed)
    # What was asked for but could not be lent: a profile whose reference was never
    # separated has no instruments to give. Returned rather than raised, because the rest
    # of the combination is perfectly usable and refusing all of it would be the wrong
    # trade.
    unavailable = sorted(set(borrowed) - set(made.instrument_sources))
    return made, unavailable


@router.post("/{track_id}/reference/combine-profiles", status_code=status.HTTP_200_OK)
def combine_reference_profiles(
    track_id: str,
    body: CombineProfilesRequest,
    settings: Settings = Depends(get_config),
    registry: TrackRegistry = Depends(get_registry),
) -> dict:
    """Aim this track at several profiles at once, one per instrument.

    The comparison downstream does not learn about this. It reads the reference side out
    of a per-stem dict, and this builds that dict from several records instead of one -
    which is why the feature is a change at one seam rather than everywhere.
    """
    try:
        registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    made, unavailable = _combined(settings, body)

    saved_to = None
    if body.save_as:
        from app.services.mastering.profile import save

        saved_to = save(made, settings.profile_dir).name

    registry.set_reference_profile(track_id, made)
    return {
        "name": made.name,
        "base": made.base_profile,
        "borrowed": made.instrument_sources,
        "saved": bool(saved_to),
        "per_stem_available": made.has_instruments,
        "instruments": sorted(made.instruments),
        "per_drum_available": made.has_drums,
        "drums": sorted(made.drums),
        # Said rather than discovered: a profile captured from an unseparated reference
        # has no instruments to lend, and silently using the base's would look like the
        # borrowing had worked.
        "unavailable": unavailable,
        "note": (
            "A borrowed instrument brings its tone, dynamics, placement and width. It "
            "does not bring its level: how loud an instrument sits is a fact about the "
            "mix it sat in, so matching a borrowed level would place yours against "
            "neighbours that record never had. The overall tone, loudness and width all "
            f"come from {made.base_profile!r}."
        ),
    }

def _figure_json(figure) -> dict:
    """One measured number, or an honest refusal, in the shape the page reads.

    `basis` travels with the value on purpose - "43 hats over 15.1 bars" is the reader's
    only way to disagree with a figure, and a number without its sample size invites
    exactly the confidence it has not earned.
    """
    return {
        "value": None if figure.value is None else round(float(figure.value), 2),
        "confidence": round(float(figure.confidence), 3),
        "unit": figure.unit,
        "basis": figure.basis,
        "caveat": figure.caveat,
        "measured": bool(figure.measured),
    }


def _fingerprint_json(print_) -> dict:
    """Everything one record's groove measured out to, as plain types."""
    return {
        "name": print_.name,
        "duration_s": round(print_.duration_s, 2),
        "tempo_bpm": round(print_.grid.tempo_bpm, 1),
        "beats_per_bar": print_.grid.beats_per_bar,
        "grid_confidence": round(print_.grid.confidence, 3),
        # How well the *bar length* is supported, which is a separate question from the
        # beat and the one a histogram actually rests on. X0R-1319 criterion 4: this was
        # computed by `detect_beats_per_bar`, written to a log and dropped, so every
        # consumer saw a bar length with no way to tell whether it had been read or
        # assumed - and drew bars against it regardless.
        "metre_confidence": round(getattr(print_.grid, "metre_confidence", 0.0), 3),
        "metre_resolved": bool(getattr(print_.grid, "metre_resolved", False)),
        # Whether the *tempo* explains the drumming, measured against what random times would
        # have scored. X0R-1319 criterion 5, and a different question from `grid_confidence`:
        # that is an F-measure over onsets, it read 0.57-0.61 on a right answer and a wrong
        # one alike, and so nothing could ever gate on it. This separated 0.72 from 0.03 on
        # real stems.
        #
        # Reported next to the figures rather than used to suppress them, because the page is
        # what decides how to show a number it cannot stand behind - and a route that silently
        # returned fewer keys would break every client that reads them.
        "grid_lock": round(getattr(print_.grid, "lock", 0.0), 3),
        "grid_locked": bool(getattr(print_.grid, "locked", False)),
        "bars": round(print_.grid.bars, 1),
        "key": print_.key_name,
        "key_confidence": round(print_.key_confidence, 3),
        "metre_source": print_.metre_source,
        # Where each drum falls across the bar, in sixteenths. The shape of a groove, and
        # the one thing here that is a picture rather than a number.
        "kick_histogram": list(print_.kick_histogram),
        "snare_histogram": list(print_.snare_histogram),
        "hat_histogram": list(print_.hat_histogram),
        "kick_on_beats": list(print_.kick_on_beats),
        "kick_on_downbeats": list(print_.kick_on_downbeats),
        "snare_on_backbeats": list(print_.snare_on_backbeats),
        "hat_offbeat_share": _figure_json(print_.hat_offbeat_share),
        "swing": _figure_json(print_.swing),
        "timing": {
            drum: {
                "raw_ms": _figure_json(spread.raw_ms),
                "detrended_ms": _figure_json(spread.detrended_ms),
                "resolution_floor_ms": round(spread.resolution_floor_ms, 1),
            }
            for drum, spread in (print_.timing or {}).items()
        },
        "duck": (
            None
            if print_.duck is None
            else {
                "dip_db": _figure_json(print_.duck.dip_db),
                "control_dip_db": _figure_json(print_.duck.control_dip_db),
                "excess_db": _figure_json(print_.duck.excess_db),
                "kicks_examined": print_.duck.kicks_examined,
                "kicks_bass_silent": print_.duck.kicks_bass_silent,
                "kicks_total": print_.duck.kicks_total,
            }
        ),
    }


@router.post(
    "/{track_id}/groove", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED
)
def compare_groove(
    track_id: str,
    request: Request,
    jobs: JobStore = Depends(get_jobs),
    registry: TrackRegistry = Depends(get_registry),
    storage: TrackStorage = Depends(get_storage),
):
    """What each record does rhythmically, measured, side by side.

    EPIC-13 stage 1. The measurements have existed and been tested for weeks -
    `analysis.fingerprint.measure` reads the beat grid, where each drum falls across the
    bar, how far from the grid it sits, the swing, and whether the bass ducks to the kick
    - and **no route ever called it**, so none of it had ever been on a screen.

    **Nothing here has a dial behind it, and the response says so.** Experiment 2 measured
    that processing gets you tone and never groove: the drum layer moves the tonal gap by
    at most 0.09 dB and places zero new grid positions. Where a reference's hats sit
    against the beat is a fact about a performance, and moving yours there would be
    composition rather than mastering - which is X0R-1307's whole point and the line this
    epic's governing sentence draws. So this reports and offers nothing, deliberately.
    """
    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    mine_stems = {
        kind: path
        for kind in StemKind
        if (path := _stem_path(record.separation, kind)) is not None
    }
    if not mine_stems:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Separate this track before reading its groove."
        )

    source = storage.normalized_path(track_id)
    if not source.exists():
        source = storage.source_path(track_id)
    if source is None or not Path(source).exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "This track's audio is gone.")

    reference = storage.reference_path(track_id)
    theirs_stems = {
        kind: Path(path) for kind, path in (record.reference_stems or {}).items()
    }

    def work(handle: JobHandle) -> dict:
        from app.services.analysis.fingerprint import measure

        plan = GROOVE_BOTH_SIDES if theirs_stems else GROOVE_ONE_SIDE

        plan.report(handle, "mine")
        mine = measure(Path(source), mine_stems, timing=record.timing, name="yours")

        theirs = None
        plan.report(handle, "theirs")
        if theirs_stems and reference is not None and reference.exists():
            theirs = measure(Path(reference), theirs_stems, name="the reference")

        plan.report(handle, "comparing")
        return {
            "yours": _fingerprint_json(mine),
            "reference": _fingerprint_json(theirs) if theirs else None,
            # Said with the measurements rather than beside them, because the whole risk
            # of putting groove on a screen is that somebody reads it as a to-do list.
            "note": (
                "These are observations, not suggestions - there is no control here and "
                "there is not going to be one. Experiment 2 measured that processing "
                "gets you tone and never groove: where a record's hats sit against the "
                "beat is a fact about a performance, and moving yours there would be "
                "composition rather than mastering."
            ),
            "reference_measured": theirs is not None,
            "why_no_reference": (
                ""
                if theirs is not None
                else "The reference has not been separated, so only your own groove was read."
            ),
        }

    return to_response(jobs.submit("groove", track_id, work))
