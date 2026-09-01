"""Serving separated stems back to the browser: audio to play, peaks to draw.

Two endpoints, and they exist for the same reason. When a transcription looks wrong, the
first question is always "is the tab wrong, or was the stem already wrong?" — and the only
way to answer it is to listen to the stem and look at its waveform.
"""

from __future__ import annotations

import json
import logging
import math

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse

from app.api.deps import get_registry, get_storage
from app.domain.notes import StemKind
from app.services.registry import TrackRegistry
from app.services.storage import TrackStorage

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tracks", tags=["audio"])

# Enough buckets for a detailed waveform at typical widths without shipping a huge array.
DEFAULT_PEAK_BUCKETS = 1200
MAX_PEAK_BUCKETS = 4000

# Bump whenever the envelope maths changes, so cached files from an older scaling are
# ignored rather than silently served.
PEAKS_CACHE_VERSION = 3

# Anything quieter than this reads as silence. Separation always leaves low-level
# artefacts behind in the parts a stem is not playing, and on a linear scale those get
# drawn as visible "peaks in the silence". A dB floor is what makes a rest look like a
# rest.
SILENCE_FLOOR_DB = -55.0


def _stem_path(track_id: str, stem: str, registry: TrackRegistry):
    try:
        kind = StemKind(stem)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown stem {stem!r}.") from exc

    try:
        record = registry.require(track_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown track.") from exc

    if record.separation is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This track has not been separated yet.")

    separated = record.separation.by_kind(kind)
    if separated is None or not separated.path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No {stem} stem for this track.")
    return separated.path


@router.get("/{track_id}/stems/{stem}/audio")
def stream_stem(
    track_id: str,
    stem: str,
    request: Request,
    registry: TrackRegistry = Depends(get_registry),
):
    """Stream one stem, honouring Range requests so the player can seek.

    Without Range support a browser re-downloads the whole file on every seek, which for
    a five-minute stem is tens of megabytes per drag of the playhead.
    """
    path = _stem_path(track_id, stem, registry)
    size = path.stat().st_size
    range_header = request.headers.get("range")

    if not range_header:
        return FileResponse(
            path,
            media_type="audio/wav",
            headers={"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"},
        )

    start, end = _parse_range(range_header, size)
    if start is None:
        raise HTTPException(
            status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            "Range is outside the file.",
            headers={"Content-Range": f"bytes */{size}"},
        )

    def chunks(chunk_size: int = 64 * 1024):
        remaining = end - start + 1
        with path.open("rb") as handle:
            handle.seek(start)
            while remaining > 0:
                data = handle.read(min(chunk_size, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        chunks(),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type="audio/wav",
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(end - start + 1),
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, max-age=3600",
        },
    )


def _parse_range(header: str, size: int) -> tuple[int | None, int]:
    """Parse a single-range `bytes=start-end` header. Returns (None, 0) if unsatisfiable.

    Only the single-range form is handled; multipart ranges are legal HTTP but no browser
    audio element asks for them.
    """
    if not header.startswith("bytes="):
        return None, 0
    spec = header.removeprefix("bytes=").split(",")[0].strip()
    if "-" not in spec:
        return None, 0

    first, _, last = spec.partition("-")
    try:
        if not first:  # suffix form: bytes=-500 means the final 500 bytes
            length = int(last)
            if length <= 0:
                return None, 0
            start = max(0, size - length)
            return start, size - 1
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return None, 0

    end = min(end, size - 1)
    if start > end or start >= size:
        return None, 0
    return start, end


@router.get("/{track_id}/stems/{stem}/peaks")
def stem_peaks(
    track_id: str,
    stem: str,
    buckets: int = Query(DEFAULT_PEAK_BUCKETS, ge=50, le=MAX_PEAK_BUCKETS),
    registry: TrackRegistry = Depends(get_registry),
    storage: TrackStorage = Depends(get_storage),
) -> dict:
    """Amplitude envelope for drawing a waveform, computed server-side and cached.

    The alternative is shipping the whole WAV to the browser and decoding it there, which
    for six stems of a five-minute song is hundreds of megabytes.
    """
    path = _stem_path(track_id, stem, registry)
    cache = path.with_suffix(f".peaks-v{PEAKS_CACHE_VERSION}-{buckets}.json")

    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.debug("discarding unreadable peak cache %s", cache.name)

    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:  # pragma: no cover - numpy/soundfile are hard requirements
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "numpy/soundfile are required for waveforms."
        ) from exc

    with sf.SoundFile(str(path)) as handle:
        total_frames = len(handle)
        sample_rate = handle.samplerate
        # RMS per bucket, not peak. Peak is dominated by isolated samples, so a stem that
        # is essentially silent but carries a few separation artefacts draws as a row of
        # spikes. RMS reflects how loud a slice actually is.
        rms = np.zeros(buckets, dtype="float32")
        peak_linear = 0.0
        frames_per_bucket = max(1, total_frames // buckets)

        blocks = handle.blocks(blocksize=frames_per_bucket, dtype="float32", always_2d=True)
        for index, block in enumerate(blocks):
            if index >= buckets:
                break
            if block.size:
                mono = block.mean(axis=1)
                rms[index] = float(np.sqrt(np.mean(mono**2)))
                peak_linear = max(peak_linear, float(np.abs(block).max()))

    # Map to decibels and floor. Loudness is logarithmic, so a linear envelope makes
    # quiet passages invisible and near-silence look busy; dB is what a DAW draws.
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(np.maximum(rms, 1e-9))
    envelope = np.clip((db - SILENCE_FLOOR_DB) / (0.0 - SILENCE_FLOOR_DB), 0.0, 1.0)

    peak = peak_linear
    loudest_db = float(db.max()) if rms.size else SILENCE_FLOOR_DB

    payload = {
        "stem": stem,
        "buckets": buckets,
        "duration_s": round(total_frames / sample_rate, 3) if sample_rate else 0.0,
        "sample_rate": sample_rate,
        # Rounded: two decimals is well under one pixel of error at any sane height.
        "peaks": [round(float(v), 3) for v in envelope],
        # "Silent" now means "never rises above the floor", which covers a stem holding
        # nothing but separation artefacts as well as one holding literal zeros.
        "silent": bool(loudest_db <= SILENCE_FLOOR_DB),
        "peak_dbfs": round(20.0 * math.log10(peak), 1) if peak > 0 else None,
        "floor_dbfs": SILENCE_FLOOR_DB,
    }

    try:
        cache.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        log.debug("could not cache peaks for %s", path.name)

    return payload
