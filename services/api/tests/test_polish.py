"""The three finishing moves a reference match cannot make for you.

Each test pins a claim the feature makes to the user, not an implementation detail:
brightness lifts only the top, widening spares the bass and survives a mono fold, and
the ceiling headroom stops the limiter being over-driven to hit a loudness number.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.dsp import (
    apply_gain_db,
    limit_with_report,
    peak_db,
    stereo_width,
)
from app.services.mastering.polish import (
    MAX_AIR_DB,
    MAX_WIDTH,
    Polish,
    add_air,
    ceiling_headroom,
    crest_db,
    shelf_curve,
    widen_above,
)

SR = 44100


def noise(seconds=3.0, seed=0, width=0.4):
    """Stereo noise with a controllable amount of side content."""
    rng = np.random.default_rng(seed)
    mid = rng.normal(0, 0.15, int(seconds * SR))
    side = rng.normal(0, 0.15 * width, int(seconds * SR))
    return np.stack([mid + side, mid - side], axis=1).astype("float64")


def band_energy_db(samples, low, high, sr=SR):
    mono = samples.mean(axis=1)
    spec = np.abs(np.fft.rfft(mono)) ** 2
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / sr)
    return 10 * np.log10(spec[(freqs >= low) & (freqs < high)].sum() + 1e-20)


# ──────────────────────────────── brightness ────────────────────────────────


def test_the_shelf_leaves_the_bottom_alone_and_lifts_the_top():
    curve = shelf_curve(4096, SR, hz=8000.0, gain_db=6.0)
    freqs = np.fft.rfftfreq(4096, d=1.0 / SR)

    at = lambda hz: float(curve[np.argmin(np.abs(freqs - hz))])  # noqa: E731
    assert at(100) == pytest.approx(1.0, abs=0.01)
    assert at(1000) == pytest.approx(1.0, abs=0.01)
    assert at(4000) == pytest.approx(1.0, abs=0.05)  # the ramp starts here
    assert at(16000) == pytest.approx(10 ** (6 / 20), rel=0.02)  # full lift


def test_the_shelf_has_no_corner():
    """A step in frequency is a smear in time, heard as a lisp on cymbals."""
    curve = shelf_curve(4096, SR, hz=8000.0, gain_db=6.0)
    jumps = np.abs(np.diff(20 * np.log10(curve)))
    assert jumps.max() < 0.5, "the shelf steps rather than ramps"


def test_brightness_lifts_the_top_without_moving_the_bass():
    audio = noise(seed=1)
    bright = add_air(audio, SR, gain_db=4.0, hz=8000.0)

    low = band_energy_db(bright, 20, 250) - band_energy_db(audio, 20, 250)
    top = band_energy_db(bright, 10000, 20000) - band_energy_db(audio, 10000, 20000)
    assert low == pytest.approx(0.0, abs=0.2)
    assert top > 3.0


def test_a_lower_shelf_reaches_down_into_presence():
    """What "clarity" usually means: the gap is often at 3 kHz, not at 10 kHz."""
    audio = noise(seed=2)
    air = add_air(audio, SR, gain_db=4.0, hz=10000.0)
    presence = add_air(audio, SR, gain_db=4.0, hz=3000.0)

    band = (2000, 6000)
    assert band_energy_db(presence, *band) - band_energy_db(audio, *band) > 2.0
    assert band_energy_db(air, *band) - band_energy_db(audio, *band) < 0.5


def test_brightness_is_clamped():
    audio = noise(seed=3)
    absurd = add_air(audio, SR, gain_db=40.0)
    capped = add_air(audio, SR, gain_db=MAX_AIR_DB)
    top = (12000, 20000)
    assert band_energy_db(absurd, *top) == pytest.approx(
        band_energy_db(capped, *top), abs=0.01
    )


def test_zero_brightness_changes_nothing():
    audio = noise(seed=4)
    assert np.array_equal(add_air(audio, SR, 0.0), audio)


# ──────────────────────────────── width ────────────────────────────────


def test_widening_makes_it_wider():
    audio = noise(seed=5)
    wide = widen_above(audio, SR, factor=1.4)
    assert stereo_width(wide) > stereo_width(audio)


def test_widening_leaves_the_low_end_exactly_where_it_was():
    """The whole reason the widener is band-limited.

    Side content cancels when channels sum to mono, and the low end carries most of a
    mix's energy - widen it and the bass vanishes on a phone speaker or a club rig.
    """
    audio = noise(seed=6)
    wide = widen_above(audio, SR, factor=1.5, crossover_hz=250.0)

    below = band_energy_db(wide, 20, 200) - band_energy_db(audio, 20, 200)
    assert below == pytest.approx(0.0, abs=0.15)


def test_the_low_end_survives_a_mono_fold():
    audio = noise(seed=7)
    wide = widen_above(audio, SR, factor=1.5, crossover_hz=250.0)

    def to_mono(x):
        m = x.mean(axis=1)
        return np.stack([m, m], axis=1)

    kept = band_energy_db(to_mono(wide), 20, 200) - band_energy_db(to_mono(audio), 20, 200)
    assert kept == pytest.approx(0.0, abs=0.2)


def test_a_width_of_one_is_a_true_no_op():
    """Zero-phase split, so low + high reconstructs the input exactly."""
    audio = noise(seed=8)
    assert np.allclose(widen_above(audio, SR, factor=1.0), audio, atol=1e-12)


def test_width_is_clamped():
    audio = noise(seed=9)
    assert np.allclose(
        widen_above(audio, SR, factor=99.0), widen_above(audio, SR, factor=MAX_WIDTH)
    )


def test_a_mono_source_is_not_given_invented_stereo():
    mono = np.stack([np.random.default_rng(10).normal(0, 0.2, SR)] * 2, axis=1)
    wide = widen_above(mono, SR, factor=1.5)
    assert stereo_width(wide) == pytest.approx(0.0, abs=1e-6)


# ──────────────────────────────── ceiling headroom ────────────────────────────
#
# What this actually is, having derived it rather than assumed it: the back-off equals
# the reference's peak minus our ceiling. Matching a reference's LUFS from a lower
# ceiling means over-driving the limiter by exactly that much. It is a peak-alignment
# correction, not a dynamics measurement - it will never make a master more dynamic than
# its reference, which is what the headroom dial is for.


def bursty(seconds=4.0, seed=11, width=0.4):
    """Noise with real transients, so it has a crest factor worth talking about."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    envelope = 0.08 + np.exp(-((t % 0.5) * 12.0))
    mid = rng.normal(0, 0.12, n) * envelope
    side = rng.normal(0, 0.12 * width, n) * envelope
    return np.stack([mid + side, mid - side], axis=1)


def test_a_reference_peaking_above_our_ceiling_makes_us_hold_back():
    """The usual case: commercial masters peak at 0 dBFS, and MP3 decoding overshoots."""
    hot = apply_gain_db(bursty(), 10.0)
    hot = np.clip(hot, -1.06, 1.06)  # peaks at about +0.5 dBFS

    guard, reference_crest = ceiling_headroom(hot, SR, ceiling_db=-1.0)
    assert guard == pytest.approx(peak_db(hot) - (-1.0), abs=0.01)
    assert guard > 0.0
    assert reference_crest > 0.0


def test_a_reference_already_under_our_ceiling_needs_no_back_off():
    quiet = apply_gain_db(bursty(seed=12), -12.0)
    guard, _ = ceiling_headroom(quiet, SR, ceiling_db=-1.0)
    assert guard == 0.0


def test_backing_off_lands_on_the_references_crest():
    """The identity the function claims: match its loudness-per-peak, inherit its crest."""
    from app.services.mastering.loudness_meter import integrated_loudness

    hot = np.clip(apply_gain_db(bursty(), 12.0), -1.06, 1.06)
    ceiling = -1.0
    guard, reference_crest = ceiling_headroom(hot, SR, ceiling_db=ceiling)

    reference_lufs, _ = integrated_loudness(hot, SR)
    target_lufs = float(reference_lufs) - guard
    # A master that peaks at the ceiling and sits at target_lufs has this crest.
    assert ceiling - target_lufs == pytest.approx(reference_crest, abs=0.01)


def test_holding_back_actually_buys_dynamic_range():
    """End to end: less gain into the limiter means less gain reduction out of it."""
    mix = bursty(seed=13)
    hot = apply_gain_db(mix, 12.0)
    eased = apply_gain_db(mix, 9.0)

    _, hot_report = limit_with_report(hot, SR, -1.0)
    _, eased_report = limit_with_report(eased, SR, -1.0)

    assert eased_report.max_reduction_db < hot_report.max_reduction_db
    assert eased_report.active_fraction < hot_report.active_fraction
    assert crest_db(eased, SR) > crest_db(hot, SR)


def test_the_limiter_reports_doing_nothing_when_it_does_nothing():
    quiet = noise(seed=14) * 0.05
    out, report = limit_with_report(quiet, SR, -1.0)
    assert report.max_reduction_db == 0.0
    assert report.active_fraction == 0.0
    assert np.allclose(out, quiet)


# ──────────────────────────────── the settings object ────────────────────────


def test_defaults_ask_for_nothing_but_still_protect():
    polish = Polish()
    assert not polish.wanted()
    assert polish.protect_dynamics is True


@pytest.mark.parametrize(
    "polish",
    [Polish(air_db=1.0), Polish(width=1.2), Polish(headroom_db=1.0)],
)
def test_any_dial_off_centre_counts_as_wanted(polish):
    assert polish.wanted()
