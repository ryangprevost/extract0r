from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from app.api import deps
from app.config import Settings, get_settings

# Long enough to clear Settings.min_duration_s, short enough that tests stay fast.
DEFAULT_TEST_SECONDS = 8.0


def write_tone_wav(
    path: Path,
    seconds: float = DEFAULT_TEST_SECONDS,
    sample_rate: int = 44100,
    channels: int = 2,
    frequency: float = 220.0,
) -> Path:
    """A real WAV with actual signal in it.

    Silence would pass the probe but is useless the moment a test touches a real
    analysis backend, so the fixture generates a tone instead.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for index in range(int(sample_rate * seconds)):
        value = int(16000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        frames += struct.pack("<h", value) * channels

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))
    return path


def write_tone_m4a(
    path: Path,
    seconds: float = 2.0,
    sample_rate: int = 48000,
    left_hz: float = 440.0,
    right_hz: float = 1000.0,
) -> Path:
    """A real AAC-in-MP4 file, with a different tone in each channel.

    The channels differ so that a decoder which mishandles planar-to-packed conversion
    is caught: that failure interleaves the two channels rather than degrading quality,
    so it is invisible to a mono fixture but obvious to this one.

    Written at 48 kHz because that is what phones and iTunes produce, which also
    exercises the resampling path.
    """
    import av
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    signal = np.stack(
        [0.5 * np.sin(2 * np.pi * left_hz * t), 0.5 * np.sin(2 * np.pi * right_hz * t)],
        axis=1,
    ).astype("float32")

    with av.open(str(path), "w") as container:
        stream = container.add_stream("aac", rate=sample_rate)
        stream.layout = "stereo"
        # "flt" is packed, so (frames, channels) reshapes straight to interleaved.
        frame = av.AudioFrame.from_ndarray(
            np.ascontiguousarray(signal.reshape(1, -1)), format="flt", layout="stereo"
        )
        frame.rate = sample_rate
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Isolated settings pointed at a temp storage root, with all backends stubbed."""
    return Settings(
        storage_dir=tmp_path / "storage",
        separation_backend="stub",
        transcription_backend="stub",
        drum_backend="stub",
        environment="test",
        # The sweep is exercised directly in tests; no timer needed in the app fixture.
        retention_sweep_minutes=0,
    )


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from app.jobs.store import JobStore
    from app.main import app
    from app.services.registry import TrackRegistry
    from app.services.storage import TrackStorage

    storage = TrackStorage(settings.storage_dir)
    registry = TrackRegistry()
    # max_workers=1 keeps job ordering deterministic under test.
    jobs = JobStore(max_workers=1)

    app.dependency_overrides[deps.get_config] = lambda: settings
    app.dependency_overrides[deps.get_storage] = lambda: storage
    app.dependency_overrides[deps.get_registry] = lambda: registry
    app.dependency_overrides[deps.get_jobs] = lambda: jobs
    monkeypatch.setattr(get_settings, "__wrapped__", lambda: settings, raising=False)

    with TestClient(app) as test_client:
        test_client.storage = storage  # type: ignore[attr-defined]
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_wav(tmp_path: Path) -> Path:
    return write_tone_wav(tmp_path / "sample.wav")


@pytest.fixture
def short_wav(tmp_path: Path) -> Path:
    """Below Settings.min_duration_s, for the ingest rejection path."""
    return write_tone_wav(tmp_path / "short.wav", seconds=1.0)


@pytest.fixture
def mono_22k_wav(tmp_path: Path) -> Path:
    """Deliberately off-spec, so normalisation has something to actually fix."""
    return write_tone_wav(tmp_path / "mono22k.wav", sample_rate=22050, channels=1)
