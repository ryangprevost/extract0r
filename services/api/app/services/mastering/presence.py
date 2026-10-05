"""Whether an instrument is actually on a record.

Separation always returns a stem. Asked for a piano, a model that knows about pianos will
hand one back whether or not anybody played one — what comes out is bleed, reverb tail and
reconstruction error, sitting tens of LU under the mix. So "does this record have a piano"
is a question about *level*, and every part of this package that compares two recordings
has to ask it before it compares anything.

The rule lives here because it was previously written down three times and one of the
three was wrong. `instrument.compare` declined when either side was absent;
`critique` declined when either side was absent; `stem_match.has_counterpart` asked only
about the **reference**, so a source with no guitar matched against a reference whose
guitar stem was residue produced a request for +37 dB, capped at +9 — an audible lift
applied to an instrument that does not exist. Measured on a real pair during the pr0ducer
experiments, and the card is X0R-1127.

One definition, two directions, and a reason to be careful about which you want:

* `is_present` is about one recording.
* `comparable` is about a pair, and it is the one almost every caller wants. Matching
  needs *both* sides — theirs to copy from, yours to apply it to — and a missing either
  is a difference of arrangement rather than of mixing. The tool's whole brief is to nudge
  a mix toward a record, not to add parts the player did not play or remove parts they did.

This matters more from here on, not less. Per-drum comparison asks the same question four
more times, of a kick, a snare, cymbals and toms.
"""

from __future__ import annotations

#: How far under its own mix a stem has to sit before it is residue rather than an
#: instrument.
#:
#: Thirty LU is a long way down - a part this quiet contributes nothing a listener could
#: name. It is deliberately not tight: the cost of being wrong in one direction is
#: declining to match a very quiet real part, and in the other it is treating separation
#: residue as a part and acting on it. The second is far worse, because acting means
#: raising it.
ABSENT_BELOW_LU = -30.0


def is_present(relative_lufs: float | None) -> bool:
    """Whether a stem at this level under its own mix is an instrument or residue."""
    return relative_lufs is not None and relative_lufs >= ABSENT_BELOW_LU


def comparable(mine: float | None, theirs: float | None) -> bool:
    """Whether two recordings both contain the instrument enough to compare them.

    Both, not either. A reference that does not play the part has nothing to teach, and a
    source that does not play it has nothing to learn — and the second was the one being
    got wrong, in the direction that makes noise.
    """
    return is_present(mine) and is_present(theirs)


def why_not(mine: float | None, theirs: float | None, instrument: str) -> str:
    """A sentence for the report saying which side was empty, or empty when both are there.

    Which side matters to whoever reads it. "The reference has no piano" means the tool
    declined to copy something; "your mix has no piano" means it declined to invent one.
    """
    mine_there, theirs_there = is_present(mine), is_present(theirs)
    if mine_there and theirs_there:
        return ""
    if not mine_there and not theirs_there:
        return f"neither mix really contains {instrument}"
    if not theirs_there:
        return f"the reference has essentially no {instrument}"
    return (
        f"your mix has essentially no {instrument}, so there is nothing to apply this to "
        f"- matching would be raising separation residue"
    )
