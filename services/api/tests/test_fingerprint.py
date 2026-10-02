"""Tests for the Experiment 1 rhythmic fingerprint.

Constructed rhythms, not audio. Every figure in `analysis.fingerprint` is arithmetic over
hit times and a grid, so the interesting failures — a flat histogram because the grid
drifted, a "duck" that is really a bass note decaying, a swing ratio from nine events —
can all be produced exactly, which is the only way to know the function caught them.

The two things under the most pressure here are the ones Experiment 1 found by accident:
the grid has to be re-derived from the drums or the histograms are noise, and a figure
with nothing to compare it against is not a measurement.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.timing import TimingEstimate
from app.services.analysis.fingerprint import (
    DETECTOR_JITTER_MS,
    MIN_GRID_CONFIDENCE,
    BeatGrid,
    Figure,
    beat_coverage,
    envelope_db,
    grid_from_drums,
    kick_duck,
    offbeat_share,
    position_histogram,
    refine_grid,
    swing_ratio,
    timing_spread,
)

BPM = 120.0
BEAT = 60.0 / BPM          # 0.5 s
STEP = BEAT / 4            # 0.125 s


def grid(bpm: float = BPM, offset: float = 0.0, seconds: float = 32.0,
         confidence: float = 0.9) -> BeatGrid:
    return BeatGrid(
        tempo_bpm=bpm, beats_per_bar=4, first_beat_s=offset,
        confidence=confidence, duration_s=seconds,
    )


def four_on_the_floor(bars: int = 8, bpm: float = BPM, offset: float = 0.0) -> list[float]:
    beat = 60.0 / bpm
    return [offset + i * beat for i in range(bars * 4)]


def every_step(bars: int = 8, bpm: float = BPM, offset: float = 0.0) -> list[float]:
    step = 60.0 / bpm / 4
    return [offset + i * step for i in range(bars * 16)]


# ──────────────────────────────── placing hits ────────────────────────────────


def test_four_on_the_floor_is_a_count_not_an_opinion():
    counts = position_histogram(four_on_the_floor(), grid())
    assert counts == [8, 0, 0, 0, 8, 0, 0, 0, 8, 0, 0, 0, 8, 0, 0, 0]


def test_offbeat_eighths_land_on_step_two():
    hats = [i * BEAT + BEAT / 2 for i in range(32)]
    counts = position_histogram(hats, grid())
    assert counts[2] == counts[6] == counts[10] == counts[14] == 8
    assert sum(counts[i] for i in (0, 4, 8, 12)) == 0


def test_beat_coverage_counts_beats_not_hits():
    # Two kicks flammed onto one downbeat is still one downbeat covered.
    covered, total = beat_coverage([0.0, 0.004, BEAT], grid(seconds=1.0))
    assert (covered, total) == (2, 2)


def test_backbeat_coverage_selects_one_beat_of_the_bar():
    snares = [BEAT + i * 2 * BEAT for i in range(16)]  # beats 1, 3, 5, 7 …
    # Sixteen bars of four beats in 32 s, so sixteen beat-2s, and a snare on every one.
    assert beat_coverage(snares, grid(), within_bar=1) == (8, 16)
    # …and on the other backbeat, beat 4, likewise.
    assert beat_coverage(snares, grid(), within_bar=3) == (8, 16)
    # Never on a downbeat.
    assert beat_coverage(snares, grid(), within_bar=0) == (0, 16)


# ─────────────────────────── the grid is the whole game ───────────────────────────


def test_a_tempo_a_quarter_percent_out_flattens_the_histogram():
    """The failure Experiment 1 hit. Not a hypothetical: this is why `refine_grid` exists.

    0.3 BPM at 129 is 0.23%. Over a thirty-second clip that is 69 ms of accumulated
    drift, and a sixteenth at this tempo is 116 ms — so the back half of the clip is
    assigned to the neighbouring step and the pattern dissolves.
    """
    kicks = four_on_the_floor(bars=16, bpm=128.9)
    counts = position_histogram(kicks, grid(bpm=129.2, seconds=30.0))
    assert sum(counts[i] for i in (0, 4, 8, 12)) < len(kicks)
    assert max(counts[i] for i in (1, 2, 3)) > 0


def test_refining_against_the_hits_recovers_the_pattern():
    kicks = four_on_the_floor(bars=16, bpm=128.9, offset=0.37)
    fitted = refine_grid(kicks, grid(bpm=129.2, offset=0.3, seconds=30.0))
    assert fitted.tempo_bpm == pytest.approx(128.9, abs=0.05)
    assert position_histogram(kicks, fitted) == [16, 0, 0, 0] * 4


def test_refining_puts_beat_one_back_on_a_beat():
    """The fit is over sixteenths and does not know which rung is a beat.

    Without the rotation step this returns the right pattern on the wrong step —
    [0,16,0,0, …] — which reads as a kick permanently a sixteenth late.
    """
    kicks = four_on_the_floor(bars=16, bpm=128.9, offset=0.37)
    fitted = refine_grid(kicks, grid(bpm=129.2, offset=0.3, seconds=30.0))
    assert position_histogram(kicks, fitted)[0] == 16


def test_refining_cannot_and_does_not_rescue_a_wrong_octave():
    """`refine_grid` sharpens a grid; only `grid_from_drums` can re-pick the octave."""
    kicks = four_on_the_floor(bars=8, bpm=128.9)
    fitted = refine_grid(kicks, grid(bpm=64.45, seconds=15.0))
    assert fitted.tempo_bpm < 100.0


def test_the_drums_resolve_the_octave_the_mix_got_wrong():
    """The Bounce failure, end to end.

    A mix-level tempo read of 64.6 BPM on a record with a kick on every beat at 128.9.
    Scored against the kicks rather than the mix, the halved grid loses on recall —
    half its beats have no drum on them — and the right octave wins.
    """
    kicks = four_on_the_floor(bars=8, bpm=128.9, offset=0.42)
    mix_said = TimingEstimate(tempo_bpm=64.6, beats_per_bar=4, confidence=0.61)
    fitted = grid_from_drums(kicks, mix_said, duration_s=15.0)

    assert fitted.tempo_bpm == pytest.approx(128.9, abs=0.1)
    assert position_histogram(kicks, fitted) == [8, 0, 0, 0] * 4


def test_refine_leaves_a_grid_alone_when_there_is_nothing_to_fit():
    before = grid()
    assert refine_grid([], before) is before


def test_grid_confidence_below_the_floor_abstains_everywhere():
    weak = grid(confidence=MIN_GRID_CONFIDENCE - 0.01)
    assert not weak.usable
    assert not swing_ratio(every_step(), weak).measured
    assert not offbeat_share(every_step(), weak).measured
    assert not timing_spread(every_step(), weak).detrended_ms.measured


# ──────────────────────────────────── swing ────────────────────────────────────


def test_straight_eighths_measure_as_straight():
    hats = [i * BEAT + BEAT / 2 for i in range(32)]
    figure = swing_ratio(hats, grid())
    assert figure.measured
    assert figure.value == pytest.approx(0.5, abs=0.01)


def test_triplet_swing_measures_as_two_thirds():
    hats = [i * BEAT + BEAT * 2 / 3 for i in range(32)]
    figure = swing_ratio(hats, grid())
    assert figure.measured
    assert figure.value == pytest.approx(0.667, abs=0.01)


def test_eleven_hats_is_not_a_swing_ratio():
    hats = [i * BEAT + BEAT / 2 for i in range(11)]
    figure = swing_ratio(hats, grid())
    assert not figure.measured
    assert figure.value is None
    assert "11" in figure.caveat


def test_sixteenths_are_not_reported_as_a_swing():
    """0.25 and 0.75 average to 0.5, and calling that 'straight' would be a lie."""
    hats = [i * BEAT + o for i in range(32) for o in (BEAT * 0.25, BEAT * 0.75)]
    figure = swing_ratio(hats, grid())
    assert figure.confidence == 0.0 or "sixteenth" in figure.caveat


# ─────────────────────────── programmed versus played ───────────────────────────


def test_a_perfect_sequence_measures_at_the_floor():
    spread = timing_spread(every_step(), grid())
    assert spread.detrended_ms.value == pytest.approx(0.0, abs=0.1)
    assert "floor" in spread.detrended_ms.caveat


def test_known_jitter_comes_back_as_itself():
    rng = np.random.default_rng(11)
    loose = [t + rng.normal(0, 0.020) for t in every_step(bars=6)]
    spread = timing_spread(loose, grid())
    assert spread.detrended_ms.value == pytest.approx(20.0, rel=0.3)


def test_a_figure_inside_the_detectors_own_jitter_says_so():
    rng = np.random.default_rng(3)
    slightly_loose = [t + rng.normal(0, 0.004) for t in every_step(bars=6)]
    spread = timing_spread(slightly_loose, grid())
    assert spread.detrended_ms.value < DETECTOR_JITTER_MS * 2
    assert "detector" in spread.detrended_ms.caveat


def test_tempo_drift_is_removed_rather_than_reported_as_looseness():
    """A grid 0.2% slow drifts steadily. That is the grid's error, not the drummer's."""
    drifting = [t * 1.002 for t in every_step(bars=6)]
    spread = timing_spread(drifting, grid())
    assert spread.raw_ms.value > spread.detrended_ms.value
    assert spread.detrended_ms.value == pytest.approx(0.0, abs=1.0)


def test_too_few_hits_is_not_a_distribution():
    spread = timing_spread([i * BEAT for i in range(6)], grid())
    assert not spread.raw_ms.measured
    assert not spread.detrended_ms.measured


# ─────────────────────────── bass ducked to the kick ───────────────────────────


SR = 8000


def bass_envelope(duck_at: list[float] | None, seconds: float = 16.0,
                  depth_db: float = 12.0, decay_db: float = 0.0):
    """A bass that is always sounding, optionally ducked at the given times.

    ``decay_db`` gives every *sixteenth* a note envelope, which is the thing a naive duck
    measurement mistakes for a sidechain.
    """
    times = np.arange(0.0, seconds, 1.0 / SR)
    level = np.zeros_like(times) - 12.0
    if decay_db:
        into_note = np.mod(times, STEP) / STEP
        level -= decay_db * into_note
    for kick in duck_at or []:
        since = times - kick
        inside = (since >= 0.0) & (since < 0.25)
        level[inside] -= depth_db * (1.0 - since[inside] / 0.25)
    return level, times


def test_a_real_duck_shows_up_as_excess_over_the_control():
    kicks = four_on_the_floor(bars=8)
    level, times = bass_envelope(duck_at=kicks, depth_db=12.0)
    result = kick_duck(level, times, kicks, grid(seconds=16.0))
    assert result.excess_db.measured
    assert result.excess_db.value == pytest.approx(12.0, abs=3.0)


def test_a_bass_with_note_envelopes_and_no_sidechain_reports_no_duck():
    """The false positive that nearly shipped: every plucked note dips after its attack."""
    kicks = four_on_the_floor(bars=8)
    level, times = bass_envelope(duck_at=None, decay_db=14.0)
    result = kick_duck(level, times, kicks, grid(seconds=16.0))
    assert result.dip_db.measured          # there IS a dip at every kick
    assert result.control_dip_db.measured  # and the same dip everywhere else
    assert abs(result.excess_db.value) < 3.0


def test_a_bass_that_does_not_play_on_the_kick_is_counted_not_credited():
    kicks = four_on_the_floor(bars=8)
    times = np.arange(0.0, 16.0, 1.0 / SR)
    level = np.full_like(times, -12.0)
    # Silent across the kick but sounding in between, which is what "the bass is arranged
    # around the kick" actually looks like. Silencing the whole clip instead would make
    # silence the 95th percentile and every position would read as active.
    for kick in kicks:
        level[(times > kick - 0.12) & (times < kick + 0.12)] = -90.0
    result = kick_duck(level, times, kicks, grid(seconds=16.0))
    assert result.kicks_bass_silent > 0
    assert not result.excess_db.measured


def test_envelope_db_tracks_level():
    quiet = np.full((SR, 2), 0.01)
    loud = np.full((SR, 2), 0.1)
    assert float(np.median(envelope_db(loud, SR)[0])) - float(
        np.median(envelope_db(quiet, SR)[0])
    ) == pytest.approx(20.0, abs=0.5)


# ──────────────────────────────── the Figure type ────────────────────────────────


def test_an_abstention_is_not_a_zero():
    figure = Figure.unmeasured("eleven hats is not a swing ratio")
    assert figure.value is None
    assert not figure.measured
    assert "eleven" in figure.render()


def test_zero_is_a_perfectly_good_measurement():
    figure = Figure(value=0.0, confidence=0.8, unit=" dB")
    assert figure.measured
    assert figure.render() == "0.00 dB"
