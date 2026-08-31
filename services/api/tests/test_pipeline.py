from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.domain.notes import StemKind
from app.services import pipeline
from app.services.storage import TrackStorage


def upload(storage: TrackStorage, sample_wav: Path) -> str:
    stored = storage.save_upload("song.wav", sample_wav.read_bytes())
    return stored.track_id


def test_stub_separation_produces_four_stems(settings: Settings, sample_wav: Path):
    storage = TrackStorage(settings.storage_dir)
    track_id = upload(storage, sample_wav)
    result = pipeline.separate(track_id, storage, settings)
    assert {s.kind for s in result.stems} == {
        StemKind.DRUMS,
        StemKind.BASS,
        StemKind.VOCALS,
        StemKind.OTHER,
    }
    assert all(s.path.exists() for s in result.stems)


def test_transcribe_writes_a_txt_per_stem_and_one_x0r(settings: Settings, sample_wav: Path):
    storage = TrackStorage(settings.storage_dir)
    track_id = upload(storage, sample_wav)
    separation = pipeline.separate(track_id, storage, settings)

    bundle = pipeline.transcribe(
        track_id=track_id,
        stems=[StemKind.BASS, StemKind.DRUMS],
        storage=storage,
        settings=settings,
        separation=separation,
    )

    assert len(bundle.artifacts) == 2
    assert all(a.tab_path.exists() for a in bundle.artifacts)
    assert bundle.x0r_path.exists()

    bass = next(a for a in bundle.artifacts if a.stem is StemKind.BASS)
    assert bass.notation.value == "string_tab"
    assert bass.note_count > 0

    drums = next(a for a in bundle.artifacts if a.stem is StemKind.DRUMS)
    assert "BD|" in drums.tab_text


def test_x0r_document_carries_provenance_and_notice(settings: Settings, sample_wav: Path):
    storage = TrackStorage(settings.storage_dir)
    track_id = upload(storage, sample_wav)
    separation = pipeline.separate(track_id, storage, settings)
    bundle = pipeline.transcribe(
        track_id, [StemKind.BASS], storage, settings, separation
    )

    document = json.loads(bundle.x0r_path.read_text(encoding="utf-8"))
    assert document["format"] == "x0r"
    assert document["schema_version"]
    assert len(document["provenance"]["source_sha256"]) == 64
    assert "copyright" in document["notice"].lower()
    assert document["stems"][0]["tuning"]["name"].startswith("Bass")
    assert document["stems"][0]["notes"]


def test_stub_transcription_is_deterministic(settings: Settings, sample_wav: Path):
    storage = TrackStorage(settings.storage_dir)
    track_id = upload(storage, sample_wav)
    separation = pipeline.separate(track_id, storage, settings)

    first = pipeline.transcribe(track_id, [StemKind.BASS], storage, settings, separation)
    second = pipeline.transcribe(track_id, [StemKind.BASS], storage, settings, separation)
    assert first.artifacts[0].tab_text == second.artifacts[0].tab_text


def test_retention_purge_removes_old_tracks(settings: Settings, sample_wav: Path):
    import os
    import time

    storage = TrackStorage(settings.storage_dir)
    track_id = upload(storage, sample_wav)
    old = time.time() - 48 * 3600
    os.utime(storage.track_dir(track_id), (old, old))

    removed = storage.purge_expired(retention_hours=24)
    assert track_id in removed
    assert not storage.track_dir(track_id).exists()
