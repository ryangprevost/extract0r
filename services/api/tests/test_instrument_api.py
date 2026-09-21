"""The instrument-by-instrument comparison, end to end through the API.

The unit tests in `test_instrument` prove the measurements and the moves. These prove the
things a unit test cannot: that the endpoints exist at the paths the page calls, that they
refuse politely when a step has been skipped, and - the one that matters most - that the
JSON carries every key the page reads off it.

That last one is not pedantry. A response missing `tone_matrix` does not throw; the page
falls back to setting each filter to its band's raw number, the monitor quietly runs a
different EQ from the render, and the only symptom is that the preview does not sound like
the master. This file is where that gets caught.
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
    """A track and a reference, both separated - what the comparison needs to exist."""
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


# --- the order of operations -------------------------------------------------------


def test_comparing_before_separating_the_reference_says_which_step_is_missing(
    client, sample_wav: Path
):
    """A 409 with the next step in it, rather than an empty comparison that looks like
    "nothing is different"."""
    track_id = _upload(client, sample_wav)
    job = client.post(f"/api/v1/tracks/{track_id}/separate")
    _finish(client, job.json()["job_id"])

    response = client.post(f"/api/v1/tracks/{track_id}/reference/instruments")
    assert response.status_code == 409
    assert "separated" in response.json()["detail"]


def test_comparing_before_separating_your_own_track_is_refused_too(client, sample_wav: Path):
    track_id = _upload(client, sample_wav)
    response = client.post(f"/api/v1/tracks/{track_id}/reference/instruments")
    assert response.status_code == 409


def test_an_unknown_track_is_a_404(client):
    assert client.post("/api/v1/tracks/nope/reference/instruments").status_code == 404


# --- the shape the page reads ---------------------------------------------------------


def test_the_comparison_carries_every_key_the_page_reads(client, compared):
    """Each assertion here is a line of `instruments.js` that would otherwise fail
    silently, drawing an empty card or a preview that disagrees with the export."""
    job = client.post(f"/api/v1/tracks/{compared}/reference/instruments")
    assert job.status_code == 200, job.text
    result = _finish(client, job.json()["job_id"])
    assert result["state"] == "succeeded", result

    body = result["result"]
    assert body["available"] is True
    assert body["instruments"], "the comparison found no instruments at all"

    for instrument in body["instruments"]:
        assert {"stem", "label", "in_reference", "yours", "moves"} <= set(instrument)
        assert {
            "relative_lufs", "bands", "dynamic_range_db", "crest_db", "pan", "width",
        } <= set(instrument["yours"])
        # Five bands, named, every time - the page indexes them by name.
        assert set(instrument["yours"]["bands"]) == {
            "low", "low_mid", "high_mid", "presence", "air",
        }
        for move in instrument["moves"]:
            assert {
                "dimension", "headline", "detail", "severity", "suggested", "control",
                "confident",
            } <= set(move)


def test_the_tone_solver_comes_back_so_the_monitor_can_run_the_same_eq(client, compared):
    """Sent already inverted and damped. The page used to invert the raw matrix itself,
    which agreed with the render right up until the render started damping its solve to
    stop overlapping filters combing - at which point the preview would have been running
    a different EQ from the export with nothing to show for it."""
    job = client.post(f"/api/v1/tracks/{compared}/reference/instruments")
    body = _finish(client, job.json()["job_id"])["result"]

    solvers = [i["tone_solver"] for i in body["instruments"]]
    assert any(s is not None for s in solvers), "no instrument came back with a solve"

    for solver in solvers:
        if solver is None:
            continue
        assert len(solver) == 5 and all(len(row) == 5 for row in solver)
        # Asking for one band has to move that band's own filter most, or the basis is
        # mislabelled and the solve is solving the wrong problem.
        for index in range(5):
            target = [3.0 if i == index else 0.0 for i in range(5)]
            gains = [sum(v * target[i] for i, v in enumerate(row)) for row in solver]
            assert gains[index] == max(gains, key=abs), f"band {index} led by another filter"
            # And no two neighbouring filters set against each other - the comb that made
            # real masters sound hollow.
            swings = [abs(gains[i] - gains[i + 1]) for i in range(4)]
            assert max(swings) < 5.0, f"filters fighting on band {index}: {gains}"


def test_the_basis_the_page_rebuilds_is_described_in_the_response(client, compared):
    job = client.post(f"/api/v1/tracks/{compared}/reference/instruments")
    body = _finish(client, job.json()["job_id"])["result"]

    assert [entry["band"] for entry in body["tone_basis"]] == [
        "low", "low_mid", "high_mid", "presence", "air",
    ]
    assert [entry["band"] for entry in body["bands"]] == [
        "low", "low_mid", "high_mid", "presence", "air",
    ]


def test_a_track_compared_against_itself_finds_nothing_to_change(client, compared):
    """The reference here is a copy of the source, so every instrument matches its own
    counterpart. Any move at all would mean the comparison is measuring noise."""
    job = client.post(f"/api/v1/tracks/{compared}/reference/instruments")
    body = _finish(client, job.json()["job_id"])["result"]

    moves = [
        (instrument["stem"], move["dimension"], move["suggested"])
        for instrument in body["instruments"]
        for move in instrument["moves"]
    ]
    assert moves == [], f"comparing a track with itself suggested changes: {moves}"


# --- hearing both sides ---------------------------------------------------------------


def test_a_reference_stem_streams_so_it_can_be_played_against_yours(client, compared):
    response = client.get(f"/api/v1/tracks/{compared}/reference/stems/drums/audio")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["accept-ranges"] == "bytes"


def test_a_reference_stem_honours_a_range_request(client, compared):
    """Without this a browser re-downloads the whole stem on every seek."""
    response = client.get(
        f"/api/v1/tracks/{compared}/reference/stems/drums/audio",
        headers={"Range": "bytes=0-1023"},
    )
    assert response.status_code == 206
    assert response.headers["content-range"].startswith("bytes 0-1023/")
    assert len(response.content) == 1024


def test_asking_for_a_reference_stem_that_was_never_separated_is_a_404(
    client, sample_wav: Path
):
    track_id = _upload(client, sample_wav)
    response = client.get(f"/api/v1/tracks/{track_id}/reference/stems/drums/audio")
    assert response.status_code == 404


def test_an_unknown_stem_name_is_a_404_rather_than_a_500(client, compared):
    assert (
        client.get(f"/api/v1/tracks/{compared}/reference/stems/kazoo/audio").status_code
        == 404
    )


# --- the moves reach the render --------------------------------------------------------


def test_a_master_accepts_the_per_instrument_controls(client, compared):
    """The end of the road for a taken suggestion: it has to survive the master request,
    which is the only place it becomes audible in a file."""
    response = client.post(
        f"/api/v1/tracks/{compared}/master",
        json={
            "stems": [
                {
                    "stem": "drums",
                    "tone_air_db": 2.5,
                    "tone_low_db": -1.0,
                    "compress_db": 3.0,
                    "saturation_db": 0.5,
                }
            ],
            "reference_track_id": compared,
        },
    )
    assert response.status_code == 202, response.text
    assert _finish(client, response.json()["job_id"])["state"] == "succeeded"


def test_a_tone_move_outside_the_allowed_range_is_refused(client, compared):
    """The sliders are built from these bounds, so a value the API would reject should
    not be reachable - but the API is what enforces it."""
    response = client.post(
        f"/api/v1/tracks/{compared}/master",
        json={"stems": [{"stem": "drums", "tone_air_db": 99.0}]},
    )
    assert response.status_code == 422


def test_every_stem_says_where_its_busy_part_starts(client, compared):
    """The preview opens here rather than at 0:00. Each side gets its own number: two
    different songs reach their choruses at different points, so a shared playhead only
    guarantees both are the same distance from their own beginnings. Measured on a real
    pair, the vocal's busy stretch began at 63.6 s in the source and 142.5 s in the
    reference."""
    job = client.post(f"/api/v1/tracks/{compared}/reference/instruments")
    body = _finish(client, job.json()["job_id"])["result"]

    for instrument in body["instruments"]:
        assert "preview_start_s" in instrument["yours"]
        assert instrument["yours"]["preview_start_s"] >= 0
        if instrument["reference"] is not None:
            assert "preview_start_s" in instrument["reference"]


def test_a_suggestion_is_part_of_the_measured_gap_and_says_which(client, compared):
    """The behaviour the whole per-instrument screen turns on: it nudges toward the
    reference rather than copying it. Both numbers travel, so the page can show the gap
    and offer the nudge."""
    job = client.post(f"/api/v1/tracks/{compared}/reference/instruments")
    body = _finish(client, job.json()["job_id"])["result"]

    for instrument in body["instruments"]:
        for move in instrument["moves"]:
            assert "measured" in move
            if not move["control"] or move["control"] == "width":
                continue
            # Never more than the gap, and never the wrong side of zero.
            assert abs(move["suggested"]) <= abs(move["measured"]) + 1e-6
            if move["measured"]:
                assert move["suggested"] * move["measured"] >= 0


# --- exporting with per-instrument matching on ------------------------------------


def test_a_master_with_per_stem_matching_on_actually_completes(client, compared):
    """The path that crashed on a real export, and the reason it hid for so long.

    `per_stem` in the response is empty unless per-instrument matching actually ran, so
    every test and every manual export that left the box unticked walked straight past a
    serialiser reading fifteen field names that do not exist on a StemAdjustment. The job
    did all its work, wrote the MP3, and then died composing the reply.
    """
    response = client.post(
        f"/api/v1/tracks/{compared}/master",
        json={
            "stems": [{"stem": "drums"}, {"stem": "bass"}, {"stem": "vocals"}],
            "reference_track_id": compared,
            "per_stem_match": True,
        },
    )
    assert response.status_code == 202, response.text

    finished = _finish(client, response.json()["job_id"], timeout_s=120.0)
    assert finished["state"] == "succeeded", finished.get("error")
    assert finished["result"]["per_stem"], "per-stem matching ran but reported nothing"


def test_the_per_stem_report_carries_exactly_what_matching_produced(client, compared):
    """Names, not just absence of a crash. The old version invented fields from a
    different dataclass; this pins the response to the one it is actually built from."""
    from dataclasses import fields

    from app.services.mastering.stem_match import StemAdjustment

    response = client.post(
        f"/api/v1/tracks/{compared}/master",
        json={
            "stems": [{"stem": "drums"}, {"stem": "bass"}],
            "reference_track_id": compared,
            "per_stem_match": True,
        },
    )
    body = _finish(client, response.json()["job_id"], timeout_s=120.0)["result"]

    expected = {spec.name for spec in fields(StemAdjustment)}
    for entry in body["per_stem"]:
        assert set(entry) == expected, f"drifted from StemAdjustment: {set(entry) ^ expected}"
        # And the stem has to survive as its name rather than as an unserialisable enum.
        assert isinstance(entry["stem"], str)


def test_every_field_the_page_reads_off_per_stem_is_present(client, compared):
    """The eight `renderMaster` actually uses. A response that merely does not crash can
    still draw an empty report."""
    response = client.post(
        f"/api/v1/tracks/{compared}/master",
        json={
            "stems": [{"stem": "drums"}, {"stem": "bass"}],
            "reference_track_id": compared,
            "per_stem_match": True,
        },
    )
    body = _finish(client, response.json()["job_id"], timeout_s=120.0)["result"]

    for entry in body["per_stem"]:
        assert {
            "stem", "gain_db", "width_factor", "eq_bands", "notes", "matched",
            "proportional", "user_gain_db",
        } <= set(entry)
