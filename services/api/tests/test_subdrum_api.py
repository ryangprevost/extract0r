"""The per-drum comparison through the API.

`test_subdrum` proves the measurements and the rules. This file proves the things a unit
test cannot: that the drums card can find out whether a second level is available before
it draws anything, that the route refuses politely in each of the ways it can be reached
too early, and that one drum's audio is served from a path the page can build.

The weights are not installed in a test run - `conftest` points `models_dir` at an empty
folder deliberately - so what is exercised here is the unavailable path, which is the one
a fresh clone gets and therefore the one worth guarding. The available path needs 167 MB
and a demucs, and `test_drum_separation` is where that lives.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

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


def _finish(client, job_id: str, timeout_s: float = 60.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body["state"] in ("succeeded", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout_s}s")


@pytest.fixture
def compared(client, sample_wav: Path):
    """A track and a reference, both separated - what any comparison needs to exist."""
    track_id = _upload(client, sample_wav)
    separated = client.post(f"/api/v1/tracks/{track_id}/separate")
    assert _finish(client, separated.json()["job_id"])["state"] == "succeeded"

    with sample_wav.open("rb") as handle:
        reference = client.post(
            f"/api/v1/tracks/{track_id}/reference",
            files={"file": ("reference.wav", handle, "audio/wav")},
            data={"owns_or_licensed": "true"},
        )
    assert reference.status_code == 201, reference.text

    split = client.post(f"/api/v1/tracks/{track_id}/reference/separate")
    assert _finish(client, split.json()["job_id"])["state"] == "succeeded"
    return track_id


# --- the capability, which the card reads before it draws anything ----------------------


def test_the_comparison_says_whether_a_second_level_is_available(client, compared):
    """Sent with the comparison even when the answer is no. Criterion 9 is that the drums
    card looks exactly as it does today without the weights, *plus one line* saying what
    would be there - and a page cannot write that line out of a key that is absent."""
    job = client.post(f"/api/v1/tracks/{compared}/reference/instruments")
    result = _finish(client, job.json()["job_id"])["result"]

    assert "per_drum" in result, "the drums card has nothing to decide with"
    per_drum = result["per_drum"]
    assert per_drum["available"] is False
    assert per_drum["reason"], "an unavailable feature has to say why"


def test_the_reason_names_the_download_and_where_it_comes_from(client, compared):
    """A sentence a user can act on, in the words `separate.why_unavailable` already
    produces, rather than a second wording of the same fact kept in the route."""
    job = client.post(f"/api/v1/tracks/{compared}/reference/instruments")
    reason = _finish(client, job.json()["job_id"])["result"]["per_drum"]["reason"]
    assert "167 MB" in reason and "huggingface" in reason, reason


def test_a_track_with_no_reference_says_so_rather_than_naming_the_model(
    client, sample_wav: Path
):
    """Order of operations first. Being told to download 167 MB when the actual missing
    step is "separate the reference" sends somebody off for ten minutes for nothing."""
    track_id = _upload(client, sample_wav)
    separated = client.post(f"/api/v1/tracks/{track_id}/separate")
    _finish(client, separated.json()["job_id"])

    from app.services.mastering.subdrum import DRUMS  # noqa: F401  (import guard)
    from app.api.routes_master import _per_drum_capability
    from app.config import Settings

    record = client.registry.require(track_id)
    capability = _per_drum_capability(
        record, Settings(_env_file=None, models_dir=Path("nowhere"))
    )
    assert capability["available"] is False
    assert "reference" in capability["reason"]
    assert "167 MB" not in capability["reason"]


def test_an_unseparated_track_is_told_to_separate_itself_first(client, sample_wav: Path):
    from app.api.routes_master import _per_drum_capability
    from app.config import Settings

    track_id = _upload(client, sample_wav)
    record = client.registry.require(track_id)
    capability = _per_drum_capability(
        record, Settings(_env_file=None, models_dir=Path("nowhere"))
    )
    assert capability["available"] is False
    assert "drums stem" in capability["reason"]


# --- the route itself -------------------------------------------------------------------


def test_an_unknown_track_is_a_404(client):
    assert client.post("/api/v1/tracks/nope/reference/drums").status_code == 404


def test_without_the_weights_the_route_refuses_with_the_same_sentence(client, compared):
    """The same words the card showed, so a user who presses it anyway is not told a
    different story by the error than by the screen."""
    response = client.post(f"/api/v1/tracks/{compared}/reference/drums")
    assert response.status_code == 409
    assert "167 MB" in response.json()["detail"]


# --- one drum's audio --------------------------------------------------------------------


def test_a_drum_that_was_never_split_out_is_a_404(client, compared):
    response = client.get(f"/api/v1/tracks/{compared}/drums/source/kick/audio")
    assert response.status_code == 404
    assert "split" in response.json()["detail"]


@pytest.mark.parametrize(
    "path",
    [
        "drums/elsewhere/kick/audio",
        "drums/source/cowbell/audio",
        "drums/../../etc/kick/audio",
    ],
)
def test_the_side_and_the_drum_are_matched_against_fixed_lists(client, compared, path):
    """Both land in a filesystem path, so neither is taken on trust. The third case is
    the one that matters: it must not reach the filesystem at all."""
    assert client.get(f"/api/v1/tracks/{compared}/{path}").status_code == 404


def test_a_split_drum_is_served_and_honours_a_range(client, compared, tmp_path):
    """Put a sub-stem on the record by hand - no endpoint produces one without the
    weights - and check the route serves it the way the reference stems are served.
    Without ranges a browser re-downloads the file on every seek."""
    import soundfile as sf
    import numpy as np

    kick = tmp_path / "kick.wav"
    sf.write(str(kick), np.zeros((44100, 2)), 44100)
    client.registry.set_drum_stems(compared, "source", {"kick": str(kick)})

    whole = client.get(f"/api/v1/tracks/{compared}/drums/source/kick/audio")
    assert whole.status_code == 200
    assert len(whole.content) > 0

    part = client.get(
        f"/api/v1/tracks/{compared}/drums/source/kick/audio",
        headers={"Range": "bytes=0-99"},
    )
    assert part.status_code == 206
    assert len(part.content) == 100


def test_one_side_being_split_does_not_forget_the_other(client, compared, tmp_path):
    """`set_drum_stems` replaces one side. The reference's pass and yours happen minutes
    apart, and the second overwriting the first would silently halve the cache - which
    shows up as the comparison being slow again rather than as an error."""
    import soundfile as sf
    import numpy as np

    for side in ("source", "reference"):
        path = tmp_path / f"{side}-kick.wav"
        sf.write(str(path), np.zeros((4410, 2)), 44100)
        client.registry.set_drum_stems(compared, side, {"kick": str(path)})

    stems = client.registry.require(compared).drum_stems
    assert sorted(stems) == ["reference", "source"]


# --- the profile, which is where the reference half stops costing anything --------------


def test_saving_a_profile_says_whether_it_carries_the_drums(client, compared):
    """Criterion 11's visible half. The save response reports it so the picker can show
    it later without re-reading every file, and so a user can tell what they just saved."""
    response = client.post(
        f"/api/v1/tracks/{compared}/reference/profile", json={"name": "test ref"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "per_drum" in body and body["per_drum"] is False
    assert body["drums"] == []
    # The stem half is unaffected by any of this, which is the regression worth guarding.
    assert body["per_stem"] is True


def test_the_picker_can_tell_which_profiles_carry_the_drums(client, compared):
    client.post(f"/api/v1/tracks/{compared}/reference/profile", json={"name": "test ref"})
    listed = client.get("/api/v1/tracks/reference/profiles").json()["profiles"]
    assert listed, "the profile that was just saved should be listed"
    assert all("per_drum" in one and "drums" in one for one in listed)


def test_a_saved_profile_picks_up_drums_that_were_already_split(client, compared, tmp_path):
    """Saving a profile never *starts* a separation - it should cost what it has always
    cost. What it does do is keep the measurements a pass already produced."""
    import soundfile as sf
    import numpy as np

    rng = np.random.default_rng(1)
    for drum, amplitude in (("kick", 0.4), ("snare", 0.2)):
        path = tmp_path / f"ref-{drum}.wav"
        sf.write(str(path), rng.normal(0, amplitude, (44100 * 2, 2)), 44100)
        stems = client.registry.require(compared).drum_stems.get("reference", {})
        client.registry.set_drum_stems(compared, "reference", {**stems, drum: str(path)})

    body = client.post(
        f"/api/v1/tracks/{compared}/reference/profile", json={"name": "with drums"}
    ).json()
    assert body["per_drum"] is True
    assert body["drums"] == ["kick", "snare"]


# --- the drum panel says which route it took (X0R-1316) ---------------------------------


def test_the_kit_panel_says_which_route_this_machine_takes(client):
    """Two routes, two failure modes, and the panel used to describe both with one
    sentence. Separation gives a stroke in the kick file, which is a kick; the classifier
    compares band rises on a summed stem and puts a quarter of the kicks within a few dB
    of the snare line."""
    body = client.get("/api/v1/tracks/drum-kits").json()
    assert "per_drum" in body
    route = body["per_drum"]
    assert route["available"] is False  # no weights in a test run
    assert "167 MB" in route["reason"]


def test_the_panel_can_tell_which_separated_drum_drives_the_hat(client):
    """The hi-hat box is fed by the cymbals stem, which holds hats, rides and crashes
    together. The page relabels the box from this, so that the box and the sound it makes
    agree - a ticked box that produced silence is what this card was filed for."""
    route = client.get("/api/v1/tracks/drum-kits").json()["per_drum"]
    assert route["voices"] == {"cymbals": "hihat"}
