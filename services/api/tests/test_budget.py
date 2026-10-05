"""One control instead of nine constants, and the two things it must not touch.

X0R-1306's trap is named in the card: a budget wired to `match_strength` would ship a
control that cannot do anything. Experiment 2 measured why - the whole strength sweep is
worth 0.56 dB of mean spectral closure, under half this codebase's own threshold for a
meaningful gap, because it scales a curve that has already been clamped. The clamps are
worth three and a half times as much. So these tests are mostly about the clamps, and
about the three places a wider budget must *not* reach.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.notes import StemKind
from app.services.mastering import budget, instrument
from app.services.mastering.dsp import MatchSettings

SR = 44100


def _profile(relative_lufs: float, bands: dict[str, float], seed: int):
    rng = np.random.default_rng(seed)
    one = instrument.profile(rng.normal(0, 0.2, (SR * 2, 2)), SR, StemKind.GUITAR)
    one.relative_lufs = relative_lufs
    one.present = True
    one.bands = dict(bands)
    return one


MINE = {"low": -30.0, "low_mid": -12.0, "high_mid": -6.0, "presence": -9.0, "air": -20.0}
THEIRS = {"low": -22.0, "low_mid": -6.0, "high_mid": -10.0, "presence": -4.0, "air": -12.0}


def _moves(name: str):
    mine = _profile(-14.0, MINE, 1)
    theirs = _profile(-3.0, THEIRS, 2)
    return instrument.compare(
        StemKind.GUITAR, mine, theirs, limits=budget.limits_for(name)
    )


# --- the default is today, exactly ------------------------------------------------------


def test_the_default_budget_changes_nothing():
    """The whole refactor has to be a no-op until somebody moves the control. These four
    numbers were each tuned against a complaint, and a budget that silently altered them
    would be a regression dressed as a feature."""
    limits = budget.limits_for(None)
    assert limits.max_level_db == 3.0
    assert limits.max_band_db == 2.5
    assert limits.tone_budget_db == 5.0
    assert limits.width_limits == (0.8, 1.35)


def test_instrument_s_constants_are_the_default_budget_and_cannot_drift():
    """They are re-exported from `budget.Limits` rather than defined twice - the same
    pattern `presence` established, and for the same reason: this card exists because
    nine constants were scattered, and fixing that with a tenth copy misses the point."""
    limits = budget.Limits()
    assert limits.max_level_db == instrument.MAX_LEVEL_DB
    assert limits.max_band_db == instrument.MAX_BAND_DB
    assert limits.tone_budget_db == instrument.TONE_BUDGET_DB
    assert limits.width_limits == instrument.WIDTH_LIMITS


def test_the_default_match_settings_are_returned_untouched():
    base = MatchSettings(strength=0.8)
    assert budget.match_settings_for("nudge", base) is base


def test_an_unknown_budget_is_the_default_rather_than_an_error():
    """A name from an older client should cost nothing."""
    assert budget.get("nonsense").name == budget.DEFAULT
    assert budget.get(None).name == budget.DEFAULT
    assert budget.limits_for("nonsense") == budget.limits_for(None)


# --- what a wider budget does ------------------------------------------------------------


def test_a_wider_budget_raises_every_ceiling():
    nudge, further = budget.limits_for("nudge"), budget.limits_for("further")
    assert further.max_level_db > nudge.max_level_db
    assert further.max_band_db > nudge.max_band_db
    assert further.tone_budget_db > nudge.tone_budget_db


def test_it_reaches_the_clamps_experiment_2_actually_measured():
    """The ones with a number behind them. Doubling `MatchSettings`' clamps bought
    1.07 dB of mean closure where the entire `match_strength` sweep bought 0.56."""
    base = MatchSettings()
    wider = budget.match_settings_for("further", base)
    assert wider.max_tilt_db == pytest.approx(base.max_tilt_db * 2)
    assert wider.max_boost_db == pytest.approx(base.max_boost_db * 2)
    assert wider.max_cut_db == pytest.approx(base.max_cut_db * 2)


def test_a_wider_budget_lets_a_big_tone_difference_move_further():
    totals = {
        name: sum(abs(m.suggested) for m in _moves(name) if m.dimension == "tone")
        for name in ("nudge", "further")
    }
    assert totals["nudge"] < totals["further"]


# --- the three things it must not touch ---------------------------------------------------


def test_the_deep_bass_guard_never_scales():
    """`max_low_cut_db` is 1.0 rather than 2.0 because a master came back with "no bass":
    the correction piled up above the guard corner and dug a 5 dB notch at 105 Hz,
    straight through the kick and bass fundamentals. A budget that widened it would
    re-open a fixed complaint and call it a feature."""
    base = MatchSettings()
    for name in ("nudge", "further"):
        widened = budget.match_settings_for(name, base)
        assert widened.max_low_cut_db == base.max_low_cut_db, name
        assert widened.low_guard_hz == base.low_guard_hz, name


def test_the_arrangement_flag_is_the_same_at_every_budget():
    """Widening means "I accept a bigger move", not "stop telling me when these are
    different songs"."""
    for name in ("nudge", "further"):
        flagged = [m for m in _moves(name) if m.dimension == "level" and not m.confident]
        # The level gap in the fixture is 11 dB, past LIKELY_ARRANGEMENT_DB at every
        # setting, so it must stay flagged however wide the budget is.
        assert flagged, f"{name} stopped flagging an 11 dB level gap"


def test_no_budget_can_turn_a_nudge_into_a_copy():
    """The property the whole design turns on, and the reason ceilings scale while the
    *share of the gap* does not. Raising the limit lets a large difference move further;
    it can never ask for more than half the gap, because the fraction takes over as soon
    as the clamp stops binding. The level move saturates well below the 11 dB measured.
    """
    gaps = {
        name: next(m for m in _moves(name) if m.dimension == "level")
        for name in ("nudge", "further")
    }
    measured = gaps["nudge"].measured
    assert measured == pytest.approx(11.0, abs=0.1)

    assert gaps["nudge"].suggested == 3.0, "today's clamp binds"
    # The wider notch lands on half the gap and stops there, however high the ceiling:
    # 5.5 of the 11 dB measured, because the share takes over once the clamp lets go.
    assert gaps["further"].suggested == pytest.approx(measured / 2, abs=0.01)
    assert gaps["further"].suggested < measured


def test_the_share_of_the_gap_is_not_a_budget_field():
    """Stated as a test because the card names `CLOSE_FRACTION` among the constants to
    fold in, and folding it in is how this control would stop being a nudge. The
    governing idea is "a nudge in a direction... not a carbon copy"; the fraction *is*
    the nudge and the clamps are the rail. A budget raises the rail."""
    assert not hasattr(budget.Limits(), "nudge_share")
    assert not hasattr(budget.Limits(), "close_fraction")
    assert instrument.NUDGE_SHARE == 0.5


# --- width is a ratio, not a quantity of decibels -------------------------------------------


def test_width_scales_around_unity_rather_than_being_multiplied():
    """Multiplying (0.8, 1.35) by two gives a *floor* of 1.6 - a budget that forbids ever
    narrowing anything, which is the opposite of "allow more width change"."""
    low, high = budget.limits_for("further").width_limits
    assert low < 1.0 < high
    assert low == pytest.approx(0.6, abs=0.001)
    assert high == pytest.approx(1.7, abs=0.001)


def test_width_never_reaches_zero_at_the_widest_setting():
    low, _ = budget.limits_for("further").width_limits
    assert low > 0.0


# --- the notches themselves -----------------------------------------------------------------


def test_there_are_two_notches_and_the_first_is_the_default():
    """Two, not three. A ×3 notch was built and measured at 0.06 dB over ×2, because
    past that point the deep-bass guard is what holds the curve rather than the tilt cap
    - and the guard is not moving. A third would be a control that does nothing, which
    is the failure this whole card exists to prevent."""
    assert [b.name for b in budget.BUDGETS] == ["nudge", "further"]
    assert budget.BUDGETS[0].name == budget.DEFAULT
    assert budget.BUDGETS[0].scale == 1.0


def test_every_notch_says_what_it_permits_in_decibels():
    """The card asks for this directly: "each wider notch says in dB what it permits".
    "More" is not a unit, and this control's whole problem is that the one it sits next
    to feels like it does something."""
    for one in budget.BUDGETS:
        assert "dB" in one.summary, one.name
        assert len(one.summary) > 60, one.name


def test_the_notches_get_wider_and_stop():
    scales = [b.scale for b in budget.BUDGETS]
    assert scales == sorted(scales)
    # Experiment 2's unclamped case bought 2.15 dB and is not a setting that should
    # exist: at that point the curve runs its full range and rebuilds one record into
    # another. There is a top notch, and it is bounded.
    assert max(scales) <= 2.0


def test_the_stem_gain_limit_widens_more_slowly_than_the_rest():
    """Nine decibels on one stem against four on another is already a thirteen-decibel
    swing between two instruments, and this is the clamp behind the "+9 dB of nothing"
    bug X0R-1127 was filed for."""
    widest = budget.stem_gain_limit_for("further")
    assert 9.0 < widest < 9.0 * 2


def test_the_json_the_page_builds_its_control_from_is_complete():
    rows = budget.as_json()
    assert len(rows) == len(budget.BUDGETS)
    assert sum(1 for row in rows if row["default"]) == 1
    for row in rows:
        assert {"name", "label", "scale", "summary", "default"} <= set(row)


# --- through the API -------------------------------------------------------------------


def test_the_budgets_route_gives_the_page_what_it_needs(client):
    body = client.get("/api/v1/tracks/budgets").json()
    assert [b["name"] for b in body["budgets"]] == ["nudge", "further"]
    assert body["default"] == "nudge"
    # The sentence that stops this shipping as a working control beside one that only
    # looks like it works.
    assert "half the measured gap" in body["note"]


def test_a_master_request_defaults_to_the_nudge_budget():
    from app.api.routes_master import MasterJobRequest

    request = MasterJobRequest(stems=[{"stem": "drums"}])
    assert request.budget == "nudge"


def test_an_unknown_budget_on_a_request_is_not_a_422():
    """An older client should keep working. The fallback happens in `budget.get`, so the
    request model stays permissive on purpose."""
    from app.api.routes_master import MasterJobRequest

    request = MasterJobRequest(stems=[{"stem": "drums"}], budget="whatever")
    assert budget.get(request.budget).name == "nudge"
