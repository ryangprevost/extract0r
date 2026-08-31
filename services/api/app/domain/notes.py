"""Core musical primitives shared by every transcription backend.

Deliberately dependency-free: everything in :mod:`app.domain` is pure Python so the
tab engine can be unit-tested without torch, librosa, or ffmpeg installed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

# MIDI note number of A4 (440 Hz), the anchor for all pitch math.
A4_MIDI = 69
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


class StemKind(StrEnum):
    """The stems Extract0r knows how to reason about."""

    VOCALS = "vocals"
    DRUMS = "drums"
    BASS = "bass"
    GUITAR = "guitar"
    PIANO = "piano"
    OTHER = "other"

    @property
    def is_pitched(self) -> bool:
        return self not in (StemKind.DRUMS,)

    @property
    def default_notation(self) -> Notation:
        if self is StemKind.DRUMS:
            return Notation.DRUM_TAB
        if self in (StemKind.GUITAR, StemKind.BASS, StemKind.OTHER):
            return Notation.STRING_TAB
        return Notation.PITCH_LIST


class Notation(StrEnum):
    STRING_TAB = "string_tab"
    DRUM_TAB = "drum_tab"
    PITCH_LIST = "pitch_list"


@dataclass(frozen=True, slots=True)
class NoteEvent:
    """A single detected note, in seconds and MIDI pitch.

    This is the hand-off contract between *any* transcription backend (basic-pitch,
    CREPE, a drum onset classifier, or the deterministic stub) and the tab engine.
    """

    start_s: float
    end_s: float
    pitch: int
    velocity: int = 96
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.end_s < self.start_s:
            raise ValueError(f"note ends before it starts: {self.start_s} -> {self.end_s}")
        if not 0 <= self.pitch <= 127:
            raise ValueError(f"pitch {self.pitch} outside MIDI range")

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    @property
    def name(self) -> str:
        return f"{NOTE_NAMES[self.pitch % 12]}{self.pitch // 12 - 1}"


@dataclass(slots=True)
class Transcription:
    """The full result of transcribing one stem."""

    stem: StemKind
    notes: list[NoteEvent] = field(default_factory=list)
    tempo_bpm: float = 120.0
    time_signature: tuple[int, int] = (4, 4)
    backend: str = "unknown"

    def sorted_notes(self) -> list[NoteEvent]:
        return sorted(self.notes, key=lambda n: (n.start_s, n.pitch))


def cluster_by_onset(
    notes: Sequence[NoteEvent], window_s: float = 0.045
) -> list[list[NoteEvent]]:
    """Group notes that start close enough together to be played as one chord.

    ``window_s`` defaults to 45 ms, roughly the point where a listener stops hearing
    two attacks and starts hearing one.
    """
    clusters: list[list[NoteEvent]] = []
    for note in sorted(notes, key=lambda n: (n.start_s, n.pitch)):
        if clusters and note.start_s - clusters[-1][0].start_s <= window_s:
            clusters[-1].append(note)
        else:
            clusters.append([note])
    return clusters


def quantize(value_s: float, tempo_bpm: float, division: int = 16) -> int:
    """Snap a timestamp to the nearest grid column at ``division`` notes per whole note."""
    seconds_per_column = (60.0 / tempo_bpm) * (4.0 / division)
    return int(round(value_s / seconds_per_column))


def pitch_range(notes: Iterable[NoteEvent]) -> tuple[int, int] | None:
    pitches = [n.pitch for n in notes]
    return (min(pitches), max(pitches)) if pitches else None
