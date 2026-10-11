"""A re-voiced part, in the rendered file. X0R-1328.

The whole of this card is one ordering question, and getting it wrong produces a render
that looks completely fine and contains none of the thing you asked for.

`_apply_as_correction` builds the output as ``original + (processed - untouched)``, so that
separation's own error cancels when nothing was changed. `untouched` therefore has to hold
the **recorded** stem: the difference then carries *the synth minus the guitar*, and the
guitar is cancelled out of the original. Substitute before that line and both sums contain
the synth, the difference is zero, and the render is the untouched original — the recorded
part still playing and no synth anywhere, with no error and nothing in the log.

The first version did exactly that, with a comment confidently asserting the opposite. These
tests exist so the next person to tidy the ordering finds out immediately.
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
SECONDS = 2.0

#: The recorded part and the replacement are pure tones, far apart, so "did the swap happen"
#: is answered by looking for energy at two frequencies rather than by a correlation.
RECORDED_HZ = 110.0
VOICED_HZ = 700.0


def tone(hz: float, level: float = 0.3) -> np.ndarray:
    t = np.arange(int(SECONDS * SR)) / SR
    return level * np.sin(2 * np.pi * hz * t)


def write(path: Path, wave: np.ndarray) -> Path:
    sf.write(str(path), np.stack([wave, wave], axis=1), SR)
    return path


def energy_at(samples: np.ndarray, hz: float) -> float:
    mono = samples.mean(axis=1) if samples.ndim > 1 else samples
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(mono.size)))
    freqs = np.fft.rfftfreq(mono.size, 1 / SR)
    band = (freqs > hz * 0.9) & (freqs < hz * 1.1)
    return float(spectrum[band].max())


@pytest.fixture
def parts(tmp_path: Path):
    """A guitar stem, a drums stem, the mixture they came from, and a replacement."""
    guitar = tone(RECORDED_HZ)
    drums = tone(300.0, 0.2)
    return {
        "stems": {
            StemKind.GUITAR: write(tmp_path / "guitar.wav", guitar),
            StemKind.DRUMS: write(tmp_path / "drums.wav", drums),
        },
        "source": write(tmp_path / "source.wav", guitar + drums),
        "voiced": write(tmp_path / "guitar.supersaw.wav", tone(VOICED_HZ)),
    }


def render(parts, tmp_path: Path, work: str, **kw) -> np.ndarray:
    """Render and read back the WAV.

    `export_wav`, not the MP3: these assertions compare energy at two frequencies and one
    of them checks two renders are bit-identical, and a lossy encode is the wrong instrument
    for either.
    """
    settings = [StemSetting(stem) for stem in parts["stems"]]
    result = master.run(
        MasterRequest(
            stems=parts["stems"],
            settings=settings,
            source=parts["source"],
            export_wav=True,
            wav_depth="32f",
            **kw,
        ),
        tmp_path / work,
    )
    assert result.wav_path is not None
    data, _ = sf.read(str(result.wav_path))
    return np.asarray(data, dtype=np.float64)


# --- the ordering bug, pinned ------------------------------------------------------------


def test_the_voiced_part_reaches_the_rendered_file(parts, tmp_path):
    """The test the first version would have failed, silently and with a clean log."""
    out = render(
        parts,
        tmp_path,
        "swapped",
        revoice={"guitar": "supersaw"},
        revoiced_audio={"guitar": parts["voiced"]},
    )

    assert energy_at(out, VOICED_HZ) > 0.05 * energy_at(out, 300.0), "the synth is not there"


def test_the_recorded_part_is_gone_from_the_rendered_file(parts, tmp_path):
    """Substitution, not layering. A guitar part played on a supersaw is not a guitar part
    with a supersaw on top of it - which is the one way this differs from `drum_kit`."""
    before = render(parts, tmp_path, "plain")
    after = render(
        parts,
        tmp_path,
        "swapped",
        revoice={"guitar": "supersaw"},
        revoiced_audio={"guitar": parts["voiced"]},
    )

    assert energy_at(after, RECORDED_HZ) < 0.25 * energy_at(before, RECORDED_HZ)


def test_the_other_stems_are_untouched(parts, tmp_path):
    """Re-voicing one part must not move anything else in the mix."""
    before = render(parts, tmp_path, "plain")
    after = render(
        parts,
        tmp_path,
        "swapped",
        revoice={"guitar": "supersaw"},
        revoiced_audio={"guitar": parts["voiced"]},
    )

    assert energy_at(after, 300.0) == pytest.approx(energy_at(before, 300.0), rel=0.2)


# --- and it stays off unless asked -------------------------------------------------------


def test_no_revoice_changes_nothing(parts, tmp_path):
    """The null case. An empty mapping must cost nothing and change nothing."""
    plain = render(parts, tmp_path, "a")
    empty = render(parts, tmp_path, "b", revoice={}, revoiced_audio={})

    length = min(len(plain), len(empty))
    assert np.allclose(plain[:length], empty[:length], atol=1e-9)


def test_naming_a_stem_without_a_render_leaves_it_as_recorded(parts, tmp_path):
    """A half-filled request must not silence a part. The render can be missing - retention
    deletes exports, and the job that made it may never have run."""
    out = render(
        parts,
        tmp_path,
        "missing",
        revoice={"guitar": "supersaw"},
        revoiced_audio={"guitar": Path(tmp_path / "not-here.wav")},
    )

    assert energy_at(out, RECORDED_HZ) > 0.0


def test_a_render_at_the_wrong_sample_rate_is_refused_rather_than_resampled(parts, tmp_path):
    """Pitch-shifting a part by playing it at the wrong rate is the worst available failure,
    and silently resampling here would hide which stage got it wrong."""
    odd = tmp_path / "odd.wav"
    sf.write(str(odd), np.stack([tone(VOICED_HZ), tone(VOICED_HZ)], axis=1), 22050)

    out = render(
        parts,
        tmp_path,
        "odd",
        revoice={"guitar": "supersaw"},
        revoiced_audio={"guitar": odd},
    )

    assert energy_at(out, RECORDED_HZ) > 0.0, "the recorded part should have been kept"
