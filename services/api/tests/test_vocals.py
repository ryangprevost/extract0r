"""Keeping the vocal audible.

Measured on a real track, vocals sat at -6.8 LU below the mix where a modern master
places them nearer -4. Nothing in reference matching guarantees a vocal lands anywhere
musical, so these are the rules that do.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.notes import StemKind
from app.services.mastering.vocals import (
    MAX_VOCAL_LIFT_DB,
    PRESENCE_TARGETS,
    VOCAL_BAND_HZ,
    VocalPresence,
    duck_under_vocal,
    should_duck,
    vocal_envelope,
    vocal_lift_db,
)

SR = 44100


def band_energy(samples, low, high):
    mono = samples.mean(axis=1) if samples.ndim > 1 else samples
    spectrum = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / SR)
    return float(spectrum[(freqs >= low) & (freqs < high)].sum())


# ──────────────────────────────── placement ────────────────────────────────


def test_a_buried_vocal_is_lifted_to_its_target():
    lift, _note = vocal_lift_db(-6.8, VocalPresence.NATURAL)
    assert lift == pytest.approx(PRESENCE_TARGETS[VocalPresence.NATURAL] + 6.8, abs=0.01)
    assert lift > 0


def test_a_vocal_already_forward_is_left_alone():
    """Pulling a deliberately forward vocal back would be second-guessing the mix."""
    lift, note = vocal_lift_db(-1.0, VocalPresence.NATURAL)
    assert lift == 0.0
    assert note is None


def test_presence_settings_are_ordered():
    back = vocal_lift_db(-10.0, VocalPresence.BACK)[0]
    natural = vocal_lift_db(-10.0, VocalPresence.NATURAL)[0]
    forward = vocal_lift_db(-10.0, VocalPresence.FORWARD)[0]
    assert back < natural < forward


def test_an_enormous_lift_is_capped_and_explained():
    """A vocal needing 20 dB was not recovered cleanly; pushing harder amplifies artefacts."""
    lift, note = vocal_lift_db(-30.0, VocalPresence.NATURAL)
    assert lift == pytest.approx(MAX_VOCAL_LIFT_DB)
    assert note is not None and "separation" in note


# ──────────────────────────────── the envelope ────────────────────────────────


def test_the_envelope_follows_where_the_vocal_sings():
    audio = np.zeros(SR * 4)
    audio[SR : SR * 2] = np.sin(2 * np.pi * 300 * np.arange(SR) / SR) * 0.5

    envelope = vocal_envelope(audio, SR)
    assert envelope[SR + SR // 2] > 0.5, "should be open while singing"
    assert envelope[SR // 2] < 0.2, "should be closed before the entry"


def test_the_envelope_releases_slowly():
    """A duck that snaps back between syllables pumps audibly; a slow release does not."""
    audio = np.zeros(SR * 3)
    audio[: SR // 2] = np.sin(2 * np.pi * 300 * np.arange(SR // 2) / SR) * 0.5

    envelope = vocal_envelope(audio, SR, release_ms=220.0)
    just_after = envelope[SR // 2 + int(0.02 * SR)]
    well_after = envelope[SR // 2 + int(1.5 * SR)]
    assert just_after > well_after, "the envelope should decay, not jump"
    assert just_after > 0.3, "and not collapse the instant the vocal stops"


def test_a_silent_vocal_gives_a_flat_envelope():
    assert np.all(vocal_envelope(np.zeros(SR), SR) == 0.0)


def test_an_empty_vocal_is_handled():
    assert vocal_envelope(np.zeros(0), SR).size == 0


# ──────────────────────────────── ducking ────────────────────────────────


def test_ducking_only_touches_the_vocal_band():
    """Ducking a guitar's whole spectrum makes it quieter without making the vocal clearer."""
    rng = np.random.default_rng(0)
    guitar = np.stack([rng.standard_normal(SR * 2)] * 2, axis=1) * 0.2
    envelope = np.ones(SR * 2)

    ducked = duck_under_vocal(guitar, envelope, SR, depth_db=6.0)

    inside_before = band_energy(guitar, *VOCAL_BAND_HZ)
    inside_after = band_energy(ducked, *VOCAL_BAND_HZ)
    below_before = band_energy(guitar, 80, 400)
    below_after = band_energy(ducked, 80, 400)

    assert inside_after < inside_before * 0.8, "the vocal band should be pulled down"
    assert below_after == pytest.approx(below_before, rel=0.15), "the low end should not be"


def test_no_ducking_while_the_vocal_is_silent():
    rng = np.random.default_rng(1)
    guitar = np.stack([rng.standard_normal(SR)] * 2, axis=1) * 0.2
    silent = np.zeros(SR)

    ducked = duck_under_vocal(guitar, silent, SR, depth_db=6.0)
    assert np.allclose(ducked, guitar, atol=1e-9)


def test_zero_depth_is_a_no_op():
    rng = np.random.default_rng(2)
    guitar = np.stack([rng.standard_normal(SR)] * 2, axis=1) * 0.2
    ducked = duck_under_vocal(guitar, np.ones(SR), SR, depth_db=0.0)
    assert np.array_equal(ducked, guitar)


def test_deeper_ducking_removes_more():
    rng = np.random.default_rng(3)
    guitar = np.stack([rng.standard_normal(SR)] * 2, axis=1) * 0.2
    envelope = np.ones(SR)

    shallow = band_energy(duck_under_vocal(guitar, envelope, SR, 2.0), *VOCAL_BAND_HZ)
    deep = band_energy(duck_under_vocal(guitar, envelope, SR, 6.0), *VOCAL_BAND_HZ)
    assert deep < shallow


def test_only_stems_that_compete_are_ducked():
    """Bass and drums live above and below a vocal; ducking them just pumps."""
    assert should_duck(StemKind.GUITAR)
    assert should_duck(StemKind.PIANO)
    assert should_duck(StemKind.OTHER)
    assert not should_duck(StemKind.BASS)
    assert not should_duck(StemKind.DRUMS)
    assert not should_duck(StemKind.VOCALS)


def test_ducking_survives_a_short_envelope():
    """The envelope comes from the vocal stem, which may be a different length."""
    rng = np.random.default_rng(4)
    guitar = np.stack([rng.standard_normal(SR * 2)] * 2, axis=1) * 0.2
    out = duck_under_vocal(guitar, np.ones(SR), SR, depth_db=3.0)
    assert out.shape == guitar.shape


# --- placement has to allow for what the match is about to do -------------------------


def _scooping_curve(n_fft: int, sample_rate: int) -> np.ndarray:
    """A match curve shaped like a real one: ends lifted, middle cut.

    This is the shape a reference with more weight at both ends than yours produces,
    and it is the shape that quietly undoes vocal placement.
    """
    freqs = np.fft.rfftfreq(n_fft, 1 / sample_rate)
    db = np.where((freqs > 200) & (freqs < 3000), -3.5, 2.0)
    return 10 ** (db / 20.0)


def test_placement_measures_the_vocal_through_the_coming_match():
    """A mid-heavy vocal loses more to a scooped match than the broad mix does.

    Placement runs before the match because it changes the gains the match reads, which
    used to leave it deciding on a balance the match then rewrote. Measuring through the
    curve is what closes that gap; without it a vocal sitting exactly on target before
    the match ends up behind it afterwards.
    """
    from app.services.mastering.dsp import DEFAULT_HOP, DEFAULT_N_FFT, apply_curve
    from app.services.mastering.loudness_meter import integrated_loudness

    rate = 44100
    t = np.arange(rate * 4) / rate
    # A vocal living in the scooped band, against a mix spread across the spectrum.
    vocal = np.stack([0.3 * np.sin(2 * np.pi * 800 * t)] * 2, axis=1)
    mix = vocal + np.stack(
        [0.3 * np.sin(2 * np.pi * 60 * t) + 0.3 * np.sin(2 * np.pi * 8000 * t)] * 2,
        axis=1,
    )

    curve = _scooping_curve(DEFAULT_N_FFT, rate)
    before = integrated_loudness(vocal, rate)[0] - integrated_loudness(mix, rate)[0]
    after = (
        integrated_loudness(apply_curve(vocal, curve, DEFAULT_N_FFT, DEFAULT_HOP), rate)[0]
        - integrated_loudness(apply_curve(mix, curve, DEFAULT_N_FFT, DEFAULT_HOP), rate)[0]
    )

    # The match pushes the vocal back relative to the mix; that is the whole problem.
    assert after < before - 0.5

    # And placement asks for more lift once it can see that happening.
    lift_blind, _ = vocal_lift_db(before, VocalPresence.NATURAL)
    lift_aware, _ = vocal_lift_db(after, VocalPresence.NATURAL)
    assert lift_aware > lift_blind


def test_predicting_the_match_curve_is_skipped_without_a_reference():
    """No reference means no tilt to allow for, and no spectra worth computing."""
    from app.services.mastering.pipeline import MasterRequest, _predicted_match_curve

    request = MasterRequest(stems={}, settings=[], reference=None)
    assert _predicted_match_curve([], [], [], 44100, request) is None
