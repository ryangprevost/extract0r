"""Observations about a recording that have no dial, as findings.

Two of them, from the Melodyne probe: how close to the grid a vocal sits (`tuning`) and
how often a part plays (`density`). Both are comparisons between two recordings and
neither has a control, because there is nothing in this application that tunes a vocal or
makes a bass play more often - and inventing either would be off-brief in two different
ways.

They are emitted as `InstrumentMove`s with an empty `control`, which is the shape `punch`
and the "already more even" half of `dynamics` already use. One way a finding looks, one
renderer, and the page needed no change to show them.
"""

from __future__ import annotations

import logging

import numpy as np

from app.domain.notes import StemKind
from app.services.mastering import density, tuning
from app.services.mastering.instrument import InstrumentMove

log = logging.getLogger(__name__)

#: Only a sung part can be in or out of tune, and only these stems carry one. Guitar and
#: piano are polyphonic, where a single f0 contour means nothing; `other` is a bag.
TUNED_STEMS = (StemKind.VOCALS,)


def observations(
    stem: StemKind,
    name: str,
    plural: bool,
    mine: np.ndarray | None,
    theirs: np.ndarray | None,
    sample_rate: int,
) -> list[InstrumentMove]:
    """Everything the contour and the onsets say about this pair, as findings."""
    out: list[InstrumentMove] = []
    if mine is None:
        return out

    out.extend(_density(stem, name, plural, mine, theirs, sample_rate))
    if stem in TUNED_STEMS:
        out.extend(_tuning(stem, name, mine, theirs, sample_rate))
    return out


def _density(stem, name, plural, mine, theirs, sample_rate) -> list[InstrumentMove]:
    try:
        ours = density.measure(mine, sample_rate)
        theirs_density = density.measure(theirs, sample_rate) if theirs is not None else None
    except Exception:
        log.info("could not measure how often %s plays", name, exc_info=True)
        return []

    said = density.compare(ours, theirs_density, name, plural)
    if not said or ours is None or theirs_density is None:
        return []
    return [
        InstrumentMove(
            stem=str(stem),
            dimension="density",
            headline=said.split(" - ")[0],
            detail=said,
            severity="slight",
            yours=round(ours.median_interval_s * 1000, 1),
            reference=round(theirs_density.median_interval_s * 1000, 1),
            measured=round(
                (ours.median_interval_s - theirs_density.median_interval_s) * 1000, 1
            ),
            suggested=0.0,
            control="",
            confident=False,
        )
    ]


def _tuning(stem, name, mine, theirs, sample_rate) -> list[InstrumentMove]:
    """Whether each side's vocal sits on a grid, and how tightly.

    Reported as a comparison and never as a verdict on one side alone: separation and
    pitch tracking both *add* spread, so "theirs is tighter than yours" is two numbers
    biased the same way, while "yours is 14 cents out" treats a biased number as
    absolute. Only the first is said.
    """
    try:
        ours = tuning.measure(mine, sample_rate)
        theirs_tuning = tuning.measure(theirs, sample_rate) if theirs is not None else None
    except Exception:
        log.info("could not read the pitch contour of %s", name, exc_info=True)
        return []

    if ours is None or theirs_tuning is None:
        return []
    if not ours.sung and not theirs_tuning.sung:
        # Neither side is sung, so nobody is missing a row they expected - an
        # instrumental, or a pair of rapped records. Explaining the absence of something
        # that was never going to be there is noise, and it showed up as exactly that:
        # comparing a track with itself produced a row saying why it had no tuning
        # comparison, on a test whose whole point is that a track against itself
        # suggests nothing.
        return []
    if not ours.sung or not theirs_tuning.sung:
        # One side sings and the other does not, which is the case where somebody *is*
        # missing a row they expected. Saying which side, and why, beats silence.
        empty = ours if not ours.sung else theirs_tuning
        whose = "your" if not ours.sung else "the reference's"
        return [
            InstrumentMove(
                stem=str(stem),
                dimension="tuning",
                headline=f"No tuning comparison for the {name}",
                detail=(
                    f"Not measured, because {whose} {name} {empty.declined}. A part that "
                    "is not sung on a scale cannot be in or out of tune, and calling one "
                    "flat would be the wrong thing to say about a person."
                ),
                severity="match",
                suggested=0.0,
                control="",
                confident=False,
            )
        ]

    gap = ours.median_cents - theirs_tuning.median_cents
    if abs(gap) < tuning.SAME_CENTS:
        return []
    tighter = gap > 0
    return [
        InstrumentMove(
            stem=str(stem),
            dimension="tuning",
            headline=(
                f"The reference's {name} sits "
                f"{'closer to' if tighter else 'further from'} the grid than yours"
            ),
            detail=(
                f"Theirs sits a median {theirs_tuning.median_cents:.0f} cents from its "
                f"own tuning and yours {ours.median_cents:.0f}, over "
                f"{theirs_tuning.voiced_frames} and {ours.voiced_frames} frames of "
                f"pitch. That record is tuned to A4 = {theirs_tuning.a4_hz:.1f} Hz "
                f"({theirs_tuning.a4_cents:+.0f} cents) and yours to "
                f"{ours.a4_hz:.1f} Hz ({ours.a4_cents:+.0f}), and each is measured "
                f"against its own. A figure near 4 cents usually means the vocal was "
                f"pitch-corrected. There is no control for this and there will not be "
                f"one. Read it as how close to the grid the vocal sits, not how well "
                f"anybody sings - vibrato and slides widen it without anyone being out "
                f"of tune - and as an upper bound, because separation and pitch tracking "
                f"both add spread and neither removes it. The comparison between the two "
                f"holds; either number on its own does not."
            ),
            severity="slight",
            yours=ours.median_cents,
            reference=theirs_tuning.median_cents,
            measured=round(gap, 1),
            suggested=0.0,
            control="",
            confident=False,
        )
    ]
