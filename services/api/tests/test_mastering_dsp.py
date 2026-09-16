"""Tests for the reference-matching DSP.

The claims worth proving: the correction curve points the right way, it is bounded, it
does not change the level on its own, applying it is faithful, and the loudness match
lands where it says it does.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.dsp import (
    MatchSettings,
    apply_curve,
    apply_gain_db,
    average_spectrum,
    limit,
    matching_curve,
    normalise_peak,
    peak_db,
    smooth_log_frequency,
    to_mono,
)
from app.services.mastering.loudness_meter import gain_to_match, integrated_loudness

SR = 44100


def noise(seconds=3.0, seed=0, scale=0.2):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(int(seconds * SR)) * scale).astype(np.float64)


def tone(freq, seconds=3.0, amplitude=0.5):
    t = np.arange(int(seconds * SR)) / SR
    return amplitude * np.sin(2 * np.pi * freq * t)


def band_energy(samples, low, high):
    spectrum = average_spectrum(samples)
    freqs = np.fft.rfftfreq((spectrum.size - 1) * 2, d=1.0 / SR)
    mask = (freqs >= low) & (freqs < high)
    return float(spectrum[mask].mean())


# ──────────────────────────────── basics ────────────────────────────────


def test_mono_conversion_handles_both_shapes():
    assert to_mono(np.zeros(100)).shape == (100,)
    assert to_mono(np.zeros((100, 2))).shape == (100,)


def test_average_spectrum_finds_a_tone():
    spectrum = average_spectrum(tone(1000))
    freqs = np.fft.rfftfreq((spectrum.size - 1) * 2, d=1.0 / SR)
    assert abs(freqs[int(np.argmax(spectrum))] - 1000) < 20


def test_average_spectrum_survives_audio_shorter_than_a_frame():
    assert average_spectrum(np.zeros(100)).size == 4096 // 2 + 1


def test_smoothing_flattens_a_spike_but_keeps_the_broad_shape():
    spectrum = np.ones(2049)
    spectrum[1000] = 50.0
    smoothed = smooth_log_frequency(spectrum, SR)

    assert smoothed[1000] < spectrum[1000], "the spike should be reduced"
    assert smoothed[1000] > 1.0, "but its energy should not vanish"
    assert smoothed[100] == pytest.approx(1.0, abs=0.2), "flat regions stay flat"


# ──────────────────────────────── the curve ─────────────────────────────


def test_the_curve_boosts_where_the_reference_has_more():
    """A dull target against a bright reference must be told to add treble."""
    dull = average_spectrum(noise(seed=1) * 0.5)
    bright = dull.copy()
    freqs = np.fft.rfftfreq((dull.size - 1) * 2, d=1.0 / SR)
    bright[freqs > 5000] *= 4.0

    curve = matching_curve(dull, bright, SR)
    high = curve[freqs > 5000].mean()
    low = curve[freqs < 1000].mean()
    assert high > low, "the high end should be lifted relative to the low"


def test_the_curve_never_exceeds_its_clamps():
    """The stated limits have to be the actual limits.

    An earlier version clamped and *then* subtracted the median, so against a much
    brighter reference the low end came out at -(max_cut + max_boost) while every boosted
    band flattened to exactly 0 dB. Measured on a real track: -18 dB at 60 Hz against a
    stated -12 dB floor. Centring before clamping is what makes the numbers honest.
    """
    settings = MatchSettings(max_boost_db=6.0, max_cut_db=12.0)

    # A reference far brighter than the target - the case that broke it.
    freqs = np.fft.rfftfreq(4096, d=1.0 / SR)
    target = np.where(freqs < 500, 1.0, 0.01)
    reference = np.where(freqs < 500, 0.01, 1.0)

    db = 20 * np.log10(matching_curve(target, reference, SR, settings))
    assert db.max() <= 6.0 + 0.01, f"boosted {db.max():.1f} dB past a 6 dB ceiling"
    assert db.min() >= -12.0 - 0.01, f"cut {db.min():.1f} dB past a 12 dB floor"

    # And the correction still points the right way.
    assert db[freqs > 2000].mean() > db[freqs < 300].mean()


def test_clamps_hold_for_a_uniformly_louder_reference():
    quiet = np.full(2049, 1e-4)
    loud = np.full(2049, 1.0)
    settings = MatchSettings(max_boost_db=6.0, max_cut_db=12.0)

    for curve in (
        matching_curve(quiet, loud, SR, settings),
        matching_curve(loud, quiet, SR, settings),
    ):
        db = 20 * np.log10(curve)
        assert db.max() <= 6.0 + 0.01
        assert db.min() >= -12.0 - 0.01


def test_zero_strength_is_a_no_op():
    a = average_spectrum(noise(seed=2))
    b = average_spectrum(noise(seed=3) * 3)
    curve = matching_curve(a, b, SR, MatchSettings(strength=0.0))
    assert np.allclose(curve, 1.0, atol=1e-9)


def test_matching_a_track_against_itself_changes_nothing():
    spectrum = average_spectrum(noise(seed=4))
    curve = matching_curve(spectrum, spectrum, SR)
    assert np.allclose(curve, 1.0, atol=1e-6)


def test_the_curve_carries_no_net_level_change():
    """Tone and level are matched separately; the EQ must not move the level too.

    "No net change" is measured per octave, not per FFT bin - see
    test_the_curve_is_centred_by_octave_not_by_bin for why the distinction matters.
    """
    from app.services.mastering.dsp import _centre_db

    a = average_spectrum(noise(seed=5))
    b = average_spectrum(noise(seed=6) * 8)
    db = 20 * np.log10(matching_curve(a, b, SR))
    assert abs(_centre_db(db, SR)) < 0.01


def test_silence_does_not_divide_by_zero():
    silent = np.zeros(2049)
    assert np.all(np.isfinite(matching_curve(silent, silent, SR)))


# ──────────────────────────────── applying it ───────────────────────────


def test_a_flat_curve_reconstructs_the_signal():
    """Overlap-add has to be faithful, or every master picks up artefacts."""
    signal = noise(seconds=1.0, seed=7)
    out = apply_curve(signal, np.ones(2049))
    assert out.shape == signal.shape
    assert np.allclose(out, signal, atol=1e-6)


def test_applying_a_curve_actually_changes_the_balance():
    signal = noise(seconds=2.0, seed=8)
    freqs = np.fft.rfftfreq(4096, d=1.0 / SR)
    curve = np.where(freqs > 5000, 4.0, 1.0)

    out = apply_curve(signal, curve)
    before = band_energy(signal, 6000, 12000) / band_energy(signal, 200, 1000)
    after = band_energy(out, 6000, 12000) / band_energy(out, 200, 1000)
    assert after > before * 2


def test_stereo_is_processed_without_collapsing_the_image():
    left = noise(seconds=1.0, seed=9)
    right = noise(seconds=1.0, seed=10)
    stereo = np.stack([left, right], axis=1)

    out = apply_curve(stereo, np.ones(2049))
    assert out.shape == stereo.shape
    assert not np.allclose(out[:, 0], out[:, 1]), "channels must stay distinct"


# ──────────────────────────────── level ─────────────────────────────────


def test_gain_is_applied_in_decibels():
    assert peak_db(apply_gain_db(tone(440, 0.5), -6.0)) == pytest.approx(
        peak_db(tone(440, 0.5)) - 6.0, abs=0.01
    )


def test_peak_normalisation_respects_its_ceiling():
    loud = tone(440, 0.5, amplitude=1.5)
    assert peak_db(normalise_peak(loud, -1.0)) == pytest.approx(-1.0, abs=0.01)


def test_peak_normalisation_leaves_quiet_audio_alone():
    quiet = tone(440, 0.5, amplitude=0.1)
    assert np.array_equal(normalise_peak(quiet, -1.0), quiet)


def test_the_limiter_holds_the_ceiling():
    loud = tone(440, 1.0, amplitude=1.6)
    out = limit(loud, SR, ceiling_db=-1.0)
    assert peak_db(out) <= -1.0 + 0.01


def test_the_limiter_leaves_quiet_audio_untouched():
    quiet = tone(440, 0.5, amplitude=0.1)
    assert np.array_equal(limit(quiet, SR, -1.0), quiet)


def test_the_limiter_keeps_far_more_loudness_than_scaling_would():
    """The whole reason it exists: one transient must not decide the level of a song.

    A quiet passage with a single loud spike is the pathological case for peak
    normalisation, which pulls the entire track down to accommodate the spike.
    """
    body = tone(440, 4.0, amplitude=0.25)
    body[SR : SR + 30] = 1.8  # one very short, very loud transient

    limited = limit(body, SR, ceiling_db=-1.0)
    scaled = normalise_peak(body, ceiling_db=-1.0)

    # Well away from the transient, so only the limiter's release could still be acting.
    quiet_region = slice(int(2.5 * SR), int(3.5 * SR))
    original_db = peak_db(body[quiet_region])

    # The real property: the body of the track is left alone entirely.
    assert peak_db(limited[quiet_region]) == pytest.approx(original_db, abs=0.5)
    # Whereas scaling drags it down by however much the transient overshot.
    assert peak_db(scaled[quiet_region]) < original_db - 5
    assert peak_db(limited) <= -1.0 + 0.01


def test_the_limiter_handles_stereo():
    stereo = np.stack([tone(440, 0.5, 1.4), tone(660, 0.5, 1.4)], axis=1)
    out = limit(stereo, SR, -1.0)
    assert out.shape == stereo.shape
    assert peak_db(out) <= -1.0 + 0.01


def test_the_limiter_on_silence_is_a_no_op():
    silence = np.zeros(1000)
    assert np.array_equal(limit(silence, SR, -1.0), silence)


def test_loudness_matching_lands_on_the_reference():
    target = noise(seconds=3.0, seed=11, scale=0.02)
    reference = noise(seconds=3.0, seed=12, scale=0.3)

    gain, info = gain_to_match(target, reference, SR)
    corrected = apply_gain_db(target, gain)

    after, _ = integrated_loudness(corrected, SR)
    wanted, _ = integrated_loudness(reference, SR)
    assert after == pytest.approx(wanted, abs=0.5)
    assert info["backend"] in ("bs1770", "rms")


def test_an_absurd_loudness_gap_is_clamped_and_reported():
    near_silence = noise(seconds=2.0, seed=13, scale=1e-5)
    loud = noise(seconds=2.0, seed=14, scale=0.5)

    gain, info = gain_to_match(near_silence, loud, SR, max_gain_db=12.0)
    assert gain == pytest.approx(12.0)
    assert info["clamped"] is True


def test_measuring_silence_does_not_explode():
    value, backend = integrated_loudness(np.zeros(SR), SR)
    assert not np.isfinite(value) or value < -60
    assert backend in ("bs1770", "rms", "empty")


def test_the_curve_is_centred_by_octave_not_by_bin():
    """A curve that only ever cuts is not centred, it is just turned down.

    rFFT bins are linearly spaced, so over half of them sit above 11 kHz. Taking the
    centre as a plain median over bins lets the top octave decide where "no change" is,
    and a mix with ordinary air then reads as a cut at every band below it. Measured on a
    real track against a pink-noise reference: nine bands reported, every one negative.
    """
    n_fft = 4096
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / SR)
    f = np.maximum(freqs, 20.0)

    # A rock mix - heavy lows, rolled-off top - against pink noise.
    mix = (f / 100.0) ** -1.4
    mix[freqs > 11000] *= 0.25
    reference = (f / 100.0) ** -1.0

    # The deep-bass guard is switched off here: it caps cuts below 140 Hz, which is a
    # separate rule with its own tests, and leaving it on would mask what this is about.
    db = 20 * np.log10(
        matching_curve(mix, reference, SR, MatchSettings(max_low_cut_db=12.0))
    )

    def at(hz):
        return db[int(np.searchsorted(freqs, hz))]

    # The correction must run downwards at the bottom and upwards at the top.
    assert at(60) < -2, f"a bass-heavy mix should be cut, got {at(60):+.1f} dB"
    assert at(8000) > 2, f"a dull mix should be lifted, got {at(8000):+.1f} dB"
    assert at(60) < at(1000) < at(8000), "the curve should rise monotonically here"

    # And it should cross zero somewhere in the middle rather than sitting entirely below.
    assert db.min() < 0 < db.max()


def test_centring_survives_an_unusual_sample_rate():
    """The log-spaced sample points must stay inside Nyquist."""
    for rate in (8000, 22050, 44100, 48000, 96000):
        bins = 2049
        spectrum = np.linspace(1.0, 0.1, bins)
        curve = matching_curve(spectrum, spectrum[::-1], rate)
        assert np.all(np.isfinite(curve)), f"{rate} Hz produced a non-finite curve"


# ─────────────────────────── the deep-bass guard ───────────────────────────
#
# A user heard it before these existed: "the bassiness to the kick was completely
# removed and the sample sounded flat". On that pair the curve wanted -4.6 dB at 45 Hz
# and +6 dB at 500 - a scoop straight through the kick's fundamental into the boxiest
# part of the spectrum.


def bass_heavy_against_light(n_fft=4096):
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / SR)
    f = np.maximum(freqs, 20.0)
    mix = (f / 100.0) ** -1.6          # a lot of weight underneath
    reference = (f / 100.0) ** -0.8    # much lighter down there
    return freqs, mix, reference


def test_the_deep_bass_is_not_scooped_out():
    freqs, mix, reference = bass_heavy_against_light()
    db = 20 * np.log10(matching_curve(mix, reference, SR))

    def at(hz):
        return db[int(np.searchsorted(freqs, hz))]

    for hz in (30, 45, 60):
        assert at(hz) >= -MatchSettings().max_low_cut_db - 0.01, (
            f"{at(hz):+.1f} dB at {hz} Hz takes the bottom off the kick"
        )


def test_the_guard_only_limits_cuts_not_boosts():
    """A mix genuinely short of low end should still be allowed to gain some."""
    freqs = np.fft.rfftfreq(4096, d=1.0 / SR)
    f = np.maximum(freqs, 20.0)
    thin = (f / 100.0) ** -0.6
    full = (f / 100.0) ** -1.6
    db = 20 * np.log10(matching_curve(thin, full, SR))
    assert db[int(np.searchsorted(freqs, 45))] > 1.0


def test_the_rest_of_the_spectrum_is_untouched_by_it():
    """The guard is about the bottom two octaves, not a general softening."""
    freqs, mix, reference = bass_heavy_against_light()
    db = 20 * np.log10(matching_curve(mix, reference, SR))
    assert db[int(np.searchsorted(freqs, 400))] < -MatchSettings().max_low_cut_db


def test_the_guard_eases_in_rather_than_stepping():
    """A cliff in the correction is a resonance; the limit tapers across an octave."""
    freqs, mix, reference = bass_heavy_against_light()
    db = 20 * np.log10(matching_curve(mix, reference, SR))
    low = int(np.searchsorted(freqs, 40))
    high = int(np.searchsorted(freqs, 400))
    # Per bin, and the bins are 10.8 Hz apart here, so this is a slope rather than a step.
    assert np.abs(np.diff(db[low:high])).max() < 1.2


def test_it_can_be_turned_off():
    """It is a default, not a law - the tests for centring need it out of the way."""
    freqs, mix, reference = bass_heavy_against_light()
    db = 20 * np.log10(
        matching_curve(mix, reference, SR, MatchSettings(max_low_cut_db=12.0))
    )
    assert db[int(np.searchsorted(freqs, 45))] < -2.0
