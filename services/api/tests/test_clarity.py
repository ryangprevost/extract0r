"""Clarity: the measures a master EQ cannot reach.

The thresholds here were set from a track held in storage with separated stems for both
a home mix and its commercial reference. That mix read 3.0 effective instruments in
2-4 kHz against the reference's 1.3, and 3.3 dB of spectral contrast against 8.3 - which
is what "muddy" turned out to mean when it was measured instead of guessed.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.clarity import (
    BANDS,
    CONTRAST_GAP_DB,
    CROWDED,
    BandReading,
    contrast_db,
    crest_db,
    findings,
    read_mix,
)

SR = 44100


def _tone(hz: float, seconds: float = 4.0, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return np.stack([amplitude * np.sin(2 * np.pi * hz * t)] * 2, axis=1)


def _noise(seconds: float = 4.0, amplitude: float = 0.1) -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.normal(0, amplitude, (int(SR * seconds), 2))


def _reading(name: str, contrast: float, crowding: float, holders=()) -> BandReading:
    low, high = next((lo, hi) for lo, hi, n in BANDS if n == name)
    return BandReading(
        name=name,
        low_hz=low,
        high_hz=high,
        contrast_db=contrast,
        crest_db=7.0,
        crowding=crowding,
        holders=holders,
    )


# --- the measures themselves ----------------------------------------------------------


def test_tones_have_more_contrast_than_noise():
    """The whole idea rests on this: a band of distinct partials reads high, a band that
    has filled in reads low. If it did not hold, nothing built on it would mean anything.
    """
    freqs = np.fft.rfftfreq(8192, 1 / SR)

    def spectrum(x):
        mono = x.mean(axis=1)
        frames = [
            np.abs(np.fft.rfft(mono[i : i + 8192] * np.hanning(8192))) ** 2
            for i in range(0, len(mono) - 8192, 4096)
        ]
        return np.mean(frames, axis=0)

    tonal = contrast_db(spectrum(_tone(2500.0)), freqs, 2000, 4000)
    wash = contrast_db(spectrum(_noise()), freqs, 2000, 4000)
    assert tonal > wash + 10.0


def test_a_tone_that_pulses_has_more_crest_than_a_steady_one():
    """Crest is a median across short windows, so it describes what a band does most of
    the time rather than its loudest moment. A part that jumps every few beats therefore
    has to jump often enough to be typical - which is the point, and is why an occasional
    crash cymbal does not register as a dynamic mix.
    """
    steady = _tone(3000.0)
    # 10 ms loud, 30 ms quiet: short enough that every measurement window sees a peak.
    envelope = np.where((np.arange(len(steady)) % (SR // 25)) < (SR // 100), 1.0, 0.25)
    pulsing = steady * envelope[:, None]

    assert crest_db(pulsing, SR, 2000, 4000) > crest_db(steady, SR, 2000, 4000) + 3.0


def test_crowding_counts_how_many_stems_share_a_band():
    """One stem owning a band reads near 1; two splitting it evenly read near 2."""
    alone = read_mix(_tone(3000.0), SR, {"guitar": _tone(3000.0)})
    presence = next(b for b in alone if b.name == "presence")
    assert presence.crowding == pytest.approx(1.0, abs=0.1)

    a, b = _tone(2500.0), _tone(3500.0)
    shared = read_mix(a + b, SR, {"guitar": a, "piano": b})
    presence = next(x for x in shared if x.name == "presence")
    assert presence.crowding == pytest.approx(2.0, abs=0.2)


def test_a_silent_band_reports_nothing_rather_than_failing():
    quiet = np.zeros((SR * 2, 2))
    readings = read_mix(quiet, SR, {"guitar": quiet})
    assert all(np.isfinite(b.contrast_db) and np.isfinite(b.crest_db) for b in readings)


# --- what it says ---------------------------------------------------------------------


def test_a_crowded_flat_band_names_the_instruments_in_it():
    yours = [_reading("presence", 3.3, 3.0, (("guitar", 0.5), ("drums", 0.3), ("vocals", 0.2)))]
    theirs = [_reading("presence", 8.3, 1.3)]

    out = findings(yours, theirs)
    assert out, "a 5 dB contrast gap in a crowded band should be reported"
    top = out[0]
    # The headline opens the sentence, so the first stem arrives capitalised.
    assert "guitar" in top["headline"].lower()
    assert top["severity"] == "notable"
    # It must not offer a dial: there is no EQ move that separates these.
    assert "action" not in top
    assert "arrangement" in top["detail"]


def test_the_band_owner_is_named_rather_than_the_loudest_stem():
    """Guitar holds the most of this band, but a vocal is what should own it. Ranking by
    loudness would tell someone to turn up the thing already covering everything."""
    yours = [_reading("presence", 3.0, 3.0, (("guitar", 0.6), ("vocals", 0.4)))]
    theirs = [_reading("presence", 8.0, 1.2)]

    assert "vocals would own this range" in findings(yours, theirs)[0]["detail"]


def test_a_crowded_band_that_still_has_structure_is_left_alone():
    """Density is not mud. A busy band that kept its contrast is an arrangement."""
    yours = [_reading("presence", 8.2, 3.0, (("guitar", 0.5), ("piano", 0.5)))]
    theirs = [_reading("presence", 8.3, 1.3)]
    assert findings(yours, theirs) == []


def test_a_flat_band_with_nothing_in_it_reads_as_thin_not_crowded():
    yours = [_reading("mid", 6.0, 1.2, (("guitar", 0.9),))]
    theirs = [_reading("mid", 9.0, 1.3)]

    out = findings(yours, theirs)
    assert len(out) == 1
    assert "thinner" in out[0]["headline"]
    assert "less happening" in out[0]["detail"]


def test_an_empty_top_is_called_out():
    yours = [_reading("air", 7.0, 1.2, (("drums", 0.8), ("vocals", 0.2)))]
    theirs = [_reading("air", 6.5, 2.0)]

    out = findings(yours, theirs)
    assert any("reach into" in f["headline"] for f in out)
    assert any("synth patch" in f["detail"] for f in out)


def test_plural_bands_take_a_plural_verb():
    yours = [_reading("upper mid", 6.0, 1.1, (("guitar", 1.0),))]
    theirs = [_reading("upper mid", 9.0, 1.2)]
    assert "upper mids are thinner" in findings(yours, theirs)[0]["headline"]

    yours = [_reading("mid", 6.0, 1.1, (("guitar", 1.0),))]
    theirs = [_reading("mid", 9.0, 1.2)]
    assert "midrange is thinner" in findings(yours, theirs)[0]["headline"]


def test_a_mix_matching_its_reference_is_told_so_by_silence():
    yours = [_reading(name, 8.0, 1.2, (("guitar", 1.0),)) for _, _, name in BANDS]
    theirs = [_reading(name, 8.0, 1.2) for _, _, name in BANDS]
    assert findings(yours, theirs) == []


def test_thresholds_are_the_ones_the_findings_claim():
    """Guards the numbers in the docstrings against quiet drift."""
    assert CROWDED == 2.0
    assert CONTRAST_GAP_DB == 1.5
