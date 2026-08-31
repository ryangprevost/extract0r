from __future__ import annotations

import pytest

from app.domain.notes import NoteEvent
from app.domain.tab.fretboard import (
    STANDARD_BASS,
    STANDARD_GUITAR,
    SolverConfig,
    Tuning,
    UnplayableError,
    UnplayablePolicy,
    candidate_positions,
    solve,
    solve_with_report,
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


def test_out_of_range_pitch_raises_under_the_strict_policy():
    cfg = SolverConfig(unplayable=UnplayablePolicy.RAISE)
    with pytest.raises(UnplayableError):
        solve([note(20)], STANDARD_GUITAR, cfg)


def test_out_of_range_pitch_is_dropped_by_default():
    """Separation bleed is routine, so one stray note must not abort a transcription."""
    report = solve_with_report([note(31, 0.0), note(52, 0.5)], STANDARD_GUITAR)

    assert len(report.shapes) == 1, "the playable note should still be solved"
    assert [n.pitch for n in report.dropped] == [31]
    assert report.folded == []


def test_fold_policy_shifts_by_octaves_and_keeps_the_pitch_class():
    cfg = SolverConfig(unplayable=UnplayablePolicy.FOLD)
    report = solve_with_report([note(31)], STANDARD_GUITAR, cfg)

    assert report.dropped == []
    assert [n.pitch for n in report.folded] == [31]
    placed = report.shapes[0].positions[0]
    sounded = STANDARD_GUITAR.open_pitches[placed.string] + placed.fret
    assert sounded % 12 == 31 % 12, "folding must preserve the pitch class"
    assert sounded > 31


def test_a_pitch_no_octave_shift_can_rescue_is_still_dropped():
    # Nothing above the top fret can be reached by shifting a very high pitch down
    # without landing below the low E, for an instrument this narrow.
    narrow = Tuning("One string, one fret", (40,), fret_count=0)
    cfg = SolverConfig(unplayable=UnplayablePolicy.FOLD)
    report = solve_with_report([note(45)], narrow, cfg)

    assert report.shapes == []
    assert [n.pitch for n in report.dropped] == [45]


def test_dropping_every_note_yields_an_empty_but_valid_result():
    report = solve_with_report([note(20), note(21)], STANDARD_GUITAR)
    assert report.shapes == []
    assert len(report.dropped) == 2
    assert report.adjusted_count == 2


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
