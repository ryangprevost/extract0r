"""Two rules that keep a matched mix coherent.

1. An instrument the reference does not contain must still move with the arrangement.
   Leaving it untouched is not neutral: every other stem has just changed level, so a
   piano left alone ends up louder or quieter *relative to the mix* by accident.
2. The user's own fader stacks on top of matching. Matching sets a starting point; the
   person listening gets the last word.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.domain.notes import StemKind
from app.services.mastering import pipeline as master
from app.services.mastering.pipeline import MasterRequest, StemSetting
from app.services.mastering.stem_match import has_counterpart, profile_stems
from app.services.mixdown.encode import read_audio

SR = 44100


def write(path: Path, samples, sr=SR) -> Path:
    audio = np.asarray(samples, dtype="float32")
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    sf.write(str(path), audio, sr)
    return path


def tone(freq, seconds=4.0, amp=0.3):
    t = np.arange(int(seconds * SR)) / SR
    return amp * np.sin(2 * np.pi * freq * t)


@pytest.fixture
def source_stems(tmp_path: Path) -> dict[StemKind, Path]:
    d = tmp_path / "src"
    d.mkdir()
    return {
        StemKind.BASS: write(d / "bass.wav", tone(80, amp=0.45)),
        StemKind.DRUMS: write(d / "drums.wav", tone(200, amp=0.4)),
        StemKind.PIANO: write(d / "piano.wav", tone(900, amp=0.3)),
    }


@pytest.fixture
def reference_without_piano(tmp_path: Path) -> dict[StemKind, Path]:
    """A reference containing bass and drums but effectively no piano.

    This is what separation returns for a track with no piano in it: not a missing file,
    a file 60 dB down.
    """
    d = tmp_path / "ref"
    d.mkdir()
    return {
        StemKind.BASS: write(d / "bass.wav", tone(80, amp=0.12)),
        StemKind.DRUMS: write(d / "drums.wav", tone(200, amp=0.5)),
        StemKind.PIANO: write(d / "piano.wav", tone(900, amp=0.00002)),
    }


# ──────────────────────────────── the decision ────────────────────────────────


def test_an_absent_instrument_is_recognised(reference_without_piano):
    profiles = profile_stems(reference_without_piano)
    assert has_counterpart(profiles.get(StemKind.BASS))
    assert not has_counterpart(profiles.get(StemKind.PIANO))


def test_a_missing_profile_has_no_counterpart():
    assert not has_counterpart(None)


# ──────────────────────────────── proportional mixing ──────────────────────────


def test_an_unmatched_stem_follows_the_rest_of_the_mix(
    tmp_path: Path, source_stems, reference_without_piano
):
    """The whole point: piano moves with the arrangement instead of standing still."""
    result = master.run(
        MasterRequest(
            stems=source_stems,
            settings=[StemSetting(s) for s in source_stems],
            reference_stems=reference_without_piano,
            vocal_presence=None,
        ),
        tmp_path / "work",
    )

    by_stem = {a.stem: a for a in result.stem_adjustments}
    piano = by_stem[StemKind.PIANO]

    assert piano.matched is False
    assert piano.proportional is True
    assert any("follows the rest of the mix" in note for note in piano.notes)

    matched = [by_stem[s].gain_db for s in (StemKind.BASS, StemKind.DRUMS)]
    assert piano.gain_db == pytest.approx(sum(matched) / len(matched), abs=0.05)


def test_an_unmatched_stem_is_not_left_at_zero(
    tmp_path: Path, source_stems, reference_without_piano
):
    """Regression guard: the old behaviour returned the stem untouched."""
    result = master.run(
        MasterRequest(
            stems=source_stems,
            settings=[StemSetting(s) for s in source_stems],
            reference_stems=reference_without_piano,
            vocal_presence=None,
        ),
        tmp_path / "work",
    )
    piano = next(a for a in result.stem_adjustments if a.stem is StemKind.PIANO)
    matched = [a.gain_db for a in result.stem_adjustments if a.matched]

    # Only meaningful if matching actually moved the other stems.
    if any(abs(g) > 0.5 for g in matched):
        assert abs(piano.gain_db) > 0.1, "the piano stood still while the mix moved"


def test_every_stem_is_reported_exactly_once(
    tmp_path: Path, source_stems, reference_without_piano
):
    result = master.run(
        MasterRequest(
            stems=source_stems,
            settings=[StemSetting(s) for s in source_stems],
            reference_stems=reference_without_piano,
            vocal_presence=None,
        ),
        tmp_path / "work",
    )
    reported = [a.stem for a in result.stem_adjustments]
    assert sorted(reported, key=lambda s: s.value) == sorted(
        source_stems, key=lambda s: s.value
    )


def test_with_nothing_matched_the_mix_is_left_alone(tmp_path: Path, source_stems):
    """No counterpart anywhere means no basis for a proportional move either.

    A reference of entirely different instruments, rather than a quiet one: the absence
    threshold is relative to the reference's own mix, so a uniformly quiet reference still
    has a counterpart for everything.
    """
    d = tmp_path / "other_ref"
    d.mkdir()
    other = {
        StemKind.VOCALS: write(d / "vocals.wav", tone(440, amp=0.3)),
        StemKind.GUITAR: write(d / "guitar.wav", tone(600, amp=0.3)),
    }

    result = master.run(
        MasterRequest(
            stems=source_stems,
            settings=[StemSetting(s) for s in source_stems],
            reference_stems=other,
            vocal_presence=None,
        ),
        tmp_path / "work",
    )
    assert all(not a.matched for a in result.stem_adjustments)
    assert all(a.gain_db == 0.0 for a in result.stem_adjustments)


# ──────────────────────────────── user overrides ────────────────────────────────


def test_the_user_fader_stacks_on_top_of_matching(
    tmp_path: Path, source_stems, reference_without_piano
):
    """Raising a stem while still matching the reference has to work."""
    plain = master.run(
        MasterRequest(
            stems=source_stems,
            settings=[StemSetting(s) for s in source_stems],
            reference_stems=reference_without_piano,
            vocal_presence=None,
        ),
        tmp_path / "plain",
    )
    boosted = master.run(
        MasterRequest(
            stems=source_stems,
            settings=[
                StemSetting(s, gain_db=6.0 if s is StemKind.PIANO else 0.0)
                for s in source_stems
            ],
            reference_stems=reference_without_piano,
            vocal_presence=None,
        ),
        tmp_path / "boosted",
    )

    # Matching decides the same thing either way - the fader is applied at the bus, so it
    # cannot pollute the measurement matching is derived from.
    plain_piano = next(a for a in plain.stem_adjustments if a.stem is StemKind.PIANO)
    boosted_piano = next(a for a in boosted.stem_adjustments if a.stem is StemKind.PIANO)
    assert boosted_piano.gain_db == pytest.approx(plain_piano.gain_db, abs=0.01)
    assert boosted_piano.user_gain_db == 6.0

    # And the boost is audible in the render.
    quiet = read_audio(tmp_path / "plain" / "mix.wav")
    loud = read_audio(tmp_path / "boosted" / "mix.wav")
    assert float(np.abs(loud.samples).max()) > float(np.abs(quiet.samples).max())


def test_the_user_fader_is_reported_separately(
    tmp_path: Path, source_stems, reference_without_piano
):
    """Two numbers, not one: what matching did, and what you did."""
    result = master.run(
        MasterRequest(
            stems=source_stems,
            settings=[
                StemSetting(s, gain_db=-3.0 if s is StemKind.DRUMS else 0.0)
                for s in source_stems
            ],
            reference_stems=reference_without_piano,
            vocal_presence=None,
        ),
        tmp_path / "work",
    )
    drums = next(a for a in result.stem_adjustments if a.stem is StemKind.DRUMS)
    assert drums.user_gain_db == -3.0
