"""Playing a part on something else, through the API. X0R-1327, X0R-503.

The measurement that justifies this route is in `synth/voice.py` and on the card: through
demucs and basic-pitch, recall is 1.000 and pitch accuracy matches a clean DI, while
precision is 0.462 before cleaning and 0.727 after. The notes are right and there are too
many of them, which is why `clean` exists and why it defaults on here and stays off on the
tab path.

These cover the exposure rather than the measurement - that a stem can be re-voiced, that
the result can be fetched back, and that the one URL this adds cannot be used to read
something it should not.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

ATTESTED = {"owns_or_licensed": "true", "personal_use_only": "true"}


@pytest.fixture
def track(client, sample_wav: Path) -> str:
    with sample_wav.open("rb") as handle:
        response = client.post(
            "/api/v1/tracks",
            files={"file": ("song.wav", handle, "audio/wav")},
            data=ATTESTED,
        )
    assert response.status_code == 201, response.text
    return response.json()["track_id"]


@pytest.fixture
def separated(client, track: str) -> str:
    started = client.post(f"/api/v1/tracks/{track}/separate")
    assert started.status_code in (200, 202), started.text
    assert finish(client, started.json()["job_id"])["state"] == "succeeded"
    return track


def finish(client, job_id: str, timeout_s: float = 240.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body["state"] in ("succeeded", "failed"):
            return body
        time.sleep(0.2)
    raise AssertionError("job never finished")


# --- the vocabulary ----------------------------------------------------------------------


def test_the_voices_are_listed_with_something_to_choose_between(client):
    body = client.get("/api/v1/tracks/voices").json()

    assert {v["id"] for v in body["voices"]} == {"supersaw", "subbass", "epiano"}
    assert all(v["about"] for v in body["voices"]), "a picker needs more than three nouns"


# --- re-voicing --------------------------------------------------------------------------


def test_an_unknown_voice_is_refused_rather_than_silently_defaulted(client, separated):
    answer = client.post(f"/api/v1/tracks/{separated}/revoice?stem=bass&voice=hammond")

    assert answer.status_code == 400
    assert "hammond" in answer.json()["detail"]


def test_revoicing_before_separating_says_which_step_is_missing(client, track):
    answer = client.post(f"/api/v1/tracks/{track}/revoice?stem=bass&voice=subbass")

    assert answer.status_code == 409
    assert "separate" in answer.json()["detail"].lower()


def test_an_unknown_track_is_a_404(client):
    answer = client.post("/api/v1/tracks/" + "f" * 32 + "/revoice?stem=bass&voice=subbass")
    assert answer.status_code == 404


@pytest.mark.ml
def test_a_stem_comes_back_as_a_playable_render(client, separated):
    started = client.post(f"/api/v1/tracks/{separated}/revoice?stem=bass&voice=subbass")
    result = finish(client, started.json()["job_id"])["result"]

    if not result.get("notes"):
        pytest.skip(result.get("why", "nothing pitched in the fixture"))

    assert result["voice"] == "subbass"
    assert result["url"].endswith("bass.subbass.wav")

    fetched = client.get(result["url"])
    assert fetched.status_code == 200
    assert fetched.headers["content-type"].startswith("audio/")


@pytest.mark.ml
def test_the_count_of_merged_fragments_is_reported(client, separated):
    """Nobody can hear a precision figure. The number of pieces put back together is the
    one thing on screen that says how much repair happened."""
    started = client.post(f"/api/v1/tracks/{separated}/revoice?stem=bass&voice=subbass")
    result = finish(client, started.json()["job_id"])["result"]

    if not result.get("notes"):
        pytest.skip("nothing pitched in the fixture")
    assert result["fragments_merged"] == result["notes_before_cleaning"] - result["notes"]
    assert result["fragments_merged"] >= 0


# --- the new URL cannot read anything it should not --------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../../../../etc/passwd",
        "..%2Fmaster.mp3",
        "master.mp3",
        "bass.supersaw.mp3",
        "bass.hammond.wav",
        "notastem.supersaw.wav",
    ],
)
def test_the_render_url_refuses_anything_that_is_not_a_render(client, separated, name):
    """This directory also holds the user's masters, so the name is rebuilt from a known
    stem and a known voice rather than taken as given."""
    assert client.get(f"/api/v1/tracks/{separated}/revoiced/{name}").status_code in (404, 400)


def test_a_render_that_was_never_made_is_a_404(client, separated):
    answer = client.get(f"/api/v1/tracks/{separated}/revoiced/piano.epiano.wav")
    assert answer.status_code == 404


# --- MIDI --------------------------------------------------------------------------------


def test_midi_before_separating_says_so(client, track):
    answer = client.get(f"/api/v1/tracks/{track}/midi")
    assert answer.status_code == 409


@pytest.mark.ml
def test_midi_comes_back_as_a_file_a_daw_would_open(client, separated):
    answer = client.get(f"/api/v1/tracks/{separated}/midi")
    if answer.status_code == 409:
        pytest.skip("nothing pitched in the fixture")

    assert answer.status_code == 200
    assert answer.content[:4] == b"MThd"
    assert "attachment" in answer.headers["content-disposition"]
