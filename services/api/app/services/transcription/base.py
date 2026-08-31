"""Transcription contract: one stem of audio in, a :class:`Transcription` out."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from app.domain.notes import StemKind, Transcription


@runtime_checkable
class Transcriber(Protocol):
    name: str

    def supports(self, stem: StemKind) -> bool:
        """True when this backend can meaningfully handle that kind of stem."""

    def available(self) -> bool:
        """True when this backend's heavy dependencies are actually installed."""

    def transcribe(self, audio: Path, stem: StemKind) -> Transcription: ...
