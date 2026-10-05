"""The four drums inside the drums stem, compared drum to drum.

The measuring and the move-writing are `instrument`'s and are tested there. What is
tested here is only what makes a sub-drum different from a stem, which is four decisions
and one trap:

1. level is read against the drums, not the mix;
2. a kick and a snare never get a pan or a width finding;
3. every finding carries the bleed caveat;
4. presence is energy, never a stroke count;

and the trap is that a reference profile has to be able to hold all of it, or the
comparison ships with a format that cannot keep what it measures and there are two
formats in the wild a week later.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering import instrument, presence, subdrum

SR = 44100


def _tone(hz: float, seconds: float = 2.0, amplitude: float = 0.3, pan: float = 0.0):
    """A steady tone, optionally off centre, as a stereo buffer."""
    t = np.arange(int(SR * seconds)) / SR
    mono = np.sin(2 * np.pi * hz * t) * amplitude
    left = mono * (1.0 - max(pan, 0.0))
    right = mono * (1.0 + min(pan, 0.0))
    return np.stack([left, right], axis=1)


def _noise(seconds: float = 2.0, amplitude: float = 0.3, seed: int = 0, width: float = 0.0):
    rng = np.random.default_rng(seed)
    mono = rng.normal(0, amplitude, int(SR * seconds))
    side = rng.normal(0, amplitude * width, mono.size)
    return np.stack([mono + side, mono - side], axis=1)


def _profile(samples, drum: str, relative_lufs: float = -6.0):
    one = instrument.profile(samples, SR, drum)
    one.relative_lufs = relative_lufs
    one.present = presence.is_present(relative_lufs)
    return one


def _write(path, samples):
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), samples, SR)
    return path


# --- decision B: four dimensions on a kick, six on a cymbal -----------------------------


@pytest.mark.parametrize("drum", ["kick", "snare"])
def test_a_kick_and_a_snare_are_never_offered_a_pan_or_a_width(drum):
    """`NEVER_MOVE_SIDEWAYS` exists because a bass belongs in the middle. A kick and a
    snare belong there for the same reason, and on a separated stem either is centred -
    so a pan finding on one is reporting separation bleed rather than a decision anybody
    made. The pair here is as far apart sideways as two signals get."""
    mine = _profile(_tone(60, pan=-0.9), drum)
    theirs = _profile(_noise(width=1.4, seed=2), drum)
    theirs.pan, theirs.width = 0.9, 1.6
    mine.pan, mine.width = -0.9, 0.2

    moves = instrument.compare(drum, mine, theirs, subdrum.words(drum))
    assert {m.dimension for m in moves}.isdisjoint({"pan", "width"}), (
        f"{drum} was offered a sideways move: {[m.dimension for m in moves]}"
    )


def test_cymbals_keep_pan_and_width_because_overheads_really_do_spread():
    """The other half of the same rule, so the test proves a distinction rather than a
    blanket refusal that would also pass with the dimensions deleted."""
    mine = _profile(_noise(width=0.2, seed=3), "cymbals")
    theirs = _profile(_noise(width=1.2, seed=4), "cymbals")
    mine.pan, mine.width = -0.4, 0.9
    theirs.pan, theirs.width = 0.4, 1.4

    moves = instrument.compare("cymbals", mine, theirs, subdrum.words("cymbals"))
    assert {"pan", "width"} <= {m.dimension for m in moves}


def test_the_rule_is_one_list_and_not_two():
    """Kick and snare are in `NEVER_MOVE_SIDEWAYS` itself rather than in a second list
    this module keeps. Two lists is how a rule ends up applied in one place only."""
    assert "kick" in instrument.NEVER_MOVE_SIDEWAYS
    assert "snare" in instrument.NEVER_MOVE_SIDEWAYS
    assert "cymbals" not in instrument.NEVER_MOVE_SIDEWAYS
    assert "toms" not in instrument.NEVER_MOVE_SIDEWAYS


# --- decision 2: level is measured against the drums ------------------------------------


def test_level_is_read_against_the_kit_and_not_against_the_mix(tmp_path):
    """A kick 8 LU under the drum bus is a statement about the kit's internal balance,
    which is the thing a user can act on and the thing that is portable between records.
    Against the whole mix it would mostly measure how loud the drums are, which the drums
    row already says.

    Proved by arithmetic rather than by eye. Every drum's `relative_lufs` has to be its
    own loudness minus *one* number, and that number has to be the loudness of the four
    summed - which is the kit. An implementation that measured against the whole mix, or
    against the loudest drum, would give a different constant, and one that measured each
    against something of its own would give four.

    Not asserted by amplitude order, which was the first version of this test and was
    wrong: loudness is K-weighted, so a 60 Hz sine at half scale measures quieter than
    broadband noise at a quarter of it. The fixture was fine; the assumption was not.
    """
    buffers = {
        "kick": _tone(60, amplitude=0.5),
        "snare": _noise(amplitude=0.25, seed=5),
        "cymbals": _noise(amplitude=0.03, seed=6),
        "toms": _tone(120, amplitude=0.0005),
    }
    stems = {name: _write(tmp_path / f"{name}.wav", buf) for name, buf in buffers.items()}
    measured = subdrum.profile_all(stems)
    assert set(measured) == {"kick", "snare", "cymbals", "toms"}

    from app.services.mastering.loudness_meter import integrated_loudness

    kit, _ = integrated_loudness(sum(buffers.values()), SR)
    for name, one in measured.items():
        assert one.relative_lufs == pytest.approx(one.loudness_lufs - kit, abs=0.01), name

    # Every one of them is at or under the kit they sum to.
    assert all(one.relative_lufs <= 0.5 for one in measured.values())


def test_a_residue_stem_is_called_absent_on_its_energy(tmp_path):
    """A record with no toms still yields a toms stem. Presence is the same rule and the
    same threshold used against the mix - and never a stroke count, because
    `separate.QUIET_STROKE_DB` has no knee on the snare and a count would make the verdict
    a function of where that gate was put."""
    stems = {
        "kick": _write(tmp_path / "kick.wav", _tone(60, amplitude=0.5)),
        "toms": _write(tmp_path / "toms.wav", _tone(120, amplitude=0.0005)),
    }
    measured = subdrum.profile_all(stems)
    assert measured["kick"].present is True
    assert measured["toms"].present is False
    assert measured["toms"].relative_lufs < presence.ABSENT_BELOW_LU


def test_an_unknown_separated_name_is_dropped_rather_than_drawn(tmp_path):
    """A model that grew a fifth output should not silently gain a row on a screen built
    for four."""
    stems = {
        "kick": _write(tmp_path / "kick.wav", _tone(60)),
        "cowbell": _write(tmp_path / "cowbell.wav", _tone(800)),
    }
    assert set(subdrum.profile_all(stems)) == {"kick"}


# --- decision 4: the bleed caveat is on the finding -------------------------------------


def test_every_finding_carries_a_bleed_caveat():
    """On the finding, not in a help panel."""
    mine = _profile(_tone(200, amplitude=0.2), "snare", relative_lufs=-10.0)
    theirs = _profile(_noise(amplitude=0.4, seed=7), "snare", relative_lufs=-4.0)

    moves = subdrum.compare_all({"snare": mine}, {"snare": theirs})["snare"]
    assert moves, "the fixture should produce findings"
    for move in moves:
        assert "Bleed check:" in move.detail, move.headline


def test_the_caveat_names_the_drum_most_likely_to_be_behind_the_finding():
    """The thing that makes it worth reading rather than wallpaper. A finding about the
    snare's 20-120 Hz is the one most likely to be the kick, because the kick is what is
    down there - and that is something a user can go and listen for."""
    from app.services.mastering.instrument import InstrumentMove

    low = InstrumentMove(stem="snare", dimension="tone", band="low")
    assert "kick" in subdrum.bleed_note("snare", low)

    air = InstrumentMove(stem="snare", dimension="tone", band="air")
    assert "cymbals" in subdrum.bleed_note("snare", air)


def test_a_drum_alone_in_its_band_is_not_told_to_suspect_itself():
    """The kick is the only thing in 20-120 Hz, so there is no neighbour to name and the
    specific sentence would have to say "the kick may be the kick"."""
    from app.services.mastering.instrument import InstrumentMove

    note = subdrum.bleed_note("kick", InstrumentMove(stem="kick", dimension="tone", band="low"))
    assert note == subdrum.GENERAL_BLEED_NOTE


def test_a_finding_that_is_not_about_a_band_gets_the_general_note():
    from app.services.mastering.instrument import InstrumentMove

    level = InstrumentMove(stem="kick", dimension="level")
    assert subdrum.bleed_note("kick", level) == subdrum.GENERAL_BLEED_NOTE


def test_every_band_the_comparison_speaks_in_has_a_resident():
    """A band missing from the table would silently fall through to the general note,
    which is the quiet failure rather than the loud one."""
    assert set(subdrum.BAND_RESIDENTS) == {name for name, _, _ in instrument.BANDS}
    for band, residents in subdrum.BAND_RESIDENTS.items():
        assert residents, band
        assert set(residents) <= set(subdrum.DRUMS), band


def test_the_caveat_is_not_bolted_onto_the_stem_rows():
    """`compare` takes it as an argument and defaults to none, so the six stem cards read
    exactly as they did. A caveat about a second separation pass on a stem that had one
    pass would be false."""
    from app.domain.notes import StemKind

    mine = _profile(_tone(200), StemKind.GUITAR, relative_lufs=-10.0)
    theirs = _profile(_noise(seed=8, amplitude=0.4), StemKind.GUITAR, relative_lufs=-4.0)
    moves = instrument.compare(StemKind.GUITAR, mine, theirs)
    assert moves
    assert all("Bleed check:" not in m.detail for m in moves)


# --- presence, one level further in -----------------------------------------------------


def test_a_drum_the_reference_does_not_play_yields_no_moves_and_a_reason():
    mine = _profile(_tone(120, amplitude=0.3), "toms", relative_lufs=-8.0)
    theirs = _profile(_tone(120, amplitude=0.001), "toms", relative_lufs=-44.0)

    compared = subdrum.compare_all({"toms": mine}, {"toms": theirs})
    assert compared["toms"] == []
    why = subdrum.why_absent(mine, theirs)
    assert "reference" in why and "toms" in why
    assert "-44.0" in why or "-44" in why


def test_the_other_direction_names_your_side():
    """Which side matters to whoever reads it. "The reference has no toms" means the tool
    declined to copy something; "your mix has no toms" means it declined to invent one -
    and the second is the direction that makes noise, which is X0R-1127."""
    mine = _profile(_tone(120, amplitude=0.001), "toms", relative_lufs=-44.0)
    theirs = _profile(_tone(120, amplitude=0.3), "toms", relative_lufs=-8.0)

    assert subdrum.compare_all({"toms": mine}, {"toms": theirs})["toms"] == []
    why = subdrum.why_absent(mine, theirs)
    assert "your mix" in why


def test_both_sides_present_has_nothing_to_explain():
    mine = _profile(_tone(60), "kick", relative_lufs=-6.0)
    theirs = _profile(_tone(60), "kick", relative_lufs=-7.0)
    assert subdrum.why_absent(mine, theirs) == ""


def test_a_drum_your_own_drums_did_not_produce_is_not_a_row():
    """`compare_all` is keyed on your side: a sub-stem that was never written is not a
    drum the user has an opinion about."""
    theirs = _profile(_tone(120), "toms", relative_lufs=-8.0)
    assert subdrum.compare_all({}, {"toms": theirs}) == {}


# --- the profile format, which is criterion 11 ------------------------------------------


def test_a_snapshot_of_a_drum_gives_the_same_advice_as_the_audio():
    """The same contract `instrument` holds for stems, one level in: a reference's kick
    reduced to seven numbers has to produce the same moves as the kick itself. If it does
    not, a profile is a quietly different reference rather than a cheaper one."""
    mine = _profile(_tone(70, amplitude=0.2), "kick", relative_lufs=-9.0)
    theirs = _profile(_noise(amplitude=0.45, seed=9), "kick", relative_lufs=-3.0)

    from_audio = instrument.compare("kick", mine, theirs, subdrum.words("kick"))
    rebuilt = subdrum.from_snapshot_all(subdrum.snapshot_all({"kick": theirs}))["kick"]
    from_numbers = instrument.compare("kick", mine, rebuilt, subdrum.words("kick"))

    assert [(m.dimension, m.band, m.suggested) for m in from_audio] == [
        (m.dimension, m.band, m.suggested) for m in from_numbers
    ]


def test_an_unknown_drum_in_a_saved_profile_is_skipped_not_raised_on():
    rebuilt = subdrum.from_snapshot_all(
        {"kick": {"relative_lufs": -6.0, "present": True}, "cowbell": {"present": True}}
    )
    assert set(rebuilt) == {"kick"}


def test_a_reference_profile_can_hold_the_four_drums(tmp_path):
    """Criterion 11. The format ships with the comparison rather than after it, because a
    comparison released against a profile that cannot hold what it measured means two
    formats in the wild and a migration."""
    from app.services.mastering.profile import capture, load, save

    drums = subdrum.snapshot_all(
        {"kick": _profile(_tone(60), "kick"), "snare": _profile(_noise(seed=1), "snare")}
    )
    captured = capture(_noise(seconds=3, seed=2), SR, "a record", drums=drums)
    assert captured.has_drums is True

    path = save(captured, tmp_path)
    again = load(path)
    assert sorted(again.drums) == ["kick", "snare"]
    assert again.drums["kick"]["relative_lufs"] == drums["kick"]["relative_lufs"]
    assert again.drums["kick"]["bands"] == drums["kick"]["bands"]


def test_a_profile_saved_before_this_existed_still_loads(tmp_path):
    """Not version-gated, on purpose: adding an optional field does not make an older file
    unreadable, and `version` is only for the changes that do."""
    import json

    from app.services.mastering.profile import ReferenceProfile, load

    path = tmp_path / "old.json"
    path.write_text(
        json.dumps({"name": "old", "version": 1, "lufs": -9.0}), encoding="utf-8"
    )
    old = load(path)
    assert isinstance(old, ReferenceProfile)
    assert old.drums == {} and old.has_drums is False
    assert old.has_instruments is False


def test_carrying_the_drums_is_more_than_carrying_the_stems():
    """A profile can hold six stems and not the four drums inside one of them, which is
    the usual case - so the two questions are asked separately everywhere."""
    from app.services.mastering.profile import ReferenceProfile

    stems_only = ReferenceProfile(name="x", instruments={"drums": {"present": True}})
    assert stems_only.has_instruments is True
    assert stems_only.has_drums is False


# --- what it costs, which has to be said before it is paid ------------------------------


def test_the_cost_scales_with_the_audio_and_with_how_many_sides_are_left():
    both = subdrum.estimate_seconds(120, sides=2)
    one = subdrum.estimate_seconds(120, sides=1)
    assert both == pytest.approx(one * 2)
    assert one > 0
    # Nothing left to do is free, which is what makes opening it twice instant.
    assert subdrum.estimate_seconds(120, sides=0) == 0.0


def test_the_four_drums_are_named_in_the_order_a_kit_is_read_in():
    """Kick and snare first, because they are the two a user came to compare. The order
    is the order the rows render in, so it is part of the screen."""
    assert subdrum.DRUMS == ("kick", "snare", "cymbals", "toms")
    assert set(subdrum.DRUM_WORDS) == set(subdrum.DRUMS)


def test_the_words_agree_with_their_verbs():
    """"cymbals ring", "the kick sits". A verb that does not agree reads as a machine
    wrote the sentence, which on a screen full of advice is the wrong impression."""
    assert subdrum.words("kick") == ("kick", False)
    assert subdrum.words("cymbals")[1] is True
    assert subdrum.words("toms")[1] is True


# --- a finding's `measured` is the gap that was found ------------------------------------


def test_every_finding_reports_the_gap_it_found_even_when_no_dial_closes_it():
    """Found by printing a real per-drum comparison, not by a test.

    Three rows left `measured` at zero: punch, pan, and the "already more even" half of
    dynamics. All three are notes rather than dials, and the field went unread until the
    drums card started showing it - at which point the response said "yours 12.1, theirs
    14.7, measured 0.0", which is the comparison contradicting itself in its own JSON.

    `measured` is the gap that was found. Whether anything closes it is `control`'s job.
    """
    from app.domain.notes import StemKind

    mine = _profile(_tone(200, amplitude=0.4), StemKind.DRUMS, relative_lufs=-6.0)
    theirs = _profile(_noise(seed=11, amplitude=0.3, width=1.2), StemKind.DRUMS, -6.2)
    mine.crest_db, theirs.crest_db = 12.0, 18.0
    mine.dynamic_range_db, theirs.dynamic_range_db = 9.0, 19.0
    mine.pan, theirs.pan = -0.4, 0.3
    mine.width, theirs.width = 0.6, 0.9

    by_dimension = {m.dimension: m for m in instrument.compare(StemKind.DRUMS, mine, theirs)}

    assert by_dimension["punch"].measured == pytest.approx(6.0)
    assert by_dimension["pan"].measured == pytest.approx(0.7)
    # Yours swings less than theirs, so this is the branch with nothing to suggest.
    assert by_dimension["dynamics"].measured == pytest.approx(-10.0)
    assert by_dimension["dynamics"].suggested == 0.0


def test_a_measured_gap_is_never_zero_on_a_row_that_exists():
    """The property behind the three fixes, so a seventh dimension cannot repeat it: a
    row only appears when something crossed a threshold, so a row reporting a zero gap is
    a row reporting that it should not be there."""
    from app.domain.notes import StemKind

    mine = _profile(_tone(300, amplitude=0.35), StemKind.GUITAR, relative_lufs=-8.0)
    theirs = _profile(_noise(seed=12, amplitude=0.25, width=1.4), StemKind.GUITAR, -3.0)
    mine.crest_db, theirs.crest_db = 10.0, 16.0
    mine.pan, theirs.pan = -0.3, 0.4
    mine.width, theirs.width = 0.5, 0.95

    for move in instrument.compare(StemKind.GUITAR, mine, theirs):
        assert move.measured != 0.0, f"{move.dimension} {move.band}: {move.headline}"
