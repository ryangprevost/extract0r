from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from app.api import deps
from app.config import Settings, get_settings


def write_silent_wav(path: Path, seconds: float = 1.0, sample_rate: int = 44100) -> Path:
    """A tiny real WAV file, so upload/format checks exercise the same code path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(struct.pack("<h", 0) * int(sample_rate * seconds))
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
    return write_silent_wav(tmp_path / "sample.wav")
