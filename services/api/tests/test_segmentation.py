"""Tests for note segmentation.

The rule under test came from comparing output against a hand-written tab for a real
song: `5-5-5-5-5-5-5-5` was being transcribed as one long note, because segmentation only
split on pitch change.
"""

from __future__ import annotations

import pytest

from app.domain.segmentation import nearest_frames, segment_notes


def track(pitches, hop=0.01):
    """Build (pitches, times, confidences) for a frame-by-frame pitch track."""
    times = [i * hop for i in range(len(pitches))]
    return pitches, times, [0.9] * len(pitches)


def test_a_held_pitch_is_one_note():
    pitches, times, conf = track([45.0] * 40)
    notes = segment_notes(pitches, times, conf)
    assert len(notes) == 1
    assert notes[0].pitch == 45


def test_a_pitch_change_starts_a_new_note():
    pitches, times, conf = track([45.0] * 20 + [47.0] * 20)
    notes = segment_notes(pitches, times, conf)
    assert [n.pitch for n in notes] == [45, 47]


def test_unvoiced_frames_end_a_note():
    pitches, times, conf = track([45.0] * 15 + [None] * 10 + [45.0] * 15)
    notes = segment_notes(pitches, times, conf)
    assert len(notes) == 2
    assert all(n.pitch == 45 for n in notes)


def test_a_restruck_note_splits_even_at_the_same_pitch():
    """The bug this module exists for: eight repeated notes must not become one."""
    pitches, times, conf = track([45.0] * 80)
    # An attack every 10 frames = every 100 ms.
    onsets = {i for i in range(0, 80, 10)}
    notes = segment_notes(pitches, times, conf, onset_indices=onsets)
    assert len(notes) >= 7, f"expected repeated notes to split, got {len(notes)}"
    assert all(n.pitch == 45 for n in notes)


def test_a_spurious_onset_cannot_shatter_a_held_note():
    """Onset detectors fire on sustained material; the refractory period absorbs that."""
    pitches, times, conf = track([45.0] * 100)
    # An "onset" on almost every frame - what a mis-tuned detector produces.
    onsets = set(range(0, 100, 2))
    notes = segment_notes(pitches, times, conf, onset_indices=onsets, min_restrike_s=0.09)
    # 100 frames at 10 ms = 1 s; at one strike per 90 ms that is ~11 notes, not 50.
    assert len(notes) <= 12, f"held note shattered into {len(notes)} fragments"


def test_notes_shorter_than_the_minimum_are_dropped():
    pitches, times, conf = track([45.0] * 3)
    assert segment_notes(pitches, times, conf, min_duration_s=0.5) == []


def test_low_confidence_notes_are_dropped():
    pitches = [45.0] * 40
    times = [i * 0.01 for i in range(40)]
    notes = segment_notes(pitches, times, [0.05] * 40, min_confidence=0.4)
    assert notes == []


def test_mismatched_input_lengths_are_rejected():
    with pytest.raises(ValueError):
        segment_notes([45.0, 45.0], [0.0], [0.9, 0.9])


def test_an_empty_track_yields_no_notes():
    assert segment_notes([], [], []) == []


def test_nearest_frames_maps_times_onto_the_analysis_grid():
    frames = [0.0, 0.1, 0.2, 0.3, 0.4]
    assert nearest_frames([0.09, 0.31], frames) == {1, 3}


def test_nearest_frames_handles_an_empty_grid():
    assert nearest_frames([1.0], []) == set()
