"""The groove read, through the API. EPIC-13 stage 1.

`analysis.fingerprint` has measured the beat grid, where each drum falls across the bar,
how far from the grid it sits, the swing and the bass duck for weeks, with 26 tests behind
it - and **no route ever called it**, so none of it had ever reached a screen. These cover
the exposure rather than the measurement: that the route is where the page calls it, that
it refuses politely when a step has been skipped, and that the JSON carries what the page
reads off it.

The one that matters most is the last. This endpoint reports things no control in the
application can act on, and the response has to say so - otherwise a screenful of
rhythmic differences reads as a to-do list, which is exactly what X0R-1307 and this
epic's governing sentence exist to prevent.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

ATTESTED = {"owns_or_licensed": "true", "personal_use_only": "true"}


def finish(client, job_id: str, timeout_s: float = 120.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body["state"] in ("succeeded", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


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


def test_reading_a_groove_needs_stems_first(client, track):
    """Said rather than crashed. Nothing here can run on a mix that has not been split."""
    response = client.post(f"/api/v1/tracks/{track}/groove")
    assert response.status_code == 409
    assert "Separate this track" in response.json()["detail"]


def test_an_unknown_track_is_a_404(client):
    assert client.post("/api/v1/tracks/not-a-track/groove").status_code == 404


def test_a_groove_comes_back_with_the_keys_the_page_reads(client, separated):
    started = client.post(f"/api/v1/tracks/{separated}/groove")
    assert started.status_code == 202, started.text
    body = finish(client, started.json()["job_id"])
    assert body["state"] == "succeeded", body.get("error")

    result = body["result"]
    mine = result["yours"]
    for key in (
        "tempo_bpm",
        "beats_per_bar",
        "bars",
        "kick_histogram",
        "snare_histogram",
        "hat_histogram",
        "snare_on_backbeats",
        "hat_offbeat_share",
        "swing",
        "timing",
        "duck",
    ):
        assert key in mine, f"the page reads {key} and it is not there"


def test_a_figure_carries_its_own_sample_size(client, separated):
    """"43 hats over 15.1 bars" is the reader's only way to disagree with a number.

    A figure without its basis invites exactly the confidence it has not earned, which is
    why `Figure` keeps the two together and why the JSON must not drop one.
    """
    started = client.post(f"/api/v1/tracks/{separated}/groove")
    result = finish(client, started.json()["job_id"])["result"]
    swing = result["yours"]["swing"]
    assert set(swing) == {"value", "confidence", "unit", "basis", "caveat", "measured"}


def test_an_unmeasurable_figure_says_so_rather_than_returning_zero(client, separated):
    """0.0 is a perfectly good swing deviation, so it cannot double as "no answer"."""
    started = client.post(f"/api/v1/tracks/{separated}/groove")
    result = finish(client, started.json()["job_id"])["result"]
    for figure in (result["yours"]["swing"], result["yours"]["hat_offbeat_share"]):
        if not figure["measured"]:
            assert figure["value"] is None
            assert figure["caveat"] or figure["basis"]


def test_with_no_separated_reference_it_reads_one_side_and_says_which(client, separated):
    started = client.post(f"/api/v1/tracks/{separated}/groove")
    result = finish(client, started.json()["job_id"])["result"]
    assert result["reference"] is None
    assert result["reference_measured"] is False
    assert "has not been separated" in result["why_no_reference"]


def test_the_response_says_there_is_nothing_to_apply(client, separated):
    """The whole risk of putting groove on a screen is that it reads as a to-do list.

    Experiment 2 measured that processing gets you tone and never groove, so this reports
    and offers nothing - and has to say so where somebody will read it.
    """
    started = client.post(f"/api/v1/tracks/{separated}/groove")
    result = finish(client, started.json()["job_id"])["result"]
    assert "observations, not suggestions" in result["note"]
    assert "composition rather than mastering" in result["note"]


def test_the_stage_plan_never_claims_work_it_has_not_done(client):
    """Same assertion the comparison's plan gets, for the same reason."""
    from app.jobs.stages import GROOVE_BOTH_SIDES, GROOVE_ONE_SIDE

    for plan in (GROOVE_BOTH_SIDES, GROOVE_ONE_SIDE):
        fractions = [plan.at(stage.key) for stage in plan.stages]
        assert fractions == sorted(fractions)
        assert fractions[0] == 0.0


def test_one_sided_reading_does_not_pause_on_a_reference_it_will_not_read(client):
    """With nothing to read on the other side, that stage must cost nothing."""
    from app.jobs.stages import GROOVE_ONE_SIDE

    assert GROOVE_ONE_SIDE.at("theirs") == GROOVE_ONE_SIDE.at("comparing")


def test_the_page_uses_the_same_grid_confidence_floor():
    """A percentage counted against an untrusted grid is an untrusted percentage.

    Caught on the first real render: every server-computed figure abstained with "the
    beat grid is below the confidence floor" while the two percentages the page works out
    for itself - kick on the beat, snare on the backbeat - printed bare beside them. They
    count hits against that same lattice, so they were the one dishonest number on the
    panel and the most eye-catching one.
    """
    import re
    from pathlib import Path

    from app.services.analysis.fingerprint import MIN_GRID_CONFIDENCE

    studio = Path(__file__).resolve().parents[3] / "apps" / "studio" / "wwwroot"
    source = (studio / "groove.js").read_text(encoding="utf-8")

    match = re.search(r"MIN_GRID_CONFIDENCE\s*=\s*([0-9.]+)", source)
    assert match, "groove.js no longer declares the floor"
    assert float(match.group(1)) == MIN_GRID_CONFIDENCE

    # And it has to actually gate the two percentages, not merely declare the constant.
    assert "grid_confidence" in source
    assert "measured: trusted" in source


def test_grid_confidence_reaches_the_page_at_all(client, separated):
    """The gate above is unenforceable if the response does not carry the number."""
    started = client.post(f"/api/v1/tracks/{separated}/groove")
    result = finish(client, started.json()["job_id"])["result"]
    assert isinstance(result["yours"]["grid_confidence"], float)
