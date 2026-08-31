"""Local-disk storage for uploads and job artifacts.

One directory per track id keeps cleanup trivial: retention is `rmtree` on a folder,
which matters because "we delete your audio" has to be true, not aspirational.
"""

from __future__ import annotations

import hashlib
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

ALLOWED_SUFFIXES = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".aiff", ".aif"}


class UnsupportedAudioError(ValueError):
    """The uploaded file is not an audio container we accept."""


@dataclass(frozen=True, slots=True)
class StoredTrack:
    track_id: str
    path: Path
    original_filename: str
    sha256: str
    size_bytes: int


class TrackStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def track_dir(self, track_id: str) -> Path:
        return self.root / track_id

    def stems_dir(self, track_id: str) -> Path:
        return self.track_dir(track_id) / "stems"

    def exports_dir(self, track_id: str) -> Path:
        return self.track_dir(track_id) / "exports"

    def save_upload(self, filename: str, data: bytes) -> StoredTrack:
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise UnsupportedAudioError(
                f"{suffix or 'file'} is not supported; accepted: "
                + ", ".join(sorted(ALLOWED_SUFFIXES))
            )
        track_id = uuid.uuid4().hex
        directory = self.track_dir(track_id)
        (directory / "stems").mkdir(parents=True, exist_ok=True)
        (directory / "exports").mkdir(parents=True, exist_ok=True)

        # Store under a fixed name so nothing user-controlled reaches the filesystem.
        path = directory / f"source{suffix}"
        path.write_bytes(data)
        return StoredTrack(
            track_id=track_id,
            path=path,
            original_filename=Path(filename).name,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
        )

    def source_path(self, track_id: str) -> Path | None:
        directory = self.track_dir(track_id)
        if not directory.is_dir():
            return None
        return next((p for p in directory.glob("source.*")), None)

    def delete(self, track_id: str) -> None:
        shutil.rmtree(self.track_dir(track_id), ignore_errors=True)

    def purge_expired(self, retention_hours: int) -> list[str]:
        """Delete track folders older than the retention window. Returns what went."""
        cutoff = time.time() - retention_hours * 3600
        removed: list[str] = []
        for directory in self.root.iterdir():
            if directory.is_dir() and directory.stat().st_mtime < cutoff:
                shutil.rmtree(directory, ignore_errors=True)
                removed.append(directory.name)
        return removed
