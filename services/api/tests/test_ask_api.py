"""The chat box through the API, which is the only way the page will ever reach it.

`test_ask` proves the parsing. This proves the three things a unit test cannot: that the
route is where the page calls it, that it refuses an unknown track rather than guessing,
and that the JSON carries the keys the page reads - `to` above all, because the page sets
that value directly and a response without it would move every fader to `undefined`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ATTESTED = {"owns_or_licensed": "true", "personal_use_only": "true"}

LANES = {
    stem: {"gain_db": 0.0, "width": 1.0, "compress_db": 0.0}
    for stem in ("vocals", "bass", "drums", "guitar", "piano", "other")
}


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
def track(client, sample_wav: Path) -> str:
    return _upload(client, sample_wav)


def test_a_sentence_comes_back_as_control_values(client, track):
    response = client.post(
        f"/api/v1/tracks/{track}/ask",
        json={"text": "a little bassier", "lanes": LANES},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["understood"] is True
    assert body["changes"]
    change = body["changes"][0]
    # Every key the page reads. `to` is the one it writes straight onto a fader.
    assert set(change) == {"control", "stem", "delta", "to", "clamped"}
    assert change["stem"] == "bass"
    assert change["to"] == pytest.approx(0.5)


def test_an_unknown_track_is_a_404_not_a_guess(client):
    response = client.post(
        "/api/v1/tracks/not-a-track/ask", json={"text": "more bass", "lanes": LANES}
    )
    assert response.status_code == 404


def test_what_it_cannot_do_is_a_200_with_no_changes(client, track):
    """Not understanding is an answer, not an error - the reply is the useful part."""
    response = client.post(
        f"/api/v1/tracks/{track}/ask",
        json={"text": "make it sound professional", "lanes": LANES},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["understood"] is False
    assert body["changes"] == []
    assert "reference" in body["reply"]


def test_the_comparison_is_carried_on_the_request(client, track):
    """It is not recomputed here: producing it costs about half the song's length."""
    response = client.post(
        f"/api/v1/tracks/{track}/ask",
        json={
            "text": "more bass",
            "lanes": LANES,
            "comparison": {
                "reference_name": "Reference Song",
                "instruments": [
                    {
                        "stem": "bass",
                        "label": "bass",
                        "moves": [{"control": "gain_db", "measured": -1.8, "band": ""}],
                    }
                ],
            },
        },
    )
    assert "1.8 dB over Reference Song's" in response.json()["reply"]


def test_an_over_long_message_is_refused_rather_than_parsed(client, track):
    response = client.post(
        f"/api/v1/tracks/{track}/ask", json={"text": "bass " * 200, "lanes": LANES}
    )
    assert response.status_code == 422


def test_the_vocabulary_is_published(client):
    """The page shows this instead of guessing at the edges of the parser."""
    body = client.get("/api/v1/tracks/ask/vocabulary").json()
    assert body["examples"]
    assert {p["label"] for p in body["parts"]} >= {"bass", "vocal", "drums", "guitars"}
    assert {t["label"] for t in body["tone"]} >= {"weight", "body", "presence", "air"}
    assert "pop" in body["qualities"]
    # Split by what the word is, not by whether it is scoped to a stem: "pump" is
    # bass-only and is still not a part, and the help text listed it as one.
    assert "pump" not in {p["label"] for p in body["parts"]}
    assert "pump" in {t["label"] for t in body["tone"]}
