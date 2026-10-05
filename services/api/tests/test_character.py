"""Two observations about a recording that have no dial attached.

X0R-1320 asks whether a vocal was pitch-corrected; X0R-1321 asks how often each part
plays. Neither has a control behind it and neither is supposed to: there is nothing in
this application that tunes a vocal or makes a bass play more often, and inventing one
would be either the off-brief sequel the proposal refuses or composing somebody's part
for them.

Synthesised signals are the right tool for most of this, and for the usual reason: a line
placed exactly on the grid has an answer known by construction, so it says whether the
measurement responds to the thing it claims to measure. Where a figure needs real music -
whether the sung/not-sung gate actually catches a rap - that is recorded on the card from
real material rather than asserted here.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering import density, tuning

SR = 44100


def _sung(cents_jitter: float, seed: int = 0, seconds: float = 12.0, note_s: float = 0.5):
    """A melody, each note placed `cents_jitter` away from equal temperament."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    wave = np.zeros_like(t)
    melody = [60, 62, 64, 65, 67, 64, 62, 60]
    for index in range(int(seconds / note_s)):
        midi = melody[index % len(melody)]
        segment = (t >= index * note_s) & (t < (index + 1) * note_s)
        hz = 440 * 2 ** ((midi - 69) / 12) * 2 ** (rng.normal(0, cents_jitter) / 1200)
        wave[segment] = np.sin(2 * np.pi * hz * t[segment])
    return np.stack([wave, wave], axis=1)


def _glide(seconds: float = 12.0, seed: int = 0):
    """A pitch sliding at a constant rate in log-frequency, never settling.

    Two earlier versions of this fixture were wrong in opposite directions, which is
    worth keeping because both are easy mistakes. A **sine** sweep lingers at its turning
    points, piling pitch up at two phases: R = 0.285, above the gate, so the fixture was
    called sung. A **random walk** wide enough to roam hit the clip rails and sat there,
    which is a held pitch by another name: R = 0.88.

    A triangular sweep at a constant rate in log-frequency spends equal time in every
    semitone, which is what "settles on nothing" actually means, and lands near the two
    real non-sung vocals this gate was set against - they measure 0.027 and 0.130.
    """
    del seed  # deterministic; kept so callers can pass one
    t = np.arange(int(SR * seconds)) / SR
    period = 3.0
    phase = np.abs(((t / period) % 2.0) - 1.0)  # 0..1..0, linear in time
    hz = 110.0 * 2 ** (phase * 2.0)  # two octaves, constant semitones per second
    wave = np.sin(2 * np.pi * np.cumsum(hz) / SR)
    return np.stack([wave, wave], axis=1)


def _clicks(interval_s: float, seconds: float = 12.0, jitter_s: float = 0.0, seed: int = 0):
    """A note every `interval_s`, tapered at the end.

    The taper is not cosmetic, and the first version of this fixture did without it. A
    50 ms decaying tone cut off while still at 13% of full scale is a *discontinuity*,
    and an onset detector is right to call that an event - so every note produced two
    onsets 58 ms apart, every click train reported a 58 ms median whatever its real
    spacing, and five tests failed pointing at the metric. The metric was fine. With the
    discontinuity removed a 250 ms train reads 255 ms and a 450 ms train reads 453.

    Worth remembering outside the test too: a chopped or gated sample really does
    contain that extra event, and this measurement will count it.
    """
    rng = np.random.default_rng(seed)
    out = np.zeros(int(SR * seconds))
    t = np.arange(int(0.05 * SR)) / SR
    hit = np.sin(2 * np.pi * 220 * t) * np.exp(-40 * t)
    tail = int(0.01 * SR)
    hit[-tail:] *= np.linspace(1.0, 0.0, tail)
    when = 0.25
    while when < seconds - 0.1:
        start = int((when + rng.normal(0, jitter_s)) * SR)
        if 0 <= start < len(out) - len(hit):
            out[start : start + len(hit)] += hit
        when += interval_s
    return np.stack([out, out], axis=1)


# --- X0R-1320: is their vocal tuned, and to what -----------------------------------------


def test_a_line_on_the_grid_reads_as_on_the_grid():
    """The floor of the measurement. Two cents of jitter must not come back as ten."""
    measured = tuning.measure(_sung(2.0), SR)
    assert measured.sung is True
    assert measured.median_cents < 5.0, measured.median_cents


def test_a_looser_line_reads_as_looser():
    """The ordering is the whole product claim - "theirs is tighter than yours" - so it
    matters far more than either absolute number."""
    tight = tuning.measure(_sung(2.0, seed=1), SR)
    loose = tuning.measure(_sung(18.0, seed=1), SR)
    assert tight.median_cents < loose.median_cents


def test_the_record_s_own_tuning_is_removed_before_anything_is_called_off_pitch():
    """Not a refinement. A record tuned 30 cents sharp is not a singer who is sharp, and
    without this step the measurement makes that exact mistake about a person."""
    on_grid = _sung(2.0, seed=2)
    # The same performance, with the whole record shifted sharp.
    sharp = tuning.measure(_resampled(on_grid, 2 ** (30 / 1200)), SR)
    assert sharp.sung is True
    assert sharp.a4_cents > 15.0, "the shift should show up in the tuning reference"
    assert sharp.median_cents < 8.0, "and not in how centred the singer is"


def _resampled(samples: np.ndarray, ratio: float) -> np.ndarray:
    """Pitch-shift by resampling, which also changes the length - fine here."""
    mono = samples[:, 0]
    index = np.arange(0, len(mono), ratio)
    shifted = np.interp(index, np.arange(len(mono)), mono)
    return np.stack([shifted, shifted], axis=1)


def test_a_part_that_never_holds_a_pitch_is_refused_rather_than_called_flat():
    """The gate, and the one way this card could insult somebody. A rap is not out of
    tune. Measured on two real non-sung vocals at concentrations of 0.03 and 0.13,
    against 0.67 and 0.91 for sung lines - the threshold sits in that gap."""
    measured = tuning.measure(_glide(), SR)
    assert measured.sung is False
    assert "rapped" in measured.declined or "spoken" in measured.declined
    assert measured.concentration < tuning.MIN_CONCENTRATION


def test_the_gate_is_not_the_measurement_in_disguise():
    """Gating centredness on centredness would relabel every high reading as "not sung"
    and guarantee the metric never disagreed with itself. A line that is genuinely loose
    but genuinely sung has to come back sung."""
    loose = tuning.measure(_sung(25.0, seed=3), SR)
    assert loose.sung is True, "25 cents of wobble is a singer, not a rapper"
    assert loose.median_cents > 10.0


def test_the_gate_clears_a_loose_singer():
    """The threshold moved for this. At 0.35 a synthesised singer scattering 22 cents
    measured R = 0.26 and was told it was a rap, which is the card's named harm pointed
    the other way round. There is still a grey zone between roughly 20 and 30 cents that
    nothing available here resolves, and the gate errs toward answering inside it."""
    loose = tuning.measure(_sung(22.0, seed=40), SR)
    assert loose.sung is True, "22 cents of scatter is a singer having a loose day"


def test_a_near_empty_stem_abstains_on_the_sample_size():
    silence = np.zeros((SR * 3, 2))
    measured = tuning.measure(silence, SR)
    assert measured.sung is False
    assert "frames" in measured.declined


def test_the_tuning_reference_wraps_the_short_way_round():
    """A circular mean, because the quantity wraps at 50 cents: a record 49 sharp and one
    49 flat are one cent apart, and an ordinary mean of the two would report dead-on
    concert pitch from two records as far from it as it is possible to get."""
    cents = np.array([49.0, -49.0] * 50)
    assert abs(tuning.tuning_reference(cents)) > 40.0


def test_concentration_is_one_when_every_frame_sits_on_the_same_point():
    on_one_spot = np.full(200, 12.0)
    assert tuning.concentration(on_one_spot) == pytest.approx(1.0, abs=1e-6)


def test_concentration_is_nearly_zero_when_pitch_is_spread_evenly():
    """Which is what makes it the confidence in the tuning reference as well as the
    gate: on a uniform distribution the circular mean points nowhere, and the A4 it
    produces is noise. On a real rap it gave 449.3 Hz, 36 cents sharp and meaningless."""
    uniform = np.linspace(-50, 50, 500)
    assert tuning.concentration(uniform) < 0.05


# --- X0R-1321: how much space their parts leave --------------------------------------------


def test_the_median_interval_is_the_interval():
    """A quarter-second between clicks must read as about a quarter of a second."""
    measured = density.measure(_clicks(0.25), SR)
    assert measured.median_interval_s == pytest.approx(0.25, abs=0.02)


def test_a_busier_part_reads_as_busier():
    busy = density.measure(_clicks(0.18, seed=1), SR)
    sparse = density.measure(_clicks(0.45, seed=1), SR)
    assert busy.median_interval_s < sparse.median_interval_s
    assert busy.per_second > sparse.per_second


def test_it_survives_the_onset_shift_that_wrecks_absolute_placement():
    """The reason this card is not blocked on X0R-1319 or X0R-412. A constant offset on
    every onset cancels in the difference between consecutive ones, so the figure is
    unmoved by the 15-31 ms backtrack that makes absolute note placement unusable."""
    clean = density.measure(_clicks(0.25, seed=2), SR)
    jittered = density.measure(_clicks(0.25, seed=2, jitter_s=0.004), SR)
    assert jittered.median_interval_s == pytest.approx(clean.median_interval_s, abs=0.02)


def test_a_part_that_barely_plays_abstains():
    assert density.measure(_clicks(4.0), SR) is None
    assert density.measure(np.zeros((SR * 4, 2)), SR) is None


def test_two_parts_at_the_same_density_produce_no_sentence():
    """Below the threshold there is nothing worth saying, and saying it anyway is how a
    screen fills with rows nobody reads."""
    a = density.measure(_clicks(0.25, seed=4), SR)
    b = density.measure(_clicks(0.27, seed=5), SR)
    assert density.compare(a, b, "bass", False) == ""


def test_a_real_difference_is_said_with_both_numbers_in_it():
    mine = density.measure(_clicks(0.18, seed=6), SR)
    theirs = density.measure(_clicks(0.45, seed=7), SR)
    said = density.compare(mine, theirs, "bass", False)
    assert said
    assert "ms between notes" in said
    assert "no control" in said, "an observation has to say it is an observation"


def test_it_says_which_side_is_busier_the_right_way_round():
    """Easy to invert, and inverting it tells the user the opposite of the truth. A
    *longer* gap between your notes means theirs is the busier record."""
    sparse_mine = density.measure(_clicks(0.50, seed=8), SR)
    busy_theirs = density.measure(_clicks(0.20, seed=9), SR)
    assert "more often" in density.compare(sparse_mine, busy_theirs, "bass", False)

    busy_mine = density.measure(_clicks(0.20, seed=10), SR)
    sparse_theirs = density.measure(_clicks(0.50, seed=11), SR)
    assert "less often" in density.compare(busy_mine, sparse_theirs, "bass", False)


def test_an_absent_side_says_nothing_rather_than_dividing_by_it():
    one = density.measure(_clicks(0.25), SR)
    assert density.compare(one, None, "bass", False) == ""
    assert density.compare(None, one, "bass", False) == ""


def test_the_verb_agrees_with_the_instrument():
    mine = density.measure(_clicks(0.18, seed=12), SR)
    theirs = density.measure(_clicks(0.45, seed=13), SR)
    assert "drums play" in density.compare(mine, theirs, "drums", True)
    assert "bass plays" in density.compare(mine, theirs, "bass", False)


# --- as findings on the comparison ---------------------------------------------------------


def _as_moves(stem, mine, theirs, plural=False):
    from app.services.mastering.character import observations

    return observations(stem, str(stem), plural, mine, theirs, SR)


def test_both_observations_arrive_with_no_control():
    """They reuse the shape `punch` already uses, so the page renders them with no work -
    and an empty `control` is what stops a dial appearing for something no dial does."""
    from app.domain.notes import StemKind

    moves = _as_moves(StemKind.BASS, _clicks(0.18, seed=20), _clicks(0.45, seed=21))
    assert moves, "a 2.5x density difference should be worth a row"
    assert all(m.control == "" for m in moves)
    assert all(m.suggested == 0.0 for m in moves)


def test_tuning_is_only_asked_of_a_stem_that_can_be_sung():
    """A single f0 contour means nothing on a polyphonic stem, and `other` is a bag."""
    from app.domain.notes import StemKind
    from app.services.mastering.character import TUNED_STEMS

    assert StemKind.VOCALS in TUNED_STEMS
    for stem in (StemKind.GUITAR, StemKind.PIANO, StemKind.OTHER, StemKind.DRUMS):
        assert stem not in TUNED_STEMS

    moves = _as_moves(StemKind.GUITAR, _sung(2.0, seed=22), _sung(20.0, seed=23))
    assert not any(m.dimension == "tuning" for m in moves)


def test_a_vocal_pair_reports_which_side_is_closer_to_the_grid():
    from app.domain.notes import StemKind

    moves = _as_moves(StemKind.VOCALS, _sung(16.0, seed=24), _sung(2.0, seed=25))
    tuned = next(m for m in moves if m.dimension == "tuning")
    assert "closer to the grid" in tuned.headline
    assert tuned.reference < tuned.yours


def test_the_tuning_finding_carries_its_three_caveats():
    """Each one is a way the number gets over-read: as a verdict on the singer, as an
    absolute, or as something a dial will fix."""
    from app.domain.notes import StemKind

    moves = _as_moves(StemKind.VOCALS, _sung(16.0, seed=26), _sung(2.0, seed=27))
    detail = next(m for m in moves if m.dimension == "tuning").detail
    assert "not how well anybody sings" in detail
    assert "upper bound" in detail
    assert "no control for this" in detail


def test_a_rapped_side_says_why_there_is_no_comparison_rather_than_vanishing():
    """The user chose that reference and deserves to know why a row they expected is
    missing - and the sentence has to be about the recording, not about the person."""
    from app.domain.notes import StemKind

    moves = _as_moves(StemKind.VOCALS, _sung(4.0, seed=28), _glide())
    tuned = next(m for m in moves if m.dimension == "tuning")
    assert "No tuning comparison" in tuned.headline
    assert "the reference's" in tuned.detail
    assert "cannot be in or out of tune" in tuned.detail


def test_nothing_is_reported_when_the_reference_is_a_profile_with_no_audio():
    from app.domain.notes import StemKind

    assert _as_moves(StemKind.VOCALS, _sung(4.0, seed=29), None) == []


def test_a_missing_source_side_reports_nothing_rather_than_raising():
    from app.domain.notes import StemKind

    assert _as_moves(StemKind.BASS, None, _clicks(0.25)) == []


def test_two_vocals_equally_close_to_their_own_grids_produce_no_row():
    """Every other dimension has a "these are the same" threshold and this one shipped
    without it - which showed up as a track compared against *itself* reporting that the
    reference's vocal sat further from the grid than its own, by zero cents."""
    from app.domain.notes import StemKind

    same = _sung(6.0, seed=50)
    assert not [m for m in _as_moves(StemKind.VOCALS, same, same) if m.dimension == "tuning"]


def test_neither_side_singing_says_nothing_at_all():
    """An instrumental, or two rapped records. Explaining the absence of a comparison
    nobody expected is noise; explaining it when one side *does* sing is not."""
    from app.domain.notes import StemKind

    both_spoken = _as_moves(StemKind.VOCALS, _glide(), _glide())
    assert not [m for m in both_spoken if m.dimension == "tuning"]


def test_the_tuning_headline_agrees_with_its_subject():
    """"The reference's vocals sits closer to the grid" - caught by reading the
    generated text rather than by any assertion, which is the argument for generating
    the demo through the real code instead of writing it by hand."""
    from app.domain.notes import StemKind
    from app.services.mastering.character import observations

    loose, tight = _sung(18.0, seed=60), _sung(2.0, seed=61)
    plural = observations(StemKind.VOCALS, "vocals", True, loose, tight, SR)
    assert "vocals sit closer" in next(m for m in plural if m.dimension == "tuning").headline

    single = observations(StemKind.VOCALS, "vocal", False, loose, tight, SR)
    assert "vocal sits closer" in next(m for m in single if m.dimension == "tuning").headline
