from __future__ import annotations

from pathlib import Path

import pytest

from app.services.audio.probe import (
    TARGET_CHANNELS,
    TARGET_SAMPLE_RATE,
    UnreadableAudioError,
    normalize,
    probe,
)
from tests.conftest import write_tone_wav


def test_probe_reads_duration_rate_and_channels(sample_wav: Path):
    info = probe(sample_wav)
    assert info.duration_s == pytest.approx(8.0, abs=0.05)
    assert info.sample_rate == 44100
    assert info.channels == 2
    assert info.backend == "soundfile"


def test_probe_rejects_a_file_that_is_not_audio(tmp_path: Path):
    fake = tmp_path / "fake.wav"
    fake.write_bytes(b"this is not a RIFF header")
    with pytest.raises(UnreadableAudioError):
        probe(fake)


def test_off_spec_audio_reports_that_it_needs_normalising(mono_22k_wav: Path):
    info = probe(mono_22k_wav)
    assert info.sample_rate == 22050
    assert info.channels == 1
    assert info.needs_normalising


def test_normalize_upsamples_and_makes_stereo(mono_22k_wav: Path, tmp_path: Path):
    out = tmp_path / "normalized.wav"
    result = normalize(mono_22k_wav, out)

    assert out.exists()
    assert result.sample_rate == TARGET_SAMPLE_RATE
    assert result.channels == TARGET_CHANNELS
    assert not result.needs_normalising
    # Resampling must preserve the timeline, not stretch it.
    assert result.duration_s == pytest.approx(probe(mono_22k_wav).duration_s, abs=0.02)


def test_normalize_leaves_conforming_audio_at_the_same_length(
    sample_wav: Path, tmp_path: Path
):
    result = normalize(sample_wav, tmp_path / "out.wav")
    assert result.duration_s == pytest.approx(8.0, abs=0.05)
    assert result.sample_rate == TARGET_SAMPLE_RATE


def test_normalize_downmixes_surround_to_stereo(tmp_path: Path):
    source = write_tone_wav(tmp_path / "quad.wav", seconds=6.0, channels=4)
    result = normalize(source, tmp_path / "quad-normalized.wav")
    assert result.channels == TARGET_CHANNELS


def test_normalized_output_does_not_clip(mono_22k_wav: Path, tmp_path: Path):
    import soundfile as sf

    out = tmp_path / "normalized.wav"
    normalize(mono_22k_wav, out)
    samples, _ = sf.read(str(out), dtype="float32", always_2d=True)
    assert abs(samples).max() <= 1.0
