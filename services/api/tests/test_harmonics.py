"""Tests for overtone removal.

A distorted guitar is mostly harmonics, and a polyphonic transcriber reports them as
notes. The rule has to remove those without eating real notes played high.
"""

from __future__ import annotations

from app.domain.harmonics import remove_harmonics
from app.domain.notes import NoteEvent


def note(pitch: int, start: float = 0.0, velocity: int = 100, length: float = 0.4):
    return NoteEvent(start_s=start, end_s=start + length, pitch=pitch, velocity=velocity)


def test_a_quiet_octave_above_a_loud_root_is_an_overtone():
    root = note(40, velocity=110)
    octave = note(52, velocity=60)
    kept, dropped = remove_harmonics([root, octave])

    assert [n.pitch for n in kept] == [40]
    assert [n.pitch for n in dropped] == [52]


def test_the_octave_and_a_fifth_is_also_an_overtone():
    kept, dropped = remove_harmonics([note(40, velocity=110), note(59, velocity=50)])
    assert [n.pitch for n in kept] == [40]
    assert [n.pitch for n in dropped] == [59]


def test_two_octaves_up_is_an_overtone():
    kept, dropped = remove_harmonics([note(40, velocity=110), note(64, velocity=40)])
    assert [n.pitch for n in dropped] == [64]


def test_a_louder_note_an_octave_up_is_kept():
    """A melody played above a quiet accompaniment is not an overtone of it."""
    kept, dropped = remove_harmonics([note(40, velocity=45), note(52, velocity=115)])
    assert sorted(n.pitch for n in kept) == [40, 52]
    assert dropped == []


def test_a_power_chord_survives():
    """Root plus fifth is 7 semitones - not a harmonic interval, and very common."""
    kept, _ = remove_harmonics([note(38, velocity=110), note(45, velocity=105)])
    assert sorted(n.pitch for n in kept) == [38, 45]


def test_a_full_triad_survives():
    kept, _ = remove_harmonics(
        [note(40, velocity=100), note(44, velocity=98), note(47, velocity=96)]
    )
    assert len(kept) == 3


def test_notes_at_different_times_are_unrelated():
    """An octave played a bar later is a note, not an overtone."""
    kept, dropped = remove_harmonics(
        [note(40, start=0.0, velocity=110), note(52, start=2.0, velocity=50)]
    )
    assert sorted(n.pitch for n in kept) == [40, 52]
    assert dropped == []


def test_an_overtone_of_an_overtone_is_still_dropped():
    notes = [note(40, velocity=120), note(52, velocity=80), note(64, velocity=40)]
    kept, dropped = remove_harmonics(notes)
    assert [n.pitch for n in kept] == [40]
    assert sorted(n.pitch for n in dropped) == [52, 64]


def test_nothing_is_lost_overall():
    notes = [note(40, velocity=110), note(52, velocity=60), note(45, velocity=100)]
    kept, dropped = remove_harmonics(notes)
    assert len(kept) + len(dropped) == len(notes)


def test_empty_input_is_handled():
    assert remove_harmonics([]) == ([], [])
