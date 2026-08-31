from __future__ import annotations

import time
from pathlib import Path

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
