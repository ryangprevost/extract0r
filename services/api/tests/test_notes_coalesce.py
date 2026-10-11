"""Putting split notes back together. X0R-1329.

Separation leaves transcription's recall at 1.000 and its precision at 0.462 - on a
synthetic chord part through demucs and basic-pitch, 52 notes where 24 were played. Played
back on the instrument that recorded them nobody notices; played on a supersaw, every
invented note is an audible wrong one.

The two obvious filters were measured and rejected, and the tests below carry the reasons so
nobody re-adds them. What survived is a merge, and the merge needed a second condition that
the first version did not have.
"""

from __future__ import annotations

import pytest

from app.domain.notes import FRAGMENT_RATIO, MAX_FRAGMENT_GAP_S, NoteEvent, coalesce


def n(start: float, end: float, pitch: int = 60, **kw) -> NoteEvent:
    return NoteEvent(start_s=start, end_s=end, pitch=pitch, **kw)


# --- what it fixes -----------------------------------------------------------------------


def test_a_held_note_broken_in_two_becomes_one():
    merged = coalesce([n(0.0, 0.9), n(0.95, 1.1)])

    assert len(merged) == 1
    assert merged[0].start_s == 0.0
    assert merged[0].end_s == pytest.approx(1.1)


def test_several_fragments_of_one_note_collapse_together():
    merged = coalesce([n(0.0, 0.8), n(0.85, 0.95), n(1.0, 1.1), n(1.15, 1.25)])

    assert len(merged) == 1
    assert merged[0].end_s == pytest.approx(1.25)


def test_overlapping_fragments_merge_too():
    """basic-pitch emits these; a negative gap is still one note."""
    assert len(coalesce([n(0.0, 0.9), n(0.7, 1.0)])) == 1


# --- what it must not break --------------------------------------------------------------


def test_a_repeated_note_keeps_both_onsets():
    """The failure the first version had, and the reason there is a ratio at all.

    A part that repeats a chord across two bars puts two real onsets of the same pitch a few
    tens of milliseconds apart. Merging on the gap alone ate one of them: measured recall
    fell from 1.000 to 0.917 merging only overlaps, and to 0.875 at a 0.2 s gap. The
    docstring on `coalesce` asserted that merging could not lose an onset, until the sweep
    said otherwise.
    """
    merged = coalesce([n(0.0, 0.95), n(1.0, 1.95)])

    assert len(merged) == 2


def test_two_different_pitches_are_never_merged():
    assert len(coalesce([n(0.0, 0.9, 60), n(0.92, 1.0, 62)])) == 2


def test_a_distant_fragment_is_left_alone():
    assert len(coalesce([n(0.0, 0.9), n(0.9 + MAX_FRAGMENT_GAP_S + 0.05, 1.3)])) == 2


def test_the_ratio_is_what_decides_and_not_the_gap():
    """Same gap, different lengths: one is a piece, the other is the next note."""
    gap = 0.05
    piece = coalesce([n(0.0, 1.0), n(1.0 + gap, 1.0 + gap + 0.2)])
    repeat = coalesce([n(0.0, 1.0), n(1.0 + gap, 1.0 + gap + 1.0)])

    assert len(piece) == 1
    assert len(repeat) == 2


def test_the_ratio_boundary_is_where_it_says_it_is():
    held = 1.0
    just_under = coalesce([n(0.0, held), n(1.01, 1.01 + held * FRAGMENT_RATIO * 0.9)])
    just_over = coalesce([n(0.0, held), n(1.01, 1.01 + held * FRAGMENT_RATIO * 1.1)])

    assert len(just_under) == 1
    assert len(just_over) == 2


# --- the filters that were measured and rejected -----------------------------------------


def test_this_is_a_merge_and_not_a_confidence_filter():
    """A confidence floor is worthless on this failure and the numbers say so: the invented
    notes scored a *higher* median confidence than the real ones, 0.710 against 0.668. A
    floor at 0.6 dropped an eighth of the real notes and removed none of the invented.

    So a low-confidence note that is nobody's fragment survives here, deliberately.
    """
    kept = coalesce([n(0.0, 0.9, 60, confidence=0.05)])

    assert len(kept) == 1
    assert kept[0].confidence == 0.05


def test_this_is_not_a_minimum_length_filter():
    """The other rejected one: it worked a little and cost too much - precision 0.600 to
    0.704, recall down to 0.792. A short note on its own is a short note."""
    assert len(coalesce([n(0.0, 0.02, 60)])) == 1


# --- the shape of the result -------------------------------------------------------------


def test_the_longer_side_supplies_velocity_and_confidence():
    merged = coalesce(
        [
            n(0.0, 0.9, 60, velocity=100, confidence=0.8),
            n(0.95, 1.0, 60, velocity=20, confidence=0.3),
        ]
    )

    assert merged[0].velocity == 100
    assert merged[0].confidence == 0.8


def test_the_result_comes_back_in_time_order():
    merged = coalesce([n(2.0, 2.5, 64), n(0.0, 0.5, 60), n(1.0, 1.5, 62)])

    assert [x.start_s for x in merged] == [0.0, 1.0, 2.0]


def test_nothing_in_is_nothing_out():
    assert coalesce([]) == []
