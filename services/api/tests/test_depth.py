"""Depth and saturation: space, glue and body.

The ambience here is a rebuild. The first version ran at 8% wet with no filtering and the
first thing anyone heard was reverb on the drums - not the idea failing, the build
failing. This one band-limits the wet signal before blending and counts the blend in
fractions of a percent, and the cymbal test below is what makes that checkable.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.depth import (
    MAX_AMBIENCE_MIX,
    MAX_PARALLEL_MIX,
    MAX_SIDE_AIR_DB,
    WET_HIGH_HZ,
    WET_LOW_HZ,
    DepthReport,
    add_ambience,
    add_side_air,
    parallel_compress,
)
from app.services.mastering.saturation import (
    MAX_SATURATION_DB,
    SaturationReport,
    add_saturation,
)

SR = 44100


def _music(seconds: float = 4.0) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    hits = ((t * 4) % 1.0 < 0.08).astype(float)
    signal = sum(0.15 * np.sin(2 * np.pi * hz * t) for hz in (110, 440, 1800))
    cymbals = 0.08 * np.sin(2 * np.pi * 12000 * t) * hits
    return np.stack([signal + cymbals, signal * 0.98 + cymbals * 0.9], axis=1)


def _band(x, low, high):
    from scipy.signal import butter, sosfiltfilt

    sos = butter(4, [low, min(high, SR / 2 * 0.99)], btype="band", fs=SR, output="sos")
    return float(np.sqrt(np.mean(sosfiltfilt(sos, x, axis=0) ** 2)))


# --- ambience -------------------------------------------------------------------------


def test_the_tail_never_reaches_the_cymbals():
    """The whole reason this was rebuilt. An unfiltered tail on the drums is the first
    thing anyone hears, so the wet signal is low-passed before it is blended."""
    audio = _music()
    out = add_ambience(audio, SR, MAX_AMBIENCE_MIX)

    change = 20 * np.log10(_band(out, 10000, 16000) / _band(audio, 10000, 16000))
    assert abs(change) < 1.0


def test_the_tail_does_not_muddy_the_bottom_either():
    audio = _music()
    out = add_ambience(audio, SR, MAX_AMBIENCE_MIX)

    change = 20 * np.log10(_band(out, 30, 150) / _band(audio, 30, 150))
    assert abs(change) < 1.0


def test_it_does_something_in_the_range_it_is_allowed():
    """Filtered to 200 Hz - 10 kHz, so that is where it has to show up."""
    audio = _music()
    quiet = add_ambience(audio, SR, 0.005)
    loud = add_ambience(audio, SR, MAX_AMBIENCE_MIX)

    def tail(x):
        # Whatever is not the dry signal, in the band the tail lives in.
        return _band(x - audio, WET_LOW_HZ + 100, WET_HIGH_HZ - 1000)

    assert tail(loud) > tail(quiet) > 0


def test_ambience_off_is_a_true_no_op():
    audio = _music()
    assert np.array_equal(add_ambience(audio, SR, 0.0), audio)


def test_the_blend_is_capped_low():
    """Past a few percent it stops being depth and becomes an effect, which is exactly
    how the first version failed."""
    report = DepthReport()
    add_ambience(_music(), SR, 0.9, report=report)
    assert report.ambience_mix <= MAX_AMBIENCE_MIX


# --- parallel compression --------------------------------------------------------------


def test_parallel_glue_is_a_balance_not_a_volume():
    """Level-matched before blending, or every comparison of it is really a comparison
    of loudness."""
    audio = _music()
    out = parallel_compress(audio, SR, 0.2)

    change = 20 * np.log10(
        float(np.sqrt(np.mean(out**2))) / float(np.sqrt(np.mean(audio**2)))
    )
    assert abs(change) < 0.5


def test_parallel_glue_lifts_the_quiet_moments():
    # A mix with loud and quiet stretches. The default fixture runs at one level, so
    # there is nothing quiet in it to lift and every percentile is the same number.
    audio = _music(seconds=8.0)
    t = np.arange(len(audio)) / SR
    audio = audio * np.where((t % 4.0) < 2.0, 1.0, 0.2)[:, None]

    out = parallel_compress(audio, SR, MAX_PARALLEL_MIX)

    def quiet_vs_typical(x):
        s = np.abs(x.mean(axis=1))
        window = SR // 10
        usable = len(s) // window * window
        levels = s[:usable].reshape(-1, window).mean(axis=1)
        return float(np.percentile(levels, 20) / (np.percentile(levels, 50) + 1e-12))

    assert quiet_vs_typical(out) > quiet_vs_typical(audio)


def test_parallel_off_is_a_true_no_op():
    audio = _music()
    assert np.array_equal(parallel_compress(audio, SR, 0.0), audio)


# --- side air ---------------------------------------------------------------------------


def test_side_air_leaves_the_middle_exactly_alone():
    """The groove lives in the mid channel. If this moved it, it would be a tone control
    wearing a width control's name."""
    audio = _music()
    out = add_side_air(audio, SR, MAX_SIDE_AIR_DB)

    assert np.abs(out.mean(axis=1) - audio.mean(axis=1)).max() < 1e-9


def test_side_air_widens_the_top_and_not_the_bottom():
    audio = _music()
    out = add_side_air(audio, SR, 4.0)

    def side(x, low, high):
        return _band(np.stack([(x[:, 0] - x[:, 1]) / 2] * 2, axis=1), low, high)

    assert side(out, 8000, 16000) > side(audio, 8000, 16000) * 1.2
    assert side(out, 60, 200) == pytest.approx(side(audio, 60, 200), rel=0.02)


def test_a_mono_input_gains_no_width():
    mono = np.stack([np.sin(np.arange(SR) / 20)] * 2, axis=1)
    assert np.abs(add_side_air(mono, SR, 4.0) - mono).max() < 1e-9


# --- saturation --------------------------------------------------------------------------


def test_saturation_makes_harmonics():
    """A pure tone in, harmonics out. If this failed, nothing else about the control
    would mean anything."""
    t = np.arange(SR) / SR
    tone = np.stack([0.3 * np.sin(2 * np.pi * 300 * t)] * 2, axis=1)

    def thd(x):
        mono = x.mean(axis=1)
        spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) ** 2
        freqs = np.fft.rfftfreq(len(mono), 1 / SR)

        def at(hz):
            return spectrum[(freqs > hz - 15) & (freqs < hz + 15)].sum()

        return 10 * np.log10(sum(at(300 * n) for n in (2, 3, 4, 5)) / at(300) + 1e-20)

    assert thd(add_saturation(tone, SR, MAX_SATURATION_DB)) > thd(
        add_saturation(tone, SR, 0.25)
    ) + 2.0


def test_the_dial_spans_a_musical_range():
    """Calibrated to about 3% distortion at the bottom and 10% at the top. An earlier
    mapping put the whole range inside the straight part of the curve, where every
    setting produced the same thing."""
    t = np.arange(SR) / SR
    tone = np.stack([0.3 * np.sin(2 * np.pi * 300 * t)] * 2, axis=1)

    def distortion(amount):
        out = add_saturation(tone, SR, amount)
        residual = out - tone * (
            float(np.sqrt(np.mean(out**2))) / float(np.sqrt(np.mean(tone**2)))
        )
        return float(np.sqrt(np.mean(residual**2)) / np.sqrt(np.mean(tone**2)))

    assert 0.002 < distortion(0.5) < 0.04
    assert 0.01 < distortion(MAX_SATURATION_DB) < 0.10


def test_saturation_adds_no_dc():
    """A squared term is strictly positive, so the naive even-harmonic trick puts a DC
    offset straight into the master."""
    report = SaturationReport()
    out = add_saturation(_music(), SR, MAX_SATURATION_DB, report)
    assert abs(float(out.mean())) < 1e-4


def test_saturation_is_a_balance_not_a_volume():
    audio = _music()
    out = add_saturation(audio, SR, MAX_SATURATION_DB)
    change = 20 * np.log10(
        float(np.sqrt(np.mean(out**2))) / float(np.sqrt(np.mean(audio**2)))
    )
    assert abs(change) < 1.0


def test_the_sub_is_left_clean():
    """Distorting the bottom does not sound like weight, it sounds like a broken speaker."""
    audio = _music()
    out = add_saturation(audio, SR, MAX_SATURATION_DB)
    assert _band(out, 30, 80) == pytest.approx(_band(audio, 30, 80), rel=0.1)


def test_it_barely_touches_the_peaks_at_these_settings():
    """At the old 3-10% range this rounded transients noticeably and the report existed to
    warn about it. Dropped to 1-2.5% it hardly moves them at all - which is the point, but
    it means the honest assertion is that the number stays small, not that it is positive.
    """
    report = SaturationReport()
    add_saturation(_music(), SR, MAX_SATURATION_DB, report)
    assert abs(report.peak_softened_db) < 1.0
    assert report.saturation_db == MAX_SATURATION_DB


def test_saturation_off_is_a_true_no_op():
    audio = _music()
    assert np.array_equal(add_saturation(audio, SR, 0.0), audio)


def test_saturation_does_not_alias():
    """Distortion makes harmonics above the original content, and any past Nyquist fold
    back at frequencies unrelated to the note - grit rather than warmth. Without
    oversampling a 7 kHz tone put an alias at 16.1 kHz only 43.8 dB down, which on a
    cymbal-heavy mix is plainly audible."""
    t = np.arange(SR) / SR
    tone = np.stack([0.3 * np.sin(2 * np.pi * 7000 * t)] * 2, axis=1)
    out = add_saturation(tone, SR, MAX_SATURATION_DB)

    mono = out.mean(axis=1)
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) ** 2
    freqs = np.fft.rfftfreq(len(mono), 1 / SR)

    def at(hz):
        return spectrum[(freqs > hz - 20) & (freqs < hz + 20)].sum()

    # 16.1 kHz is where the fourth harmonic folds back to. Nothing musical is there.
    assert 10 * np.log10(at(16100) / at(7000) + 1e-20) < -80.0
