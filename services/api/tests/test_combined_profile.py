"""Guitars from one record, drums from another. X0R-1419.

Ryan asked for it and chose the rule it turns on: **character, not balance.**

`relative_lufs` is portable on its own - it is how an instrument sat in its own record,
which is a fact about that instrument. A *set* of them is not, because a set is a balance:
take the guitars' figure from a pop-punk record and the drums' from a dance one and the
guitar-to-drum relationship you end up with matches neither. Everything else in a snapshot
travels, because tone, dynamics, crest, placement and width are properties of how an
instrument was recorded rather than of what was beside it.

So these pin two things. A borrowed stem must not produce a level suggestion, and it must
produce everything else - because a feature that quietly dropped four dimensions along with
the one it meant to would be worse than the problem.
"""

from __future__ import annotations

import pytest

from app.domain.notes import StemKind
from app.services.mastering.instrument import (
    InstrumentProfile,
    compare,
    from_snapshot,
    snapshot,
)
from app.services.mastering.profile import ReferenceProfile, combine


def instrument(stem: str, *, level: float, band: float = 0.0, width: float = 1.0) -> dict:
    return snapshot(
        InstrumentProfile(
            stem=stem,
            relative_lufs=level,
            bands={"low": band, "low_mid": band, "high_mid": band,
                   "presence": band, "air": band},
            dynamic_range_db=8.0,
            crest_db=10.0,
            pan=0.0,
            width=width,
            present=True,
        )
    )


def profile(name: str, **instruments) -> ReferenceProfile:
    return ReferenceProfile(
        name=name,
        captured_from=name + ".wav",
        lufs=-9.0,
        true_peak_db=-1.0,
        curve_hz=[100.0, 1000.0],
        curve_db=[0.0, 0.0],
        width={"low": 0.1},
        stereo_width=1.0,
        instruments=instruments,
    )


@pytest.fixture
def pop_punk() -> ReferenceProfile:
    return profile(
        "Pop punk",
        guitar=instrument("guitar", level=-4.0, band=2.0, width=1.3),
        drums=instrument("drums", level=-6.0),
    )


@pytest.fixture
def dance() -> ReferenceProfile:
    return profile(
        "Dance",
        guitar=instrument("guitar", level=-14.0),
        drums=instrument("drums", level=-3.0, band=-1.5),
    )


# --- assembling -----------------------------------------------------------------------


def test_the_borrowed_instrument_comes_from_the_record_it_was_borrowed_from(pop_punk, dance):
    made = combine("Mine", base=dance, borrowed={"guitar": pop_punk})
    assert made.instruments["guitar"]["bands"]["air"] == pytest.approx(2.0)
    assert made.instruments["drums"]["bands"]["air"] == pytest.approx(-1.5)


def test_the_whole_mix_half_comes_wholesale_from_the_base(pop_punk, dance):
    """Averaging a curve across records would invent a master nobody made."""
    made = combine("Mine", base=dance, borrowed={"guitar": pop_punk})
    assert made.lufs == dance.lufs
    assert made.curve_db == dance.curve_db
    assert made.base_profile == "Dance"


def test_every_borrowed_stem_is_named(pop_punk, dance):
    """`captured_from` is one string and a combined profile has several answers."""
    made = combine("Mine", base=dance, borrowed={"guitar": pop_punk})
    assert made.instrument_sources == {"guitar": "Pop punk"}
    assert made.is_combined


def test_an_uncombined_profile_does_not_claim_to_be_combined(dance):
    assert not dance.is_combined
    assert combine("Mine", base=dance, borrowed={}).is_combined is False


def test_borrowing_from_a_profile_with_no_instruments_is_skipped_not_raised(dance):
    """A whole-mix-only profile has nothing to lend, and the caller finds out by looking
    at `instrument_sources` rather than by catching something."""
    empty = profile("Whole mix only")
    made = combine("Mine", base=dance, borrowed={"guitar": empty})
    assert made.instrument_sources == {}
    assert made.instruments["guitar"] == dance.instruments["guitar"]


def test_the_four_drums_travel_with_the_drums_stem(pop_punk, dance):
    """A kick borrowed from a record whose snare stayed behind is the exact balance
    decision this whole feature exists to refuse."""
    pop_punk.drums = {
        "kick": instrument("kick", level=-5.0),
        "snare": instrument("snare", level=-8.0),
    }
    dance.drums = {"kick": instrument("kick", level=-2.0)}
    made = combine("Mine", base=dance, borrowed={"drums": pop_punk})
    assert set(made.drums) == {"kick", "snare"}
    assert all(d.get("comparable_level") is False for d in made.drums.values())


# --- what the rule actually does ---------------------------------------------------------


def mine(level: float = -10.0) -> InstrumentProfile:
    return InstrumentProfile(
        stem=StemKind.GUITAR,
        relative_lufs=level,
        bands=dict.fromkeys(("low", "low_mid", "high_mid", "presence", "air"), 0.0),
        dynamic_range_db=8.0,
        crest_db=10.0,
        pan=0.0,
        width=1.0,
        present=True,
    )


def moves_for(made: ReferenceProfile, stem: str = "guitar"):
    theirs = from_snapshot(StemKind.GUITAR, made.instruments[stem])
    return compare(StemKind.GUITAR, mine(), theirs, ("guitars", True))


def test_a_borrowed_instrument_suggests_no_level(pop_punk, dance):
    """The decision, as an assertion. Yours is 6 dB under that record's guitars and the
    comparison must not offer to close it."""
    made = combine("Mine", base=dance, borrowed={"guitar": pop_punk})
    level = [m for m in moves_for(made) if m.dimension == "level"]
    assert len(level) == 1
    assert level[0].control == "", "a borrowed level was offered as a control"


def test_it_says_why_rather_than_going_quiet(pop_punk, dance):
    """A dimension that silently stops being offered is indistinguishable from one that
    found no difference."""
    made = combine("Mine", base=dance, borrowed={"guitar": pop_punk})
    level = next(m for m in moves_for(made) if m.dimension == "level")
    assert "borrowed" in level.headline
    assert "neighbours that record never had" in level.detail
    # And it must say what *is* still being compared, or it reads as a failure.
    assert "tone, dynamics, placement and width" in level.detail


def test_everything_except_level_still_travels(pop_punk, dance):
    """The borrowed guitar is 2 dB brighter in every band and wider. Those are properties
    of the sound, and dropping them with the level would be the wrong fix."""
    made = combine("Mine", base=dance, borrowed={"guitar": pop_punk})
    dimensions = {m.dimension for m in moves_for(made) if m.control}
    assert "tone" in dimensions
    assert "width" in dimensions


def test_the_base_s_own_instruments_keep_their_levels(pop_punk, dance):
    """They are still mutually coherent - they all came from one mix. Only the borrowed
    stem's neighbours have changed."""
    made = combine("Mine", base=dance, borrowed={"guitar": pop_punk})
    theirs = from_snapshot(StemKind.DRUMS, made.instruments["drums"])
    moves = compare(StemKind.DRUMS, mine(-10.0), theirs, ("drums", True))
    level = [m for m in moves if m.dimension == "level"]
    assert level and level[0].control == "gain_db"


def test_an_ordinary_profile_is_completely_unaffected(dance):
    """Every profile saved before this existed, and every one made from one record after."""
    theirs = from_snapshot(StemKind.GUITAR, dance.instruments["guitar"])
    assert theirs.comparable_level is True
    level = [m for m in compare(StemKind.GUITAR, mine(), theirs, ("guitars", True))
             if m.dimension == "level"]
    assert level and level[0].control == "gain_db"


# --- the file on disk ---------------------------------------------------------------------


def test_the_flag_is_only_written_when_it_is_false():
    """So an ordinary profile's bytes are exactly what they would have been."""
    ordinary = snapshot(InstrumentProfile(stem="guitar", present=True))
    assert "comparable_level" not in ordinary

    borrowed = snapshot(InstrumentProfile(stem="guitar", present=True, comparable_level=False))
    assert borrowed["comparable_level"] is False


def test_a_profile_saved_before_this_existed_still_loads(tmp_path, dance):
    """Absent means ordinary, which is the only thing keeping old files readable."""
    from app.services.mastering.profile import load, save

    path = save(dance, tmp_path)
    again = load(path)
    assert not again.is_combined
    assert from_snapshot("guitar", again.instruments["guitar"]).comparable_level is True


def test_a_combined_profile_survives_a_round_trip(tmp_path, pop_punk, dance):
    from app.services.mastering.profile import load, save

    made = combine("Mine", base=dance, borrowed={"guitar": pop_punk})
    again = load(save(made, tmp_path))
    assert again.instrument_sources == {"guitar": "Pop punk"}
    assert again.base_profile == "Dance"
    assert from_snapshot("guitar", again.instruments["guitar"]).comparable_level is False
