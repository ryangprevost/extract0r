"""Rearranging the song: its sections, found; and any order of them, built. Sprint 5.

Ryan, asked what "more manipulation" should mean first: **rearrange the song**. A remix is
rarely the original's running order at a new tempo. It opens on a stripped-back intro, goes
to the chorus sooner, drops out the drums for a breakdown before the last chorus, and plays
that chorus twice. Each of those is a decision about *sections*, and none of them moves a
note within one - so this is arrangement, not the re-sequencing this project still leaves
to the user's DAW.

### Finding the sections

The song is cut into four-bar phrases on its own beat grid - four bars being the unit pop
and dance music are built from - and each phrase is described by the same bar features the
drop finder uses (a log spectrum in 24 bands, and loudness). Phrases that sound alike are
grouped (A, B, C ...), runs of one group become one section, and the groups are named by
what they usually are: the loudest is the chorus, the first other is the verse. The names
are guesses and the page says so; the letters are what the grouping actually found.

### Building an order of them

Every part is cut at the same bar lines and the pieces laid end to end, so the beat carries
straight through a cut. Where two pieces were not next to each other in the song, the one
ending rings on for a moment under the next, fading - a hard cut at a bar line chops every
note that was still sounding, which is the click everybody hears in a bad edit.

Everything added afterwards - the pump, the beat, builds and drops - is laid on the *new*
timeline, so a drop goes wherever the arrangement says, as many times as it says.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

PHRASE_BARS = 4
#: Phrases closer than this are one group: the distance between two phrases' mean bar
#: features (24 log bands, in bels, plus log loudness). Absolute, not relative - the first
#: version used 0.4 of the largest distance, and a near-silent scrap after the last bar was
#: so far from everything that the demo's verse and chorus came out as one group.
#: Calibrated on synthetic songs only, said plainly: identical phrases measure 0, and the pop
#: punk demo's verse and chorus - the same chords, the lead an octave-ish up - 1.72. Real
#: recordings vary more within a section; if this over-splits a song, the blocks are smaller
#: than they need be, which is the safer way to be wrong for an arrangement editor.
SAME_GROUP_DIST = 1.2
#: How long a cut piece rings on under the next one, fading out.
TAIL_S = 0.08
#: The fade-in at a cut, so the new piece does not start with a click.
EDGE_S = 0.004


@dataclass
class Section:
    id: str
    #: The grouping's own letter: two sections with one letter sound alike.
    group: str
    #: A guess at what it is: "verse", "chorus", "bridge", "intro", "ending".
    label: str
    #: First bar, counted from 1, and how many.
    start_bar: int
    bars: int
    start_s: float
    #: Where its last bar ends. Always a bar line, so a repeated section keeps the grid.
    end_s: float
    #: The ring-out after the song's last bar, on the last section only. Not part of the
    #: section: repeating a chorus that carried half a second of ring-out with it put that
    #: half second into the middle of the song every time, and the beat after it landed late.
    tail_s: float = 0.0

    def to_dict(self) -> dict:
        return {"id": self.id, "group": self.group, "label": self.label,
                "start_bar": self.start_bar, "bars": self.bars,
                "start_s": round(self.start_s, 3), "end_s": round(self.end_s, 3),
                "tail_s": round(self.tail_s, 3)}


def find_sections(audio: np.ndarray, sample_rate: int, beats: np.ndarray) -> list[Section]:
    """The song's sections, in order. See the module docstring."""
    from app.services.synth.drop import _bar_features, bar_times

    mono = audio.mean(axis=1) if audio.ndim > 1 else np.asarray(audio, dtype=np.float64)
    duration = mono.size / sample_rate
    starts = bar_times(beats)
    period = float(np.median(np.diff(starts))) if starts.size > 1 else duration
    # Whole bars only. What is left after the last one - a ring-out - joins the last section
    # rather than becoming a "phrase" of near-silence that is unlike everything.
    starts = starts[starts + period <= duration + 0.01]
    if starts.size == 0:
        return [Section("s1", "A", "section", 1, 0, 0.0, duration)]
    edges = np.append(starts, starts[-1] + period)
    features = _bar_features(mono, sample_rate, edges)

    # Whole phrases, then whatever is left over as a short ending.
    phrases = [(b, min(b + PHRASE_BARS, len(features)))
               for b in range(0, len(features), PHRASE_BARS)]
    means = np.array([features[a:b].mean(axis=0) for a, b in phrases])
    loud = means[:, -1].copy()
    shape = means[:, :-1]

    distances = np.linalg.norm(shape[:, None, :] - shape[None, :, :], axis=-1)
    distances += np.abs(loud[:, None] - loud[None, :])
    limit = SAME_GROUP_DIST
    groups: list[int] = []
    leaders: list[int] = []
    for i in range(len(phrases)):
        found = next((g for g, lead in enumerate(leaders) if distances[i, lead] <= limit), None)
        if found is None:
            leaders.append(i)
            found = len(leaders) - 1
        groups.append(found)

    # Runs of one group are one section.
    runs: list[tuple[int, int, int]] = []          # (group, first phrase, last phrase)
    for i, grp in enumerate(groups):
        if runs and runs[-1][0] == grp:
            runs[-1] = (grp, runs[-1][1], i)
        else:
            runs.append((grp, i, i))

    names = _names(groups, loud)
    mean_loud = float(np.mean(loud))
    out = []
    for n, (grp, first, last) in enumerate(runs, start=1):
        a, b = phrases[first][0], phrases[last][1]
        label = names[grp]
        once = groups.count(grp) == last - first + 1
        quiet = float(np.mean(loud[first: last + 1])) < mean_loud - 0.1
        if b - a < PHRASE_BARS and n == len(runs) and len(runs) > 1:
            label = "ending"
        elif once and quiet and len(runs) > 2 and n == 1:
            label = "intro"
        elif once and quiet and len(runs) > 2 and n == len(runs):
            label = "outro"
        out.append(Section(f"s{n}", chr(ord("A") + grp), label, a + 1, b - a,
                           float(edges[a]), float(edges[b]) if b < len(edges) else duration))
    # What rings on after the last bar belongs to the end of the song, not to the section.
    out[-1].tail_s = max(0.0, duration - out[-1].end_s)
    return out


def _names(groups: list[int], loud: np.ndarray) -> dict[int, str]:
    """Guess what each group is: the loudest is the chorus, the first other the verse."""
    count = max(groups) + 1
    if count == 1:
        return {0: "section"}
    level = {g: float(np.mean([loud[i] for i, x in enumerate(groups) if x == g]))
             for g in range(count)}
    # Within half a dB is a tie - the pop punk demo's verse and chorus measure the same -
    # and a tie goes to the group that appears later, because a song rarely opens on its
    # chorus. Groups are numbered in order of first appearance, so later is larger.
    top = max(level.values())
    chorus = max(g for g, v in level.items() if v >= top - 0.05)
    names, spare = {chorus: "chorus"}, ["verse", "bridge", "part D", "part E", "part F"]
    for g in range(count):
        if g not in names:
            names[g] = spare.pop(0) if spare else f"part {chr(ord('A') + g)}"
    return names


# --- building an order of them -----------------------------------------------------------


@dataclass
class Piece:
    """One block of an arrangement, in the version's own time (seconds at the new tempo)."""

    start_s: float
    end_s: float
    #: Stems silent in this block, plus "beat" for the added beat.
    mute: frozenset[str] = field(default_factory=frozenset)
    #: Build up into the start of this block and drop there.
    drop: bool = False


def assemble(audio: np.ndarray, sample_rate: int, pieces: list[Piece], stem: str
             ) -> np.ndarray:
    """One part, cut into `pieces` and laid end to end. See the module docstring."""
    audio = np.asarray(audio, dtype=np.float64)
    stereo = audio if audio.ndim > 1 else audio[:, None]
    spans = [(int(round(p.start_s * sample_rate)), int(round(p.end_s * sample_rate)))
             for p in pieces]
    total = sum(end - start for start, end in spans)
    tail = int(TAIL_S * sample_rate)
    edge = max(1, int(EDGE_S * sample_rate))
    out = np.zeros((total + tail, stereo.shape[1]))
    at = 0
    for i, (piece, (start, end)) in enumerate(zip(pieces, spans, strict=True)):
        size = end - start
        if stem not in piece.mute:
            # Contiguous with the next piece in the song: no tail, the next piece carries on.
            joined = i + 1 < len(spans) and spans[i + 1][0] == end
            ring = 0 if joined else tail
            chunk = stereo[start: min(len(stereo), end + ring)].copy()
            if chunk.shape[0] > size:
                fade = np.linspace(1.0, 0.0, chunk.shape[0] - size)[:, None]
                chunk[size:] *= fade
            previous_joined = i > 0 and spans[i - 1][1] == start
            if not previous_joined and chunk.shape[0]:
                ramp = np.linspace(0.0, 1.0, min(edge, chunk.shape[0]))[:, None]
                chunk[: ramp.shape[0]] *= ramp
            out[at: at + chunk.shape[0]] += chunk
        at += size
    out = out[:total]
    return out if audio.ndim > 1 else out[:, 0]


def arranged_beats(beats: np.ndarray, pieces: list[Piece]) -> np.ndarray:
    """The version's beats, carried into the arrangement's timeline piece by piece."""
    beats = np.asarray(beats, dtype=np.float64)
    out, at = [], 0.0
    for piece in pieces:
        inside = beats[(beats >= piece.start_s - 1e-6) & (beats < piece.end_s - 1e-6)]
        out.extend(inside - piece.start_s + at)
        at += piece.end_s - piece.start_s
    return np.asarray(out)


def piece_spans(pieces: list[Piece]) -> list[tuple[float, float]]:
    """Where each piece sits in the arrangement's timeline, (start, end) in seconds."""
    out, at = [], 0.0
    for piece in pieces:
        length = piece.end_s - piece.start_s
        out.append((at, at + length))
        at += length
    return out


def muted_spans(pieces: list[Piece], what: str) -> list[tuple[float, float]]:
    """Spans of the arrangement where `what` (a stem, or "beat") is silent."""
    return [span for piece, span in zip(pieces, piece_spans(pieces), strict=True)
            if what in piece.mute]


def drop_bars(pieces: list[Piece], beats: np.ndarray) -> list[int]:
    """Bars of the arranged timeline, counted from 1, where a block marked `drop` starts."""
    from app.services.synth.drop import bar_times

    bars = bar_times(beats)
    out = []
    for piece, (start, _) in zip(pieces, piece_spans(pieces), strict=True):
        if piece.drop and bars.size:
            out.append(int(np.argmin(np.abs(bars - start))) + 1)
    return out


def place_notes(notes, pieces: list[Piece], stem: str):
    """Notes in the version's time, carried into the arrangement: each copy of a section
    gets its own copy of its notes, notes in a muted block are left out, and a note still
    held at a cut ends there."""
    from app.domain.notes import NoteEvent

    out = []
    for piece, (at, _) in zip(pieces, piece_spans(pieces), strict=True):
        if stem in piece.mute:
            continue
        for note in notes:
            if piece.start_s - 1e-6 <= note.start_s < piece.end_s - 1e-6:
                start = note.start_s - piece.start_s + at
                end = min(note.end_s, piece.end_s) - piece.start_s + at
                out.append(NoteEvent(start, max(end, start + 0.01), note.pitch, note.velocity))
    return sorted(out, key=lambda n: n.start_s)


# --- sections the person marked - Sprint 13 ---------------------------------------------------
#
# Ryan: "please let me determine the parts of the song instead of parsing them." A mark is a
# bar where a section starts and a name for it. Everything that uses sections uses these when
# they exist; the detector's guess is only a starting suggestion.

#: Longest name a section may have.
MAX_LABEL = 24


def sections_from_marks(marks: list[tuple[int, str]], beats: np.ndarray,
                        duration_s: float) -> list[Section]:
    """Sections from the person's marks: each runs from its bar to the next mark, the last
    to the end of the song's last whole bar, with the ring-out after it as its tail. Marks
    with the same name are one group - two choruses get one letter, as the detector would
    give two phrases that sound alike."""
    from app.services.synth.drop import bar_times

    starts = bar_times(beats)
    period = float(np.median(np.diff(starts))) if starts.size > 1 else duration_s
    whole = starts[starts + period <= duration_s + 0.01]
    bars = int(whole.size)
    if bars == 0:
        return [Section("s1", "A", "section", 1, 0, 0.0, duration_s)]
    edges = np.append(whole, whole[-1] + period)
    marks = sorted({min(max(1, b), bars): label for b, label in marks}.items())
    if marks[0][0] != 1:
        # The song before the first mark is still the song; it gets a section of its own.
        marks.insert(0, (1, "intro"))
    letters: dict[str, str] = {}
    out = []
    for n, (bar, label) in enumerate(marks, start=1):
        end_bar = marks[n][0] if n < len(marks) else bars + 1
        name = label.strip().lower()[:MAX_LABEL] or "section"
        group = letters.setdefault(name, chr(ord("A") + len(letters)))
        out.append(Section(f"s{n}", group, name, bar, end_bar - bar,
                           float(edges[bar - 1]), float(edges[end_bar - 1])))
    out[-1].tail_s = max(0.0, duration_s - out[-1].end_s)
    return out


def bar_levels(audio: np.ndarray, sample_rate: int, beats: np.ndarray) -> list[float]:
    """Loudness of every bar, in dB - the strip the person marks sections on, where a chorus
    usually stands taller than a verse."""
    from app.services.synth.drop import bar_times

    mono = audio.mean(axis=1) if audio.ndim > 1 else np.asarray(audio, dtype=np.float64)
    starts = bar_times(beats)
    period = float(np.median(np.diff(starts))) if starts.size > 1 else mono.size / sample_rate
    out = []
    for start in starts:
        piece = mono[int(start * sample_rate): int((start + period) * sample_rate)]
        if piece.size == 0:
            break
        out.append(round(float(10 * np.log10(np.mean(piece**2) + 1e-12)), 1))
    return out
