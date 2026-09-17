"""Matching a reference's stereo image band by band.

The numbers here come from a home master of a pop-punk song measured against the
commercial reference it was aimed at. The record was half as wide at 120-250 Hz and
nearly three times as wide above 8 kHz - a shape a single factor over one crossover
cannot produce, and the reason this module exists.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.width import (
    BAND_NAMES,
    CROSSOVERS,
    MAX_FACTOR,
    MIN_FACTOR,
    match_profile,
    mono_loss_db,
    side_to_mid,
    split_bands,
    width_profile,
)

SR = 44100


def _stereo(hz: float, width: float, seconds: float = 4.0) -> np.ndarray:
    """A tone with a known side-to-mid ratio."""
    t = np.arange(int(SR * seconds)) / SR
    mid = 0.3 * np.sin(2 * np.pi * hz * t)
    # A different frequency in the side channel, so it is genuinely decorrelated rather
    # than a scaled copy that would collapse to a pan.
    side = 0.3 * width * np.sin(2 * np.pi * (hz * 1.5) * t)
    return np.stack([mid + side, mid - side], axis=1)


def _mixture(width_low: float, width_high: float) -> np.ndarray:
    return _stereo(80.0, width_low) + _stereo(10000.0, width_high)


# --- the filterbank -------------------------------------------------------------------


def test_the_bands_sum_back_to_what_went_in():
    """Built as differences of lowpasses for exactly this reason. Independent bandpasses
    would leave overlaps and gaps that comb-filter the moment the bands are summed."""
    audio = _mixture(0.2, 0.8)
    rebuilt = sum(split_bands(audio, SR))
    assert np.abs(rebuilt - audio).max() < 1e-9


def test_there_is_one_band_per_name():
    assert len(BAND_NAMES) == len(CROSSOVERS) + 1
    assert len(split_bands(_mixture(0.3, 0.3), SR)) == len(BAND_NAMES)


def test_side_to_mid_reads_what_was_put_in():
    assert side_to_mid(_stereo(1000.0, 0.0)) == pytest.approx(0.0, abs=1e-6)
    assert side_to_mid(_stereo(1000.0, 0.5)) == pytest.approx(0.5, abs=0.05)


def test_a_mono_signal_reads_as_no_width():
    mono = np.stack([np.ones(SR), np.ones(SR)], axis=1)
    assert side_to_mid(mono) == pytest.approx(0.0, abs=1e-9)


# --- matching -------------------------------------------------------------------------


def test_each_band_moves_towards_the_reference_independently():
    """The whole point: narrow the bottom and widen the top in one pass."""
    mine = _mixture(width_low=0.6, width_high=0.2)
    theirs = _mixture(width_low=0.2, width_high=0.7)

    out, report = match_profile(mine, theirs, SR)
    before, after, target = (
        width_profile(mine, SR),
        width_profile(out, SR),
        width_profile(theirs, SR),
    )

    def err(profile):
        return np.sqrt(
            np.mean([
                (20 * np.log10((profile[n] + 1e-9) / (target[n] + 1e-9))) ** 2
                for n in BAND_NAMES
                if target[n] > 0.02
            ])
        )

    assert err(after) < err(before) / 2
    # And in opposite directions, which a single factor could never do.
    assert report.factors["sub"] < 1.0
    assert report.factors["top"] > 1.0


def test_factors_are_capped_in_both_directions():
    mine = _mixture(0.9, 0.02)
    theirs = _mixture(0.01, 0.9)
    _, report = match_profile(mine, theirs, SR)
    for factor in report.factors.values():
        assert MIN_FACTOR <= factor <= MAX_FACTOR


def test_strength_scales_the_move():
    mine = _mixture(0.6, 0.2)
    theirs = _mixture(0.2, 0.7)

    _, full = match_profile(mine, theirs, SR, strength=1.0)
    _, half = match_profile(mine, theirs, SR, strength=0.5)
    _, none = match_profile(mine, theirs, SR, strength=0.0)

    assert all(f == 1.0 for f in none.factors.values())
    for name in BAND_NAMES:
        # Half strength is halfway between no move and the full one.
        assert abs(half.factors[name] - 1.0) == pytest.approx(
            abs(full.factors[name] - 1.0) / 2, abs=0.02
        )


def test_a_band_with_no_image_is_not_invented():
    """Multiplying a near-mono band by 2.5 would be manufacturing stereo that was never
    recorded - and what is down there is mostly noise, so it would be amplifying noise."""
    mine = _mixture(width_low=0.0, width_high=0.5)
    theirs = _mixture(width_low=0.9, width_high=0.5)

    _, report = match_profile(mine, theirs, SR)
    assert report.factors["sub"] == 1.0
    assert any("mono" in note for note in report.notes)


def test_a_dual_mono_source_is_handed_straight_back():
    """Two identical channels have no side content anywhere, so every band is left at
    1.0 - and when nothing changes the input is returned untouched rather than rebuilt
    from the filterbank, which is only accurate to floating point."""
    mono = np.stack([np.sin(np.arange(SR) / 20)] * 2, axis=1)
    out, report = match_profile(mono, _mixture(0.5, 0.5), SR)

    assert out is mono
    assert set(report.factors) == set(BAND_NAMES)
    assert all(f == 1.0 for f in report.factors.values())


def test_a_single_channel_source_is_left_alone():
    mono = np.sin(np.arange(SR) / 20)
    out, report = match_profile(mono, _mixture(0.5, 0.5), SR)
    assert np.array_equal(out, mono)
    assert report.factors == {}
    assert any("mono" in note for note in report.notes)


# --- the mono guard -------------------------------------------------------------------


def test_widening_is_eased_back_when_it_costs_more_mono_than_the_reference():
    """Widening always sounds better on headphones, so the guard cannot be about taste.
    A master may not give up more when summed than the record it is matching."""
    # A reference that is wide in a way that survives summing, against a source whose
    # width is anti-phase and therefore cancels.
    t = np.arange(SR * 4) / SR
    anti = np.stack([np.sin(2 * np.pi * 300 * t), -np.sin(2 * np.pi * 300 * t)], axis=1)
    mine = anti * 0.3 + _stereo(300.0, 0.05) * 0.2
    theirs = _stereo(300.0, 0.9)

    out, report = match_profile(mine, theirs, SR)
    # Either it stayed within the allowance, or it says it eased back.
    assert report.pulled_back or report.mono_loss_db >= report.reference_mono_loss_db - 0.35
    assert np.isfinite(mono_loss_db(out))


def test_mono_loss_is_zero_for_a_centred_signal_and_negative_for_a_wide_one():
    centred = np.stack([np.sin(np.arange(SR) / 20)] * 2, axis=1)
    assert mono_loss_db(centred) == pytest.approx(0.0, abs=0.01)
    assert mono_loss_db(_stereo(1000.0, 0.8)) < -0.5


def test_the_report_names_every_band():
    out, report = match_profile(_mixture(0.5, 0.3), _mixture(0.3, 0.6), SR)
    assert set(report.factors) == set(BAND_NAMES)
    assert out.shape == _mixture(0.5, 0.3).shape
