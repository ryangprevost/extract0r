"""A grid that follows the drummer. X0R-1319, criteria 1 and 2.

The measurement that motivates the card is in the module docstring: on Ryan's own separated
drums a hit sits a median of **37.7 ms** from its nearest sixteenth, where a sixteenth at
129 BPM is 116 ms and a *random* set of times would sit 29 ms away. The grid was further
from the playing than chance.

Half of these are about the improvement. The other half are about **the improvement not
being bought by cheating**, which is the real risk here: a map allowed to bend freely drives
the residual to zero by landing a beat on every hit, and then every timing figure in the
application reads zero by construction and the groove card measures nothing. So there are
tests that the cap holds, that swing survives, and that a shove is not read as a tempo
change.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.tempo_map import (
    LOCK_FLOOR,
    MAX_TEMPO_DRIFT,
    TempoMap,
    fit,
    residual_ms,
    subdivisions,
)

SIXTEENTHS_PER_BEAT = 4


def hits(tempo_bpm: float, bars: int, first_beat_s: float = 0.0, every: int = 2) -> list[float]:
    """A machine playing every `every`-th sixteenth at a dead steady tempo."""
    step = 60.0 / tempo_bpm / SIXTEENTHS_PER_BEAT
    return [first_beat_s + t * step for t in range(0, bars * 16, every)]


def drifting(
    start_bpm: float, end_bpm: float, bars: int, every: int = 2
) -> tuple[list[float], float]:
    """A drummer speeding up evenly. Returns the hit times and the duration."""
    out, now = [], 0.0
    total = bars * 16
    for t in range(total):
        if t % every == 0:
            out.append(now)
        bpm = start_bpm + (end_bpm - start_bpm) * t / total
        now += 60.0 / bpm / SIXTEENTHS_PER_BEAT
    return out, now


# --- the improvement ---------------------------------------------------------------------


def test_a_drifting_record_gets_much_closer_to_its_grid():
    """Criterion 2, the whole point. 124 to 132 BPM over eight bars is an ordinary live
    take, not a pathological one."""
    anchors, duration = drifting(124.0, 132.0, bars=8)
    # A global estimator lands on the average, which is what this hands it.
    mapped = fit(anchors, 128.0, 0.0, duration)

    assert mapped.fitted
    assert mapped.residual_after_ms < mapped.residual_before_ms / 2


def test_the_figures_are_reported_rather_than_asserted():
    """Criterion 2 asks for the improvement to be *visible*. A caller that cannot read both
    numbers off the result cannot show it."""
    anchors, duration = drifting(124.0, 132.0, bars=8)
    mapped = fit(anchors, 128.0, 0.0, duration)

    assert mapped.residual_before_ms > 0
    assert mapped.improvement_ms == pytest.approx(
        mapped.residual_before_ms - mapped.residual_after_ms, abs=0.01
    )


def test_the_drift_itself_is_reported():
    """A map whose shape nobody can see is a magic number. 124 to 132 is 8 BPM of drift and
    the map should say so."""
    anchors, duration = drifting(124.0, 132.0, bars=16)
    mapped = fit(anchors, 128.0, 0.0, duration)

    assert mapped.drift_bpm > 2.0
    assert mapped.mean_bpm == pytest.approx(128.0, abs=3.0)


def test_a_record_already_on_its_grid_is_left_alone():
    """Nothing to fix, and a map that moved anyway would be inventing drift."""
    anchors = hits(120.0, bars=8)
    mapped = fit(anchors, 120.0, 0.0, 16.0)

    assert mapped.residual_before_ms == pytest.approx(0.0, abs=0.5)
    assert mapped.residual_after_ms == pytest.approx(0.0, abs=0.5)


# --- the improvement is not bought by cheating -------------------------------------------


def test_the_local_tempo_never_strays_past_the_cap():
    """The guard that stops this being a transcription of the onsets. Random anchors are the
    adversarial case: every beat has a nearby hit begging to be snapped to.

    Note what is *not* asserted - that no beat moved far from the steady grid. That was the
    first version of this guard and it is the wrong quantity, because real drift accumulates
    without the tempo ever being unreasonable. The module docstring has the measurement.
    """
    rng = np.random.default_rng(1319)
    anchors = sorted(rng.uniform(0.0, 16.0, 200).tolist())
    mapped = fit(anchors, 120.0, 0.0, 16.0)

    assert np.all(mapped.bpm <= 120.0 / (1.0 - MAX_TEMPO_DRIFT) + 1e-6)
    assert np.all(mapped.bpm >= 120.0 / (1.0 + MAX_TEMPO_DRIFT) - 1e-6)


def test_swing_is_not_absorbed():
    """A swung record's off-eighths are *late on purpose*. If the map flattened that, the
    groove card would report a straight performance and the thing it exists to show would
    be gone."""
    period = 60.0 / 120.0
    anchors = []
    for beat in range(32):
        anchors.append(beat * period)
        anchors.append(beat * period + period * 0.62)  # a hard swing, not a neighbour
    mapped = fit(anchors, 120.0, 0.0, 32 * period)

    # The swing sits 0.12 of a beat - 60 ms - off the straight eighth, and it has to survive.
    assert mapped.residual_after_ms > 25.0


def test_one_shoved_hit_does_not_bend_the_tempo():
    """Smoothing, stated as a behaviour. A fill landing 50 ms late is a fill, and a map that
    followed it would report a tempo change nobody played."""
    anchors = hits(120.0, bars=8)
    anchors[20] += 0.05
    mapped = fit(anchors, 120.0, 0.0, 16.0)

    assert np.max(np.abs(mapped.bpm - 120.0)) < 4.0


def test_a_tempo_change_too_large_to_be_drift_is_refused_outright():
    """100 to 150 BPM is not a drifting take, it is two tempos, and `MAX_TEMPO_DRIFT` means
    the loop cannot follow it. The honest outcome is the steady grid and `fitted` false -
    **not** a half-tracked map that is wrong in the middle while looking fitted.

    This is the case that caught the previous version: its second pass restarted from the
    beat *spacing*, which carries phase drift, and that let the tempo escape its own clamp
    and report a ramp it had no right to claim.
    """
    anchors, duration = drifting(100.0, 150.0, bars=12)
    mapped = fit(anchors, 120.0, 0.0, duration)

    assert not mapped.fitted
    assert mapped.residual_after_ms == mapped.residual_before_ms


def test_the_reported_tempo_is_the_tracked_one_not_the_beat_spacing():
    """Measured on real drums, spacing showed 25 BPM of drift under a clamp permitting 21 -
    the reported figure contradicted the module's own guarantee. Spacing is tempo *plus*
    that beat's phase correction; only the first is a tempo."""
    rng = np.random.default_rng(404)
    anchors = sorted(rng.uniform(0.0, 20.0, 180).tolist())
    mapped = fit(anchors, 129.0, 0.0, 20.0)

    span = 129.0 / (1.0 - MAX_TEMPO_DRIFT) - 129.0 / (1.0 + MAX_TEMPO_DRIFT)
    assert mapped.drift_bpm <= span + 1e-6
    spacing = 60.0 / np.diff(mapped.beats)
    assert np.max(spacing) - np.min(spacing) > mapped.drift_bpm


def test_too_few_anchors_leaves_the_global_grid_standing():
    """Four hits is not a tempo. Fitting one anyway is how a quiet intro gets a grid built
    out of nothing."""
    mapped = fit([0.0, 0.5, 1.0, 1.5], 120.0, 0.0, 8.0)

    assert not mapped.fitted
    assert mapped.residual_before_ms == mapped.residual_after_ms
    assert np.allclose(np.diff(mapped.beats), 0.5)


def test_an_off_eighth_is_not_read_as_a_late_beat():
    """The bug this was written against. Measuring each anchor from its nearest *beat* and
    accepting anything within half a beat makes an ordinary snare on 2-and read as a beat
    half a beat late, and it drags the grid along. Backbeats only, dead steady."""
    period = 60.0 / 120.0
    anchors = [beat * period + period * 0.5 for beat in range(40)]
    mapped = fit(anchors, 120.0, 0.0, 40 * period)

    steady = np.arange(mapped.beats.size) * period
    assert np.max(np.abs(mapped.beats - steady)) < 0.005


def test_beats_never_go_backwards():
    """A grid whose beats are out of order breaks every consumer downstream, and opposing
    pulls on adjacent beats can produce one."""
    rng = np.random.default_rng(7)
    anchors = sorted(rng.uniform(0.0, 20.0, 300).tolist())
    mapped = fit(anchors, 97.0, 0.3, 20.0)

    assert np.all(np.diff(mapped.beats) > 0)


def test_a_fit_that_made_things_worse_is_discarded():
    """Clipping, smoothing and the monotonic pass can each move a beat away from its own
    evidence, so the result is checked rather than trusted."""
    rng = np.random.default_rng(99)
    for extra in range(8):
        anchors = sorted(rng.uniform(0.0, 12.0, 60 + extra).tolist())
        mapped = fit(anchors, 133.0, 0.0, 12.0)
        assert mapped.residual_after_ms <= mapped.residual_before_ms + 1e-6


# --- the pieces --------------------------------------------------------------------------


def test_subdivisions_land_between_the_beats_it_was_given():
    beats = np.array([0.0, 0.5, 1.2])  # deliberately uneven
    grid = subdivisions(beats, 4)

    assert grid[0] == 0.0
    assert grid[4] == pytest.approx(0.5)
    assert grid[1] == pytest.approx(0.125)
    assert grid[5] == pytest.approx(0.675)  # a wider beat has wider sixteenths
    assert grid[-1] == pytest.approx(1.2)


def test_step_at_follows_the_local_tempo():
    """What a consumer asks when it wants a deviation as a fraction of a beat."""
    anchors, duration = drifting(124.0, 134.0, bars=16)
    mapped = fit(anchors, 129.0, 0.0, duration)

    assert mapped.fitted
    assert mapped.step_at(duration * 0.9) < mapped.step_at(duration * 0.1)


def test_nearest_uses_the_map_and_not_a_steady_grid():
    anchors, duration = drifting(124.0, 134.0, bars=16)
    mapped = fit(anchors, 129.0, 0.0, duration)

    late_anchor = anchors[-4]
    assert abs(mapped.nearest(late_anchor) - late_anchor) < 0.02


def test_residual_is_a_median_distance_in_milliseconds():
    grid = np.array([0.0, 1.0, 2.0])
    assert residual_ms(np.array([0.01, 0.99, 2.02]), grid) == pytest.approx(10.0, abs=0.01)


def test_nothing_to_fit_is_not_an_error():
    for bad in (fit([], 0.0, 0.0, 10.0), fit([1.0], 120.0, 0.0, 0.0)):
        assert isinstance(bad, TempoMap)
        assert not bad.fitted


# --- is this grid worth computing against at all ------------------------------------------
#
# Criterion 5. These exist because two of the four real stems measured for criterion 2
# started at *exactly* the chance distance: the tempo they were handed explained nothing
# about the playing, and every figure computed against it was noise with units.


def test_chance_is_a_quarter_of_a_step():
    """The number the lock is measured against. A time unrelated to the grid lands uniformly
    within a step, so its distance to the nearest grid point has a median of a quarter step -
    29 ms for a sixteenth at 129 BPM."""
    mapped = fit(hits(129.0, bars=8), 129.0, 0.0, 15.0)

    assert mapped.chance_residual_ms == pytest.approx(60.0 / 129.0 / 4 * 1000 / 4, rel=0.02)


def test_a_record_on_its_grid_locks():
    mapped = fit(hits(120.0, bars=8), 120.0, 0.0, 16.0)

    assert mapped.lock > 0.9
    assert mapped.locked


def test_a_grid_no_better_than_chance_does_not_lock():
    """The case from real material: 29.0 ms at 129 BPM, which is chance exactly. Criterion 5
    asks for this to be said plainly rather than quietly carried downstream."""
    rng = np.random.default_rng(1319)
    anchors = sorted(rng.uniform(0.0, 20.0, 160).tolist())
    mapped = fit(anchors, 129.0, 0.0, 20.0)

    assert mapped.lock < LOCK_FLOOR
    assert not mapped.locked


def test_lock_does_not_resolve_the_octave():
    """Stated as a test so nobody reads `lock` as an octave check. Every hit on a 100 BPM
    grid is also on a 200 BPM grid, so the doubled reading scores **at least as well** - and
    this card proved no onset-only measure can prefer the slower one on subdivided material.
    Criterion 3 is still open and this is not it."""
    period = 60.0 / 100.0
    eighths = [i * period / 2 for i in range(64)]

    truth = fit(eighths, 100.0, 0.0, 32 * period)
    doubled = fit(eighths, 200.0, 0.0, 32 * period)

    assert doubled.lock >= truth.lock
    assert doubled.locked


def test_an_unfitted_map_still_reports_a_lock():
    """A caller gating on `locked` must get an answer even when there was nothing to fit -
    otherwise the quiet intro case silently skips the gate."""
    mapped = fit([0.0, 0.5, 1.0, 1.5], 120.0, 0.0, 8.0)

    assert not mapped.fitted
    assert 0.0 <= mapped.lock <= 1.0


def test_lock_is_zero_when_there_is_no_grid():
    assert fit([], 0.0, 0.0, 10.0).lock == 0.0


def test_lock_cannot_be_compared_across_tempo_hypotheses():
    """The misuse this number invites, pinned so nobody ships it.

    A denser lattice fits everything better, so the faster hypothesis scores higher whether or
    not it is right. Measured on one real reference, the same drums scored 0.02 at 129.2 BPM
    and 0.84 at 193.8 - two estimators disagreeing by exactly 3:2, and not evidence for either.
    """
    rng = np.random.default_rng(1500)
    # Times with no relationship to either grid, so neither hypothesis deserves to win.
    anchors = sorted(rng.uniform(0.0, 20.0, 150).tolist())

    slow = fit(anchors, 129.2, 0.0, 20.0)
    fast = fit(anchors, 129.2 * 1.5, 0.0, 20.0)

    assert fast.lock >= slow.lock
