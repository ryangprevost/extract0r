"""Editing notes and beats. Sprint 6.

The claims: notes kept in beats come back at any tempo exactly where they were; quantise
moves a note the chosen share of the way and no further; swing moves only off-sixteenths;
drum strokes survive the round trip through notes; and an edit that changes nothing is not
called an edit.
"""

from __future__ import annotations

import pytest

from app.domain.notes import NoteEvent
from app.services.drums.detect import Hit
from app.services.synth import edit
from app.services.synth.edit import BeatNote
from app.services.synth.retempo import move_notes


def test_beats_come_back_at_any_tempo():
    notes = [NoteEvent(1.0, 1.5, 40, 90), NoteEvent(2.0, 2.25, 43, 100)]
    beats = edit.to_beats(notes, first_beat_s=0.25, bpm=120.0)
    assert beats[0].beat == pytest.approx(1.5) and beats[0].length == pytest.approx(1.0)
    again = edit.to_seconds(beats, 0.25, 120.0)
    assert [(n.start_s, n.end_s) for n in again] == [(1.0, 1.5), (2.0, 2.25)]


def test_a_part_through_beats_is_the_same_as_a_part_moved():
    """Re-playing an unedited part at a new tempo went through `move_notes`; an edited one
    goes through beats. The two must agree, or editing nothing would move the part."""
    notes = [NoteEvent(0.7, 1.1, 40, 90), NoteEvent(3.3, 3.4, 47, 80)]
    first, src, dst = 0.12, 170.0, 128.0
    scale = src / dst
    moved = move_notes(notes, scale)
    via = edit.to_seconds(edit.to_beats(notes, first, src), first * scale, dst)
    for a, b in zip(moved, via, strict=True):
        assert a.start_s == pytest.approx(b.start_s) and a.end_s == pytest.approx(b.end_s)


@pytest.mark.parametrize("strength, expected", [(1.0, 1.0), (0.5, 1.05), (0.0, 1.1)])
def test_quantise_moves_a_note_the_chosen_share_of_the_way(strength, expected):
    out = edit.quantize([BeatNote(1.1, 0.4, 60)], 0.25, strength)
    assert out[0].beat == pytest.approx(expected)
    assert out[0].length == pytest.approx(0.4)


def test_quantising_the_ends_snaps_where_notes_stop():
    out = edit.quantize([BeatNote(1.02, 0.43, 60)], 0.25, 1.0, ends=True)
    assert (out[0].beat, out[0].length) == (pytest.approx(1.0), pytest.approx(0.5))


def test_triplet_grids_are_triplets():
    out = edit.quantize([BeatNote(0.3, 0.2, 60), BeatNote(0.7, 0.2, 60)],
                        edit.GRIDS["1/8 triplet"])
    assert [n.beat for n in out] == [pytest.approx(1 / 3), pytest.approx(2 / 3)]


def test_swing_moves_only_the_off_sixteenths():
    notes = [BeatNote(0.0, 0.2, 60), BeatNote(0.25, 0.2, 60), BeatNote(0.5, 0.2, 60),
             BeatNote(0.6, 0.2, 60)]
    out = edit.groove(notes, 1.0)
    assert out[0].beat == 0.0 and out[2].beat == 0.5
    assert out[1].beat == pytest.approx(0.25 + 1 / 12)
    assert out[3].beat == 0.6                      # off the grid: left as played


def test_transpose_stays_inside_midi():
    out = edit.transpose([BeatNote(0, 1, 120), BeatNote(0, 1, 5)], 12)
    assert [n.pitch for n in out] == [127, 17]


def test_drum_strokes_survive_the_round_trip_through_notes():
    hits = [Hit(time_s=0.5, kinds=["kick", "hihat"], strength=1.0),
            Hit(time_s=1.0, kinds=["snare"], strength=0.5),
            Hit(time_s=1.25, kinds=["cymbals"], strength=0.25)]
    back = edit.notes_to_hits(edit.hits_to_notes(hits))
    assert [(h.time_s, sorted(h.kinds)) for h in back] == [
        (0.5, ["hihat", "kick"]), (1.0, ["snare"]), (1.25, ["hihat"])]
    assert back[1].strength == pytest.approx(0.5, abs=0.01)


def test_an_edit_that_changes_nothing_is_not_an_edit():
    played = [BeatNote(1.0, 0.5, 60, 100), BeatNote(2.0, 0.5, 62, 90)]
    assert not edit.differs(list(reversed(played)), played)
    assert edit.differs([BeatNote(1.0, 0.5, 61, 100), played[1]], played)


def test_a_note_is_never_shorter_than_a_64th():
    assert BeatNote.from_dict({"beat": 0, "length": 0.0001, "pitch": 60}).length == 1 / 16
