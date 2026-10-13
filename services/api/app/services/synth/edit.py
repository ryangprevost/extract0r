"""Editing a part's notes and the added beat's steps. Sprint 6.

Ryan, 2026-10-12: *"yes, go ahead with editing notes and beats"* - reopening the
re-sequencing non-goal that every sprint before this kept closed. It is opened the way the
rest of this application opens things: **by the user, visibly.** A part nobody edits is
exactly as played; a part somebody edits says so in the version's account ("as you edited
it"), so an edit is never mistaken for the band.

### Notes are kept in beats, not seconds

A note at 2.35 s means nothing once the tempo changes; a note on beat 5.5 means the same
thing at 170 BPM and at 128. So a part's notes are stored as beat positions counted from the
song's first beat, and turned into seconds only when a part is rendered - which is what lets
an edit made at 128 survive moving the version to 140.

### What editing means here

Everything a producer does to a part in a piano roll, as plain functions on a list:
**quantise** (snap to a grid, by a chosen strength, so it can tighten without going robotic),
**groove** (lock the off-sixteenths to a swing, the way the added beat swings), and
**transpose**. Moving, adding, deleting and resizing single notes is the page's job; these are
the operations that need to be the same every time and tested.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.domain.notes import NoteEvent

#: Grids a part can be quantised to, in beats, by the names a producer uses.
GRIDS = {
    "1/4": 1.0,
    "1/8": 0.5,
    "1/16": 0.25,
    "1/8 triplet": 1.0 / 3.0,
    "1/16 triplet": 1.0 / 6.0,
}
#: A note is never shorter than this, in beats, after any edit - a 64th at any tempo.
MIN_LENGTH = 1.0 / 16.0
#: Drum notes, as General MIDI keys, and back.
DRUM_KEYS = {"kick": 36, "snare": 38, "hihat": 42}
DRUM_OF_KEY = {v: k for k, v in DRUM_KEYS.items()}


@dataclass
class BeatNote:
    """A note in beats from the song's first beat. `velocity` is MIDI 1-127."""

    beat: float
    length: float
    pitch: int
    velocity: int = 100

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, data: dict) -> BeatNote:
        return cls(beat=float(data["beat"]), length=max(MIN_LENGTH, float(data["length"])),
                   pitch=int(max(0, min(127, int(data["pitch"])))),
                   velocity=int(max(1, min(127, int(data.get("velocity", 100))))))


# --- seconds <-> beats ----------------------------------------------------------------------


def to_beats(notes: list[NoteEvent], first_beat_s: float, bpm: float) -> list[BeatNote]:
    """Notes in seconds, at `bpm`, to beats counted from the first beat."""
    period = 60.0 / bpm
    return [BeatNote((n.start_s - first_beat_s) / period,
                     max(MIN_LENGTH, (n.end_s - n.start_s) / period), int(n.pitch),
                     int(n.velocity)) for n in notes]


def to_seconds(notes: list[BeatNote], first_beat_s: float, bpm: float) -> list[NoteEvent]:
    """Beats back to seconds at `bpm` - any tempo, which is the point of keeping beats."""
    period = 60.0 / bpm
    out = []
    for n in sorted(notes, key=lambda n: (n.beat, n.pitch)):
        start = first_beat_s + n.beat * period
        if start + n.length * period <= 0:
            continue
        out.append(NoteEvent(max(0.0, start), first_beat_s + (n.beat + n.length) * period,
                             n.pitch, n.velocity))
    return out


def hits_to_notes(hits) -> list[NoteEvent]:
    """Drum strokes as notes on GM keys, one per drum in the stroke, velocity from strength."""
    loudest = max((h.strength for h in hits), default=0.0) or 1.0
    out = []
    for hit in hits:
        for kind in dict.fromkeys(k if k != "cymbals" else "hihat" for k in hit.kinds):
            if kind in DRUM_KEYS:
                out.append(NoteEvent(hit.time_s, hit.time_s + 0.1, DRUM_KEYS[kind],
                                     int(max(1, min(127, round(127 * hit.strength / loudest))))))
    return out


def notes_to_hits(notes: list[NoteEvent]):
    """Drum notes back to strokes - strokes at one instant merged, as the detector makes them."""
    from app.services.drums.detect import Hit

    by_time: dict[float, Hit] = {}
    for note in sorted(notes, key=lambda n: n.start_s):
        kind = DRUM_OF_KEY.get(note.pitch)
        if kind is None:
            continue
        key = round(note.start_s, 4)
        hit = by_time.setdefault(key, Hit(time_s=note.start_s, kinds=[], strength=0.0))
        if kind not in hit.kinds:
            hit.kinds.append(kind)
        hit.strength = max(hit.strength, note.velocity / 127.0)
    return list(by_time.values())


# --- the edits -------------------------------------------------------------------------------


def quantize(notes: list[BeatNote], grid: float, strength: float = 1.0,
             ends: bool = False) -> list[BeatNote]:
    """Move each note `strength` of the way to the nearest line of `grid` (beats).

    Strength under 1 is how a producer tightens a part without flattening it: 50% halves
    every note's distance from the grid and keeps which notes were early and which late.
    `ends` snaps the note's end too, for a part that should stop on the grid as well.
    """
    strength = max(0.0, min(1.0, strength))
    out = []
    for n in notes:
        target = round(n.beat / grid) * grid
        beat = n.beat + strength * (target - n.beat)
        length = n.length
        if ends:
            end = n.beat + n.length
            end_target = max(target + grid, round(end / grid) * grid)
            length = (end + strength * (end_target - end)) - beat
        out.append(BeatNote(beat, max(MIN_LENGTH, length), n.pitch, n.velocity))
    return out


def groove(notes: list[BeatNote], swing: float) -> list[BeatNote]:
    """Push every note that falls on an off-sixteenth late by `swing` of a triplet - the same
    swing the added beat plays with, so a quantised part and the beat bounce together."""
    from app.services.synth.groove import TRIPLET

    out = []
    for n in notes:
        sixteenth = round(n.beat * 4)
        on_grid = abs(n.beat * 4 - sixteenth) < 0.08
        beat = n.beat
        if on_grid and sixteenth % 2 == 1:
            beat = sixteenth / 4 + swing * TRIPLET / 4
        out.append(BeatNote(beat, n.length, n.pitch, n.velocity))
    return out


def transpose(notes: list[BeatNote], semitones: int) -> list[BeatNote]:
    """Every note up or down, kept inside MIDI's range."""
    return [BeatNote(n.beat, n.length, int(max(0, min(127, n.pitch + semitones))), n.velocity)
            for n in notes]


#: Legato never holds a note longer than this, in beats - two bars - so a last note before a
#: long gap does not ring through it.
LEGATO_MAX = 8.0


def legato(notes: list[BeatNote], amount: float = 1.0) -> list[BeatNote]:
    """Every note held towards the next onset in the part - `amount` of the way, 1 to the
    next note exactly. Sprint 18.

    Ryan: *"feel free to drag out the individual notes to have it more side chained and less
    choppy."* A transcribed guitar part is short strums and stabs; on a synth that is choppy,
    and the pump has nothing held to swell. Held to the next note, the synth sustains and the
    sidechain is heard as the breathing around every kick. Chords move together: every note
    of one onset is held to the same next onset. A note is never shortened."""
    amount = max(0.0, min(1.0, float(amount)))
    onsets = sorted({round(n.beat, 4) for n in notes})
    out = []
    for n in notes:
        later = [b for b in onsets if b > n.beat + 0.05]
        if not later:
            out.append(n)
            continue
        gap_end = min(later[0], n.beat + LEGATO_MAX)
        want = n.beat + n.length + amount * (gap_end - (n.beat + n.length))
        out.append(BeatNote(n.beat, max(n.length, want - n.beat), n.pitch, n.velocity))
    return out


def differs(edited: list[BeatNote], played: list[BeatNote]) -> bool:
    """Whether an edit changed anything - so "as you edited it" is only said when true."""
    def key(notes):
        return sorted((round(n.beat, 3), round(n.length, 3), n.pitch, n.velocity) for n in notes)

    return key(edited) != key(played)
