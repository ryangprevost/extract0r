"""What the exported WAV is written as. X0R-1414.

Ryan: *"is it possible to pick different bit encodings? 16, 32, etc to upscale the quality
of the mastered mp3?"*

**Not of the MP3, and that is the first thing these pin.** LAME takes 16-bit PCM;
`lameenc.Encoder` has `set_bit_rate` in kbps and no setter for sample depth at all. So the
16-bit quantisation before encoding is not a hard-coded choice somebody forgot to expose -
it is the encoder's input format, and a control for it would be a dial wired to nothing.
`MasterResult.quantisation` saying "the user cannot choose it" is literally true.

What was real was the WAV, hard-coded to `PCM_24` since it was written, with the choice
never discussed. That is what moved.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.services.mixdown.encode import (
    DEFAULT_WAV_SUBTYPE,
    WAV_SUBTYPES,
    write_wav,
)

SR = 44100


def tone(seconds: float = 0.5) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return 0.4 * np.sin(2 * np.pi * 220.0 * t)


# --- the MP3 has no bit depth to choose -------------------------------------------------


def test_lame_has_no_bit_depth_setter():
    """The reason this card could not do what it was asked, as an assertion.

    If a future lameenc grows one, this fails and somebody gets to revisit the question
    instead of taking the docstring's word for it years later.
    """
    lameenc = pytest.importorskip("lameenc")
    setters = {name for name in dir(lameenc.Encoder()) if name.startswith("set_")}
    # set_bit_rate is kilobits per second, not bits per sample.
    assert not {s for s in setters if "depth" in s or "sample_size" in s or "bits" in s}


# --- the WAV does -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "depth,expected",
    [("16", "PCM_16"), ("24", "PCM_24"), ("32f", "FLOAT")],
)
def test_each_depth_writes_that_file(tmp_path: Path, depth: str, expected: str):
    path = write_wav(tmp_path / f"{depth}.wav", tone(), SR, depth)
    assert sf.info(str(path)).subtype == expected


def test_the_default_is_what_it_always_was(tmp_path: Path):
    """24-bit, so every existing caller and every saved expectation is unchanged."""
    assert DEFAULT_WAV_SUBTYPE == "24"
    assert WAV_SUBTYPES[DEFAULT_WAV_SUBTYPE] == "PCM_24"
    path = write_wav(tmp_path / "default.wav", tone(), SR)
    assert sf.info(str(path)).subtype == "PCM_24"


def test_an_unknown_depth_falls_back_rather_than_raising(tmp_path: Path):
    """A bad value should cost a sensible file, not a failed export at the last step of
    a render that took minutes."""
    path = write_wav(tmp_path / "odd.wav", tone(), SR, "nonsense")
    assert sf.info(str(path)).subtype == "PCM_24"


def test_a_deeper_file_is_a_bigger_file(tmp_path: Path):
    """The cheapest possible check that the subtype reached the encoder."""
    sizes = {
        depth: write_wav(tmp_path / f"{depth}.wav", tone(), SR, depth).stat().st_size
        for depth in ("16", "24", "32f")
    }
    assert sizes["16"] < sizes["24"] < sizes["32f"]


def test_the_audio_survives_a_round_trip_at_every_depth(tmp_path: Path):
    """A depth that silently mangled the signal would be worse than not offering it."""
    original = tone()
    for depth in WAV_SUBTYPES:
        path = write_wav(tmp_path / f"rt-{depth}.wav", original, SR, depth)
        back, rate = sf.read(str(path))
        assert rate == SR
        # 16-bit quantisation is the loosest of the three, so one tolerance covers all.
        assert np.abs(back[:, 0] - original).max() < 1e-3, depth


def test_float_keeps_what_integers_cannot(tmp_path: Path):
    """The only honest reason to pick 32-bit float: samples over 0 dBFS survive.

    Not "better" in any audible sense at a sane level - it matters to a mix going back
    into another tool and not at all to a finished file.
    """
    # 1.5 x a 0.4-peak tone is 0.6, which clips nothing - the first version of this
    # fixture tested nothing at all. Scaled to an actual peak of 1.5 instead.
    hot = tone() * (1.5 / 0.4)
    clipped = sf.read(str(write_wav(tmp_path / "hot24.wav", hot, SR, "24")))[0]
    kept = sf.read(str(write_wav(tmp_path / "hot32.wav", hot, SR, "32f")))[0]

    assert clipped.max() <= 1.0 + 1e-6, "integers should clip"
    assert kept.max() > 1.2, "float should not"


# --- through the pipeline ------------------------------------------------------------------


def test_the_request_carries_it_to_the_export(tmp_path: Path):
    from app.domain.notes import StemKind
    from app.services.mastering import pipeline as master
    from app.services.mastering.pipeline import MasterRequest, StemSetting

    stem = tmp_path / "bass.wav"
    sf.write(str(stem), np.stack([tone(2.0), tone(2.0)], axis=1), SR)

    result = master.run(
        MasterRequest(
            stems={StemKind.BASS: stem},
            settings=[StemSetting(StemKind.BASS)],
            export_wav=True,
            wav_depth="16",
        ),
        tmp_path / "work",
    )
    assert result.wav_path is not None
    assert sf.info(str(result.wav_path)).subtype == "PCM_16"


def test_the_mp3_is_the_same_whatever_the_wav_depth(tmp_path: Path):
    """Because it has to be. The two have nothing to do with each other, and a user who
    picked 32-bit expecting a better MP3 should at least not get a different one."""
    from app.domain.notes import StemKind
    from app.services.mastering import pipeline as master
    from app.services.mastering.pipeline import MasterRequest, StemSetting

    stem = tmp_path / "bass.wav"
    sf.write(str(stem), np.stack([tone(2.0), tone(2.0)], axis=1), SR)

    sizes = []
    for depth in ("16", "32f"):
        result = master.run(
            MasterRequest(
                stems={StemKind.BASS: stem},
                settings=[StemSetting(StemKind.BASS)],
                export_wav=True,
                wav_depth=depth,
            ),
            tmp_path / f"work-{depth}",
        )
        sizes.append(result.mp3_path.stat().st_size)
        assert result.quantisation == "16-bit with TPDF dither and noise shaping"

    # Dither is random per render, so the bytes differ; the length must not.
    assert abs(sizes[0] - sizes[1]) < 2048
