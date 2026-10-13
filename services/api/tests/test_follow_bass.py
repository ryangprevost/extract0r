"""Parts made to follow the bass's chords, and held only within them. Sprint 18b."""

from __future__ import annotations

from app.services.synth.edit import BeatNote, chord_tones, follow_bass, legato, scale_of

D_MAJOR = scale_of([BeatNote(0, 1, p, 100) for p in (62, 64, 66, 67, 69, 71, 73)])


def test_the_scale_is_found_from_the_notes():
    assert D_MAJOR[0] == 2 and sorted(D_MAJOR) == [1, 2, 4, 6, 7, 9, 11]


def test_chord_tones_step_the_scale():
    assert chord_tones(7, D_MAJOR) == {7, 11, 2}        # G: G B D
    assert chord_tones(9, D_MAJOR) == {9, 1, 4}         # A: A C# E
    assert chord_tones(0, D_MAJOR) == {0, 4, 7}         # C, borrowed: C major


def test_a_clashing_note_moves_to_the_nearest_chord_tone():
    bass = [BeatNote(0, 4, 43, 100), BeatNote(4, 4, 45, 100)]      # G then A
    part = [BeatNote(0, 1, 73, 90),     # C# over G - a tritone; nearest chord tone D (74)
            BeatNote(0, 1, 71, 90),     # B over G - fine
            BeatNote(4, 1, 74, 90)]     # D over A - nearest chord tone is C# (73)
    out = follow_bass(part, bass, scale=D_MAJOR)
    assert sorted(n.pitch for n in out if n.beat == 0) == [71, 74]
    assert [n.pitch for n in out if n.beat == 4] == [73]


def test_duplicates_go_and_at_most_four_notes_sound_together():
    bass = [BeatNote(0, 4, 38, 100)]                               # D
    part = [BeatNote(0, 1, p, v) for p, v in
            ((62, 50), (62, 90), (66, 80), (69, 70), (74, 60), (78, 40), (81, 30))]
    out = follow_bass(part, bass, voices=4, scale=D_MAJOR)
    assert len(out) == 4
    assert [n.velocity for n in out if n.pitch == 62] == [90]


def test_legato_stops_at_the_bass_changes():
    part = [BeatNote(0, 0.5, 71, 90), BeatNote(8, 0.5, 73, 90)]
    held = legato(part, 1.0, stops=[0, 4, 8])
    assert held[0].length == 4.0
