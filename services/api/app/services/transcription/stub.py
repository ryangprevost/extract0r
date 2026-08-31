"""Deterministic fake transcriber.

Seeded off the file path, so the same stem always yields the same notes. That makes
the API, the tab renderer, and the front end testable end to end with no model
weights present, and gives the UI something musical-looking to lay out.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

from app.domain.notes import NoteEvent, StemKind, Transcription

# One octave of A natural minor, plus the drum keys the GM map understands.
PITCHED_SCALE = (57, 59, 60, 62, 64, 65, 67, 69)


class StubTranscriber:
    name = "stub"

    def __init__(self, seconds: float = 8.0, tempo_bpm: float = 120.0) -> None:
        self.seconds = seconds
        self.tempo_bpm = tempo_bpm

    def supports(self, stem: StemKind) -> bool:
        return True

    def available(self) -> bool:
        return True

    def transcribe(self, audio: Path, stem: StemKind) -> Transcription:
        seed = int(hashlib.sha256(str(audio).encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        step = (60.0 / self.tempo_bpm) / 4  # sixteenth notes
        notes: list[NoteEvent] = []
        octave_shift = -24 if stem is StemKind.BASS else 0

        for index in range(int(self.seconds / step)):
            start = index * step
            if stem is StemKind.DRUMS:
                if index % 4 == 0:
                    notes.append(self._note(start, step, 36))
                if index % 8 == 4:
                    notes.append(self._note(start, step, 38))
                notes.append(self._note(start, step, 42, velocity=70))
                continue
            if rng.random() < 0.35:
                continue
            pitch = rng.choice(PITCHED_SCALE) + octave_shift
            notes.append(self._note(start, step * rng.choice((1, 2)), pitch))

        return Transcription(
            stem=stem, notes=notes, tempo_bpm=self.tempo_bpm, backend=self.name
        )

    @staticmethod
    def _note(start: float, length: float, pitch: int, velocity: int = 96) -> NoteEvent:
        return NoteEvent(
            start_s=start, end_s=start + length, pitch=pitch, velocity=velocity
        )
