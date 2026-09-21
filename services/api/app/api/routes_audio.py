"""Serving separated stems back to the browser: audio to play, peaks to draw.

Two endpoints, and they exist for the same reason. When a transcription looks wrong, the
first question is always "is the tab wrong, or was the stem already wrong?" — and the only
way to answer it is to listen to the stem and look at its waveform.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse

from app.api.deps import get_registry, get_storage
from app.domain.notes import StemKind
from app.services.registry import TrackRegistry
from app.services.storage import TrackStorage
from app.services.waveform import (
    DEFAULT_PEAK_BUCKETS,
    MAX_PEAK_BUCKETS,
    measure,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tracks", tags=["audio"])

# Bump whenever the envelope maths changes, so cached files from an older scaling are
# ignored rather than silently served.
PEAKS_CACHE_VERSION = 4


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
    return ranged_file(_stem_path(track_id, stem, registry), request)


def ranged_file(path, request: Request):
    """Serve a WAV, honouring a Range header so the player can seek.

    Shared with the reference stems, which are streamed by `routes_master` for the
    side-by-side comparison. One implementation rather than two, because the seek path is
    exactly the kind of thing that gets fixed in one copy and not the other.
    """
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

    The maths lives in app.services.waveform because the mastering page compares two of
    these against each other, and a waveform that means one thing on one page and
    something else on another is worse than no waveform.
    """
    path = _stem_path(track_id, stem, registry)
    cache = path.with_suffix(f".peaks-v{PEAKS_CACHE_VERSION}-{buckets}.json")

    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.debug("discarding unreadable peak cache %s", cache.name)

    try:
        envelope = measure(path, buckets)
    except ImportError as exc:  # pragma: no cover - numpy/soundfile are hard requirements
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "numpy/soundfile are required for waveforms."
        ) from exc

    payload = {"stem": stem, **envelope.as_payload()}

    try:
        cache.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        log.debug("could not cache peaks for %s", path.name)

    return payload
