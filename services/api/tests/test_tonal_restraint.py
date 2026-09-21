"""How far the tool is allowed to move a mix, and why the limits are where they are.

Written from a real failure. A bass-heavy electronic mix was matched against MSTRKRFT's
"Bounce" and came back, in its author's words, "super hollow with no bass ... very spread
out in my car". Measured against the source, level-matched, the master had been cut 4-6 dB
below 250 Hz and lifted 5-10 dB above 2 kHz: a 14.6 dB tilt end to end.

Nothing in the chain was individually out of bounds. The match curve respected its own
per-band clamps, the brightness shelf respected its own ceiling, and both were correcting
the *same measured gap* with no knowledge of each other. Three separate limits were
missing, and this file is where each of them is pinned:

* a bound on how far the whole curve may tilt, not just each band;
* real protection for 60-250 Hz, where "bass" lives on every system anyone actually
  listens on, rather than for the sub alone;
* a suggestion engine that offers a nudge on top of the match rather than a second
  full correction of the gap the match is already closing.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.dsp import (
    DEFAULT_HOP,
    DEFAULT_N_FFT,
    MatchSettings,
    average_spectrum,
    matching_curve,
)
from app.services.mastering.suggest import (
    CLOSE_FRACTION,
    FURTHER_THAN_EQ_CAN_FIX_DB,
    MAX_SUGGESTED_SHELF_DB,
    suggest,
)

SR = 44100


def _tone_stack(weights: dict[float, float], seconds: float = 8.0) -> np.ndarray:
    """Noise shaped to a given spectral tilt, as a stand-in for a whole mix."""
    from scipy.signal import butter, sosfilt

    rng = np.random.default_rng(11)
    n = int(SR * seconds)
    out = np.zeros((n, 2))
    for hz, gain in weights.items():
        sos = butter(2, [max(hz * 0.7, 20) / (SR / 2), min(hz * 1.4, SR / 2 * 0.98) / (SR / 2)],
                     btype="band", output="sos")
        band = sosfilt(sos, rng.standard_normal((n, 2)), axis=0)
        out += band * gain
    return out / np.abs(out).max() * 0.5


def _bass_heavy() -> np.ndarray:
    return _tone_stack({50: 8.0, 100: 6.0, 200: 3.0, 800: 1.0, 4000: 0.35, 11000: 0.2})


def _bright() -> np.ndarray:
    return _tone_stack({50: 1.0, 100: 1.2, 200: 1.5, 800: 2.0, 4000: 2.5, 11000: 2.0})


def _curve_db(source: np.ndarray, reference: np.ndarray, **kwargs) -> tuple:
    a = average_spectrum(source, DEFAULT_N_FFT, DEFAULT_HOP)
    b = average_spectrum(reference, DEFAULT_N_FFT, DEFAULT_HOP)
    db = 20 * np.log10(matching_curve(a, b, SR, MatchSettings(**kwargs)))
    freqs = np.fft.rfftfreq(DEFAULT_N_FFT, 1 / SR)
    return db, freqs


def _mean_db(db, freqs, low, high) -> float:
    mask = (freqs >= low) & (freqs < high)
    return float(db[mask].mean())


# --- the tilt limit -------------------------------------------------------------------


def test_two_very_different_songs_do_not_produce_a_huge_tilt():
    """The headline guard. Per-band clamps bound each band and say nothing about the
    total, so a reference with a different centre of gravity pins the curve to its floor
    at the bottom and its ceiling at the top - twelve decibels of tilt, measured, on the
    real pair this test was written from."""
    db, freqs = _curve_db(_bass_heavy(), _bright())
    audible = (freqs > 30) & (freqs < 16000)
    span = float(db[audible].max() - db[audible].min())

    assert span <= MatchSettings().max_tilt_db + 0.1, f"tilted the master {span:.1f} dB"


def test_the_tilt_limit_scales_the_curve_rather_than_clipping_it():
    """Shape survives, size changes - the same treatment a per-stem tone request gets.
    Clipping would flatten the extremes into plateaux and leave the middle alone, which
    changes what the curve says rather than how loudly it says it."""
    source, reference = _bass_heavy(), _bright()
    loose, freqs = _curve_db(source, reference, max_tilt_db=100.0)
    tight, _ = _curve_db(source, reference, max_tilt_db=6.0)

    audible = (freqs > 30) & (freqs < 16000)
    ratio = tight[audible] / np.where(np.abs(loose[audible]) < 1e-9, 1e-9, loose[audible])
    moving = np.abs(loose[audible]) > 0.5
    assert np.std(ratio[moving]) < 0.05, "the curve changed shape, not just size"


def test_a_close_pair_is_left_alone_by_the_tilt_limit():
    """The guard must not become a tax on matches that were already reasonable."""
    source = _bright()
    db, freqs = _curve_db(source, source * 0.9)
    audible = (freqs > 30) & (freqs < 16000)
    assert float(db[audible].max() - db[audible].min()) < 1.0


# --- the low end ----------------------------------------------------------------------


def test_the_bass_a_car_can_actually_play_is_protected():
    """60-250 Hz, not the sub. The old guard covered below 140 Hz, so the correction piled
    up just above the corner and dug a 5 dB notch at 105 Hz - through the kick and bass
    fundamentals, and exactly the band a car stereo reproduces."""
    db, freqs = _curve_db(_bass_heavy(), _bright())
    assert _mean_db(db, freqs, 60, 250) > -2.0, "cut the bass out of the mix"


def test_there_is_no_notch_left_where_the_guard_used_to_end():
    """A guard that switches on creates a cliff, and the correction dumps into the band
    just above it. The bass should slope, not dip: no band between 60 and 250 Hz should be
    cut much harder than the octave above it."""
    db, freqs = _curve_db(_bass_heavy(), _bright())
    low = _mean_db(db, freqs, 60, 120)
    mid = _mean_db(db, freqs, 120, 250)
    above = _mean_db(db, freqs, 250, 500)

    assert low <= mid + 1.5, f"notch at 60-120 Hz: {low:.2f} against {mid:.2f} above it"
    assert mid <= above + 2.5, f"notch at 120-250 Hz: {mid:.2f} against {above:.2f}"


def test_a_boost_of_the_low_end_is_not_restricted_the_same_way():
    """The guard is about *cuts*. A mix genuinely short of low end should still be given
    it - the asymmetry is the whole point."""
    db, freqs = _curve_db(_bright(), _bass_heavy())
    assert _mean_db(db, freqs, 60, 250) > 0.5


# --- the suggestions on top -------------------------------------------------------------


def test_a_suggested_shelf_is_a_nudge_rather_than_a_second_full_correction():
    """The shelves land on top of a matching curve that has already moved the same bands.
    Closing 70% of the remaining gap with a 6 dB ceiling meant both stages correcting the
    same difference, which is how a mix ends up 10 dB brighter than it started."""
    result = suggest(_bass_heavy(), _bright(), SR)
    assert result.polish.air_db <= MAX_SUGGESTED_SHELF_DB
    assert result.polish.warmth_db <= MAX_SUGGESTED_SHELF_DB
    assert result.polish.bass_db <= MAX_SUGGESTED_SHELF_DB


def test_a_gap_too_big_for_eq_is_named_as_such():
    """Honest rather than silent. Past a point the two recordings are not the same kind of
    song, and no shelf will make them one."""
    result = suggest(_bass_heavy(), _bright(), SR)
    brightness = next((r for r in result.reasons if r.control == "brightness"), None)
    if brightness is None:
        pytest.skip("this fixture pair produced no brightness suggestion")

    presence_gap = result.bands["presence"][2]
    if presence_gap > FURTHER_THAN_EQ_CAN_FIX_DB:
        assert "the two songs being different" in brightness.text


def test_closing_a_fraction_means_a_fraction():
    """Pins the constant itself. It was 0.7, which on the real pair asked for the maximum
    the control allows - which is not a fraction of anything."""
    assert 0.2 <= CLOSE_FRACTION <= 0.5


def test_the_whole_chain_stays_inside_a_sane_tilt():
    """Match plus both shelves, which is what actually reaches the file. Measured on the
    real pair: 16.9 dB of tilt before these limits, 8.4 dB after."""
    from app.services.mastering.polish import bell_curve, shelf_curve

    source, reference = _bass_heavy(), _bright()
    result = suggest(source, reference, SR)
    db, freqs = _curve_db(source, reference)

    total = (
        db
        + 20 * np.log10(shelf_curve(DEFAULT_N_FFT, SR, result.polish.air_hz, result.polish.air_db))
        + 20 * np.log10(bell_curve(DEFAULT_N_FFT, SR, 450.0, result.polish.warmth_db))
    )
    audible = (freqs > 30) & (freqs < 16000)
    span = float(total[audible].max() - total[audible].min())
    assert span < 11.0, f"the whole chain tilts the mix {span:.1f} dB"
