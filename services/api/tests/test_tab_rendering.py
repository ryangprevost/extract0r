from __future__ import annotations

from app.domain.notes import NoteEvent, StemKind, cluster_by_onset, quantize
from app.domain.tab import ascii_tab, drum_tab
from app.domain.tab.fretboard import STANDARD_GUITAR, solve


def note(pitch: int, start: float, length: float = 0.25) -> NoteEvent:
    return NoteEvent(start_s=start, end_s=start + length, pitch=pitch)


def test_ascii_tab_has_one_line_per_string():
    shapes = solve([note(40, 0.0), note(45, 0.5)], STANDARD_GUITAR)
    text = ascii_tab.render(shapes, STANDARD_GUITAR, tempo_bpm=120)
    staff_lines = [line for line in text.splitlines() if line.strip().endswith("-|")]
    assert len(staff_lines) == STANDARD_GUITAR.string_count


def test_ascii_tab_prints_the_high_string_first():
    shapes = solve([note(40, 0.0)], STANDARD_GUITAR)
    text = ascii_tab.render(shapes, STANDARD_GUITAR)
    staff = [line for line in text.splitlines() if "|" in line and "-" in line]
    assert staff[0].strip().startswith("e|")
    assert staff[-1].strip().startswith("E|")


def test_empty_transcription_still_renders_a_staff():
    text = ascii_tab.render([], STANDARD_GUITAR)
    assert "no notes detected" in text
    assert text.count("|") >= STANDARD_GUITAR.string_count


def test_ascii_tab_places_later_notes_further_right():
    shapes = solve([note(40, 0.0), note(40, 1.0)], STANDARD_GUITAR)
    text = ascii_tab.render(shapes, STANDARD_GUITAR, tempo_bpm=120)
    low_e = [line for line in text.splitlines() if line.strip().startswith("E|")][0]
    first, second = low_e.index("0"), low_e.rindex("0")
    assert second > first


def test_drum_tab_uses_lane_labels():
    hits = [note(36, 0.0), note(38, 0.5), note(42, 0.25)]
    text = drum_tab.render(hits, tempo_bpm=120)
    assert "BD|" in text and "SD|" in text and "HH|" in text


def test_drum_tab_drops_unused_lanes():
    text = drum_tab.render([note(36, 0.0)], tempo_bpm=120)
    assert "BD|" in text
    assert "RD|" not in text


def test_quantize_snaps_to_the_grid():
    # At 120 BPM a sixteenth note is 0.125 s.
    assert quantize(0.0, 120, 16) == 0
    assert quantize(0.125, 120, 16) == 1
    assert quantize(0.13, 120, 16) == 1
    assert quantize(1.0, 120, 16) == 8


def test_onset_clustering_groups_simultaneous_notes():
    notes = [note(52, 0.0), note(55, 0.01), note(59, 0.02), note(60, 0.9)]
    clusters = cluster_by_onset(notes)
    assert [len(c) for c in clusters] == [3, 1]


def test_stem_kinds_pick_sensible_notation():
    assert StemKind.DRUMS.default_notation.value == "drum_tab"
    assert StemKind.BASS.default_notation.value == "string_tab"
    assert StemKind.VOCALS.default_notation.value == "pitch_list"
