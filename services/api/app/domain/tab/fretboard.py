"""Fretboard solver: turn MIDI pitches into playable string/fret assignments.

A pitch can usually be played in three or four places on a guitar neck. Picking the
*right* one is what separates a readable tab from a useless one, so this is a real
optimiser rather than a "lowest string that fits" heuristic: a Viterbi pass over
onset clusters minimising hand travel plus per-shape ergonomics.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.notes import NoteEvent, cluster_by_onset


@dataclass(frozen=True, slots=True)
class Tuning:
    """Open-string pitches, ordered low string (index 0) to high string."""

    name: str
    open_pitches: tuple[int, ...]
    fret_count: int = 22

    @property
    def string_count(self) -> int:
        return len(self.open_pitches)


# Index 0 is always the lowest-sounding string; renderers flip it for display.
STANDARD_GUITAR = Tuning("Guitar - Standard E", (40, 45, 50, 55, 59, 64))
DROP_D_GUITAR = Tuning("Guitar - Drop D", (38, 45, 50, 55, 59, 64))
HALF_STEP_DOWN = Tuning("Guitar - Eb Standard", (39, 44, 49, 54, 58, 63))
SEVEN_STRING = Tuning("Guitar - 7 String B", (35, 40, 45, 50, 55, 59, 64), fret_count=24)
STANDARD_BASS = Tuning("Bass - Standard E", (28, 33, 38, 43), fret_count=24)
DROP_D_BASS = Tuning("Bass - Drop D", (26, 33, 38, 43), fret_count=24)
FIVE_STRING_BASS = Tuning("Bass - 5 String B", (23, 28, 33, 38, 43), fret_count=24)

TUNINGS: dict[str, Tuning] = {
    "guitar_standard": STANDARD_GUITAR,
    "guitar_drop_d": DROP_D_GUITAR,
    "guitar_eb": HALF_STEP_DOWN,
    "guitar_7": SEVEN_STRING,
    "bass_standard": STANDARD_BASS,
    "bass_drop_d": DROP_D_BASS,
    "bass_5": FIVE_STRING_BASS,
}


@dataclass(frozen=True, slots=True)
class Position:
    """One note pinned to a physical spot on the neck."""

    string: int  # 0 = lowest-sounding string
    fret: int
    note: NoteEvent


@dataclass(frozen=True, slots=True)
class Shape:
    """A set of simultaneous positions — one chord voicing or a single note."""

    positions: tuple[Position, ...]

    @property
    def start_s(self) -> float:
        return min(p.note.start_s for p in self.positions)

    @property
    def fretted(self) -> tuple[int, ...]:
        """Fret numbers excluding open strings, which impose no hand position."""
        return tuple(p.fret for p in self.positions if p.fret > 0)

    @property
    def anchor(self) -> float | None:
        """Where the fretting hand sits for this shape, or None if all-open."""
        fretted = self.fretted
        return sum(fretted) / len(fretted) if fretted else None

    @property
    def span(self) -> int:
        fretted = self.fretted
        return max(fretted) - min(fretted) if fretted else 0


class UnplayableError(ValueError):
    """Raised when a pitch cannot be produced by the requested instrument at all."""


class UnplayablePolicy(StrEnum):
    """What to do with a note the instrument physically cannot play.

    This is not a theoretical concern. Separation leaks: a guitar stem from Demucs
    routinely contains bass bleed, and a polyphonic transcriber will happily report a
    note two octaves below the low E. Under RAISE a single such note aborts the whole
    transcription, which is exactly what happened the first time this pipeline was run
    end to end on real model output.
    """

    #: Abort. Correct for tests and for hand-entered input; wrong for model output.
    RAISE = "raise"
    #: Leave it out and count it. Honest: the tab shows only what is playable.
    DROP = "drop"
    #: Shift by whole octaves until it fits, preserving the pitch class.
    FOLD = "fold"


@dataclass(frozen=True, slots=True)
class SolverConfig:
    """Weights for the cost model. Tuning these is a legitimate UX knob."""

    travel_weight: float = 1.0
    span_weight: float = 2.5
    high_fret_weight: float = 0.08
    open_string_bonus: float = 0.6
    max_hand_span: int = 5
    max_candidates_per_shape: int = 48
    capo: int = 0
    unplayable: UnplayablePolicy = UnplayablePolicy.DROP


def candidate_positions(
    note: NoteEvent, tuning: Tuning, capo: int = 0
) -> list[Position]:
    """Every place on the neck this pitch can be played.

    A capo at fret N raises every open string to N, so frets below it are unreachable.
    """
    out: list[Position] = []
    for string, open_pitch in enumerate(tuning.open_pitches):
        fret = note.pitch - open_pitch
        if capo <= fret <= tuning.fret_count:
            out.append(Position(string=string, fret=fret, note=note))
    return out


def _shape_candidates(
    cluster: Sequence[NoteEvent], tuning: Tuning, cfg: SolverConfig
) -> list[Shape]:
    """All voicings of one onset cluster, cheapest-looking first, then truncated."""
    per_note = [candidate_positions(n, tuning, cfg.capo) for n in cluster]
    for note, options in zip(cluster, per_note, strict=True):
        if not options:
            raise UnplayableError(
                f"{note.name} (MIDI {note.pitch}) is out of range for {tuning.name}"
            )

    shapes: list[Shape] = []
    for combo in itertools.product(*per_note):
        strings = [p.string for p in combo]
        if len(set(strings)) != len(strings):
            continue  # two notes cannot share a string
        shape = Shape(tuple(combo))
        if shape.span > cfg.max_hand_span:
            continue
        shapes.append(shape)

    if not shapes:
        # Fall back to the least-bad voicing rather than dropping the chord entirely.
        combo = tuple(sorted(opts, key=lambda p: p.fret)[0] for opts in per_note)
        shapes = [Shape(combo)]

    shapes.sort(key=lambda s: (s.span, s.anchor if s.anchor is not None else 0.0))
    return shapes[: cfg.max_candidates_per_shape]


def _static_cost(shape: Shape, cfg: SolverConfig) -> float:
    cost = cfg.span_weight * shape.span
    for pos in shape.positions:
        if pos.fret == 0:
            cost -= cfg.open_string_bonus
        else:
            cost += cfg.high_fret_weight * pos.fret
    return cost


def _transition_cost(prev: Shape, nxt: Shape, cfg: SolverConfig) -> float:
    a, b = prev.anchor, nxt.anchor
    if a is None or b is None:
        return 0.0  # an all-open shape lets the hand stay wherever it was
    return cfg.travel_weight * abs(a - b)


@dataclass(slots=True)
class SolveReport:
    """The solved tab plus what had to be thrown away to get it."""

    shapes: list[Shape] = field(default_factory=list)
    dropped: list[NoteEvent] = field(default_factory=list)
    folded: list[NoteEvent] = field(default_factory=list)

    @property
    def adjusted_count(self) -> int:
        return len(self.dropped) + len(self.folded)


def _fold_into_range(note: NoteEvent, tuning: Tuning, capo: int) -> NoteEvent | None:
    """Shift by whole octaves until the pitch fits the neck, or give up."""
    lowest = min(tuning.open_pitches) + capo
    highest = max(tuning.open_pitches) + tuning.fret_count
    pitch = note.pitch
    while pitch < lowest:
        pitch += 12
    while pitch > highest:
        pitch -= 12
    if not lowest <= pitch <= highest:
        return None
    return NoteEvent(
        start_s=note.start_s,
        end_s=note.end_s,
        pitch=pitch,
        velocity=note.velocity,
        confidence=note.confidence,
    )


def _filter_playable(
    notes: Sequence[NoteEvent], tuning: Tuning, cfg: SolverConfig
) -> tuple[list[NoteEvent], list[NoteEvent], list[NoteEvent]]:
    """Split notes into (playable, dropped, folded) according to the configured policy."""
    playable: list[NoteEvent] = []
    dropped: list[NoteEvent] = []
    folded: list[NoteEvent] = []

    for note in notes:
        if candidate_positions(note, tuning, cfg.capo):
            playable.append(note)
            continue
        if cfg.unplayable is UnplayablePolicy.RAISE:
            raise UnplayableError(
                f"{note.name} (MIDI {note.pitch}) is out of range for {tuning.name}"
            )
        if cfg.unplayable is UnplayablePolicy.FOLD:
            shifted = _fold_into_range(note, tuning, cfg.capo)
            if shifted is not None and candidate_positions(shifted, tuning, cfg.capo):
                playable.append(shifted)
                folded.append(note)
                continue
        dropped.append(note)

    return playable, dropped, folded


def solve(
    notes: Sequence[NoteEvent],
    tuning: Tuning = STANDARD_GUITAR,
    cfg: SolverConfig | None = None,
    chord_window_s: float = 0.045,
) -> list[Shape]:
    """Assign every note a string and fret, minimising total hand movement."""
    return solve_with_report(notes, tuning, cfg, chord_window_s).shapes


def solve_with_report(
    notes: Sequence[NoteEvent],
    tuning: Tuning = STANDARD_GUITAR,
    cfg: SolverConfig | None = None,
    chord_window_s: float = 0.045,
) -> SolveReport:
    """Solve, and report what the instrument could not play.

    Viterbi over onset clusters: state space is the candidate voicings of a cluster,
    transitions are how far the fretting hand has to move between them.
    """
    cfg = cfg or SolverConfig()
    playable, dropped, folded = _filter_playable(notes, tuning, cfg)
    report = SolveReport(dropped=dropped, folded=folded)
    clusters = cluster_by_onset(playable, chord_window_s)
    if not clusters:
        return report

    frontier: list[tuple[float, Shape, int]] = []  # (cost, shape, backpointer)
    lattice: list[list[tuple[float, Shape, int]]] = []

    for index, cluster in enumerate(clusters):
        shapes = _shape_candidates(cluster, tuning, cfg)
        layer: list[tuple[float, Shape, int]] = []
        for shape in shapes:
            base = _static_cost(shape, cfg)
            if index == 0:
                layer.append((base, shape, -1))
                continue
            best_cost, best_back = None, -1
            for back, (prev_cost, prev_shape, _) in enumerate(frontier):
                total = prev_cost + base + _transition_cost(prev_shape, shape, cfg)
                if best_cost is None or total < best_cost:
                    best_cost, best_back = total, back
            layer.append((best_cost or base, shape, best_back))
        lattice.append(layer)
        frontier = layer

    # Walk the backpointers from the cheapest end state.
    best_index = min(range(len(frontier)), key=lambda i: frontier[i][0])
    path: list[Shape] = []
    for layer in reversed(lattice):
        cost, shape, back = layer[best_index]
        path.append(shape)
        best_index = back
        if best_index < 0:
            break
    path.reverse()
    report.shapes = path
    return report
