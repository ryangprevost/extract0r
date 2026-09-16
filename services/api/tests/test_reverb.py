"""The estimator and the processor have to agree, or the suggestion means nothing.

The whole feature is a loop: measure the reference's tail, ask for that much, get it. Each
half is checked against a tail of known length rather than against the other, so a shared
mistake cannot cancel out and look like success.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import fftconvolve

from app.services.mastering.reverb import (
    DAMPING_SHORTENS_BY,
    MAX_MIX,
    MAX_SECONDS,
    MIN_SECONDS,
    apply_reverb,
    impulse_response,
    mix_for_gap,
)
from app.services.mastering.space import (
    FLOOR_SECONDS,
    PLAUSIBLE_MAX_S,
    reverb_time_s,
)

SR = 44100


def dry_hits(seconds=20.0, rate=1.5, decay=60.0, seed=0):
    """Sharp hits with fast decay: about as dry as a signal gets."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    out = np.zeros(n)
    for start in range(0, n, int(SR / rate)):
        length = min(int(SR * 0.15), n - start)
        t = np.arange(length) / SR
        out[start : start + length] += rng.normal(0, 0.3, length) * np.exp(-decay * t)
    return np.stack([out, out], axis=1)


def known_tail(signal, rt60, mix=0.5, seed=1):
    """Convolve with a response that decays by exactly 60 dB over rt60 seconds.

    Built here rather than taken from the module under test, so the measurement is checked
    against an independent tail.
    """
    rng = np.random.default_rng(seed)
    length = int(rt60 * SR)
    t = np.arange(length) / SR
    ir = rng.normal(0, 1, length) * 10 ** (-3.0 * t / rt60)
    ir /= np.abs(ir).sum()

    wet = np.empty_like(signal)
    for channel in range(signal.shape[1]):
        wet[:, channel] = fftconvolve(signal[:, channel], ir)[: signal.shape[0]]
    wet *= np.abs(signal).max() / (np.abs(wet).max() + 1e-12)
    return (1 - mix) * signal + mix * wet


def schroeder_rt60(ir):
    """Read a decay time straight off an impulse response, the textbook way."""
    energy = (ir**2).sum(axis=1)
    curve = np.cumsum(energy[::-1])[::-1]
    db = 10 * np.log10(np.maximum(curve / curve.max(), 1e-12))
    low, high = int(np.argmax(db <= -5)), int(np.argmax(db <= -25))
    seconds = np.arange(high - low) / SR
    return 60.0 / abs(float(np.polyfit(seconds, db[low:high], 1)[0]))


# ──────────────────────────── the estimator ────────────────────────────


@pytest.mark.parametrize("rt60", [0.4, 0.8, 1.2, 2.0, 2.5])
def test_a_known_tail_is_measured_back(rt60):
    """Within 0.1 s across the range a mix reverb actually occupies. Everything
    downstream rests on this. The top of the range is PLAUSIBLE_MAX_S, which has its
    own test - past it the answer is deliberately withheld."""
    got = reverb_time_s(known_tail(dry_hits(), rt60), SR)
    assert got is not None
    assert got == pytest.approx(rt60, abs=0.1)


@pytest.mark.parametrize("mix", [0.3, 0.5, 0.7])
def test_the_answer_does_not_depend_on_how_loud_the_tail_is(mix):
    """A tail's decay rate is not a function of its level, and the estimate must not be
    either. Fitting from the peak instead of from -5 dB got this wrong: a quiet tail read
    short because the source's own decay dominated the window."""
    got = reverb_time_s(known_tail(dry_hits(), 1.2, mix=mix), SR)
    assert got == pytest.approx(1.2, abs=0.15)


def test_a_dry_signal_reads_as_dry_rather_than_unmeasurable():
    """There is a real difference between "nothing rings" and "nothing to go on"."""
    assert reverb_time_s(dry_hits(), SR) == FLOOR_SECONDS


def test_silence_gives_no_answer_at_all():
    assert reverb_time_s(np.zeros((SR * 5, 2)), SR) is None


def test_a_sustained_note_is_refused_rather_than_called_a_cathedral():
    """A held tone decays slowly because it is held, not because of a room. Measured
    against a real reference the guitar stem came back at 6 s and the piano at 5.2 s."""
    t = np.arange(int(12 * SR)) / SR
    held = 0.3 * np.sin(2 * np.pi * 220 * t)
    held[: int(0.01 * SR)] *= np.linspace(0, 1, int(0.01 * SR))
    assert reverb_time_s(np.stack([held, held], axis=1), SR) is None


def test_nothing_above_the_plausible_ceiling_is_reported():
    got = reverb_time_s(known_tail(dry_hits(), 5.0), SR)
    assert got is None or got <= PLAUSIBLE_MAX_S


# ──────────────────────────── the processor ────────────────────────────


@pytest.mark.parametrize("seconds", [0.4, 0.8, 1.2, 2.0, 3.0])
def test_the_response_decays_over_the_time_it_was_asked_for(seconds):
    """Damping and truncation both steepen the decay. Uncompensated the response came out
    at 0.86x its nominal length at every size, so asking for the reference's 1.4 s would
    have delivered 1.2 s."""
    assert schroeder_rt60(impulse_response(seconds, SR)) == pytest.approx(
        seconds, rel=0.05
    )


def test_the_correction_is_the_constant_it_claims_to_be():
    """It divides out exactly only because it is the same at every length."""
    ratios = [
        schroeder_rt60(impulse_response(s, SR)) / s for s in (0.4, 1.0, 2.0, 3.0)
    ]
    assert max(ratios) - min(ratios) < 0.08
    assert 0.8 < DAMPING_SHORTENS_BY < 0.95


def test_the_two_sides_of_the_tail_are_independent():
    """A correlated tail collapses to the centre and sounds like a filter, not a space."""
    ir = impulse_response(1.0, SR)
    assert abs(float(np.corrcoef(ir[:, 0], ir[:, 1])[0, 1])) < 0.1


def test_the_tail_darkens_as_it_fades():
    """Treble dies first in any real room; a tail that keeps its top end is hiss."""
    ir = impulse_response(2.0, SR)
    half = ir.shape[0] // 2

    def brightness(block):
        spectrum = np.abs(np.fft.rfft(block[:, 0])) ** 2
        freqs = np.fft.rfftfreq(block.shape[0], d=1.0 / SR)
        return spectrum[freqs > 6000].sum() / (spectrum.sum() + 1e-20)

    assert brightness(ir[half:]) < brightness(ir[:half])


def test_no_mix_is_a_true_no_op():
    audio = dry_hits(seconds=2.0)
    assert np.array_equal(apply_reverb(audio, SR, 1.2, 0.0), audio)


def test_reverb_does_not_run_away_with_the_level():
    """`mix` is a balance, not a volume: a longer tail must not also be a louder one."""
    audio = dry_hits(seconds=4.0)
    before = float(np.sqrt((audio**2).mean()))
    for seconds in (0.5, 3.0):
        after = float(np.sqrt((apply_reverb(audio, SR, seconds, 0.4) ** 2).mean()))
        assert 0.5 < after / before < 1.6


def test_the_processor_and_the_estimator_agree():
    """The loop the whole feature depends on: ask for what was measured, get it back."""
    wet = apply_reverb(dry_hits(), SR, 1.2, MAX_MIX)
    assert reverb_time_s(wet, SR) == pytest.approx(1.2, abs=0.35)


@pytest.mark.parametrize("seconds", [0.0, 0.01, 99.0])
def test_absurd_lengths_are_clamped(seconds):
    """Measured on the decay itself rather than the buffer, which also holds the
    pre-delay."""
    decay = schroeder_rt60(impulse_response(seconds, SR))
    assert MIN_SECONDS * 0.8 <= decay <= MAX_SECONDS * 1.05


# ──────────────────────────── the suggestion ────────────────────────────


def test_a_dry_stem_against_a_wet_reference_is_offered_the_difference():
    seconds, mix = mix_for_gap(0.3, 1.4)
    assert seconds == pytest.approx(1.4)
    assert 0 < mix <= MAX_MIX


def test_a_stem_already_in_the_same_space_is_offered_nothing():
    assert mix_for_gap(1.2, 1.3) == (0.0, 0.0)


def test_reverb_is_never_suggested_to_remove_it():
    """Nothing here can take a tail off a stem that already has one, so a wetter stem
    than the reference gets no offer rather than a negative one."""
    assert mix_for_gap(2.0, 0.5) == (0.0, 0.0)


def test_a_bigger_gap_earns_more_of_it():
    _, small = mix_for_gap(1.0, 1.5)
    _, large = mix_for_gap(0.2, 2.5)
    assert large > small


def test_an_unmeasurable_side_is_offered_nothing():
    assert mix_for_gap(None, 1.4) == (0.0, 0.0)
    assert mix_for_gap(0.3, None) == (0.0, 0.0)
