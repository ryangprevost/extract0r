"""Sparkle: manufacturing top end that was never recorded.

Three attempts got this wrong before it worked, and each failure is pinned by a test
here: a fixed gain that raised the air band by 0.36 dB at maximum, amplitude arithmetic
where the signals add as power, and a peak cap so tight that every setting delivered the
same thing.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.exciter import (
    MAX_FROM_HZ,
    MAX_SPARKLE_DB,
    MIN_FROM_HZ,
    SparkleReport,
    add_sparkle,
)

SR = 44100


def _music(seconds: float = 4.0, top: bool = True) -> np.ndarray:
    """Something with harmonic content in the upper mids, to make harmonics from."""
    t = np.arange(int(SR * seconds)) / SR
    signal = sum(0.15 * np.sin(2 * np.pi * hz * t) for hz in (220, 660, 1800, 2600))
    if top:
        signal = signal + 0.02 * np.sin(2 * np.pi * 9000 * t)
    return np.stack([signal, signal * 0.98], axis=1)


def _air(x, sr=SR):
    from scipy.signal import butter, sosfiltfilt

    sos = butter(4, 8000.0, btype="high", fs=sr, output="sos")
    return float(np.sqrt(np.mean(sosfiltfilt(sos, x.mean(axis=1)) ** 2)))


def _band(x, low, high, sr=SR):
    from scipy.signal import butter, sosfiltfilt

    sos = butter(4, [low, min(high, sr / 2 * 0.99)], btype="band", fs=sr, output="sos")
    return float(np.sqrt(np.mean(sosfiltfilt(sos, x.mean(axis=1)) ** 2)))


def test_nothing_asked_for_is_nothing_done():
    audio = _music()
    assert np.array_equal(add_sparkle(audio, SR, 0.0), audio)


def test_it_adds_roughly_the_decibels_it_was_asked_for():
    """The first version applied a fixed fraction of the generated harmonics, which
    raised the air band by 0.36 dB at maximum - how much a constant gain achieves depends
    entirely on how much top end the mix already had."""
    audio = _music()
    before = _air(audio)

    for asked in (1.5, 3.0, 6.0):
        report = SparkleReport()
        out = add_sparkle(audio, SR, asked, report=report)
        got = 20 * np.log10(_air(out) / before)
        # Generous, because softening the harmonics moves the figure a little. The point
        # is that the number on the dial means something.
        assert asked - 1.0 < got < asked + 2.0
        # The report measures with a causal filter and this test with a zero-phase one,
        # so they agree on the answer without agreeing to the last decimal.
        assert report.air_added_db == pytest.approx(got, abs=0.6)


def test_more_is_more():
    audio = _music()
    amounts = [_air(add_sparkle(audio, SR, db)) for db in (1.5, 3.0, 4.5, 6.0)]
    assert amounts == sorted(amounts)


def test_a_dark_source_is_the_case_this_exists_for():
    """A high shelf can only lift what is there. A part played from a synth patch has
    nothing above 8 kHz to lift, so a shelf raises hiss and this has to raise music."""
    audio = _music(top=False)
    report = SparkleReport()
    out = add_sparkle(audio, SR, 4.5, report=report)

    assert _air(out) > _air(audio) * 2
    assert report.air_added_db > 2.0


def test_what_arrives_follows_the_playing():
    """If the added content did not track the source it would be a haze, not sparkle."""
    audio = _music()
    report = SparkleReport()
    add_sparkle(audio, SR, 4.5, report=report)
    assert report.tracks_source > 0.4


def test_the_harsh_range_is_left_alone():
    """2-5 kHz is where harshness lives. Harmonics are kept above it, or this would be a
    midrange distortion control wearing a brighter name."""
    audio = _music()
    out = add_sparkle(audio, SR, 6.0)

    harsh_rise = 20 * np.log10(_band(out, 2000, 5000) / _band(audio, 2000, 5000))
    air_rise = 20 * np.log10(_air(out) / _air(audio))
    assert harsh_rise < air_rise / 2


def test_peaks_are_kept_in_hand():
    """This runs just before the limiter, so every decibel of new peak is a decibel the
    master gives back. Capping the gain was tried and disabled the control; softening the
    spikes is what let the energy through."""
    audio = _music()
    out = add_sparkle(audio, SR, MAX_SPARKLE_DB)

    rise = 20 * np.log10(np.abs(out).max() / np.abs(audio).max())
    assert rise < 6.0


def test_the_setting_is_clamped():
    audio = _music()
    report = SparkleReport()
    add_sparkle(audio, SR, 99.0, report=report)
    assert report.sparkle_db <= MAX_SPARKLE_DB


def test_silence_does_not_divide_by_zero():
    quiet = np.zeros((SR, 2))
    out = add_sparkle(quiet, SR, 4.5)
    assert np.all(np.isfinite(out))


def test_mono_input_comes_back_stereo_and_finite():
    mono = np.sin(np.arange(SR * 2) / 12)
    out = add_sparkle(mono, SR, 3.0)
    assert out.ndim == 2 and out.shape[1] == 2
    assert np.all(np.isfinite(out))


def test_the_focus_decides_between_presence_and_air():
    """An exciter is sold on three words - brighter, clearer, more present - and which one
    it delivers is entirely where the harmonics land. Low is definition; high is sheen."""
    audio = _music()

    low = add_sparkle(audio, SR, 4.0, 3500.0)
    high = add_sparkle(audio, SR, 4.0, 9000.0)

    def presence(x):
        return _band(x, 3000, 6000)

    assert presence(low) > presence(high) * 1.5
    # Both still reach the top; it is the presence range that separates them.
    assert _air(low) > _air(audio) and _air(high) > _air(audio)


def test_the_focus_is_clamped_to_a_usable_range():
    """Below about 3 kHz it stops adding definition and starts adding grit."""
    audio = _music()
    report = SparkleReport()
    add_sparkle(audio, SR, 3.0, 100.0, report)
    assert report.from_hz >= MIN_FROM_HZ

    report = SparkleReport()
    add_sparkle(audio, SR, 3.0, 40000.0, report)
    assert report.from_hz <= MAX_FROM_HZ
