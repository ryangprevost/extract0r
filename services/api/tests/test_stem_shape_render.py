"""The per-instrument moves have to reach the file.

Every other test in this area proves a number is carried from one object to another. This
one proves the audio is different, which is the only claim a user can hear. It exists
because the failure it guards against is silent and has happened before: a control wired
through the request model, the pipeline dataclass and the UI, and dropped at one line in
between, so the slider moved and the master did not change.

Rendered to WAV rather than MP3 so the assertions measure the mastering chain and not the
encoder.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.domain.notes import StemKind
from app.services.mastering import pipeline as master
from app.services.mastering.dsp import DEFAULT_HOP, DEFAULT_N_FFT, average_spectrum
from app.services.mastering.dynamics import dynamic_range_db
from app.services.mastering.instrument import band_levels
from app.services.mixdown.encode import read_audio

SR = 44100


def _broadband(path: Path, seconds: float = 6.0, seed: int = 3) -> Path:
    """One stem with content in every band, so a tone move has something to move."""
    from scipy.signal import butter, sosfilt

    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    white = rng.standard_normal((n, 2))
    sos = butter(1, 300 / (SR / 2), btype="low", output="sos")
    audio = sosfilt(sos, white, axis=0) * 4 + white * 0.2

    t = np.arange(n) / SR
    for hz in (80, 220, 900, 4500, 11000):
        audio[:, 0] += 0.15 * np.sin(2 * np.pi * hz * t)
        audio[:, 1] += 0.14 * np.sin(2 * np.pi * hz * t + 0.4)

    sf.write(str(path), audio / np.abs(audio).max() * 0.4, SR)
    return path


def _swinging(path: Path, seconds: float = 12.0) -> Path:
    """A stem with quiet and loud stretches, so there is range to compress."""
    t = np.arange(int(SR * seconds)) / SR
    level = np.where((t % 6.0) < 3.0, 0.12, 0.55)
    signal = level * (np.sin(2 * np.pi * 220 * t) + 0.4 * np.sin(2 * np.pi * 660 * t))
    sf.write(str(path), np.stack([signal, signal * 0.98], axis=1), SR)
    return path


def _render(tmp_path: Path, stems, settings, name: str) -> np.ndarray:
    """Run the chain and read the rendered audio back.

    `preserve_source` off and no reference, so nothing but the stem settings is moving -
    otherwise a difference could be the matching curve rather than the control under test.
    """
    result = master.run(
        master.MasterRequest(stems=stems, settings=settings, export_wav=True),
        tmp_path / name,
    )
    path = result.wav_path or result.mp3_path
    return read_audio(path).samples


def _bands(samples: np.ndarray) -> dict[str, float]:
    return band_levels(average_spectrum(samples, DEFAULT_N_FFT, DEFAULT_HOP), SR)


def _relative_move(before: dict, after: dict, band: str) -> float:
    """How far a band moved against the others - see `instrument.tone_curve`."""
    others = [after[key] - before[key] for key in before if key != band]
    return (after[band] - before[band]) - float(np.mean(others))


@pytest.fixture
def one_stem(tmp_path: Path):
    return {StemKind.GUITAR: _broadband(tmp_path / "guitar.wav")}


def test_a_tone_move_changes_the_rendered_band(tmp_path: Path, one_stem):
    """The whole point of the per-instrument screen: taking the air suggestion on one
    instrument has to put air in the file."""
    flat = _render(
        tmp_path, one_stem, [master.StemSetting(StemKind.GUITAR)], "flat",
    )
    lifted = _render(
        tmp_path,
        one_stem,
        [master.StemSetting(StemKind.GUITAR, tone_air_db=4.0)],
        "lifted",
    )

    # Around two thirds of the request, by design: the solve is damped so that
    # overlapping filters are not set against each other. See `instrument`.
    moved = _relative_move(_bands(flat), _bands(lifted), "air")
    assert moved > 1.8, f"asked for 4 dB of air and the render moved {moved:.2f}"


def test_a_tone_cut_moves_the_other_way(tmp_path: Path, one_stem):
    flat = _render(tmp_path, one_stem, [master.StemSetting(StemKind.GUITAR)], "flat2")
    cut = _render(
        tmp_path,
        one_stem,
        [master.StemSetting(StemKind.GUITAR, tone_low_db=-4.0)],
        "cut",
    )
    assert _relative_move(_bands(flat), _bands(cut), "low") < -2.0


def test_compression_narrows_the_rendered_range(tmp_path: Path):
    stems = {StemKind.GUITAR: _swinging(tmp_path / "swing.wav")}
    loose = _render(tmp_path, stems, [master.StemSetting(StemKind.GUITAR)], "loose")
    tight = _render(
        tmp_path, stems, [master.StemSetting(StemKind.GUITAR, compress_db=5.0)], "tight",
    )

    before = dynamic_range_db(loose, SR)
    after = dynamic_range_db(tight, SR)
    assert after < before - 2.0, f"range went {before:.1f} -> {after:.1f}"


def test_saturation_adds_harmonics_to_the_render(tmp_path: Path):
    """A pure tone in: anything at a multiple of it afterwards was made by the drive."""
    path = tmp_path / "tone.wav"
    t = np.arange(int(SR * 4)) / SR
    tone = 0.3 * np.sin(2 * np.pi * 300 * t)
    sf.write(str(path), np.stack([tone, tone], axis=1), SR)
    stems = {StemKind.GUITAR: path}

    def harmonics(samples: np.ndarray) -> float:
        mono = samples.mean(axis=1)
        spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) ** 2
        freqs = np.fft.rfftfreq(len(mono), 1 / SR)

        def at(hz: float) -> float:
            return float(spectrum[(freqs > hz - 15) & (freqs < hz + 15)].sum())

        return 10 * np.log10(sum(at(300 * n) for n in (2, 3, 4)) / (at(300) + 1e-20) + 1e-20)

    clean = _render(tmp_path, stems, [master.StemSetting(StemKind.GUITAR)], "clean")
    driven = _render(
        tmp_path, stems, [master.StemSetting(StemKind.GUITAR, saturation_db=2.0)], "driven",
    )
    assert harmonics(driven) > harmonics(clean) + 6.0


def test_leaving_every_per_instrument_control_alone_changes_nothing(tmp_path: Path, one_stem):
    """The default has to be a true no-op. A chain that slightly re-EQs everything even
    when every control reads zero is a chain nobody can reason about."""
    plain = _render(tmp_path, one_stem, [master.StemSetting(StemKind.GUITAR)], "plain")
    explicit = _render(
        tmp_path,
        one_stem,
        [
            master.StemSetting(
                StemKind.GUITAR,
                tone_low_db=0.0,
                tone_air_db=0.0,
                compress_db=0.0,
                saturation_db=0.0,
            )
        ],
        "explicit",
    )
    assert np.allclose(plain, explicit)


def test_two_stems_are_shaped_independently(tmp_path: Path):
    """The reason this is per instrument at all. Air on the drums must not become air on
    the bass - which is exactly what a master-bus shelf would do."""
    stems = {
        StemKind.DRUMS: _broadband(tmp_path / "drums.wav", seed=5),
        StemKind.BASS: _broadband(tmp_path / "bass.wav", seed=9),
    }
    settings_flat = [master.StemSetting(StemKind.DRUMS), master.StemSetting(StemKind.BASS)]
    settings_drums = [
        master.StemSetting(StemKind.DRUMS, tone_air_db=5.0),
        master.StemSetting(StemKind.BASS),
    ]

    flat = _render(tmp_path, stems, settings_flat, "pair-flat")
    shaped = _render(tmp_path, stems, settings_drums, "pair-drums")

    # The mix as a whole gains air, because one of its two stems did.
    assert _relative_move(_bands(flat), _bands(shaped), "air") > 0.8

    # And the bass stem alone, rendered on its own, is untouched by a drums setting.
    bass_only = {StemKind.BASS: stems[StemKind.BASS]}
    before = _render(tmp_path, bass_only, [master.StemSetting(StemKind.BASS)], "bass-a")
    after = _render(tmp_path, bass_only, [master.StemSetting(StemKind.BASS)], "bass-b")
    assert np.allclose(before, after)
