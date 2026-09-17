from __future__ import annotations

import time
from pathlib import Path

import pytest

ATTESTED = {"owns_or_licensed": "true", "personal_use_only": "true"}


def upload(client, sample_wav: Path, **overrides):
    data = {**ATTESTED, **overrides}
    with sample_wav.open("rb") as handle:
        return client.post(
            "/api/v1/tracks",
            files={"file": ("song.wav", handle, "audio/wav")},
            data=data,
        )


def wait_for(client, job_id: str, timeout_s: float = 20.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body["state"] in ("succeeded", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout_s}s")


def test_health_reports_ok(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"


def test_legal_endpoint_serves_the_notices(client):
    body = client.get("/api/v1/legal").json()
    assert body["terms_version"]
    assert "copyright" in body["copyright_notice"].lower()
    assert body["retention_hours"] > 0


def test_upload_requires_the_rights_attestation(client, sample_wav):
    response = upload(client, sample_wav, owns_or_licensed="false")
    assert response.status_code == 403
    assert "rights" in response.json()["detail"].lower()


def test_upload_rejects_a_track_that_is_too_short(client, short_wav):
    response = upload(client, short_wav)
    assert response.status_code == 422
    assert "accepts" in response.json()["detail"]


def test_upload_rejects_a_file_that_only_looks_like_audio(client, tmp_path):
    # Right extension, wrong contents - the probe is what catches this.
    impostor = tmp_path / "song.wav"
    impostor.write_bytes(b"definitely not a RIFF header, but the name says wav")
    with impostor.open("rb") as handle:
        response = client.post(
            "/api/v1/tracks",
            files={"file": ("song.wav", handle, "audio/wav")},
            data=ATTESTED,
        )
    assert response.status_code == 415


def test_rejected_upload_leaves_nothing_on_disk(client, short_wav):
    upload(client, short_wav)
    # A rejected track must not linger past the request that created it.
    assert not any(client.storage.root.iterdir())


def test_upload_returns_probed_audio_properties(client, sample_wav):
    body = upload(client, sample_wav).json()
    assert body["duration_s"] == pytest.approx(8.0, abs=0.05)
    assert body["sample_rate"] == 44100
    assert body["channels"] == 2


def test_separation_job_reports_increasing_progress(client, sample_wav):
    track_id = upload(client, sample_wav).json()["track_id"]
    job_id = client.post(f"/api/v1/tracks/{track_id}/separate").json()["job_id"]

    seen = []
    deadline = time.time() + 20
    while time.time() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        seen.append(body["progress"])
        if body["state"] in ("succeeded", "failed"):
            break
        time.sleep(0.02)

    assert seen == sorted(seen), "progress went backwards"
    assert seen[-1] == 1.0


def test_stems_listing_includes_duration(client, sample_wav):
    track_id = upload(client, sample_wav).json()["track_id"]
    wait_for(client, client.post(f"/api/v1/tracks/{track_id}/separate").json()["job_id"])
    stems = client.get(f"/api/v1/tracks/{track_id}/stems").json()["stems"]
    assert all(s["duration_s"] == pytest.approx(8.0, abs=0.05) for s in stems)


def test_upload_rejects_unsupported_formats(client, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("not audio")
    with bad.open("rb") as handle:
        response = client.post(
            "/api/v1/tracks",
            files={"file": ("notes.txt", handle, "text/plain")},
            data=ATTESTED,
        )
    assert response.status_code == 415


def test_full_upload_separate_transcribe_flow(client, sample_wav):
    created = upload(client, sample_wav)
    assert created.status_code == 201
    track_id = created.json()["track_id"]

    separation = client.post(f"/api/v1/tracks/{track_id}/separate")
    assert separation.status_code == 202
    assert wait_for(client, separation.json()["job_id"])["state"] == "succeeded"

    stems = client.get(f"/api/v1/tracks/{track_id}/stems").json()
    assert {s["stem"] for s in stems["stems"]} >= {"drums", "bass"}

    transcription = client.post(
        f"/api/v1/tracks/{track_id}/transcribe",
        json={"stems": ["bass", "drums"], "tunings": {"bass": "bass_5"}},
    )
    assert transcription.status_code == 202
    job = wait_for(client, transcription.json()["job_id"])
    assert job["state"] == "succeeded", job.get("error")
    assert len(job["result"]["artifacts"]) == 2

    tab = client.get(f"/api/v1/tracks/{track_id}/tabs/bass")
    assert tab.status_code == 200
    assert "attachment" in tab.headers["content-disposition"]

    assert client.get(f"/api/v1/tracks/{track_id}/x0r").status_code == 200


def test_transcribe_before_separate_is_a_conflict(client, sample_wav):
    track_id = upload(client, sample_wav).json()["track_id"]
    response = client.post(
        f"/api/v1/tracks/{track_id}/transcribe", json={"stems": ["bass"]}
    )
    assert response.status_code == 409


def test_unknown_tuning_is_rejected(client, sample_wav):
    track_id = upload(client, sample_wav).json()["track_id"]
    wait_for(client, client.post(f"/api/v1/tracks/{track_id}/separate").json()["job_id"])
    response = client.post(
        f"/api/v1/tracks/{track_id}/transcribe",
        json={"stems": ["bass"], "tunings": {"bass": "sitar"}},
    )
    assert response.status_code == 422


def test_delete_removes_the_audio_from_disk(client, sample_wav):
    track_id = upload(client, sample_wav).json()["track_id"]
    storage = client.storage
    assert storage.track_dir(track_id).exists()

    assert client.delete(f"/api/v1/tracks/{track_id}").status_code == 204
    assert not storage.track_dir(track_id).exists()
    assert client.get(f"/api/v1/tracks/{track_id}/stems").status_code == 404


def test_tunings_reference_lists_guitar_and_bass(client):
    body = client.get("/api/v1/tracks/tunings").json()
    assert "guitar_standard" in body
    assert body["bass_standard"]["strings"] == 4


def test_timing_endpoint_reports_a_grid(client, sample_wav):
    track_id = upload(client, sample_wav).json()["track_id"]
    wait_for(client, client.post(f"/api/v1/tracks/{track_id}/separate").json()["job_id"])

    body = client.get(f"/api/v1/tracks/{track_id}/timing").json()
    assert body["tempo_bpm"] > 0
    assert body["beats_per_bar"] >= 2
    assert body["source"]


def test_transcription_honours_a_tempo_override(client, sample_wav):
    """The tab header must show the tempo the user asked for, not the detected one."""
    track_id = upload(client, sample_wav).json()["track_id"]
    wait_for(client, client.post(f"/api/v1/tracks/{track_id}/separate").json()["job_id"])

    job = client.post(
        f"/api/v1/tracks/{track_id}/transcribe",
        json={"stems": ["bass"], "tempo_bpm": 93.0, "beats_per_bar": 3},
    ).json()
    finished = wait_for(client, job["job_id"])
    assert finished["state"] == "succeeded", finished.get("error")

    assert finished["result"]["timing"]["tempo_bpm"] == 93.0
    assert finished["result"]["timing"]["beats_per_bar"] == 3

    tab = client.get(f"/api/v1/tracks/{track_id}/tabs/bass").text
    assert "93 BPM" in tab
    assert "3/4" in tab


def test_an_out_of_range_tempo_override_is_rejected(client, sample_wav):
    track_id = upload(client, sample_wav).json()["track_id"]
    wait_for(client, client.post(f"/api/v1/tracks/{track_id}/separate").json()["job_id"])

    response = client.post(
        f"/api/v1/tracks/{track_id}/transcribe",
        json={"stems": ["bass"], "tempo_bpm": 5000},
    )
    assert response.status_code == 422


def test_every_finishing_control_is_reachable_through_the_api():
    """A control that exists in Polish but has no request field is invisible: the page can
    send it, pydantic drops it, and the dial silently does nothing. That shipped once -
    the cohesion slider was wired end to end except for this, so it moved and changed
    nothing at all."""
    from app.api.routes_master import MasterJobRequest
    from app.services.mastering.polish import Polish

    # Polish field -> the request field that feeds it. Both names are listed on purpose:
    # they differ often enough that inferring the mapping would hide the very mistake
    # this is here to catch.
    wiring = {
        "air_db": "brightness_db",
        "air_hz": "brightness_from_hz",
        "warmth_db": "warmth_db",
        "bass_db": "bass_db",
        "width": "width",
        "width_profile": "width_profile",
        "sparkle_db": "sparkle_db",
        "centre_bass_hz": "centre_bass_hz",
        "centre_bass_amount": "centre_bass_amount",
        "subsonic_hz": "subsonic_hz",
        "ambience_mix": "ambience_mix",
        "ambience_s": "ambience_s",
        "headroom_db": "headroom_db",
        "protect_dynamics": "protect_dynamics",
    }
    request_fields = set(MasterJobRequest.model_fields)
    for polish_field, request_field in wiring.items():
        assert hasattr(Polish(), polish_field), f"Polish lost {polish_field}"
        assert request_field in request_fields, (
            f"Polish.{polish_field} has no way in: {request_field} is not a request field"
        )

    # And nothing in Polish was added without being listed here.
    known = set(wiring) | {"warmth_hz", "bass_hz", "width_floor_hz"}
    unmapped = {f for f in Polish.__dataclass_fields__ if f not in known}
    assert not unmapped, f"new Polish controls with no API wiring or exemption: {unmapped}"
