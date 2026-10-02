"""Quantising to 16 bits without turning the quiet parts into distortion.

The claim this file has to defend is specific, and it is not "dither makes it quieter" -
dither makes the noise floor *louder* by about 5 dB. The claim is that it changes the
error from something correlated with the signal into something that is not, and that the
ear cares far more about the correlation than about the 5 dB.

So the measurements here are of harmonic distortion, not of noise level. A quiet sine
quantised by truncation comes out as a staircase, and a staircase is a sine plus its
harmonics. Dithered, the same sine comes out with a flat noise floor and no harmonics at
all. That difference is the entire feature and every test below is a way of measuring it.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mixdown.dither import (
    FULL_SCALE_16,
    SHAPER,
    describe,
    to_int16,
)

SR = 44100
LSB = 1.0 / FULL_SCALE_16


def _quiet_sine(hz: float = 1000.0, lsbs: float = 2.0, seconds: float = 2.0) -> np.ndarray:
    """A sine a couple of LSBs tall - the signal that shows quantisation for what it is.

    Deliberately tiny. At a normal listening level the error is 90 dB down and nothing can
    be measured through the signal; it is the fade-outs and the reverb tails that live
    down here, which is exactly where the complaint comes from.

    Not an exact divisor of the sample rate, so the sine does not land on the same few
    phases every cycle and produce a staircase that happens to be periodic with the FFT.
    """
    n = int(SR * seconds)
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * hz * t) * lsbs * LSB


def _spectrum(pcm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Magnitude spectrum of a quantised signal, back in float terms."""
    audio = np.asarray(pcm, dtype=np.float64) / FULL_SCALE_16
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    window = np.hanning(audio.size)
    mag = np.abs(np.fft.rfft(audio * window))
    freqs = np.fft.rfftfreq(audio.size, d=1.0 / SR)
    return freqs, mag


def _at(freqs: np.ndarray, mag: np.ndarray, hz: float, width_hz: float = 12.0) -> float:
    """Energy in a narrow bin around one frequency."""
    band = (freqs > hz - width_hz) & (freqs < hz + width_hz)
    return float(np.sqrt(np.sum(mag[band] ** 2)))


def _harmonic_distortion_db(pcm: np.ndarray, fundamental: float = 1000.0) -> float:
    """Harmonics 2-7 against the fundamental, in dB. Lower is cleaner."""
    freqs, mag = _spectrum(pcm)
    first = _at(freqs, mag, fundamental)
    harmonics = np.sqrt(
        sum(_at(freqs, mag, fundamental * n) ** 2 for n in range(2, 8))
    )
    if first <= 0:
        return 0.0
    return float(20 * np.log10(max(harmonics, 1e-20) / first))


def _truncated(audio: np.ndarray) -> np.ndarray:
    """What the encoder did before this module existed, reproduced for comparison."""
    return (np.clip(audio, -1.0, 1.0) * FULL_SCALE_16).astype("<i2")


# --- the point of the whole module ------------------------------------------------------


def test_truncation_turns_a_quiet_sine_into_harmonics():
    """Establishes the problem. If this ever stops being true the rest is pointless."""
    distortion = _harmonic_distortion_db(_truncated(_quiet_sine()))
    assert distortion > -26.0, (
        f"expected truncation to produce obvious harmonics, measured {distortion:.1f} dB"
    )


def test_dither_removes_the_harmonics():
    """The feature, in one assertion.

    The same signal, the same quantiser, the same 16 bits out - and the harmonics are
    gone, because the error no longer knows anything about the signal.
    """
    truncated = _harmonic_distortion_db(_truncated(_quiet_sine()))
    dithered = _harmonic_distortion_db(
        to_int16(_quiet_sine(), noise_shaping=False, seed=1)
    )
    assert dithered < truncated - 10.0, (
        f"truncated {truncated:.1f} dB, dithered {dithered:.1f} dB - "
        "dither should have removed the harmonics, not merely moved them"
    )


def test_dither_costs_noise_and_that_is_the_trade():
    """Stated rather than hidden. Dither is louder and better; a test that only checked
    the noise floor would call this a regression."""
    quiet = np.zeros(SR)  # digital silence: anything present is the quantiser's doing
    truncated = float(np.std(_truncated(quiet).astype(np.float64)))
    dithered = float(np.std(to_int16(quiet, noise_shaping=False, seed=2).astype(np.float64)))

    assert truncated == 0.0, "silence truncates to silence"
    assert 0.3 < dithered < 1.2, f"TPDF noise should be about one LSB, measured {dithered:.2f}"


# --- noise shaping ----------------------------------------------------------------------


def _shaping_gain_db(low_hz: float, high_hz: float, seed: int = 3) -> float:
    """How much quieter the shaped noise floor is than the flat one, over a band.

    Measured on digital silence, so everything in the spectrum is the quantiser's doing
    and nothing has to be separated from a signal.
    """
    quiet = np.zeros(SR * 2)
    freqs, flat = _spectrum(to_int16(quiet, noise_shaping=False, seed=seed))
    _, shaped = _spectrum(to_int16(quiet, noise_shaping=True, seed=seed))

    band = (freqs >= low_hz) & (freqs <= high_hz)
    flat_rms = float(np.sqrt(np.mean(flat[band] ** 2)))
    shaped_rms = float(np.sqrt(np.mean(shaped[band] ** 2)))
    return float(20 * np.log10(shaped_rms / flat_rms))


def _predicted_gain_db(low_hz: float, high_hz: float) -> float:
    """The same figure from the transfer function alone, with no audio involved."""
    freqs = np.linspace(1.0, SR / 2, 20000)
    w = 2 * np.pi * freqs / SR
    response = np.abs(sum(c * np.exp(-1j * w * (k + 1)) for k, c in enumerate(SHAPER)) + 1.0)
    band = (freqs >= low_hz) & (freqs <= high_hz)
    return float(20 * np.log10(np.sqrt(np.mean(response[band] ** 2))))


def test_noise_shaping_moves_noise_out_of_the_midrange():
    """The reason shaping is on by default: less noise where the ear is sensitive.

    Around 2-4 kHz the ear is at its most acute and this is where the gain is largest.
    """
    assert _shaping_gain_db(1000, 4000) < -12.0
    assert _shaping_gain_db(500, 5000) < -10.0
    assert _shaping_gain_db(100, 8000) < -4.0


def test_the_measured_noise_floor_matches_the_transfer_function():
    """Ties the implementation to the maths rather than to a number someone observed.

    This is the test that caught the two bugs this module shipped with. The first had the
    feedback sign inverted, which made `1 + 2z^-1 - z^-2` - a *low*-pass on the error, 3.9
    dB worse than no shaping. The second fed back an error measured after the dither
    rather than before, so only the rounding error was shaped and the dither, which is
    twice its power, passed through flat: -1.2 dB measured against -5.3 predicted.

    Both left every other test in this file passing. Only comparing against the
    theoretical response told them apart.
    """
    for low, high in ((100, 8000), (500, 5000), (1000, 4000), (16000, 22050)):
        measured = _shaping_gain_db(low, high)
        predicted = _predicted_gain_db(low, high)
        assert measured == pytest.approx(predicted, abs=1.0), (
            f"{low}-{high} Hz: measured {measured:+.1f} dB, "
            f"transfer function predicts {predicted:+.1f} dB"
        )


def test_noise_shaping_pays_for_it_up_top():
    """Where the noise went. Conservation, not magic - and worth asserting so that a
    shaper which silently added overall noise would be caught."""
    quiet = np.zeros(SR * 2)
    freqs, flat_mag = _spectrum(to_int16(quiet, noise_shaping=False, seed=4))
    _, shaped_mag = _spectrum(to_int16(quiet, noise_shaping=True, seed=4))

    top = freqs > 16000
    flat_rms = float(np.sqrt(np.mean(flat_mag[top] ** 2)))
    shaped_rms = float(np.sqrt(np.mean(shaped_mag[top] ** 2)))
    assert shaped_rms > flat_rms, "the noise has to go somewhere"


def test_shaping_does_not_run_away():
    """Error feedback is a recursion, and a recursion can diverge. A shaper that rang
    would show up as a handful of enormous samples rather than as a bad spectrum."""
    loud = np.sin(2 * np.pi * 440 * np.arange(SR) / SR) * 0.9
    out = to_int16(loud, seed=5).astype(np.float64)
    assert np.abs(out).max() <= FULL_SCALE_16
    assert np.isfinite(out).all()


def test_the_shaper_is_a_highpass():
    """Documents the coefficients rather than trusting the comment: (1 - z^-1)^2 has a
    null at DC, so the error feedback must sum to zero against a constant."""
    assert sum((1.0, *SHAPER)) == pytest.approx(0.0)


# --- the quantiser itself ---------------------------------------------------------------


def test_nothing_exceeds_what_the_format_holds():
    """Dither is added before rounding, so a sample already at full scale can be pushed
    past it. Wrapping a sample round to the opposite polarity is the loudest possible
    click, which makes this the one failure mode worth a dedicated test."""
    full = np.ones((1000, 2)) * 0.99999
    out = to_int16(full, seed=6)
    assert out.max() <= 32767
    assert out.min() >= -32767
    assert out.dtype == np.dtype("<i2")

    both = np.stack([np.ones(1000), -np.ones(1000)], axis=1)
    out = to_int16(both, seed=7)
    assert out.max() <= 32767 and out.min() >= -32767


def test_the_undithered_path_rounds_rather_than_truncating():
    """Turning dither off asks for a plain quantiser, not for the old bug back.

    Truncation biases every sample toward zero by up to a whole LSB. Half an LSB of
    rounding error is the best a quantiser can do, and there is no reading of
    `dither=False` under which the worse one was intended.
    """
    # Values that sit just under an integer number of LSBs: truncation drops them a whole
    # step, rounding keeps them.
    audio = np.array([0.9, 1.9, 2.9, 3.9]) * LSB
    plain = to_int16(audio, dither=False)
    assert list(plain) == [1, 2, 3, 4]
    assert list(_truncated(audio)) == [0, 1, 2, 3]


def test_stereo_channels_get_independent_noise():
    """Shared noise between channels would be centred, and centred noise is where the
    vocal is. It also would not be noise, it would be a signal."""
    quiet = np.zeros((SR, 2))
    out = to_int16(quiet, seed=8).astype(np.float64)
    left, right = out[:, 0], out[:, 1]
    assert np.std(left) > 0 and np.std(right) > 0
    correlation = float(np.corrcoef(left, right)[0, 1])
    assert abs(correlation) < 0.1, f"channels correlate at {correlation:.3f}"


def test_mono_in_mono_out():
    out = to_int16(_quiet_sine(), seed=9)
    assert out.ndim == 1
    assert out.dtype == np.dtype("<i2")


def test_a_fade_keeps_its_shape():
    """The actual complaint - a fade-out gaining a gritty edge - restated as a property.
    The dithered fade must still be a fade: monotonically decreasing in envelope, ending
    in something indistinguishable from silence rather than in a stuck value."""
    n = SR
    fade = np.sin(2 * np.pi * 440 * np.arange(n) / SR) * np.linspace(0.02, 0.0, n)
    out = to_int16(fade, seed=10).astype(np.float64) / FULL_SCALE_16

    chunks = out.reshape(10, -1)
    levels = [float(np.sqrt(np.mean(c**2))) for c in chunks]
    assert levels[0] > levels[-1] * 4, "the fade should still fade"
    # The tail is noise rather than a frozen staircase: it has to keep changing.
    assert len(np.unique(np.asarray(out[-SR // 10:]))) > 2


def test_describe_says_what_was_done():
    assert "TPDF" in describe(True, False)
    assert "noise shaping" in describe(True, True)
    assert "no dither" in describe(False, False)
