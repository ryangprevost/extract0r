"""Combining profiles through the API, which is the only way the page reaches it.

`test_combined_profile` proves the merge and the rule. These prove the route is where the
page calls it, that it refuses a name it cannot find rather than guessing, and - the one
that matters most - that a profile which has nothing to lend is reported rather than
silently replaced by the base's own instrument.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.mastering.instrument import InstrumentProfile, snapshot
from app.services.mastering.profile import ReferenceProfile, save

ATTESTED = {"owns_or_licensed": "true", "personal_use_only": "true"}


def instrument(stem: str, level: float, band: float) -> dict:
    return snapshot(
        InstrumentProfile(
            stem=stem,
            relative_lufs=level,
            bands=dict.fromkeys(
                ("low", "low_mid", "high_mid", "presence", "air"), band
            ),
            dynamic_range_db=8.0,
            crest_db=10.0,
            present=True,
        )
    )


def written(directory: Path, name: str, **instruments) -> ReferenceProfile:
    made = ReferenceProfile(
        name=name,
        captured_from=name + ".wav",
        lufs=-9.0,
        curve_hz=[100.0, 1000.0],
        curve_db=[0.0, 0.0],
        instruments=instruments,
    )
    save(made, directory)
    return made


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
def profiles(settings) -> Path:
    directory = Path(settings.profile_dir)
    written(directory, "Pop punk", guitar=instrument("guitar", -4.0, 2.0))
    written(directory, "Dance", drums=instrument("drums", -3.0, -1.5),
            guitar=instrument("guitar", -14.0, 0.0))
    written(directory, "Whole mix only")
    return directory


def test_a_combination_can_be_aimed_at_without_saving(client, track, profiles):
    """Trying one out should not leave a file behind."""
    response = client.post(
        f"/api/v1/tracks/{track}/reference/combine-profiles",
        json={"base": "Dance", "instruments": {"guitar": "Pop punk"}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["base"] == "Dance"
    assert body["borrowed"] == {"guitar": "Pop punk"}
    assert body["saved"] is False
    assert not (profiles / "Dance---borrowed.json").exists()


def test_saving_keeps_it_under_its_own_name(client, track, profiles):
    response = client.post(
        f"/api/v1/tracks/{track}/reference/combine-profiles",
        json={
            "base": "Dance",
            "instruments": {"guitar": "Pop punk"},
            "save_as": "My blend",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["saved"] is True

    listed = client.get("/api/v1/tracks/reference/profiles").json()
    names = [p["name"] for p in listed.get("profiles", listed)]
    assert "My blend" in names


def test_a_profile_with_nothing_to_lend_is_reported_not_hidden(client, track, profiles):
    """Silently using the base's own instrument would look like the borrowing worked."""
    response = client.post(
        f"/api/v1/tracks/{track}/reference/combine-profiles",
        json={"base": "Dance", "instruments": {"guitar": "Whole mix only"}},
    )
    body = response.json()
    assert body["unavailable"] == ["guitar"]
    assert body["borrowed"] == {}


def test_an_unknown_profile_is_a_404(client, track, profiles):
    for payload in (
        {"base": "Nope", "instruments": {}},
        {"base": "Dance", "instruments": {"guitar": "Nope"}},
    ):
        response = client.post(
            f"/api/v1/tracks/{track}/reference/combine-profiles", json=payload
        )
        assert response.status_code == 404, payload


def test_asking_for_the_base_s_own_instrument_is_not_borrowing(client, track, profiles):
    """It is the default, not an error, and it must not be marked as borrowed - which
    would drop a level that is perfectly comparable."""
    response = client.post(
        f"/api/v1/tracks/{track}/reference/combine-profiles",
        json={"base": "Dance", "instruments": {"guitar": "Dance"}},
    )
    assert response.json()["borrowed"] == {}


def test_the_response_explains_what_a_borrowed_instrument_does_not_bring(
    client, track, profiles
):
    """The rule is the feature. A response that did not state it would leave somebody to
    discover the missing level by noticing its absence."""
    response = client.post(
        f"/api/v1/tracks/{track}/reference/combine-profiles",
        json={"base": "Dance", "instruments": {"guitar": "Pop punk"}},
    )
    note = response.json()["note"]
    assert "does not bring its level" in note
    assert "'Dance'" in note


def test_an_unknown_track_is_a_404(client, profiles):
    response = client.post(
        "/api/v1/tracks/not-a-track/reference/combine-profiles",
        json={"base": "Dance", "instruments": {}},
    )
    assert response.status_code == 404
