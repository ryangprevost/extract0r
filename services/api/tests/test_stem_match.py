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
from app.services.mastering.dsp import DEFAULT_N_FFT, set_width, stereo_width
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
    # -25 rather than the -40 this used to use. The gap only has to exceed the cap, and
    # -40 is now *absent* - X0R-1127 made `match_stem` decline when the source stem is
    # residue, so the old fixture tested the cap by way of a stem that no longer gets
    # matched at all. 25 dB is still comfortably past a 9 dB cap.
    source.relative_lufs = -25.0
    target.relative_lufs = 0.0

    audio = np.stack([tone(80, amp=0.05)] * 2, axis=1)
    _out, adjustment = match_stem(audio, SR, source, target, match_tone=False)

    assert adjustment.matched is True, adjustment.notes
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


def test_a_reference_without_the_instrument_leaves_the_stem_alone(tmp_path: Path):
    """A reference with no piano must not silence your piano.

    Separation always returns a stem for every instrument the model knows, even when the
    track has none - it just comes back tens of LU below the mix. Matching against that
    asks for a -60 dB cut, which would quietly delete a part the user actually played.
    Measured on a real run: guitar wanted -68 dB against a reference that had no guitar.
    """
    source = build(tmp_path, "src.wav", tone(300, amp=0.4))
    target = build(tmp_path, "ref.wav", tone(300, amp=0.4))
    source.relative_lufs = -6.0
    target.relative_lufs = -55.0  # what separation returns for an absent instrument

    audio = np.stack([tone(300, amp=0.4)] * 2, axis=1)
    out, adjustment = match_stem(audio, SR, source, target)

    assert adjustment.gain_db == 0.0
    assert adjustment.eq_bands == []
    assert np.allclose(out, audio), "an absent reference instrument must change nothing"
    assert any("essentially no" in note for note in adjustment.notes)


def test_a_quiet_but_present_instrument_is_still_matched(tmp_path: Path):
    """The absent-instrument guard must not swallow genuinely quiet parts."""
    source = build(tmp_path, "src.wav", tone(300, amp=0.4))
    target = build(tmp_path, "ref.wav", tone(300, amp=0.4))
    source.relative_lufs = -6.0
    target.relative_lufs = -18.0  # quiet in the mix, but unmistakably there

    audio = np.stack([tone(300, amp=0.4)] * 2, axis=1)
    _out, adjustment = match_stem(audio, SR, source, target, match_tone=False)

    assert adjustment.gain_db == pytest.approx(-9.0)  # capped, but applied


def test_width_changes_are_bounded(tmp_path: Path):
    """Collapsing a part to a quarter of its width is not a subtle match.

    Width measured on a separated stem is noisy - artefacts land in the side channel - so
    the extremes of the measurement are not trustworthy enough to act on fully.
    """
    from app.services.mastering.dsp import match_width
    from app.services.mastering.stem_match import WIDTH_LIMITS

    rng = np.random.default_rng(7)
    wide = np.stack([rng.standard_normal(SR), rng.standard_normal(SR)], axis=1)

    _narrowed, factor = match_width(wide, 0.001, *WIDTH_LIMITS)
    assert factor >= WIDTH_LIMITS[0]

    nearly_mono = np.stack([tone(440), tone(440) * 1.001], axis=1)
    _widened, factor = match_width(nearly_mono, 5.0, *WIDTH_LIMITS)
    assert factor <= WIDTH_LIMITS[1]


# --- an instrument your mix does not contain --------------------------------------------
#
# X0R-1127. `has_counterpart` asked only whether the *reference* had the instrument, so
# the mirror case went straight through: your mix has no guitar, theirs has separation
# residue that clears the threshold, and the level match asks for the difference. Measured
# on a real pair during the pr0ducer experiments - source guitar at -59.7 LU, reference
# guitar residue at -22.7 - matching wanted +37 dB and applied the +9 the clamp allowed,
# to an instrument nobody played.
#
# Inaudible in that instance only because the stem was already 50 LU down. The mechanism
# is not bounded by that: a quiet *real* guitar in the same position gets an audible 9 dB
# lift of the wrong thing, and the louder the user's part the louder the mistake.


def _profile(stem, relative_lufs, spectrum=None, sample_rate=SR):
    from app.services.mastering.stem_match import StemProfile

    return StemProfile(
        stem=stem,
        spectrum=spectrum if spectrum is not None else np.ones(DEFAULT_N_FFT // 2 + 1),
        loudness_lufs=-20.0,
        width=1.0,
        relative_lufs=relative_lufs,
        sample_rate=sample_rate,
    )


def test_a_stem_missing_from_your_mix_is_not_matched():
    """The bug. Your side empty, their side residue that clears the threshold."""
    from app.domain.notes import StemKind
    from app.services.mastering.stem_match import match_stem

    audio = np.zeros((SR, 2))
    out, adjustment = match_stem(
        audio, SR,
        source=_profile(StemKind.GUITAR, -59.7),
        reference=_profile(StemKind.GUITAR, -22.7),
    )
    assert adjustment.matched is False
    assert adjustment.gain_db == 0.0, f"no gain on an absent instrument: {adjustment.gain_db}"
    assert np.array_equal(out, audio), "the audio should be returned untouched"
    assert any("your mix" in note for note in adjustment.notes), adjustment.notes


def test_the_note_says_which_side_was_empty():
    """Which side matters to whoever reads the report: "the reference has no piano" means
    the tool declined to copy something, "your mix has no piano" means it declined to
    invent one."""
    from app.domain.notes import StemKind
    from app.services.mastering.stem_match import match_stem

    audio = np.zeros((SR, 2))
    _, theirs_empty = match_stem(
        audio, SR,
        source=_profile(StemKind.PIANO, -8.0),
        reference=_profile(StemKind.PIANO, -44.0),
    )
    _, mine_empty = match_stem(
        audio, SR,
        source=_profile(StemKind.PIANO, -44.0),
        reference=_profile(StemKind.PIANO, -8.0),
    )
    assert any("reference has essentially no piano" in n for n in theirs_empty.notes)
    assert any("your mix has essentially no piano" in n for n in mine_empty.notes)


def test_two_instruments_both_present_still_match():
    """The other half: a rule that declined everything would pass the tests above."""
    from app.domain.notes import StemKind
    from app.services.mastering.stem_match import match_stem

    rng = np.random.default_rng(4)
    audio = rng.standard_normal((SR, 2)) * 0.2
    _, adjustment = match_stem(
        audio, SR,
        source=_profile(StemKind.BASS, -9.0),
        reference=_profile(StemKind.BASS, -5.0),
    )
    assert adjustment.matched is True
    assert adjustment.gain_db != 0.0, "a 4 LU gap should move the level"


def test_every_path_asks_the_same_question():
    """The duplication that let them disagree.

    `ABSENT_BELOW_LU` was written out twice and imported from a third place. Two of the
    three checked both sides and one checked the reference only. One definition now, and
    this fails if anybody re-introduces a local copy that drifts.
    """
    from app.services.mastering import critique, instrument, presence, stem_match

    assert instrument.ABSENT_BELOW_LU is presence.ABSENT_BELOW_LU
    assert stem_match.ABSENT_BELOW_LU is presence.ABSENT_BELOW_LU
    assert "ABSENT_BELOW_LU = -30" not in __import__("pathlib").Path(
        critique.__file__
    ).read_text(encoding="utf-8")


def test_presence_is_about_one_recording_and_comparable_is_about_two():
    from app.services.mastering.presence import comparable, is_present

    assert is_present(-8.0) and not is_present(-44.0)
    assert comparable(-8.0, -5.0)
    assert not comparable(-8.0, -44.0), "their side empty"
    assert not comparable(-44.0, -8.0), "your side empty"
    assert not comparable(None, -8.0)
