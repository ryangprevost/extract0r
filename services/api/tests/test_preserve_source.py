"""Building the mix as a correction to the original instead of as a sum of the stems.

Separation is not lossless. Summing this project's six stems back up reproduces the track
only to within -25.6 dB, worst in the presence range - which is what a sizzle is: what the
separator could not put back, sitting where nothing masks it. Summing the processed stems
inherits all of it. Applying the difference to the original does not.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.domain.notes import StemKind
from app.services.mastering import pipeline as master
from app.services.mastering.pipeline import MasterRequest, StemSetting
from app.services.mixdown.encode import read_audio

SR = 44100


def write(path: Path, samples) -> Path:
    audio = np.asarray(samples, dtype="float32")
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    sf.write(str(path), audio, SR)
    return path


def tone(freq, seconds=3.0, amp=0.25):
    t = np.arange(int(seconds * SR)) / SR
    return amp * np.sin(2 * np.pi * freq * t)


@pytest.fixture
def imperfect(tmp_path):
    """Stems that do not quite add back up, plus the original they came from.

    The gap between them is the point: it stands in for everything a separator gets wrong.
    """
    d = tmp_path / "t"
    d.mkdir()
    rng = np.random.default_rng(0)

    parts = {
        StemKind.BASS: tone(80, amp=0.3),
        StemKind.DRUMS: tone(200, amp=0.25),
        StemKind.VOCALS: tone(900, amp=0.2),
    }
    # The original carries something the stems do not: the separation error.
    error = rng.normal(0, 0.01, parts[StemKind.BASS].size)
    original = sum(parts.values()) + error

    return (
        write(d / "source.wav", original),
        {kind: write(d / f"{kind.value}.wav", part) for kind, part in parts.items()},
    )


def run(source, stems, preserve, work, settings=None):
    return master.run(
        MasterRequest(
            stems=stems,
            settings=settings or [StemSetting(s) for s in stems],
            source=source,
            preserve_source=preserve,
            vocal_presence=None,
        ),
        work,
    )


def distance_db(a, b):
    n = min(len(a), len(b))
    return 10 * np.log10(
        float(((a[:n] - b[:n]) ** 2).mean() + 1e-20) / float((a[:n] ** 2).mean() + 1e-20)
    )


def test_with_nothing_changed_the_output_is_the_original(imperfect, tmp_path):
    """The property the whole thing rests on: the two sums cancel exactly."""
    source, stems = imperfect
    run(source, stems, True, tmp_path / "w")

    original = read_audio(source).samples
    mixed = read_audio(tmp_path / "w" / "mix.wav").samples
    assert distance_db(original, mixed) < -100


def test_summing_the_stems_does_not_give_the_original_back(imperfect, tmp_path):
    """The comparison that makes the first test mean something."""
    source, stems = imperfect
    run(source, stems, False, tmp_path / "w")

    original = read_audio(source).samples
    mixed = read_audio(tmp_path / "w" / "mix.wav").samples
    assert distance_db(original, mixed) > -60


def test_the_two_differ_by_exactly_what_separation_lost(imperfect, tmp_path):
    """Algebraically the renders differ by the reconstruction residual and nothing else,
    so the saving is the same whatever the settings."""
    source, stems = imperfect
    run(source, stems, True, tmp_path / "a")
    run(source, stems, False, tmp_path / "b")

    corrected = read_audio(tmp_path / "a" / "mix.wav").samples
    summed = read_audio(tmp_path / "b" / "mix.wav").samples

    original = read_audio(source).samples
    stacked = np.zeros_like(original)
    for path in stems.values():
        part = read_audio(path).samples
        n = min(len(stacked), len(part))
        stacked[:n] += part[:n]
    residual = original - stacked

    n = min(len(corrected), len(summed), len(residual))
    assert distance_db(residual[:n], (corrected - summed)[:n]) < -40


@pytest.mark.parametrize(
    "gains", [{}, {StemKind.VOCALS: 2.0}, {StemKind.VOCALS: 6.0, StemKind.BASS: -4.0}]
)
def test_the_saving_does_not_depend_on_the_settings(imperfect, tmp_path, gains):
    source, stems = imperfect
    settings = [StemSetting(s, gain_db=gains.get(s, 0.0)) for s in stems]
    run(source, stems, True, tmp_path / "a", settings)
    run(source, stems, False, tmp_path / "b", settings)

    corrected = read_audio(tmp_path / "a" / "mix.wav").samples
    summed = read_audio(tmp_path / "b" / "mix.wav").samples
    n = min(len(corrected), len(summed))
    gap = 10 * np.log10(float(((corrected[:n] - summed[:n]) ** 2).mean()) + 1e-20)
    assert -60 < gap < -20


def test_the_faders_still_do_what_they_say(imperfect, tmp_path):
    """Keeping the original underneath must not mean ignoring what was asked for."""
    source, stems = imperfect
    quiet = run(source, stems, True, tmp_path / "a")
    loud = run(
        source, stems, True, tmp_path / "b",
        [StemSetting(s, gain_db=6.0 if s is StemKind.VOCALS else 0.0) for s in stems],
    )
    assert quiet and loud
    a = read_audio(tmp_path / "a" / "mix.wav").samples
    b = read_audio(tmp_path / "b" / "mix.wav").samples
    assert float(np.abs(b).max()) > float(np.abs(a).max())


def test_muting_a_stem_removes_it_from_the_original(imperfect, tmp_path):
    """Subtracting one part leaves the others at the original's fidelity rather than at
    their own reconstruction's."""
    source, stems = imperfect
    settings = [StemSetting(s, muted=s is StemKind.VOCALS) for s in stems]
    run(source, stems, True, tmp_path / "w", settings)

    mixed = read_audio(tmp_path / "w" / "mix.wav").samples
    vocals = read_audio(stems[StemKind.VOCALS]).samples

    def band(x, low=800, high=1000):
        mono = x.mean(axis=1)
        spec = np.abs(np.fft.rfft(mono)) ** 2
        freqs = np.fft.rfftfreq(mono.size, 1 / SR)
        return 10 * np.log10(spec[(freqs >= low) & (freqs < high)].sum() + 1e-20)

    assert band(mixed) < band(vocals) - 20


def test_it_can_be_turned_off(imperfect, tmp_path):
    source, stems = imperfect
    run(source, stems, False, tmp_path / "w")
    original = read_audio(source).samples
    mixed = read_audio(tmp_path / "w" / "mix.wav").samples
    assert distance_db(original, mixed) > -60


def test_a_missing_original_falls_back_rather_than_failing(imperfect, tmp_path):
    source, stems = imperfect
    result = master.run(
        MasterRequest(
            stems=stems,
            settings=[StemSetting(s) for s in stems],
            source=tmp_path / "not-here.wav",
            preserve_source=True,
            vocal_presence=None,
        ),
        tmp_path / "w",
    )
    assert result.mp3_path.exists()
