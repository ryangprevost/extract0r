"""A progress bar is a claim about the work, and claims get tested.

What this is really guarding is the failure that prompted `jobs.stages`: the comparison
reported 0.9 immediately before the stage that is half the job. Nothing caught it,
because nothing was watching the relationship between a fraction and what came after it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.jobs.stages import (
    COMPARE_BOTH_SIDES,
    COMPARE_FROM_PROFILE,
    SECONDS_PER_SECOND_OF_AUDIO,
    Plan,
    Stage,
)

STUDIO = Path(__file__).resolve().parents[3] / "apps" / "studio" / "wwwroot"


def test_a_plan_starts_at_zero():
    """The first stage has nothing behind it, so it claims nothing."""
    plan = Plan(Stage("a", "a", 1.0), Stage("b", "b", 1.0))
    assert plan.at("a") == 0.0


def test_fractions_are_the_share_of_work_before_each_stage():
    plan = Plan(Stage("a", "a", 1.0), Stage("b", "b", 3.0))
    assert plan.at("b") == pytest.approx(0.25)


def test_fractions_never_go_backwards():
    for plan in (COMPARE_BOTH_SIDES, COMPARE_FROM_PROFILE):
        fractions = [plan.at(s.key) for s in plan.stages]
        assert fractions == sorted(fractions), f"{fractions} is not in order"
        assert all(0.0 <= f < 1.0 for f in fractions)


def test_no_stage_claims_more_than_the_work_behind_it():
    """The actual defect, as an assertion.

    A stage's fraction must be at most one minus its own share, or it is reporting work
    it has not done. The old job said 0.9 before a stage worth 0.5, which fails this by
    forty points.
    """
    for plan in (COMPARE_BOTH_SIDES, COMPARE_FROM_PROFILE):
        total = sum(s.weight for s in plan.stages)
        for stage in plan.stages:
            share = stage.weight / total
            assert plan.at(stage.key) <= 1.0 - share + 1e-9, (
                f"{stage.key} reports {plan.at(stage.key):.2f} with {share:.2f} still to do"
            )


def test_the_character_pass_is_not_announced_as_nearly_done():
    """It is half the job. It used to be announced at 90%."""
    assert COMPARE_BOTH_SIDES.at("character") < 0.6


def test_a_weightless_stage_does_not_move_the_bar():
    """Reading a saved profile is a dictionary lookup, and the bar should say so."""
    assert COMPARE_FROM_PROFILE.at("theirs") == pytest.approx(
        COMPARE_FROM_PROFILE.at("character"), abs=0.01
    )


def test_a_profile_is_estimated_as_cheaper_than_two_sides():
    from app.jobs.stages import estimate_seconds

    assert estimate_seconds(210, both_sides=False) < estimate_seconds(210, both_sides=True)
    assert estimate_seconds(0, both_sides=True) == 0.0


def test_the_estimate_is_within_sight_of_the_measurement():
    """98.75 s was measured on 210 s of audio. An estimate is allowed to be rough; it is
    not allowed to be a different answer."""
    from app.jobs.stages import estimate_seconds

    assert estimate_seconds(210, both_sides=True) == pytest.approx(98.75, rel=0.15)


def test_the_browser_uses_the_same_constant():
    """The same number in two languages, and only one of them has a test runner.

    Without this, the server's estimate and the one on screen drift apart silently and
    the user sees the stale one.
    """
    source = (STUDIO / "waiting.js").read_text(encoding="utf-8")
    match = re.search(r"SECONDS_PER_SECOND_OF_AUDIO\s*=\s*([0-9.]+)", source)
    assert match, "waiting.js no longer declares the constant"
    assert float(match.group(1)) == SECONDS_PER_SECOND_OF_AUDIO


def test_the_comparison_job_reports_every_stage_it_has():
    """Each stage declared is a stage reported, in the route that owns the plan."""
    route = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_master.py"
    source = route.read_text(encoding="utf-8")
    for stage in COMPARE_BOTH_SIDES.stages:
        assert f'plan.report(handle, "{stage.key}")' in source, stage.key
