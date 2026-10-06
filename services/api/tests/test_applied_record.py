"""A dial that says "Applied" was applied. X0R-1405.

"Applied ✓" was decided by comparing the lane's value with the suggestion, which is right
whenever the suggestion asks for a move and wrong whenever it does not. A reference whose
guitars are already centred offers `pan: 0`, and 0 is also where pan sits when nobody has
touched it - so the row claimed credit for a move it had never made. Width at 1.0 and
dynamics at 0 have the same shape.

**What these tests are, and are not.** This project has no JavaScript runner, and adding
one for a two-point card would be a bigger decision than the card. So these read the
source and assert the structure that makes the defect impossible - the same technique as
`test_ask.test_the_controls_match_the_page_s`, which mirrors a constant across two
languages, and `test_language`, which parses the Studio's string literals.

They would not catch a logic error inside the expression. What they catch is the thing
that actually happened: somebody deciding "applied" from the value alone. The behaviour
itself was walked in a browser - untouched reads Apply, taking a no-op suggestion reads
Applied ✓, pressing again undoes it, and a normal suggestion is unaffected - and that walk
is written up on the card rather than pretended at here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parents[3] / "apps" / "studio" / "wwwroot"
SOURCE = (STUDIO / "instruments.js").read_text(encoding="utf-8")


def function_body(name: str) -> str:
    """One top-level function's source, by brace matching from its opening line."""
    start = SOURCE.index(f"function {name}(")
    depth, i = 0, SOURCE.index("{", start)
    for j in range(i, len(SOURCE)):
        if SOURCE[j] == "{":
            depth += 1
        elif SOURCE[j] == "}":
            depth -= 1
            if depth == 0:
                return SOURCE[start : j + 1]
    raise AssertionError(f"could not find the end of {name}")


def test_there_is_a_record_of_what_was_taken():
    """The lanes keep no record of their own, which is why the defect existed."""
    assert "const takenMoves = new Set()" in SOURCE
    assert "function markTaken(" in SOURCE


def test_applied_is_not_decided_by_the_value_alone():
    """The defect, as an assertion.

    The old expression was `Math.abs(current - wanted) <= step / 2`, full stop. Any
    rewrite that goes back to deciding from the value alone fails here.
    """
    body = function_body("refreshMoveButtons")
    applied = re.search(r"const applied =(.*?);", body, re.S)
    assert applied, "refreshMoveButtons no longer computes `applied`"
    expression = applied.group(1)

    assert "suggestsNothing(" in expression, (
        "nothing distinguishes a suggestion that asks for a move from one that does not"
    )
    assert "takenMoves.has(" in expression, (
        "the record of what was taken is not consulted"
    )


def test_a_suggestion_that_asks_for_nothing_is_recognised():
    """`suggestsNothing` compares against the control's own resting value, not zero.

    Width rests at 1.0, so a hard-coded zero would get that one wrong in the opposite
    direction - it would never recognise a no-op width suggestion at all.
    """
    body = function_body("suggestsNothing")
    assert ".off" in body, "the resting value is not read from MOVE_CONTROLS"
    assert "atSuggestion(" in body, "the comparison does not use the shared tolerance"


def test_the_tolerance_is_half_a_step_and_shared():
    """Both comparisons go through one function, so they cannot drift apart.

    The half-step tolerance exists because the slider quantises: a suggestion of +2.43 dB
    becomes 2.4 the moment it is applied. That bug shipped once on the whole-mix findings,
    and having two copies of the rule is how it would ship again.
    """
    body = function_body("atSuggestion")
    assert "step / 2" in body
    assert len(re.findall(r"step / 2", SOURCE)) == 1, "the tolerance is written twice"


@pytest.mark.parametrize(
    "route,marker",
    [
        ("the Apply button", 'markTaken(button.dataset.stem, control, !applied)'),
        ("dragging the slider", "markTaken(\n        slider.dataset.stem,"),
        ("the per-instrument reset", "markTaken(one.dataset.stem, control, false)"),
    ],
)
def test_every_route_to_a_value_updates_the_record(route, marker):
    """Three ways to reach the same value; all three must agree it was taken.

    Dragging the slider onto the suggested number is taking the suggestion - people do
    that, and being told "Apply" afterwards would be the original bug with its sign
    flipped.
    """
    assert marker in SOURCE, f"{route} does not update the record"


def test_a_fresh_comparison_forgets_what_was_taken():
    """Otherwise "Compare again" at a different budget inherits the last run's credit."""
    assert "function forgetTakenMoves(" in SOURCE
    assert "forgetTakenMoves();" in function_body("renderInstruments")


def test_the_slider_knows_what_was_suggested():
    """It did not before. The Apply button carried the number and the slider did not,
    so the slider could not tell whether a drag had landed on the suggestion."""
    assert "slider.dataset.suggested" in SOURCE
