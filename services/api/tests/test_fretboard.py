from __future__ import annotations

import pytest

from app.domain.notes import NoteEvent
from app.domain.tab.fretboard import (
    STANDARD_BASS,
    STANDARD_GUITAR,
    SolverConfig,
    UnplayableError,
    candidate_positions,
    solve,
)


def note(pitch: int, start: float = 0.0, length: float = 0.25) -> NoteEvent:
    return NoteEvent(start_s=start, end_s=start + length, pitch=pitch)


def test_open_low_e_is_string_zero_fret_zero():
    positions = candidate_positions(note(40), STANDARD_GUITAR)
    assert (0, 0) in [(p.string, p.fret) for p in positions]


def test_middle_pitch_has_several_candidates():
    # E4 (64) is playable open on the high E and fretted on four other strings.
    positions = candidate_positions(note(64), STANDARD_GUITAR)
    assert len(positions) >= 4
    assert all(0 <= p.fret <= STANDARD_GUITAR.fret_count for p in positions)


def test_pitch_below_the_instrument_is_unplayable():
    with pytest.raises(UnplayableError):
        solve([note(20)], STANDARD_GUITAR)


def test_solver_prefers_staying_in_position():
    # An ascending line that could be played across strings or by leaping up one string.
    line = [note(pitch, i * 0.25) for i, pitch in enumerate((52, 54, 55, 57, 59))]
    shapes = solve(line, STANDARD_GUITAR)
    anchors = [s.anchor for s in shapes if s.anchor is not None]
    assert max(anchors) - min(anchors) <= 4, "hand wandered more than a fret-hand span"


def test_chord_notes_land_on_distinct_strings():
    # An E minor triad struck together.
    chord = [note(p, 0.0) for p in (52, 55, 59)]
    shapes = solve(chord, STANDARD_GUITAR)
    assert len(shapes) == 1
    strings = [p.string for p in shapes[0].positions]
    assert len(set(strings)) == len(strings)


def test_every_note_is_assigned():
    line = [note(p, i * 0.25) for i, p in enumerate((40, 45, 50, 55, 59, 64))]
    shapes = solve(line, STANDARD_GUITAR)
    assigned = sum(len(s.positions) for s in shapes)
    assert assigned == len(line)


def test_bass_solves_against_bass_tuning():
    line = [note(p, i * 0.5) for i, p in enumerate((28, 33, 38, 43))]
    shapes = solve(line, STANDARD_BASS)
    assert all(p.fret == 0 for s in shapes for p in s.positions), "open strings expected"


def test_capo_shifts_the_playable_window():
    cfg = SolverConfig(capo=3)
    shapes = solve([note(43)], STANDARD_GUITAR, cfg)
    assert shapes[0].positions[0].fret >= 3
