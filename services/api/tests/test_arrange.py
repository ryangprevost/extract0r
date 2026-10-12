"""Rearranging the song. Sprint 5.

What must hold for an arrangement to be usable: the sections found are where the song
changes; a cut keeps the beat - every repeat starts exactly a bar after the last; muting is
per block; and the notes in a MIDI export follow the same cuts as the audio.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.notes import NoteEvent
from app.services.synth import arrange
from app.services.synth.arrange import Piece
from app.services.synth.retempo import beat_grid, bounce

SR = 22050
BPM = 120.0
BAR = 4 * 60.0 / BPM


def tone(hz: float, seconds: float, level: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return level * np.sin(2 * np.pi * hz * t)


def song(parts=(("A", 110.0, 0.2), ("B", 880.0, 0.4)), bars=4, ring=0.4) -> np.ndarray:
    audio = np.concatenate([tone(hz, bars * BAR, level) for _, hz, level in parts])
    return np.concatenate([audio, np.zeros(int(ring * SR))])


def test_sections_are_found_where_the_song_changes():
    audio = song()
    found = arrange.find_sections(audio, SR, beat_grid(0.0, BPM, len(audio) / SR))
    assert [(s.start_bar, s.bars, s.group) for s in found] == [(1, 4, "A"), (5, 4, "B")]
    assert found[1].label == "chorus"           # louder
    assert found[1].end_s == pytest.approx(8 * BAR, abs=1e-6)
    assert found[1].tail_s == pytest.approx(0.4, abs=0.01)


def test_a_song_that_never_changes_is_one_section():
    audio = np.concatenate([tone(220.0, 8 * BAR), np.zeros(SR // 4)])
    found = arrange.find_sections(audio, SR, beat_grid(0.0, BPM, len(audio) / SR))
    assert len(found) == 1 and found[0].bars == 8


def test_a_section_that_comes_back_gets_its_letter_back():
    audio = song((("A", 110.0, 0.2), ("B", 880.0, 0.4), ("A", 110.0, 0.2)))
    found = arrange.find_sections(audio, SR, beat_grid(0.0, BPM, len(audio) / SR))
    assert [s.group for s in found] == ["A", "B", "A"]


def ramp(seconds: float) -> np.ndarray:
    return np.linspace(0.0, 1.0, int(seconds * SR))


def test_pieces_are_laid_end_to_end_at_exactly_their_length():
    audio = ramp(8 * BAR)
    pieces = [Piece(4 * BAR, 8 * BAR), Piece(0.0, 4 * BAR), Piece(4 * BAR, 8 * BAR)]
    out = arrange.assemble(audio, SR, pieces, "bass")
    assert len(out) == int(round(12 * BAR * SR))
    # The middle of the first piece is the middle of the song's second half.
    mid = int(2 * BAR * SR)
    assert out[mid] == pytest.approx(audio[int(6 * BAR * SR)], abs=1e-3)


def test_a_muted_block_is_silent_and_only_that_block():
    audio = np.ones(int(8 * BAR * SR))
    pieces = [Piece(0.0, 4 * BAR, frozenset({"bass"})), Piece(4 * BAR, 8 * BAR)]
    out = arrange.assemble(audio, SR, pieces, "bass")
    assert not np.any(out[: int(4 * BAR * SR) - 10])
    assert np.all(out[int(4 * BAR * SR) + 200:] > 0.99)


def test_a_cut_does_not_click_and_the_last_piece_rings_under_the_next():
    audio = np.ones(int(8 * BAR * SR))
    pieces = [Piece(0.0, 2 * BAR), Piece(6 * BAR, 8 * BAR)]   # not contiguous
    out = arrange.assemble(audio, SR, pieces, "x")
    join = int(2 * BAR * SR)
    assert out[join] < 1.5                                   # ring-out plus fade-in, no spike
    assert np.max(np.abs(np.diff(out[join - 50: join + 50]))) < 0.3


def test_beats_carry_straight_across_every_cut():
    beats = beat_grid(0.0, BPM, 8 * BAR)
    pieces = [Piece(4 * BAR, 8 * BAR), Piece(0.0, 4 * BAR), Piece(4 * BAR, 8 * BAR)]
    arranged = arrange.arranged_beats(beats, pieces)
    assert len(arranged) == 12 * 4
    assert np.allclose(np.diff(arranged), 60.0 / BPM)


def test_drops_are_counted_in_the_arrangement_s_bars():
    beats = beat_grid(0.0, BPM, 8 * BAR)
    pieces = [Piece(0.0, 4 * BAR), Piece(4 * BAR, 8 * BAR, drop=True),
              Piece(4 * BAR, 8 * BAR, drop=True)]
    assert arrange.drop_bars(pieces, arrange.arranged_beats(beats, pieces)) == [5, 9]


def test_notes_follow_the_cuts():
    notes = [NoteEvent(0.5, 1.0, 40, 100), NoteEvent(4 * BAR + 0.5, 4 * BAR + 1.0, 52, 100),
             NoteEvent(4 * BAR - 0.2, 4 * BAR + 0.5, 45, 100)]
    pieces = [Piece(4 * BAR, 8 * BAR), Piece(0.0, 4 * BAR), Piece(4 * BAR, 8 * BAR,
                                                                    frozenset({"bass"}))]
    placed = arrange.place_notes(notes, pieces, "bass")
    assert [(round(n.start_s, 3), n.pitch) for n in placed] == [
        (0.5, 52), (round(4 * BAR + 0.5, 3), 40), (round(8 * BAR - 0.2, 3), 45)]
    held = placed[-1]
    assert held.end_s == pytest.approx(8 * BAR)               # cut at the block's end


def test_a_bounce_follows_the_arrangement():
    stems = {"bass": np.stack([song()] * 2, axis=1)}
    beats = beat_grid(0.0, BPM, 8 * BAR + 0.4)
    pieces = [Piece(0.0, 4 * BAR), Piece(4 * BAR, 8 * BAR, frozenset({"bass"})),
              Piece(4 * BAR, 8 * BAR, drop=True)]
    mix, account = bounce(stems, SR, 1.0, {}, beats=beats, bpm=BPM, pieces=pieces)
    assert len(mix) == int(round(12 * BAR * SR))
    # The muted block runs bars 5-8; its last two bars are the build into the drop at 9.
    muted = mix[int(4.1 * BAR * SR): int(5.9 * BAR * SR), 0]
    assert np.max(np.abs(muted)) < 1e-6
    detail = next(p.detail for p in account if p.how == "arranged")
    assert detail == "3 blocks, 12 bars, 1 drop"


# --- Sprint 13: sections the person marked -------------------------------------------------------


def test_marks_become_sections_named_and_grouped_by_name():
    beats = beat_grid(0.0, BPM, 16 * BAR + 0.5)
    found = arrange.sections_from_marks(
        [(1, "Verse"), (5, "chorus"), (9, "verse"), (13, "chorus")], beats, 16 * BAR + 0.5)
    assert [(s.start_bar, s.bars, s.label, s.group) for s in found] == [
        (1, 4, "verse", "A"), (5, 4, "chorus", "B"), (9, 4, "verse", "A"), (13, 4, "chorus", "B")]
    assert found[1].start_s == pytest.approx(4 * BAR)
    assert found[-1].end_s == pytest.approx(16 * BAR)
    assert found[-1].tail_s == pytest.approx(0.5, abs=0.01)


def test_the_song_before_the_first_mark_is_an_intro():
    beats = beat_grid(0.0, BPM, 8 * BAR)
    found = arrange.sections_from_marks([(3, "drop")], beats, 8 * BAR)
    assert [(s.start_bar, s.label) for s in found] == [(1, "intro"), (3, "drop")]


def test_a_mark_past_the_end_is_held_to_the_last_bar():
    beats = beat_grid(0.0, BPM, 8 * BAR)
    found = arrange.sections_from_marks([(1, "a"), (99, "b")], beats, 8 * BAR)
    assert found[-1].start_bar == 8 and found[-1].bars == 1


def test_bar_levels_follow_the_music():
    audio = song()
    levels = arrange.bar_levels(audio, SR, beat_grid(0.0, BPM, len(audio) / SR))
    assert len(levels) >= 8
    assert levels[5] > levels[1] + 3          # the louder second half stands taller
