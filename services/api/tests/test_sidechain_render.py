"""The duck as it reaches the export, which is the only place it is heard.

`test_sidechain` proves the envelope and the calibration. These prove the two things that
are only true once the pipeline is involved: that a control at rest changes nothing at all,
and that a control that is not at rest changes the bass and nothing else.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.domain.notes import StemKind
from app.services.mastering import pipeline as master
from app.services.mastering.pipeline import MasterRequest, StemSetting

SR = 44100
SECONDS = 4.0


def write(path: Path, wave: np.ndarray) -> Path:
    sf.write(str(path), np.stack([wave, wave], axis=1), SR)
    return path


@pytest.fixture
def stems(tmp_path: Path) -> dict[StemKind, Path]:
    """A held bass and a kick on every beat, which is the arrangement this is for."""
    t = np.arange(int(SECONDS * SR)) / SR
    bass = 0.3 * np.sin(2 * np.pi * 55.0 * t)

    drums = np.zeros_like(t)
    thump = np.exp(-np.arange(int(SR * 0.12)) / (SR * 0.02))
    beat = int(SR * 0.5)
    for start in range(0, len(drums) - len(thump), beat):
        drums[start : start + len(thump)] += thump * np.sin(
            2 * np.pi * 60.0 * np.arange(len(thump)) / SR
        )

    return {
        StemKind.BASS: write(tmp_path / "bass.wav", bass),
        StemKind.DRUMS: write(tmp_path / "drums.wav", 0.5 * drums),
    }


def render(stems, tmp_path: Path, sidechain_db: float, work: str):
    settings = [
        StemSetting(
            stem,
            sidechain_db=sidechain_db if stem is StemKind.BASS else 0.0,
        )
        for stem in stems
    ]
    return master.run(
        MasterRequest(stems=stems, settings=settings), tmp_path / work
    )


def read(path: Path) -> np.ndarray:
    data, _ = sf.read(str(path))
    return np.asarray(data, dtype=np.float64)


def test_a_duck_at_rest_is_lost_in_the_noise_a_real_one_is_not(stems, tmp_path):
    """The null case, measured against this pipeline's own floor rather than against zero.

    Exactness is asserted where it can be - `test_sidechain` checks that `apply` with no
    depth returns the very same array. It cannot be asserted here, and the reason is worth
    recording: the export dithers, TPDF dither is random per render, and MP3 is lossy, so
    a difference of about 1e-8 at the input comes out as **8.5e-4** after the codec. Two
    byte-identical requests do not produce byte-identical files and never will.

    So this measures the floor instead of assuming one, and asks that a real duck clear it
    by a wide margin. A threshold typed in by hand would have been 1e-5, which is below
    the floor, and the test would have failed for a reason that has nothing to do with
    this feature.
    """
    floor = _difference(render(stems, tmp_path, 0.0, "a"), render(stems, tmp_path, 0.0, "b"))
    real = _difference(render(stems, tmp_path, 0.0, "flat"), render(stems, tmp_path, 4.0, "duck"))

    assert real > floor * 20, f"a 4 dB duck ({real:.4f}) is not clear of the floor ({floor:.4f})"


def _difference(one, other) -> float:
    a, b = read(one.mp3_path), read(other.mp3_path)
    length = min(len(a), len(b))
    return float(np.abs(a[:length] - b[:length]).max())


def notes_for(result, stem: StemKind) -> str:
    row = next((a for a in result.stem_adjustments if a.stem is stem), None)
    return " ".join(row.notes) if row else ""


def test_the_report_says_what_it_did_on_the_bass_row(stems, tmp_path):
    """A user who took the dial has to see in the export that it ran - and on the bass,
    because the kick only supplied the timing. The decision was the bass's."""
    result = render(stems, tmp_path, 4.0, "noted")
    assert "ducked 4.0 dB" in notes_for(result, StemKind.BASS)
    assert "ducked" not in notes_for(result, StemKind.DRUMS)


def test_no_kick_means_no_duck_and_no_crash(tmp_path):
    """A bass with no drums beside it. The duck has nothing to key to, so it does
    nothing - rather than refusing the whole master over an optional stage."""
    t = np.arange(int(SECONDS * SR)) / SR
    only_bass = {StemKind.BASS: write(tmp_path / "b.wav", 0.3 * np.sin(2 * np.pi * 55 * t))}
    result = master.run(
        MasterRequest(
            stems=only_bass,
            settings=[StemSetting(StemKind.BASS, sidechain_db=4.0)],
        ),
        tmp_path / "work",
    )
    assert result.mp3_path.exists()
    assert "ducked" not in notes_for(result, StemKind.BASS)


def test_the_duck_is_on_the_bass_and_not_the_drums(stems, tmp_path):
    """Set on a stem this does not measure, it is ignored rather than quietly applied."""
    settings = [
        StemSetting(stem, sidechain_db=6.0 if stem is StemKind.DRUMS else 0.0)
        for stem in stems
    ]
    result = master.run(
        MasterRequest(stems=stems, settings=settings), tmp_path / "work"
    )
    assert all("ducked" not in notes_for(result, stem) for stem in stems)
