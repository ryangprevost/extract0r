"""A part at a different tempo, without stretching it. Sprint 3, candidates B and C.

The claim this module makes is narrow and worth testing precisely: **a re-played part is
not a stretched part.** A tempo change normally goes through a phase vocoder, and librosa's
own documentation says of its own:

> does not try to handle transients and is likely to produce many audible artifacts

Drums are nothing but transients. This avoids the problem rather than solving it — for any
part already reduced to notes or hits, a tempo change is arithmetic on a list of times and
then a fresh render.

So these test two things. That the arithmetic is right, and that the things which must
*not* happen do not: no quantising, no silent clamping, and no pretending a part can move
further than a performance survives.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.notes import NoteEvent
from app.services.drums.detect import Hit
from app.services.synth.retempo import (
    MAX_RATIO,
    MIN_RATIO,
    move_hits,
    move_notes,
    plan,
    rebuild_drums,
)

SR = 44100

#: The use case, stated once: pop punk to EDM.
POP_PUNK = 170.0
EDM = 128.0


def notes(count: int = 8, step: float = 0.5) -> list[NoteEvent]:
    return [
        NoteEvent(start_s=i * step, end_s=i * step + step * 0.8, pitch=40 + i)
        for i in range(count)
    ]


# --- the move ----------------------------------------------------------------------------


def test_the_use_case_is_a_move_this_can_make():
    move = plan(POP_PUNK, EDM, 180.0)

    assert move is not None
    assert move.scale == pytest.approx(170 / 128, rel=1e-6)
    assert move.percent == 25
    assert move.direction == "slower"


def test_a_slower_target_makes_the_song_longer():
    move = plan(POP_PUNK, EDM, 180.0)
    assert move.duration_after_s == pytest.approx(180.0 * 170 / 128, rel=1e-6)


def test_a_faster_target_makes_it_shorter():
    move = plan(100.0, 140.0, 60.0)
    assert move.duration_after_s < 60.0
    assert move.direction == "faster"


def test_the_same_tempo_says_so_rather_than_doing_arithmetic():
    assert "nothing moved" in plan(128.0, 128.0, 60.0).describe()


def test_the_sentence_says_re_played_rather_than_stretched():
    """The claim is the product. If this wording ever drifts to "stretched", the thing it
    describes has either changed or is being described wrongly."""
    said = plan(POP_PUNK, EDM, 180.0).describe()

    assert "rather than stretched" in said
    assert "128" in said and "170" in said


# --- what it refuses ---------------------------------------------------------------------


@pytest.mark.parametrize("target", [40.0, 60.0, 400.0])
def test_a_move_too_far_is_refused_rather_than_clamped(target: float):
    """None, not a clamp. Silently doing something smaller than what was asked is how a
    user ends up at 140 BPM believing they are at 100."""
    assert plan(170.0, target, 60.0) is None


def test_the_boundaries_are_where_they_are_said_to_be():
    assert plan(100.0, 100.0 / MAX_RATIO, 60.0) is not None
    assert plan(100.0, 100.0 / MIN_RATIO, 60.0) is not None
    assert plan(100.0, 100.0 / (MAX_RATIO + 0.01), 60.0) is None


@pytest.mark.parametrize("pair", [(0.0, 128.0), (170.0, 0.0), (-1.0, 128.0)])
def test_a_tempo_nobody_measured_is_not_a_move(pair):
    assert plan(pair[0], pair[1], 60.0) is None


# --- notes -------------------------------------------------------------------------------


def test_positions_and_lengths_scale_together():
    """A note held for a beat is still held for a beat at the new tempo. Scaling only the
    starts would turn a legato line staccato as the song slowed down."""
    move = plan(POP_PUNK, EDM, 10.0)
    before = notes()
    after = move_notes(before, move.scale)

    for was, now in zip(before, after, strict=True):
        assert now.start_s == pytest.approx(was.start_s * move.scale)
        assert now.end_s - now.start_s == pytest.approx(
            (was.end_s - was.start_s) * move.scale
        )


def test_microtiming_survives_as_a_fraction_of_the_beat():
    """A snare 20 ms behind the beat at 170 is 27 ms behind it at 128 — the same lateness
    measured in beats, which is what makes a performance sound played rather than
    programmed. Quantising here would be a different product, and one this project has
    twice decided against.
    """
    beat = 60.0 / POP_PUNK
    late = 0.020
    move = plan(POP_PUNK, EDM, 10.0)

    [moved] = move_notes([NoteEvent(beat + late, beat + late + 0.1, 45)], move.scale)
    new_beat = 60.0 / EDM

    assert moved.start_s - new_beat == pytest.approx(late * move.scale, abs=1e-6)
    assert (moved.start_s - new_beat) / new_beat == pytest.approx(late / beat, rel=1e-6)


def test_nothing_is_snapped_to_a_grid():
    """The non-goal, asserted in the module best placed to break it by accident."""
    odd = [NoteEvent(0.337, 0.59, 48), NoteEvent(1.013, 1.4, 50)]
    moved = move_notes(odd, 1.328)

    for was, now in zip(odd, moved, strict=True):
        assert now.start_s == pytest.approx(was.start_s * 1.328, rel=1e-9)


def test_pitch_and_velocity_are_untouched():
    moved = move_notes([NoteEvent(1.0, 2.0, 55, velocity=77, confidence=0.4)], 1.5)
    assert moved[0].pitch == 55
    assert moved[0].velocity == 77
    assert moved[0].confidence == 0.4


def test_an_empty_part_moves_to_an_empty_part():
    assert move_notes([], 1.3) == []


# --- drums -------------------------------------------------------------------------------


def hits(count: int = 16, step: float = 0.35) -> list[Hit]:
    return [
        Hit(time_s=i * step, kinds=["kick" if i % 2 == 0 else "snare"], strength=0.8)
        for i in range(count)
    ]


def test_strokes_move_and_stay_the_drums_they_were():
    moved = move_hits(hits(), 1.328)

    assert [h.kinds for h in moved] == [h.kinds for h in hits()]
    assert moved[4].time_s == pytest.approx(hits()[4].time_s * 1.328)


def test_a_rebuilt_drum_part_is_audio_of_the_right_length():
    audio = rebuild_drums(move_hits(hits(), 1.328), SR, 8.0)

    assert audio.shape == (int(8.0 * SR), 2)
    assert np.max(np.abs(audio)) > 0.01


def test_the_strokes_land_where_they_were_moved_to():
    """The whole claim, measured rather than asserted: the audio has energy at the new
    positions and silence between them, which is what not-smeared means."""
    scale = 1.5
    moved = move_hits(hits(count=8, step=0.4), scale)
    audio = rebuild_drums(moved, SR, 6.0).mean(axis=1)

    for hit in moved:
        at = int(hit.time_s * SR)
        here = np.max(np.abs(audio[at : at + int(0.02 * SR)]))
        # Halfway to the next stroke, which should be quiet.
        between = int((hit.time_s + 0.4 * scale / 2) * SR)
        quiet = np.max(np.abs(audio[between : between + int(0.02 * SR)]))
        assert here > quiet * 2, f"no stroke at {hit.time_s:.3f}s"


def test_dynamics_survive_the_move():
    """A kit that played everything at one velocity would be a machine, not a drummer's
    part re-struck."""
    soft = rebuild_drums([Hit(0.5, ["kick"], strength=0.1)], SR, 2.0)
    hard = rebuild_drums([Hit(0.5, ["kick"], strength=1.0)], SR, 2.0)

    assert np.max(np.abs(hard)) > np.max(np.abs(soft)) * 3


def test_nothing_clips():
    dense = [Hit(i * 0.02, ["kick", "snare"], strength=1.0) for i in range(100)]
    assert np.max(np.abs(rebuild_drums(dense, SR, 3.0))) <= 1.0


def test_a_stroke_past_the_end_is_dropped_rather_than_crashing():
    """Scaling moves strokes later, and the last of them can land past a duration computed
    from something else."""
    audio = rebuild_drums([Hit(99.0, ["kick"], strength=0.8)], SR, 2.0)
    assert audio.shape[0] == int(2.0 * SR)


def test_no_strokes_is_silence_rather_than_an_error():
    assert not np.any(rebuild_drums([], SR, 1.0))


# --- Sprint 3 D/E: stretching what cannot be re-played -----------------------------------

from app.services.synth.retempo import (  # noqa: E402
    StaleRender,
    bounce,
    stretch,
    summarise,
)


def _have_a_stretcher() -> bool:
    import importlib.util

    return any(importlib.util.find_spec(m) for m in ("python_stretch", "librosa"))


#: Only on the tests that actually stretch. The fast CI job installs neither stretcher on
#: purpose (ADR-0002), and the tests that only re-play, refuse, or do nothing at tempo 1.0
#: should still run there - marking the whole module would quietly drop them.
needs_stretcher = pytest.mark.skipif(
    not _have_a_stretcher(), reason="no time-stretcher installed (ML extras)"
)


def tone(seconds: float = 2.0, hz: float = 220.0) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return 0.3 * np.sin(2 * np.pi * hz * t)


@needs_stretcher
def test_a_stretch_makes_the_part_longer_not_shorter():
    """Signalsmith's time factor is a *speed* factor, the opposite of librosa's and Rubber
    Band's: 1.328 made audio shorter when first tried. Getting it backwards turns a
    slowdown into a speed-up, which nobody would hear as a bug - they would hear a song
    that went the wrong way and blame themselves."""
    out = stretch(tone(), SR, 170 / 128)
    assert len(out) == round(len(tone()) * 170 / 128)


@needs_stretcher
def test_a_stretch_keeps_the_pitch():
    out = stretch(tone(hz=220.0), SR, 170 / 128)
    spectrum = np.abs(np.fft.rfft(out * np.hanning(out.size)))
    peak = np.fft.rfftfreq(out.size, 1 / SR)[int(np.argmax(spectrum))]
    assert peak == pytest.approx(220.0, rel=0.01)


@needs_stretcher
def test_stereo_stays_stereo_and_exactly_as_long_as_the_arithmetic_says():
    """Exactly, because a stretched part a few samples off drifts against the re-played
    parts it is summed with."""
    pair = np.stack([tone(hz=220), tone(hz=330)], axis=1)
    out = stretch(pair, SR, 1.5)
    assert out.shape == (round(pair.shape[0] * 1.5), 2)


def test_no_move_is_no_work():
    assert np.array_equal(stretch(tone(), SR, 1.0), tone())


@needs_stretcher
def test_a_bounce_re_plays_what_was_re_played_and_stretches_the_rest():
    scale = 170 / 128
    stems = {"vocals": tone(hz=330), "drums": tone(hz=60)}
    replay = np.zeros(round(len(tone()) * scale))

    mix, account = bounce(stems, SR, scale, {"drums": (replay, "punchy kit")})

    assert len(mix) == round(len(tone()) * scale)
    how = {p.stem: p.how for p in account}
    assert how == {"vocals": "stretched", "drums": "re-played"}


def test_a_part_rendered_at_another_tempo_is_refused_by_name():
    """Renders are named by stem and voice, not tempo, so a bass played at 90 and then a
    version at 128 would otherwise be summed - a song at two tempos at once."""
    with pytest.raises(StaleRender) as caught:
        bounce({"bass": tone()}, SR, 170 / 128, {"bass": (np.zeros(len(tone())), "subbass")})

    assert caught.value.stem == "bass"
    assert "again at this tempo" in str(caught.value)


@needs_stretcher
def test_the_bounce_does_not_clip():
    loud = {name: tone(hz=hz) * 3 for name, hz in (("a", 110), ("b", 220), ("c", 330))}
    mix, _ = bounce(loud, SR, 1.2, {})
    assert np.max(np.abs(mix)) <= 10 ** (-1 / 20) + 1e-9


@needs_stretcher
def test_the_summary_counts_rather_than_reassures():
    """The first bounce printed "nothing is smeared" over a version where five of six parts
    had been stretched, drums included. A reassurance that is false is worse than none for a
    screen whose whole job is to make somebody trust what they made."""
    move = plan(POP_PUNK, EDM, 60.0)
    _, account = bounce(
        {"drums": tone(), "vocals": tone(), "bass": tone()},
        SR,
        move.scale,
        {"bass": (np.zeros(round(len(tone()) * move.scale)), "subbass")},
    )
    said = summarise(move, account)
    text = " ".join([said["headline"], *said["lines"], said["tip"]])

    assert "smeared" not in text
    assert "bass" in said["lines"][0]
    assert "drums" in said["lines"][1] and "vocals" in said["lines"][1]


@needs_stretcher
def test_stretched_drums_come_with_what_to_do_about_it():
    """The weakness, turned into the next thing to try."""
    move = plan(POP_PUNK, EDM, 60.0)
    _, account = bounce({"drums": tone()}, SR, move.scale, {})

    tip = summarise(move, account)["tip"]
    assert "drums" in tip and "kit" in tip


def test_re_played_drums_need_no_tip():
    move = plan(POP_PUNK, EDM, 60.0)
    _, account = bounce(
        {"drums": tone()}, SR, move.scale,
        {"drums": (np.zeros(round(len(tone()) * move.scale)), "punchy kit")},
    )
    assert summarise(move, account)["tip"] == ""
