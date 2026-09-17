"""In-memory record of what we know about each uploaded track.

Swapped for Postgres in EPIC-07; until then this keeps the MVP dependency-free and
makes the retention promise easy to honour (drop the row, delete the folder).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.domain.timing import TimingEstimate
from app.services.audio.probe import AudioInfo
from app.services.separation.base import SeparationResult
from app.services.storage import StoredTrack


@dataclass(slots=True)
class TrackRecord:
    stored: StoredTrack
    attestation: dict[str, Any]
    audio: AudioInfo | None = None
    separation: SeparationResult | None = None
    timing: TimingEstimate | None = None
    #: Separated stems of the mastering reference, if it has been split.
    reference_stems: dict = field(default_factory=dict)
    #: What the reference was called when it arrived. On disk it becomes "reference.mp3"
    #: like every other, but an export should be able to say what it was matched against.
    reference_name: str = ""
    uploaded_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )


class TrackRegistry:
    def __init__(self) -> None:
        self._records: dict[str, TrackRecord] = {}
        self._lock = threading.Lock()

    def add(self, record: TrackRecord) -> TrackRecord:
        with self._lock:
            self._records[record.stored.track_id] = record
        return record

    def get(self, track_id: str) -> TrackRecord | None:
        with self._lock:
            return self._records.get(track_id)

    def require(self, track_id: str) -> TrackRecord:
        record = self.get(track_id)
        if record is None:
            raise KeyError(track_id)
        return record

    def set_separation(self, track_id: str, result: SeparationResult) -> None:
        with self._lock:
            if track_id in self._records:
                self._records[track_id].separation = result

    def set_timing(self, track_id: str, timing: TimingEstimate) -> None:
        with self._lock:
            if track_id in self._records:
                self._records[track_id].timing = timing

    def set_reference_stems(self, track_id: str, stems: dict) -> None:
        with self._lock:
            if track_id in self._records:
                self._records[track_id].reference_stems = stems

    def remove(self, track_id: str) -> None:
        with self._lock:
            self._records.pop(track_id, None)

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._records)
