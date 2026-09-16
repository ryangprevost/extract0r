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
from tests.conftest import write_tone_m4a, write_tone_wav


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


# --- m4a / AAC ------------------------------------------------------------------------
#
# libsndfile has never read AAC. Until PyAV was added, an m4a passed the extension check
# on upload and then failed at decode on any machine without a system ffmpeg, so the
# upload form advertised a format the app could not actually ingest.

av = pytest.importorskip("av", reason="PyAV is what decodes m4a")


@pytest.fixture
def tone_m4a(tmp_path: Path) -> Path:
    return write_tone_m4a(tmp_path / "tone.m4a")


def test_libsndfile_still_cannot_read_aac(tone_m4a: Path):
    """The premise of the PyAV backend. If this ever fails, the fallback is redundant."""
    import soundfile as sf

    with pytest.raises(Exception):
        sf.info(str(tone_m4a))


def test_probe_reads_an_m4a_without_a_system_ffmpeg(tone_m4a: Path, monkeypatch):
    # Prove it is not quietly finding ffmpeg on this machine.
    monkeypatch.setattr("shutil.which", lambda _name: None)

    info = probe(tone_m4a)
    assert info.backend == "av"
    assert info.format == "AAC"
    assert info.sample_rate == 48000
    assert info.channels == 2
    assert info.duration_s == pytest.approx(2.0, abs=0.1)


def test_normalize_converts_an_m4a_to_canonical_wav(tone_m4a: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    result = normalize(tone_m4a, tmp_path / "out.wav")
    assert result.sample_rate == TARGET_SAMPLE_RATE
    assert result.channels == TARGET_CHANNELS
    assert not result.needs_normalising
    assert result.duration_s == pytest.approx(2.0, abs=0.1)


def test_normalizing_an_m4a_keeps_the_channels_apart(tone_m4a: Path, tmp_path: Path):
    """Each channel must still hold its own tone and not the other one.

    A planar buffer read as packed produces audio that is loud, stereo and the right
    length - and completely wrong. Only comparing the two channels catches it.
    """
    import numpy as np
    import soundfile as sf

    out = tmp_path / "out.wav"
    normalize(tone_m4a, out)
    samples, rate = sf.read(str(out), dtype="float64", always_2d=True)

    def energy_at(channel: int, hz: float) -> float:
        window = samples[rate // 4 : rate // 4 + rate, channel]
        spectrum = np.abs(np.fft.rfft(window * np.hanning(window.size))) ** 2
        freqs = np.fft.rfftfreq(window.size, 1 / rate)
        band = (freqs > hz - 25) & (freqs < hz + 25)
        return 10 * np.log10(spectrum[band].sum() / spectrum.sum())

    # Its own tone is essentially all of the channel; the other one is far below.
    assert energy_at(0, 440.0) > -1.0
    assert energy_at(1, 1000.0) > -1.0
    assert energy_at(0, 1000.0) < -40.0
    assert energy_at(1, 440.0) < -40.0


def test_normalizing_an_m4a_does_not_clip(tone_m4a: Path, tmp_path: Path):
    import soundfile as sf

    out = tmp_path / "out.wav"
    normalize(tone_m4a, out)
    samples, _ = sf.read(str(out), dtype="float32", always_2d=True)
    assert abs(samples).max() <= 1.0


def test_a_corrupt_m4a_is_rejected_rather_than_half_decoded(tmp_path: Path):
    broken = tmp_path / "broken.m4a"
    # A plausible MP4 header followed by nothing decodable.
    broken.write_bytes(bytes([0, 0, 0, 32]) + b"ftypM4A " + b"garbage" * 200)
    with pytest.raises(UnreadableAudioError):
        probe(broken)


def test_read_audio_opens_an_m4a_reference(tone_m4a: Path):
    """A reference is read by `read_audio`, not by `normalize`.

    That is a separate, soundfile-only path, so an m4a reference used to probe cleanly
    on upload and only fail later, when the master was rendered against it.
    """
    from app.services.mixdown.encode import read_audio

    buffer = read_audio(tone_m4a)
    assert buffer.sample_rate == 48000
    assert buffer.samples.shape[1] == 2
    assert abs(buffer.samples).max() > 0.1  # actual signal, not a silent decode
