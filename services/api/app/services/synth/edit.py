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


def legato(notes: list[BeatNote], amount: float = 1.0,
           stops: list[float] | None = None) -> list[BeatNote]:
    """Every note held towards the next onset in the part - `amount` of the way, 1 to the
    next note exactly. Sprint 18.

    Ryan: *"feel free to drag out the individual notes to have it more side chained and less
    choppy."* A transcribed guitar part is short strums and stabs; on a synth that is choppy,
    and the pump has nothing held to swell. Held to the next note, the synth sustains and the
    sidechain is heard as the breathing around every kick. Chords move together: every note
    of one onset is held to the same next onset. A note is never shortened.

    `stops` are further places a held note must end - the bass's chord changes, so a chord
    is not held into the next one (Sprint 18b)."""
    amount = max(0.0, min(1.0, float(amount)))
    onsets = sorted({round(n.beat, 4) for n in notes} | {round(s, 4) for s in stops or []})
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


def trim(notes: list[BeatNote], short: float = 0.25, quiet: float = 0.6,
         leap: int = 7) -> list[BeatNote]:
    """The questionable notes taken out. Sprint 19.

    Ryan: *"the midi feels a little off maybe trim some of the questionable notes."* Two kinds,
    each something a player would not have meant:

    - **ghosts** - shorter than `short` beats *and* quieter than `quiet` of the part's median
      velocity: a transcriber's echo of a note, not a note;
    - **leaps** - in a single line, a note more than `leap` semitones from both the note
      before and the note after: one wrong octave or overtone in an otherwise smooth line.
      Only judged where one note sounds at a time; chords are left to `follow_bass`."""
    if not notes:
        return []
    ordered = sorted(notes, key=lambda n: (n.beat, n.pitch))
    loud = sorted(n.velocity for n in ordered)[len(ordered) // 2]
    kept = [n for n in ordered if not (n.length < short and n.velocity < quiet * loud)]
    onsets: dict[int, int] = {}
    for n in kept:
        onsets[round(n.beat / 0.05)] = onsets.get(round(n.beat / 0.05), 0) + 1
    out = []
    for i, n in enumerate(kept):
        alone = onsets[round(n.beat / 0.05)] == 1
        if alone and 0 < i < len(kept) - 1:
            before, after = kept[i - 1].pitch, kept[i + 1].pitch
            if abs(n.pitch - before) > leap and abs(n.pitch - after) > leap:
                continue
        out.append(n)
    return out


def top_line(notes: list[BeatNote], highest: int = 71, lowest: int = 55) -> list[BeatNote]:
    """The top note of every chord, as one line - a lead to play over the chords. Sprint 19.

    Moved by whole octaves into `lowest`..`highest` (G3 to B4 by default): a lead that sits
    over the chords without becoming the lone high note Ryan asked to be rid of."""
    groups: dict[int, BeatNote] = {}
    for n in notes:
        key = round(n.beat / 0.05)
        if key not in groups or n.pitch > groups[key].pitch:
            groups[key] = n
    out = []
    for key in sorted(groups):
        n = groups[key]
        pitch = n.pitch
        while pitch > highest:
            pitch -= 12
        while pitch < lowest:
            pitch += 12
        out.append(BeatNote(n.beat, n.length, pitch, n.velocity))
    return out


#: Complextro stab rhythms, two bars of sixteenths: syncopated off the kick, never on it.
STABS = ("..x..x..x...x.x.", "..x..x..x..x.xx.")


def stabs(chords: list[BeatNote], pattern: tuple[str, ...] = STABS,
          length: float = 0.2) -> list[BeatNote]:
    """The chords re-cut into short stabs on a rhythm. Sprint 19.

    Wherever the pattern has an `x`, the chord sounding at that sixteenth is played short.
    The harmony is the chords'; only the rhythm is new - which is what complextro does to
    a chord part: the same changes, chopped against the kick."""
    if not chords:
        return []
    end = max(n.beat + n.length for n in chords)
    steps = "".join(pattern)
    out = []
    step = 0
    while step * 0.25 < end:
        if steps[step % len(steps)] == "x":
            at = step * 0.25
            sounding = [n for n in chords if n.beat <= at + 0.01 < n.beat + n.length]
            for n in sounding:
                out.append(BeatNote(at, length, n.pitch, n.velocity))
        step += 1
    return out


MAJOR = (0, 2, 4, 5, 7, 9, 11)


def scale_of(notes: list[BeatNote]) -> list[int]:
    """The major scale (as pitch classes, from its tonic) that holds the most of these notes,
    weighted by how long each sounds. A relative minor is the same seven notes, so this is
    the song's scale whichever mode it is in."""
    weight = [0.0] * 12
    for n in notes:
        weight[n.pitch % 12] += max(n.length, MIN_LENGTH)
    best = max(range(12), key=lambda t: (sum(weight[(t + d) % 12] for d in MAJOR), weight[t]))
    return [(best + d) % 12 for d in MAJOR]


def chord_tones(root: int, scale: list[int]) -> set[int]:
    """The triad on `root` inside `scale` - root, third and fifth, stepping the scale - or a
    major triad when the root is outside it (a borrowed chord)."""
    root %= 12
    if root not in scale:
        return {root, (root + 4) % 12, (root + 7) % 12}
    i = scale.index(root)
    return {scale[i], scale[(i + 2) % 7], scale[(i + 4) % 7]}


def follow_bass(notes: list[BeatNote], bass: list[BeatNote], voices: int = 4,
                scale: list[int] | None = None) -> list[BeatNote]:
    """A part's notes made to agree with the bass's chords. Sprint 18b.

    Ryan, on the legato remix: *"there were some overtones and held out notes that just
    conflicted with the overall vibe ... i want it like a wall of pulsating distorted
    synth."* Every part was in key - 98 to 100% of each part's notes were in D major - so a
    key filter would have changed nothing. The clashes were each part's transcription
    picking its own extra chord tones (overtones read as sevenths and ninths) and legato
    holding them across the bass's changes. So each note is checked against the triad on the
    bass note under it, and one that is not in it moves to the nearest note that is - the
    rhythm kept, the harmony made one chord. Then a chord's duplicates go, and at most
    `voices` notes sound together: a wall, not a cluster."""
    if not notes or not bass:
        return list(notes)
    scale = scale or scale_of(list(notes) + list(bass))
    roots = sorted(bass, key=lambda b: b.beat)
    starts = [b.beat for b in roots]

    def root_at(beat: float) -> int:
        from bisect import bisect_right

        i = bisect_right(starts, beat + 0.05) - 1
        return roots[max(0, i)].pitch

    moved = []
    for n in notes:
        tones = chord_tones(root_at(n.beat), scale)
        pitch = n.pitch
        if pitch % 12 not in tones:
            # Nearest chord tone; a tie goes down, which keeps the line from creeping up.
            for step in (1, 2, 3, 4, 5, 6):
                if (pitch - step) % 12 in tones:
                    pitch -= step
                    break
                if (pitch + step) % 12 in tones:
                    pitch += step
                    break
        moved.append(BeatNote(n.beat, n.length, int(max(0, min(127, pitch))), n.velocity))

    # One of each pitch per onset, the loudest; then the `voices` loudest of each onset.
    groups: dict[float, dict[int, BeatNote]] = {}
    for n in moved:
        key = round(n.beat / 0.05) * 0.05
        same = groups.setdefault(key, {})
        if n.pitch not in same or n.velocity > same[n.pitch].velocity:
            same[n.pitch] = n
    out = []
    for key in sorted(groups):
        chord = sorted(groups[key].values(), key=lambda n: (-n.velocity, n.pitch))[:voices]
        out.extend(sorted(chord, key=lambda n: n.pitch))
    return out


def differs(edited: list[BeatNote], played: list[BeatNote]) -> bool:
    """Whether an edit changed anything - so "as you edited it" is only said when true."""
    def key(notes):
        return sorted((round(n.beat, 3), round(n.length, 3), n.pitch, n.velocity) for n in notes)

    return key(edited) != key(played)
