"""Per-instrument matching: bass against bass, drums against drums.

The behaviour that matters: levels are matched *relatively*, tone comes from the right
counterpart, and bass stays in the middle.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.domain.notes import StemKind
from app.services.mastering.dsp import set_width, stereo_width
from app.services.mastering.stem_match import (
    MAX_STEM_GAIN_DB,
    match_stem,
    profile_stems,
)

SR = 44100


def write(path: Path, samples, sr=SR):
    audio = np.asarray(samples, dtype="float32")
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    sf.write(str(path), audio, sr)
    return path


def tone(freq, seconds=4.0, amp=0.3):
    t = np.arange(int(seconds * SR)) / SR
    return amp * np.sin(2 * np.pi * freq * t)


# ──────────────────────────────── width ────────────────────────────────


def test_mono_measures_as_zero_width():
    assert stereo_width(np.stack([tone(440)] * 2, axis=1)) == pytest.approx(0.0, abs=1e-6)


def test_uncorrelated_channels_measure_as_wide():
    rng = np.random.default_rng(0)
    stereo = rng.standard_normal((SR, 2))
    assert stereo_width(stereo) > 0.5


def test_widening_increases_measured_width():
    rng = np.random.default_rng(1)
    stereo = np.stack([rng.standard_normal(SR), rng.standard_normal(SR)], axis=1)
    before = stereo_width(stereo)
    after = stereo_width(set_width(stereo, 2.0))
    assert after > before


def test_collapsing_to_zero_width_gives_mono():
    rng = np.random.default_rng(2)
    stereo = np.stack([rng.standard_normal(SR), rng.standard_normal(SR)], axis=1)
    mono = set_width(stereo, 0.0)
    assert np.allclose(mono[:, 0], mono[:, 1])


def test_widening_is_mono_safe():
    """Collapsing a widened signal to mono must return the original mid, not silence."""
    rng = np.random.default_rng(3)
    stereo = np.stack([rng.standard_normal(SR), rng.standard_normal(SR)], axis=1)
    mid_before = (stereo[:, 0] + stereo[:, 1]) / 2

    widened = set_width(stereo, 2.5)
    mid_after = (widened[:, 0] + widened[:, 1]) / 2
    assert np.allclose(mid_before, mid_after, atol=1e-9)


# ──────────────────────────────── profiling ────────────────────────────────


def test_profiling_measures_levels_relative_to_the_mix(tmp_path: Path):
    """The portable number is how far a stem sits from its own mix, not its absolute level."""
    loud = write(tmp_path / "drums.wav", tone(200, amp=0.5))
    quiet = write(tmp_path / "bass.wav", tone(80, amp=0.05))

    profiles = profile_stems({StemKind.DRUMS: loud, StemKind.BASS: quiet})

    assert profiles[StemKind.DRUMS].relative_lufs > profiles[StemKind.BASS].relative_lufs
    # The loud stem dominates the mix, so it sits near it; the quiet one sits well below.
    assert profiles[StemKind.BASS].relative_lufs < -6


def test_silent_stems_are_skipped(tmp_path: Path):
    """Demucs routinely returns an empty piano stem; it is not a matching target."""
    real = write(tmp_path / "bass.wav", tone(80))
    silent = write(tmp_path / "piano.wav", np.zeros(SR * 4))

    profiles = profile_stems({StemKind.BASS: real, StemKind.PIANO: silent})
    assert StemKind.BASS in profiles
    assert StemKind.PIANO not in profiles


def test_profiling_an_empty_set_is_safe():
    assert profile_stems({}) == {}


# ──────────────────────────────── matching ────────────────────────────────


def build(tmp_path, name, samples):
    return profile_stems({StemKind.BASS: write(tmp_path / name, samples)})[StemKind.BASS]


def test_a_quiet_stem_is_turned_up_towards_the_reference(tmp_path: Path):
    source = build(tmp_path, "src.wav", tone(80, amp=0.05))
    target = build(tmp_path, "ref.wav", tone(80, amp=0.5))
    # A single stem is its own mix, so both sit at 0 relative - force a difference.
    source.relative_lufs = -12.0
    target.relative_lufs = -4.0

    audio = np.stack([tone(80, amp=0.05)] * 2, axis=1)
    _out, adjustment = match_stem(audio, SR, source, target, match_tone=False)

    assert adjustment.gain_db == pytest.approx(8.0, abs=0.1)


def test_stem_gain_is_capped_and_the_cap_is_reported(tmp_path: Path):
    source = build(tmp_path, "src.wav", tone(80, amp=0.05))
    target = build(tmp_path, "ref.wav", tone(80, amp=0.5))
    source.relative_lufs = -40.0
    target.relative_lufs = 0.0

    audio = np.stack([tone(80, amp=0.05)] * 2, axis=1)
    _out, adjustment = match_stem(audio, SR, source, target, match_tone=False)

    assert adjustment.gain_db == pytest.approx(MAX_STEM_GAIN_DB)
    assert any("capped" in note for note in adjustment.notes)


def test_bass_is_never_widened(tmp_path: Path):
    """Widening the low end thins it and causes trouble in mono."""
    rng = np.random.default_rng(4)
    wide = np.stack([rng.standard_normal(SR * 2), rng.standard_normal(SR * 2)], axis=1)
    write(tmp_path / "ref.wav", wide)

    source = build(tmp_path, "src.wav", tone(80))
    target = profile_stems({StemKind.BASS: tmp_path / "ref.wav"})[StemKind.BASS]

    narrow = np.stack([tone(80)] * 2, axis=1)
    out, adjustment = match_stem(narrow, SR, source, target, match_tone=False,
                                 match_levels=False)

    assert adjustment.width_factor == 1.0
    assert np.allclose(out[:, 0], out[:, 1]), "bass must stay centred"
    assert any("centred" in note for note in adjustment.notes)


def test_tone_matching_reports_the_bands_it_moved(tmp_path: Path):
    source = build(tmp_path, "src.wav", tone(80, amp=0.3))
    target = build(tmp_path, "ref.wav", tone(4000, amp=0.3))

    audio = np.stack([tone(80, amp=0.3)] * 2, axis=1)
    _out, adjustment = match_stem(audio, SR, source, target, match_levels=False,
                                  match_stereo=False)

    assert adjustment.eq_bands, "the applied curve should be reported"
    assert all(-13 <= db <= 7 for _hz, db in adjustment.eq_bands)


def test_every_matching_stage_can_be_turned_off(tmp_path: Path):
    source = build(tmp_path, "src.wav", tone(80, amp=0.1))
    target = build(tmp_path, "ref.wav", tone(4000, amp=0.5))

    audio = np.stack([tone(80, amp=0.1)] * 2, axis=1)
    out, adjustment = match_stem(
        audio, SR, source, target,
        match_levels=False, match_tone=False, match_stereo=False,
    )

    assert adjustment.gain_db == 0.0
    assert adjustment.eq_bands == []
    assert np.allclose(out, audio)
