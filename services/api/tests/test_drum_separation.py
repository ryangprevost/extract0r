"""Splitting a drums stem into the drums inside it.

The point of this module is one property, and it is structural rather than statistical:
after separation a stroke carries exactly one drum, because it came out of that drum's
file. There is no threshold to tune and therefore nothing to flicker.

That is worth stating against what it replaces. `detect` decides between a kick and a
snare by comparing how far two bands rose on a summed stem, and on real material a quarter
of the kicks sit within a few decibels of the line - which is heard not as a few wrong
labels but as a snare that comes and goes between consecutive kicks.

These tests do not need the DrumSep weights. The ones that would are skipped when the
model is absent, and say so, because a 167 MB download is not a reasonable thing for a
test run to require.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.services.drums.detect import Hit
from app.services.drums.separate import (
    MODEL,
    QUIET_STROKE_DB,
    STEM_NAMES,
    available,
    hits_from_stems,
    model_path,
    why_unavailable,
)

SR = 44100


def _write(path: Path, strokes: list[tuple[float, float]], hz: float, seconds: float = 4.0):
    """A stem containing one drum: decaying tones at the given times and amplitudes."""
    import soundfile as sf

    n = int(SR * seconds)
    audio = np.zeros(n)
    for when, amplitude in strokes:
        start = int(when * SR)
        length = min(int(0.2 * SR), n - start)
        if length <= 0:
            continue
        t = np.arange(length) / SR
        audio[start : start + length] += (
            np.sin(2 * np.pi * hz * t) * np.exp(-25 * t) * amplitude
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.stack([audio, audio], axis=1), SR)
    return path


# --- the property the whole card exists for ---------------------------------------------


def test_every_stroke_carries_exactly_one_drum(tmp_path):
    """No threshold, no ambiguity, no flicker. A stroke in the kick file is a kick."""
    stems = {
        "kick": _write(tmp_path / "kick.wav", [(0.5, 0.9), (1.0, 0.9), (1.5, 0.9)], 60),
        "snare": _write(tmp_path / "snare.wav", [(0.75, 0.8), (1.75, 0.8)], 220),
    }
    hits = hits_from_stems(stems)
    assert hits, "the fixture should produce strokes"
    for hit in hits:
        assert len(hit.kinds) == 1, f"a separated stroke is one drum: {hit.kinds}"
    assert {h.kinds[0] for h in hits} == {"kick", "snare"}


def test_strokes_come_back_in_time_order(tmp_path):
    """Merged from several files, so ordering is this module's job rather than a given.
    `layer` walks them in order and a sample placed out of order lands on the wrong beat."""
    stems = {
        "kick": _write(tmp_path / "kick.wav", [(0.5, 0.9), (1.5, 0.9)], 60),
        "snare": _write(tmp_path / "snare.wav", [(1.0, 0.8), (2.0, 0.8)], 220),
    }
    times = [h.time_s for h in hits_from_stems(stems)]
    assert times == sorted(times)


def test_a_kick_in_the_kick_file_is_never_called_a_snare(tmp_path):
    """The reported bug, restated as what separation makes impossible.

    The signal here is the one that broke the classifier: a kick with a bright click, so
    its energy reaches the snare's rattle band. The classifier had to decide; this does
    not, because the file it came from already answered.
    """
    import soundfile as sf

    n = int(SR * 3.0)
    audio = np.zeros(n)
    rng = np.random.default_rng(3)
    for when in (0.5, 1.0, 1.5, 2.0):
        start = int(when * SR)
        t = np.arange(int(0.25 * SR)) / SR
        body = np.sin(2 * np.pi * (170 * np.exp(-20 * t) + 47) * t) * np.exp(-9 * t)
        click = rng.normal(0, 1, t.size) * np.exp(-200 * t) * 0.8
        audio[start : start + t.size] += body + click

    path = tmp_path / "kick.wav"
    sf.write(str(path), np.stack([audio, audio], axis=1), SR)

    hits = hits_from_stems({"kick": path})
    assert hits
    assert all(h.kinds == ["kick"] for h in hits), (
        "a bright kick out of the kick file is still only a kick"
    )


# --- the bleed gate ----------------------------------------------------------------------


def test_bleed_below_the_gate_is_not_a_stroke(tmp_path):
    """Separation is not surgery: a kick leaves a trace in the snare file, and an onset
    detector run over that trace finds strokes that are really the kick arriving late."""
    loud = 0.9
    bleed = loud * 10 ** ((QUIET_STROKE_DB - 10) / 20)  # well under the gate
    stems = {
        "snare": _write(
            tmp_path / "snare.wav",
            [(0.5, loud), (0.75, bleed), (1.5, loud), (1.75, bleed)],
            220,
        )
    }
    hits = hits_from_stems(stems)
    assert len(hits) == 2, f"only the real strokes should survive: {[h.time_s for h in hits]}"
    assert all(h.time_s < 0.7 or 1.4 < h.time_s < 1.7 for h in hits)


def test_the_gate_is_relative_to_each_drum_and_not_to_the_loudest(tmp_path):
    """A quiet instrument played properly is not bleed.

    Gating across stems would silence an entire snare on a record the kick dominates,
    which on a club track is most of them.
    """
    stems = {
        "kick": _write(tmp_path / "kick.wav", [(0.5, 0.95), (1.0, 0.95)], 60),
        "snare": _write(tmp_path / "snare.wav", [(0.75, 0.05), (1.25, 0.05)], 220),
    }
    kinds = {h.kinds[0] for h in hits_from_stems(stems)}
    assert kinds == {"kick", "snare"}, (
        f"a snare 25 dB under the kick is still a snare: {kinds}"
    )


def test_a_silent_stem_contributes_nothing(tmp_path):
    """A record with no toms yields a toms file that is residue. It must not become a
    drum part — this is the same trap as the -30 LU presence threshold elsewhere."""
    import soundfile as sf

    path = tmp_path / "toms.wav"
    sf.write(str(path), np.zeros((SR, 2)), SR)
    assert hits_from_stems({"toms": path}) == []


def test_an_unreadable_stem_costs_its_own_drum_and_nothing_else(tmp_path):
    junk = tmp_path / "snare.wav"
    junk.write_bytes(b"not audio")
    stems = {
        "kick": _write(tmp_path / "kick.wav", [(0.5, 0.9), (1.0, 0.9)], 60),
        "snare": junk,
    }
    hits = hits_from_stems(stems)
    assert hits and {h.kinds[0] for h in hits} == {"kick"}


# --- availability ------------------------------------------------------------------------


def test_the_model_is_named_the_way_demucs_wants_it():
    """`-n 49469ca8` is not a name anyone chose, it is the hash demucs assigns a set of
    weights, and the CLI takes it verbatim. A typo here is a download that never matches."""
    assert MODEL == "49469ca8"
    assert model_path(Path("/models")).name == "49469ca8.th"


def test_a_missing_model_explains_itself_rather_than_failing(tmp_path):
    assert available(tmp_path) is False
    why = why_unavailable(tmp_path)
    assert "167 MB" in why and "huggingface" in why, why


def test_the_spanish_names_are_translated_at_the_boundary():
    """The model was published in Spanish. Translating here means nothing downstream has
    to know that, and the names match `kit.DRUMS` so `layer` needs no mapping of its own."""
    from app.services.drums.kit import DRUMS

    assert STEM_NAMES == {
        "bombo": "kick",
        "redoblante": "snare",
        "platillos": "cymbals",
        "toms": "toms",
    }
    for english in ("kick", "snare"):
        assert english in DRUMS


# --- against the real model, when it happens to be installed ------------------------------

MODELS = Path(__file__).resolve().parents[3] / "models"


@pytest.mark.skipif(not available(MODELS), reason="DrumSep weights not installed")
def test_a_real_drum_loop_separates_into_the_right_drums(tmp_path):
    """End to end, with the actual weights. Skipped unless they are on this machine.

    Asserts the thing that makes the separation worth having rather than merely present:
    the kick stem is low and the cymbal stem is high. A model wired up wrongly - the
    Spanish names mapped in the wrong order, say - would still produce four files.
    """
    import soundfile as sf

    from app.services.drums.separate import separate
    from app.services.mastering.dsp import DEFAULT_HOP, DEFAULT_N_FFT, average_spectrum

    n = int(SR * 4.0)
    audio = np.zeros(n)
    rng = np.random.default_rng(5)
    for index in range(8):
        start = int((0.25 + index * 0.45) * SR)
        t = np.arange(int(0.25 * SR)) / SR
        audio[start : start + t.size] += (
            np.sin(2 * np.pi * (150 * np.exp(-22 * t) + 50) * t) * np.exp(-11 * t)
        )
        if index % 2:
            audio[start : start + t.size] += rng.normal(0, 1, t.size) * np.exp(-30 * t) * 0.5

    loop = tmp_path / "drums.wav"
    sf.write(str(loop), np.stack([audio, audio], axis=1), SR)

    stems = separate(loop, tmp_path / "out", MODELS)
    assert "kick" in stems, f"expected a kick stem, got {sorted(stems)}"

    def centroid(path: Path) -> float:
        from app.services.mixdown.encode import read_audio

        buffer = read_audio(path)
        spectrum = average_spectrum(buffer.samples, DEFAULT_N_FFT, DEFAULT_HOP)
        freqs = np.fft.rfftfreq(DEFAULT_N_FFT, d=1.0 / buffer.sample_rate)
        power = spectrum**2
        return float((freqs * power).sum() / max(power.sum(), 1e-20))

    assert centroid(stems["kick"]) < 400, "the kick stem should be low"
    if "cymbals" in stems:
        assert centroid(stems["cymbals"]) > centroid(stems["kick"])
