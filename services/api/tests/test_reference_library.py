"""Adopting a reference from a folder of music you already own.

The ranking side of this has existed for a while and was unreachable: it could tell you
which of your own records made the best target and there was no way to act on it short of
going and finding the file yourself.

Most of this file is about the path check. `from-library` takes a path from the browser,
which is an arbitrary file read wearing a library's name unless the server proves the path
really is inside the folder the operator configured. Traversal, absolute paths and symlinks
all get their own test, because they fail differently and a check that stops one can easily
miss the others.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from tests.conftest import write_tone_wav

ATTESTED = {"owns_or_licensed": "true", "personal_use_only": "true"}


def _upload(client, wav: Path) -> str:
    with wav.open("rb") as handle:
        response = client.post(
            "/api/v1/tracks",
            files={"file": ("song.wav", handle, "audio/wav")},
            data=ATTESTED,
        )
    assert response.status_code == 201, response.text
    return response.json()["track_id"]


@pytest.fixture
def library(tmp_path: Path, settings):
    """A configured library with one real recording in it."""
    root = tmp_path / "music"
    root.mkdir()
    write_tone_wav(root / "a-record-i-own.wav", frequency=180.0)
    settings.library_dir = root
    return root


# --- the status route ------------------------------------------------------------------


def test_an_unconfigured_library_says_so_rather_than_failing(client, sample_wav: Path):
    """The page needs to tell these apart before anyone waits on a scan: "nothing is
    configured" and "scanning two thousand files" are different screens."""
    track_id = _upload(client, sample_wav)
    body = client.get(f"/api/v1/tracks/{track_id}/reference/library").json()

    assert body["configured"] is False
    assert "EXTRACT0R_LIBRARY_DIR" in body["why"]


def test_a_configured_library_reports_where_it_is(client, sample_wav: Path, library: Path):
    track_id = _upload(client, sample_wav)
    body = client.get(f"/api/v1/tracks/{track_id}/reference/library").json()

    assert body["configured"] is True
    assert Path(body["path"]) == library


def test_a_library_pointed_at_a_missing_folder_is_not_configured(
    client, sample_wav: Path, settings, tmp_path: Path
):
    settings.library_dir = tmp_path / "nowhere"
    track_id = _upload(client, sample_wav)
    assert client.get(f"/api/v1/tracks/{track_id}/reference/library").json()["configured"] is False


# --- adopting a file -------------------------------------------------------------------


def test_a_library_track_can_become_the_reference(client, sample_wav: Path, library: Path):
    track_id = _upload(client, sample_wav)
    chosen = library / "a-record-i-own.wav"

    response = client.post(
        f"/api/v1/tracks/{track_id}/reference/from-library", json={"path": str(chosen)}
    )
    assert response.status_code == 201, response.text
    assert response.json()["filename"]
    assert response.json()["duration_s"] > 0

    # And it is really usable as a reference, not merely recorded as one.
    suggest = client.get(f"/api/v1/tracks/{track_id}/master/suggest").json()
    assert suggest["available"] is True


def test_the_adopted_file_is_measured_like_any_other_reference(
    client, sample_wav: Path, library: Path
):
    track_id = _upload(client, sample_wav)
    body = client.post(
        f"/api/v1/tracks/{track_id}/reference/from-library",
        json={"path": str(library / "a-record-i-own.wav")},
    ).json()
    assert body["integrated_lufs"] is not None


# --- the path check --------------------------------------------------------------------


def test_a_path_outside_the_library_is_refused(client, sample_wav: Path, library: Path,
                                               tmp_path: Path):
    """The plain case: an absolute path somewhere else entirely."""
    outside = tmp_path / "not-in-the-library.wav"
    write_tone_wav(outside)
    track_id = _upload(client, sample_wav)

    response = client.post(
        f"/api/v1/tracks/{track_id}/reference/from-library", json={"path": str(outside)}
    )
    assert response.status_code == 403
    assert "outside" in response.json()["detail"]


def test_traversal_out_of_the_library_is_refused(client, sample_wav: Path, library: Path,
                                                 tmp_path: Path):
    """`library/../secret.wav` points at something that only *looks* like it is inside.
    Resolving both sides before comparing is what catches it."""
    secret = tmp_path / "secret.wav"
    write_tone_wav(secret)
    track_id = _upload(client, sample_wav)

    response = client.post(
        f"/api/v1/tracks/{track_id}/reference/from-library",
        json={"path": str(library / ".." / "secret.wav")},
    )
    assert response.status_code == 403


def test_a_symlink_pointing_out_of_the_library_is_refused(
    client, sample_wav: Path, library: Path, tmp_path: Path
):
    """A link inside the folder, resolving outside it, with nothing suspicious in the
    path text at all. This is the one a string-prefix check would wave through."""
    secret = tmp_path / "private.wav"
    write_tone_wav(secret)
    link = library / "looks-innocent.wav"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("this platform will not create symlinks without elevation")

    track_id = _upload(client, sample_wav)
    response = client.post(
        f"/api/v1/tracks/{track_id}/reference/from-library", json={"path": str(link)}
    )
    assert response.status_code == 403


def test_a_directory_is_not_a_reference(client, sample_wav: Path, library: Path):
    inner = library / "an album"
    inner.mkdir()
    track_id = _upload(client, sample_wav)

    response = client.post(
        f"/api/v1/tracks/{track_id}/reference/from-library", json={"path": str(inner)}
    )
    assert response.status_code == 403


def test_a_file_that_is_not_there_is_a_404(client, sample_wav: Path, library: Path):
    track_id = _upload(client, sample_wav)
    response = client.post(
        f"/api/v1/tracks/{track_id}/reference/from-library",
        json={"path": str(library / "imaginary.wav")},
    )
    assert response.status_code == 404


def test_adopting_without_a_library_configured_is_refused(client, sample_wav: Path,
                                                          tmp_path: Path):
    """No library means no path is inside one, whatever the browser sends."""
    stray = tmp_path / "stray.wav"
    write_tone_wav(stray)
    track_id = _upload(client, sample_wav)

    response = client.post(
        f"/api/v1/tracks/{track_id}/reference/from-library", json={"path": str(stray)}
    )
    assert response.status_code == 409


def test_something_that_is_not_audio_is_rejected(client, sample_wav: Path, library: Path):
    """The library is a folder of files, not a folder of guaranteed recordings."""
    (library / "sleeve-notes.txt").write_text("not audio", encoding="utf-8")
    track_id = _upload(client, sample_wav)

    response = client.post(
        f"/api/v1/tracks/{track_id}/reference/from-library",
        json={"path": str(library / "sleeve-notes.txt")},
    )
    assert response.status_code in (415, 422)


def test_the_streaming_refusal_still_applies_to_urls(client, sample_wav: Path):
    """The library route exists precisely because the streaming ones do not. This pins
    that the URL fetcher has not quietly grown a YouTube path alongside it."""
    from app.services.fetch import STREAMING_HOSTS

    assert "youtube.com" in STREAMING_HOSTS
    assert "open.spotify.com" in STREAMING_HOSTS

    track_id = _upload(client, sample_wav)
    response = client.post(
        f"/api/v1/tracks/{track_id}/reference/url",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
              "owns_or_licensed": True},
    )
    assert response.status_code == 422
