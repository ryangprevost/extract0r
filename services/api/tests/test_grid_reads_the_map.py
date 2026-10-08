"""The half of X0R-1319 criteria 1 and 5 that is about being *used*.

Both criteria have two clauses and the first version of this work met only the first of each.
Criterion 1 asks for a tempo map **and** for the figure to be *available to anything that
reads a grid*; criterion 5 asks for an unlockable clip to be named **and** for every figure
downstream to *abstain*. The map and the lock existed, measured and tested, and nothing read
either one - `BeatGrid.step_of` still answered from a single tempo, so every histogram in the
application was still computed against the grid the card calls wrong.

`step_of` and `phase_of` are what "anything that reads a grid" means in practice: every
rhythmic figure here goes through one of them. So these tests are about the grid, not about
the map - the map has its own file.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.timing import TimingEstimate
from app.services.analysis.fingerprint import (
    STEPS_PER_BEAT,
    BeatGrid,
    grid_from_drums,
)
from app.services.analysis.tempo_map import fit


def drifting(start_bpm: float, end_bpm: float, bars: int) -> tuple[list[float], float]:
    """A drummer speeding up evenly, hitting every eighth."""
    out, now = [], 0.0
    total = bars * 16
    for t in range(total):
        if t % 2 == 0:
            out.append(now)
        now += 60.0 / (start_bpm + (end_bpm - start_bpm) * t / total) / STEPS_PER_BEAT
    return out, now


def timing_for(bpm: float) -> TimingEstimate:
    return TimingEstimate(tempo_bpm=bpm, beats_per_bar=4, first_beat_s=0.0, confidence=0.8)


# --- criterion 1, second clause: the grid reads it ---------------------------------------


def test_a_grid_built_from_drums_carries_a_map():
    anchors, duration = drifting(124.0, 134.0, bars=16)
    grid = grid_from_drums(anchors, timing_for(129.0), duration)

    assert grid.tempo_map is not None
    assert grid.tempo_map.fitted


def test_step_of_puts_a_late_hit_on_the_right_step():
    """The behaviour the whole card is about. On a drifting take the steady grid walks away
    from the playing, so a hit near the end lands on the wrong step - and `step_of` is what
    every histogram indexes by, so a wrong step is a wrong bar position."""
    anchors, duration = drifting(124.0, 134.0, bars=16)
    grid = grid_from_drums(anchors, timing_for(129.0), duration)

    late = anchors[-6]
    _index, off_map = grid.step_of(late)
    bare = BeatGrid(
        tempo_bpm=grid.tempo_bpm,
        beats_per_bar=4,
        first_beat_s=grid.first_beat_s,
        confidence=grid.confidence,
        duration_s=duration,
    )
    _index, off_steady = bare.step_of(late)

    assert abs(off_map) < abs(off_steady)


def test_a_hit_outside_the_mapped_span_falls_back_rather_than_extrapolating():
    """An extrapolated map is a worse answer than an honest constant one, and a clip's first
    hit can precede the first mapped beat."""
    anchors, duration = drifting(124.0, 134.0, bars=16)
    grid = grid_from_drums(anchors, timing_for(129.0), duration)

    index, off = grid.step_of(duration + 30.0)
    assert isinstance(index, int)
    assert np.isfinite(off)


def test_phase_of_still_answers_between_zero_and_one():
    """It feeds a histogram bucket, so anything outside [0, 1) silently lands in no bucket or
    the wrong one."""
    anchors, duration = drifting(124.0, 134.0, bars=16)
    grid = grid_from_drums(anchors, timing_for(129.0), duration)

    for t in anchors:
        assert 0.0 <= grid.phase_of(t) < 1.0


def test_a_grid_with_no_drums_has_no_map_and_still_works():
    """No anchors is not a reason to build a map out of nothing, and every property has to
    keep answering."""
    grid = grid_from_drums([], timing_for(129.0), 20.0)

    assert grid.tempo_map is None
    assert grid.step_of(5.0)[0] > 0
    assert 0.0 <= grid.phase_of(5.0) < 1.0


def test_steps_stay_in_order():
    """`step_of` must be monotonic in time or a histogram's bars are not bars. The map's
    beats are monotonic by construction, and this is the check that the lattice built from
    them, and the fallback at its edges, preserve it."""
    anchors, duration = drifting(124.0, 134.0, bars=16)
    grid = grid_from_drums(anchors, timing_for(129.0), duration)

    indices = [grid.step_of(t)[0] for t in np.linspace(0.0, duration, 400)]
    assert all(b >= a for a, b in zip(indices, indices[1:], strict=False))


# --- criterion 5, second clause: something to abstain on ---------------------------------


def test_the_grid_reports_a_lock():
    anchors, duration = drifting(124.0, 134.0, bars=16)
    grid = grid_from_drums(anchors, timing_for(129.0), duration)

    assert 0.0 <= grid.lock <= 1.0
    assert grid.locked


def test_a_grid_no_better_than_chance_is_not_locked_even_when_usable():
    """The case the gate exists for, and the reason `locked` is not folded into `usable`.

    On real material a clip read 0.03 at a confidence that cleared `MIN_GRID_CONFIDENCE`
    comfortably: there was a tempo, and it explained nothing. `usable` asks whether a tempo
    exists; `locked` asks whether it describes the playing.
    """
    rng = np.random.default_rng(1319)
    anchors = sorted(rng.uniform(0.0, 20.0, 160).tolist())
    grid = BeatGrid(
        tempo_bpm=129.0,
        beats_per_bar=4,
        first_beat_s=0.0,
        confidence=0.9,
        duration_s=20.0,
        tempo_map=fit(anchors, 129.0, 0.0, 20.0, STEPS_PER_BEAT),
    )

    assert grid.usable
    assert not grid.locked


def test_no_map_means_no_lock_rather_than_a_free_pass():
    """Absence of drum anchors is not evidence that the grid is good, and a gate that
    defaults to open is not a gate."""
    grid = grid_from_drums([], timing_for(129.0), 20.0)

    assert grid.lock == 0.0
    assert not grid.locked


def test_lock_and_usable_are_different_questions():
    """Stated as a test because folding one into the other is the obvious simplification and
    it would lose the case above."""
    anchors, duration = drifting(124.0, 134.0, bars=16)
    grid = grid_from_drums(anchors, timing_for(129.0), duration)

    assert grid.usable
    assert grid.locked
    assert BeatGrid.usable.fget is not BeatGrid.locked.fget


# --- the map must not quietly change a record that was already right ---------------------


def test_a_steady_record_is_not_disturbed():
    """The map is a correction, and a correction that moves a correct answer is a regression.
    A machine-steady pattern must come out on the same steps it always did."""
    period = 60.0 / 120.0
    anchors = [i * period / 2 for i in range(96)]
    duration = 96 * period / 2

    grid = grid_from_drums(anchors, timing_for(120.0), duration)
    bare = BeatGrid(
        tempo_bpm=grid.tempo_bpm,
        beats_per_bar=4,
        first_beat_s=grid.first_beat_s,
        confidence=grid.confidence,
        duration_s=duration,
    )

    for t in anchors[:40]:
        assert grid.step_of(t)[0] == bare.step_of(t)[0]


@pytest.mark.parametrize("bpm", [90.0, 120.0, 147.7, 166.7])
def test_a_steady_record_is_undisturbed_at_any_tempo(bpm: float):
    """The same guarantee across the range this application actually sees, because the one
    tempo a bug hides at is the one nobody parametrised."""
    period = 60.0 / bpm
    anchors = [i * period / 2 for i in range(96)]
    duration = 96 * period / 2

    grid = grid_from_drums(anchors, timing_for(bpm), duration)
    bare = BeatGrid(
        tempo_bpm=grid.tempo_bpm,
        beats_per_bar=4,
        first_beat_s=grid.first_beat_s,
        confidence=grid.confidence,
        duration_s=duration,
    )

    disagreements = sum(grid.step_of(t)[0] != bare.step_of(t)[0] for t in anchors)
    assert disagreements == 0, f"{disagreements} of {len(anchors)} steps moved at {bpm} BPM"
