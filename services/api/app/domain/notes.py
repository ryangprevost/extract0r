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


#: How close two same-pitch notes must be before a merge is even considered.
#:
#: Swept rather than chosen, with the ratio guard in place and recall pinned at 1.000
#: throughout - precision 0.632 at 0.0 s, 0.649 at 0.08, **0.727 at 0.2**, 0.774 at 0.4.
#: Stopping at 0.2 leaves precision on the table deliberately: 0.2 s is under an eighth note
#: at 120 BPM, so a gap this short cannot hold a repeat a listener would hear as separate,
#: and 0.4 s can. The fixture that produced these figures repeats notes only on bar lines,
#: so it cannot tell the difference up there - and a threshold the evidence cannot support
#: is a threshold chosen by taste.
MAX_FRAGMENT_GAP_S = 0.2

#: And how much shorter the second must be than the first to count as a piece of it rather
#: than the next note. Without this a repeated chord loses an onset per repeat - see
#: `coalesce` for the figures.
FRAGMENT_RATIO = 0.6


def coalesce(
    notes: list[NoteEvent],
    max_gap_s: float = MAX_FRAGMENT_GAP_S,
    fragment_ratio: float = FRAGMENT_RATIO,
) -> list[NoteEvent]:
    """Join same-pitch fragments of one held note back into that note. X0R-1329.

    Separation leaves transcription's recall at 1.000 and its precision at 0.462: on a
    synthetic chord part put through demucs and basic-pitch, 52 notes came back where 24
    were played. Played on the instrument that recorded them nobody notices; played on a
    supersaw, every invented note is an audible wrong note.

    **The obvious filters do not work, and the measurement is why this is a merge instead.**
    A confidence floor is worthless here - the invented notes scored a *higher* median
    confidence than the real ones, 0.710 against 0.668, so a floor at 0.6 dropped 12.5% of
    the real notes and removed none of the invented. A minimum length does something and
    costs too much: precision 0.600 to 0.704, recall down to 0.792.

    What the invented notes turned out to be: **all sixteen of them sat at unison with a
    real note already sounding.** They are not hallucinations, harmonics or noise. They are
    one held note that basic-pitch broke into pieces, and a piece of a real note is
    genuinely confident, which is exactly why no threshold could see it.

    **Merging on the gap alone is not safe, and the first version of this claimed it was.**
    A part that repeats a note - the same chord across two bars, which is most music - puts
    two real onsets of the same pitch a few tens of milliseconds apart, and a gap rule eats
    one of them. Measured: recall fell from 1.000 to 0.917 merging only overlaps, and to
    0.875 at a gap of 0.2 s. The docstring here asserted the opposite until the sweep was
    run.

    So a fragment is identified by **being short relative to the note it broke off**, not by
    being close to it. A 0.2 s event touching a 0.95 s note of the same pitch is a piece of
    it; a 0.95 s event touching another 0.95 s event is the next bar. `FRAGMENT_RATIO` is
    where that line sits.

    Velocity and confidence come from the longer side, which is the one most likely to be
    the note rather than its tail.
    """
    if not notes:
        return []

    out: list[NoteEvent] = []
    for note in sorted(notes, key=lambda n: (n.pitch, n.start_s)):
        previous = out[-1] if out else None
        joins = False
        if previous is not None and previous.pitch == note.pitch:
            gap = note.start_s - previous.end_s
            held = previous.end_s - previous.start_s
            piece = note.end_s - note.start_s
            joins = gap <= max_gap_s and (
                gap < 0 or piece <= fragment_ratio * max(held, 1e-9)
            )
        if not joins:
            out.append(note)
            continue
        longer = previous if previous.end_s - previous.start_s >= note.end_s - note.start_s else note
        out[-1] = NoteEvent(
            start_s=previous.start_s,
            end_s=max(previous.end_s, note.end_s),
            pitch=note.pitch,
            velocity=longer.velocity,
            confidence=longer.confidence,
        )
    return sorted(out, key=lambda n: (n.start_s, n.pitch))
