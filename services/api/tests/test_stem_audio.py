"""Tests for stem playback and waveform peaks.

These back the "is the tab wrong, or was the stem already wrong?" workflow, so the
behaviour that matters is: the bytes come back, seeking works, and the envelope actually
follows the audio.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.api.routes_audio import _parse_range

ATTESTED = {"owns_or_licensed": "true", "personal_use_only": "true"}


def upload_and_separate(client, wav: Path) -> str:
    with wav.open("rb") as handle:
        created = client.post(
            "/api/v1/tracks",
            files={"file": ("song.wav", handle, "audio/wav")},
            data=ATTESTED,
        )
    track_id = created.json()["track_id"]

    import time

    job_id = client.post(f"/api/v1/tracks/{track_id}/separate").json()["job_id"]
    deadline = time.time() + 20
    while time.time() < deadline:
        if client.get(f"/api/v1/jobs/{job_id}").json()["state"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    return track_id


# ──────────────────────────────── range parsing ────────────────────────────────


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        ("bytes=0-99", 1000, (0, 99)),
        ("bytes=100-", 1000, (100, 999)),
        ("bytes=-200", 1000, (800, 999)),
        ("bytes=0-99999", 1000, (0, 999)),   # clamped to the end of the file
        ("bytes=0-0", 1000, (0, 0)),         # a single byte is a legal probe
    ],
)
def test_parse_range_handles_the_forms_browsers_send(header, size, expected):
    assert _parse_range(header, size) == expected


@pytest.mark.parametrize(
    ("header", "size"),
    [
        ("items=0-99", 1000),   # wrong unit
        ("bytes=2000-3000", 1000),  # entirely past the end
        ("bytes=500-100", 1000),    # backwards
        ("bytes=abc-def", 1000),
        ("bytes=", 1000),
    ],
)
def test_parse_range_rejects_nonsense(header, size):
    assert _parse_range(header, size)[0] is None


# ──────────────────────────────── streaming ────────────────────────────────────


def test_stem_audio_streams_the_whole_file_by_default(client, sample_wav):
    track_id = upload_and_separate(client, sample_wav)
    response = client.get(f"/api/v1/tracks/{track_id}/stems/bass/audio")

    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"].startswith("audio/")
    assert len(response.content) > 0


def test_stem_audio_honours_a_range_request(client, sample_wav):
    """Seeking in an <audio> element depends entirely on this returning 206."""
    track_id = upload_and_separate(client, sample_wav)
    url = f"/api/v1/tracks/{track_id}/stems/bass/audio"

    full = client.get(url)
    total = len(full.content)

    partial = client.get(url, headers={"Range": "bytes=0-1023"})
    assert partial.status_code == 206
    assert len(partial.content) == 1024
    assert partial.headers["content-range"] == f"bytes 0-1023/{total}"
    assert partial.content == full.content[:1024]


def test_stem_audio_range_past_the_end_is_416(client, sample_wav):
    track_id = upload_and_separate(client, sample_wav)
    response = client.get(
        f"/api/v1/tracks/{track_id}/stems/bass/audio",
        headers={"Range": "bytes=999999999-"},
    )
    assert response.status_code == 416


def test_unknown_stem_is_404(client, sample_wav):
    track_id = upload_and_separate(client, sample_wav)
    assert client.get(f"/api/v1/tracks/{track_id}/stems/kazoo/audio").status_code == 404


def test_audio_before_separation_is_a_conflict(client, sample_wav):
    with sample_wav.open("rb") as handle:
        track_id = client.post(
            "/api/v1/tracks",
            files={"file": ("song.wav", handle, "audio/wav")},
            data=ATTESTED,
        ).json()["track_id"]

    assert client.get(f"/api/v1/tracks/{track_id}/stems/bass/audio").status_code == 409


# ──────────────────────────────── peaks ────────────────────────────────────────


def test_peaks_describe_the_waveform(client, sample_wav):
    track_id = upload_and_separate(client, sample_wav)
    body = client.get(f"/api/v1/tracks/{track_id}/stems/bass/peaks?buckets=200").json()

    assert body["buckets"] == 200
    assert len(body["peaks"]) == 200
    assert body["duration_s"] == pytest.approx(8.0, abs=0.05)
    assert body["sample_rate"] == 44100
    assert all(0.0 <= p <= 1.0 for p in body["peaks"]), "peaks must be normalised"
    # The fixture is a steady tone, so the envelope should be loud essentially throughout.
    assert not body["silent"]
    assert max(body["peaks"]) == pytest.approx(1.0)


def test_peaks_are_cached_between_requests(client, sample_wav):
    track_id = upload_and_separate(client, sample_wav)
    url = f"/api/v1/tracks/{track_id}/stems/bass/peaks?buckets=300"

    first = client.get(url).json()
    second = client.get(url).json()
    assert first == second

    cached = list(client.storage.stems_dir(track_id).glob("*.peaks300.json"))
    assert cached, "a peaks cache file should have been written"


def test_peaks_bucket_count_is_bounded(client, sample_wav):
    track_id = upload_and_separate(client, sample_wav)
    base = f"/api/v1/tracks/{track_id}/stems/bass/peaks"

    assert client.get(f"{base}?buckets=10").status_code == 422
    assert client.get(f"{base}?buckets=99999").status_code == 422


def test_silence_is_reported_rather_than_dividing_by_zero(client, tmp_path, monkeypatch):
    """An empty stem is a normal Demucs outcome - a song with no piano, say."""
    import numpy as np
    import soundfile as sf

    quiet = tmp_path / "quiet.wav"
    sf.write(str(quiet), np.zeros((44100 * 8, 2), dtype="float32"), 44100)

    track_id = upload_and_separate(client, quiet)
    body = client.get(f"/api/v1/tracks/{track_id}/stems/bass/peaks?buckets=100").json()

    assert body["silent"] is True
    assert set(body["peaks"]) == {0.0}
