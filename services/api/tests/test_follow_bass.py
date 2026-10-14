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


def test_trim_takes_out_ghosts_and_lone_leaps():
    from app.services.synth.edit import trim

    line = [BeatNote(0, 1, 60, 80), BeatNote(1, 1, 62, 80), BeatNote(2, 1, 76, 80),
            BeatNote(3, 1, 64, 80), BeatNote(3.5, 0.1, 65, 20), BeatNote(4, 1, 65, 80)]
    kept = [n.pitch for n in trim(line)]
    assert kept == [60, 62, 64, 65]


def test_top_line_is_the_top_of_each_chord_in_the_lead_register():
    from app.services.synth.edit import top_line

    chords = [BeatNote(0, 1, 50, 80), BeatNote(0, 1, 54, 80), BeatNote(0, 1, 57, 80),
              BeatNote(1, 1, 52, 80), BeatNote(1, 1, 79, 80)]
    assert [(n.beat, n.pitch) for n in top_line(chords)] == [(0, 57), (1, 67)]


def test_fill_runs_each_note_exactly_into_the_next():
    from app.services.synth.edit import fill

    notes = [BeatNote(0, 0.25, 60, 80), BeatNote(0, 3.0, 64, 80),    # a chord, one too long
             BeatNote(1, 0.5, 62, 80), BeatNote(2, 0.25, 65, 80)]
    out = fill(notes)
    assert [n.length for n in out] == [1.0, 1.0, 1.0, 0.25]
