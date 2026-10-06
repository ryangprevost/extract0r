"""The chat box, held to the two things that make it honest.

It must do what was asked, and it must say what the measurement thinks of that. A box
that only did the first is a worse version of the faders; one that only did the second is
a worse version of the comparison.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.mastering import ask

STUDIO = Path(__file__).resolve().parents[3] / "apps" / "studio" / "wwwroot"

STEMS = ("vocals", "bass", "drums", "guitar", "piano", "other")


def lanes(**overrides) -> dict:
    """Six stems at rest, with anything named moved."""
    out = {
        s: {"gain_db": 0.0, "width": 1.0, "compress_db": 0.0, "sidechain_db": 0.0}
        for s in STEMS
    }
    for stem, values in overrides.items():
        out[stem].update(values)
    return out


def by_control(answer, control):
    return [c for c in answer.changes if c.control == control]


# --- the ask itself ------------------------------------------------------------------------


def test_a_little_bassier_moves_the_bass():
    answer = ask.interpret("I want this song a little bassier", lanes=lanes())
    assert answer.understood
    moved = by_control(answer, "gain_db")
    assert [c.stem for c in moved] == ["bass"]
    assert moved[0].delta == pytest.approx(0.5)


def test_a_little_is_half_of_plain_and_a_lot_is_double():
    plain = ask.interpret("more bass", lanes=lanes()).changes[0].delta
    little = ask.interpret("a little more bass", lanes=lanes()).changes[0].delta
    lots = ask.interpret("a lot more bass", lanes=lanes()).changes[0].delta
    assert little == pytest.approx(plain / 2)
    assert lots == pytest.approx(plain * 2)


def test_naming_a_part_with_no_verb_means_more_of_it():
    assert ask.interpret("vocal", lanes=lanes()).changes[0].delta > 0


def test_a_direction_word_is_obeyed():
    assert ask.interpret("less bass", lanes=lanes()).changes[0].delta < 0
    assert ask.interpret("turn the drums down", lanes=lanes()).changes[0].delta < 0


def test_guitars_pop_moves_level_and_that_part_s_presence():
    answer = ask.interpret("make the guitars pop", lanes=lanes())
    assert answer.understood
    assert {(c.control, c.stem) for c in answer.changes} == {
        ("gain_db", "guitar"),
        ("tone_presence_db", "guitar"),
    }
    # Most of it on the level, a little on the presence - the recipe, not an accident.
    gain = by_control(answer, "gain_db")[0].delta
    presence = by_control(answer, "tone_presence_db")[0].delta
    assert gain > presence > 0


def test_a_quality_with_no_part_asks_which_part():
    answer = ask.interpret("make it pop", lanes=lanes())
    assert not answer.understood
    assert "which part" in answer.reply.lower()
    assert answer.suggestions


def test_a_quality_can_be_reversed():
    answer = ask.interpret("the vocal should sit back", lanes=lanes())
    assert answer.understood
    assert all(c.delta < 0 for c in answer.changes)


def test_a_tonal_word_moves_every_part():
    """One band on all six is what a master EQ is, in controls that already exist."""
    answer = ask.interpret("less mud", lanes=lanes())
    assert answer.understood
    assert {c.stem for c in answer.changes} == set(STEMS)
    assert all(c.control == "tone_low_mid_db" for c in answer.changes)
    assert all(c.delta < 0 for c in answer.changes)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("muddy", -1),          # naming a complaint means you want less of it
        ("less mud", -1),       # and saying so out loud means the same thing
        ("too much mud", -1),
        ("more mud", +1),       # odd to ask for, and it must still mean what it says
        ("harsh", -1),
        ("less harsh", -1),
    ],
)
def test_a_complaint_word_goes_the_way_the_complaint_does(text, expected):
    """The bug this is here for: "less mud" once *added* low-mid.

    A complaint word pulls its two signs apart - more mud is more low-mid, and somebody
    typing "muddy" wants less of it - and conflating the two inverts exactly the phrase a
    user is most likely to type.
    """
    answer = ask.interpret(text, lanes=lanes())
    assert answer.understood, answer.reply
    assert all((c.delta > 0) == (expected > 0) for c in answer.changes), answer.reply


def test_mud_and_body_are_the_same_band_opposite_ways():
    mud = ask.interpret("muddy", lanes=lanes()).changes[0]
    body = ask.interpret("warmer", lanes=lanes()).changes[0]
    assert mud.control == body.control
    assert mud.delta == pytest.approx(-body.delta)


def test_widening_leaves_the_bass_alone():
    """The reference match holds the bass centred on purpose; a sentence may not undo it."""
    answer = ask.interpret("wider", lanes=lanes())
    assert answer.understood
    assert "bass" not in {c.stem for c in answer.changes}
    assert all(c.to > 1.0 for c in answer.changes)


def test_a_longer_phrase_beats_a_shorter_one_inside_it():
    """"low end" is the bass, not the weight band."""
    answer = ask.interpret("more low end", lanes=lanes())
    assert [c.stem for c in answer.changes] == ["bass"]


def test_a_word_inside_another_word_is_not_a_match():
    """"air" must not match "chair", or a sentence about a chair lifts 8 kHz."""
    answer = ask.interpret("the chair is repaired", lanes=lanes())
    assert not answer.understood


# --- the duck, which is the one control that only goes one way ---------------------------


def test_a_process_beats_a_part_when_a_sentence_names_both():
    """"make the bass pump a lot" matches "bass" and "pump" at four letters each.

    Read as the part it came out as a level change, which is not what anybody who typed
    the word "pump" meant.
    """
    answer = ask.interpret("make the bass pump a lot", lanes=lanes())
    assert [c.control for c in answer.changes] == ["sidechain_db"]
    assert answer.changes[0].delta == pytest.approx(2.0)


def test_the_duck_is_on_the_bass_whatever_the_sentence_says():
    """The bass against the kick is the only pair this application measures."""
    answer = ask.interpret("more pump", lanes=lanes())
    assert [c.stem for c in answer.changes] == ["bass"]


def test_the_reply_never_prints_a_field_name():
    """It said "sidechain_db +1.0 dB" at a user before this."""
    for text in ask.EXAMPLES + ("more pump", "steadier", "wider"):
        reply = ask.interpret(text, lanes=lanes()).reply
        assert "_db" not in reply, reply


def test_taking_away_a_duck_that_is_not_there_says_so():
    """"already as far as typing will take it" is true and useless."""
    answer = ask.interpret("less pumping", lanes=lanes())
    assert not answer.understood
    assert "already at rest" in answer.reply
    assert "only ever adds it" in answer.reply


# --- two things in one sentence ------------------------------------------------------


def test_two_requests_in_one_sentence_both_happen():
    """Before this, the longer verb won and the rest was silently dropped."""
    answer = ask.interpret("less bass and more drums", lanes=lanes())
    assert answer.understood
    assert {(c.stem, c.delta > 0) for c in answer.changes} == {
        ("bass", False),
        ("drums", True),
    }


def test_a_modifier_stated_once_governs_both_halves():
    """"up a lot" sits at the end and means it about both."""
    answer = ask.interpret("bass and drums up a lot", lanes=lanes())
    deltas = {c.stem: c.delta for c in answer.changes}
    assert deltas["bass"] == pytest.approx(deltas["drums"])
    assert deltas["bass"] == pytest.approx(2.0)


def test_each_half_keeps_its_own_direction_when_it_states_one():
    answer = ask.interpret("less bass and more drums", lanes=lanes())
    deltas = {c.stem: c.delta for c in answer.changes}
    assert deltas["bass"] < 0 < deltas["drums"]


def test_two_asks_on_the_same_control_add_up():
    """The second half sees the faders where the first half left them."""
    answer = ask.interpret("more bass and more bass", lanes=lanes())
    assert answer.changes[-1].to == pytest.approx(2.0)


def test_a_split_that_does_not_help_is_not_taken():
    """"sit back" contains no conjunction worth splitting; neither does this.

    If either half fails to parse, the sentence is read whole - which is what stops a
    conjunction inside a phrase from breaking a request that would otherwise work.
    """
    answer = ask.interpret("a little more bass and", lanes=lanes())
    assert answer.understood
    assert [c.stem for c in answer.changes] == ["bass"]


# --- the limits -------------------------------------------------------------------------


def test_typing_the_same_thing_forever_stops():
    """A chat box can be asked nine times, and somebody will."""
    current = lanes()
    base = {k: dict(v) for k, v in current.items()}
    for _ in range(9):
        answer = ask.interpret("more bass", lanes=current, baseline=base)
        for change in answer.changes:
            current[change.stem][change.control] = change.to
    assert current["bass"]["gain_db"] == pytest.approx(ask.CEILING["gain_db"])


def test_the_ceiling_is_measured_from_where_the_conversation_started():
    """Somebody who dragged the fader up by hand first is not refused their first ask."""
    current = lanes(bass={"gain_db": 5.0})
    answer = ask.interpret(
        "more bass", lanes=current, baseline={k: dict(v) for k, v in current.items()}
    )
    assert answer.understood
    assert answer.changes[0].to == pytest.approx(6.0)


def test_a_control_never_leaves_its_own_range():
    """The fader's range wins over this box's step, both ways."""
    low, high, _ = ask.limit_of("gain_db")
    current = lanes(bass={"gain_db": high - 0.2})
    answer = ask.interpret("a lot more bass", lanes=current, baseline=lanes())
    assert answer.changes[0].to <= high
    assert answer.changes[0].clamped


def test_running_out_of_room_says_so_rather_than_doing_nothing():
    current = lanes(bass={"gain_db": ask.CEILING["gain_db"]})
    answer = ask.interpret("more bass", lanes=current, baseline=lanes())
    assert not answer.understood
    assert "as far as typing will take it" in answer.reply


def test_nothing_separated_yet_is_explained():
    answer = ask.interpret("more bass", lanes={})
    assert not answer.understood
    assert "separate a track first" in answer.reply


# --- the half that makes it honest ----------------------------------------------------------


def comparison(stem: str, control: str, measured: float, label: str = "bass") -> dict:
    return {
        "reference_name": "Reference Song",
        "instruments": [
            {
                "stem": stem,
                "label": label,
                "moves": [{"control": control, "measured": measured, "band": ""}],
            }
        ],
    }


def test_it_says_where_the_measurement_had_you():
    answer = ask.interpret(
        "a little bassier",
        lanes=lanes(),
        comparison=comparison("bass", "gain_db", -1.8),
    )
    assert answer.understood
    assert "1.8 dB over Reference Song's" in answer.reply


def test_it_says_when_the_ask_moves_away_from_the_reference():
    """The whole point. Yours is already louder; you asked for louder still."""
    answer = ask.interpret(
        "more bass", lanes=lanes(), comparison=comparison("bass", "gain_db", -1.8)
    )
    assert "moves away from it" in answer.reply


def test_it_says_when_the_ask_agrees_with_the_reference():
    answer = ask.interpret(
        "more bass", lanes=lanes(), comparison=comparison("bass", "gain_db", +1.8)
    )
    assert "the way the comparison was already pointing" in answer.reply


def test_with_no_comparison_it_simply_does_not_claim_one():
    answer = ask.interpret("more bass", lanes=lanes())
    assert answer.understood
    assert "comparison" not in answer.reply


def test_a_gap_too_small_to_mention_is_not_mentioned():
    answer = ask.interpret(
        "more bass", lanes=lanes(), comparison=comparison("bass", "gain_db", 0.05)
    )
    assert "comparison put" not in answer.reply


# --- saying no ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "make it sound professional",
        "give me an instrumental",
        "can you speed it up",
        "add reverb to the vocal",
    ],
)
def test_the_things_it_cannot_do_get_a_straight_answer(text):
    answer = ask.interpret(text, lanes=lanes())
    assert not answer.understood
    assert not answer.changes
    # Not a shrug: each one names the nearest thing that does exist.
    assert len(answer.reply) > 80


def test_nonsense_lists_what_it_does_know():
    answer = ask.interpret("asdfgh qwerty", lanes=lanes())
    assert not answer.understood
    assert answer.suggestions
    assert "presence" in answer.reply


def test_an_empty_ask_is_not_an_error():
    answer = ask.interpret("   ", lanes=lanes())
    assert not answer.understood
    assert answer.suggestions


def test_every_example_it_offers_actually_works():
    """The examples are shown to a user as things to type. They had better parse."""
    for example in ask.EXAMPLES:
        answer = ask.interpret(example, lanes=lanes())
        assert answer.understood, f"{example!r} -> {answer.reply}"
        assert answer.changes


# --- the same numbers in two languages --------------------------------------------------


def test_the_controls_match_the_page_s():
    """`LIMITS` mirrors `MOVE_CONTROLS` in instruments.js, and only one has a test runner."""
    source = (STUDIO / "instruments.js").read_text(encoding="utf-8")
    block = re.search(r"const MOVE_CONTROLS = \{(.*?)\n\};", source, re.S)
    assert block, "MOVE_CONTROLS is no longer where this test looks"

    page = {}
    for name, body in re.findall(r"(\w+):\s*\{([^}]*)\}", block.group(1)):
        fields = dict(
            (k, float(v))
            for k, v in re.findall(r"(\w+):\s*(-?[\d.]+)", body)
        )
        page[name] = (fields["min"], fields["max"], fields["off"])

    assert page == ask.LIMITS


def test_every_target_names_a_control_that_exists():
    for target in ask.TARGETS:
        assert target.control in ask.LIMITS, target.label
    for label, recipe, _ in ask.QUALITIES.values():
        for control, _share in recipe:
            assert control in ask.LIMITS, label
