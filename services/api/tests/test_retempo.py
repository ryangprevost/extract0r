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


# --- what makes it sound like a dance record ---------------------------------------------

from app.services.synth.retempo import (  # noqa: E402
    PUMP_DB,
    beat_grid,
    four_on_the_floor,
    pump,
    pump_envelope,
)


def level_db(signal: np.ndarray, reference: np.ndarray, at: int) -> float:
    a = float(np.sqrt((signal[at : at + 300] ** 2).mean()))
    b = float(np.sqrt((reference[at : at + 300] ** 2).mean()))
    return 20 * np.log10(a / b)


def test_the_grid_starts_on_the_song_s_own_first_beat():
    """So an added kick lands on the drummer's downbeats, not on a grid of its own."""
    beats = beat_grid(0.1, 128.0, 4.0)
    assert beats[0] == pytest.approx(0.1)
    assert np.diff(beats) == pytest.approx(60 / 128)


def test_the_pump_stays_down_and_then_swells():
    """The dip *is* the sound. The first version reused the mastering duck, which recovers
    with a time constant a quarter of its release, and an "8 dB" pump read -1.9 dB 60 ms
    after the beat - a correction meant to be felt, used as an effect meant to be heard."""
    bpm = 128.0
    beats = beat_grid(0.1, bpm, 4.0)
    steady = tone(4.0)
    pumped = pump(steady, SR, beats, bpm)
    beat = 60 / bpm

    just_after = int((beats[2] + 0.05 * beat) * SR)
    third = int((beats[2] + 0.3 * beat) * SR)
    late = int((beats[2] + 0.9 * beat) * SR)

    assert level_db(pumped, steady, just_after) < -PUMP_DB + 1.0
    assert level_db(pumped, steady, third) < -3.0
    assert level_db(pumped, steady, late) == pytest.approx(0.0, abs=0.2)


def test_the_pump_has_recovered_before_the_next_beat():
    """A release longer than the beat never recovers and just makes everything quieter."""
    bpm = 174.0
    beats = beat_grid(0.0, bpm, 3.0)
    gain = pump_envelope(beats, int(3.0 * SR), SR, bpm)
    just_before = int(beats[3] * SR) - int(0.01 * SR)
    assert gain[just_before] == pytest.approx(1.0, abs=0.01)


def test_no_depth_is_no_pump():
    assert np.array_equal(pump(tone(), SR, beat_grid(0, 128, 2), 128, depth_db=0), tone())


def test_four_on_the_floor_is_a_kick_on_every_beat():
    bpm = 128.0
    beats = beat_grid(0.05, bpm, 4.0)
    layer = four_on_the_floor(beats, bpm, SR, int(4 * SR)).mean(axis=1)

    for beat in beats[:-1]:
        at = int(beat * SR)
        on = np.max(np.abs(layer[at : at + int(0.03 * SR)]))
        assert on > 0.3, f"no kick at {beat:.3f}"


def test_four_on_the_floor_is_labelled_as_added_not_as_the_band():
    """Added, not moved: re-sequencing the drummer is still out. The account has to say this
    part is not from the recording, so nobody mistakes it for their band."""
    bpm = 128.0
    move = plan(POP_PUNK, bpm, 4.0)
    beats = beat_grid(0.0, bpm, 4.0 * move.scale)
    _, account = bounce(
        {"bass": tone(4.0)}, SR, move.scale,
        {"bass": (np.zeros(round(len(tone(4.0)) * move.scale)), "808")},
        beats=beats, bpm=bpm, floor_kick=True,
    )
    added = [p for p in account if p.how == "added"]
    assert added and "not from your recording" in added[0].detail

    said = summarise(move, account)
    assert any("Added" in line for line in said["lines"])


@needs_stretcher
def test_the_pump_spares_the_drums():
    """Ducking the kick to itself is silence on every beat - the opposite of the effect."""
    bpm = 128.0
    beats = beat_grid(0.0, bpm, 2.0)
    drums = tone(2.0, hz=60)
    _, account = bounce(
        {"drums": drums, "bass": tone(2.0)}, SR, 1.0, {},
        beats=beats, bpm=bpm, pump_db=PUMP_DB,
    )
    pumped = next(p for p in account if p.how == "pumped")
    assert "bass" in pumped.detail and "drums" not in pumped.detail


# --- the dance kit -----------------------------------------------------------------------

from app.services.drums.kit import KITS, render_voice  # noqa: E402


def band_db(audio: np.ndarray, lo: float, hi: float) -> float:
    spectrum = np.abs(np.fft.rfft(audio)) ** 2
    freqs = np.fft.rfftfreq(audio.size, 1 / SR)
    return 10 * np.log10(spectrum[(freqs >= lo) & (freqs < hi)].sum() / spectrum.sum())


def test_the_dance_kick_carries_more_sub_than_a_rock_kick():
    """Tuned against the same measurement as the other kits, to a deliberately different
    target. A real rock kick has -2.25 dB in 20-60 Hz; the first dance kick measured -3.78,
    short of even that."""
    edm = band_db(render_voice(KITS["edm"]["kick"], SR), 20, 60)
    rock = band_db(render_voice(KITS["punchy"]["kick"], SR), 20, 60)
    assert edm > rock


def test_the_clap_is_several_hands_not_one():
    """Counted as sudden rises in energy, which is what a burst *is*.

    The first version of this test counted local maxima of a smoothed envelope, and broke
    the moment the clap was band-limited: narrower-band noise has many small peaks inside
    each burst. The sound had not changed - 1 ms RMS frames still jump about 18 dB at 0, 11,
    22 and 33 ms - the measure had.
    """
    clap = render_voice(KITS["edm"]["snare"], SR)[: int(0.05 * SR)]
    frame = int(0.001 * SR)
    rms = np.array(
        [np.sqrt((clap[i : i + frame] ** 2).mean()) for i in range(0, len(clap) - frame, frame)]
    )
    level = 20 * np.log10(rms / rms.max() + 1e-9)
    jumps = [i for i in range(1, len(level)) if level[i] - level[i - 1] > 10]
    onsets = [j for k, j in enumerate(jumps) if k == 0 or j - jumps[k - 1] > 5]
    # The first burst starts at the very top of the file, before any frame to rise from.
    assert len(onsets) + 1 >= 4


def test_the_clap_sounds_like_a_clap_and_not_hiss():
    """Highpassed white noise alone measured a centroid of 11.5 kHz. A clap lives around
    1-3 kHz, which only a band-limit reaches."""
    clap = render_voice(KITS["edm"]["snare"], SR)
    spectrum = np.abs(np.fft.rfft(clap))
    freqs = np.fft.rfftfreq(clap.size, 1 / SR)
    centroid = float((spectrum * freqs).sum() / spectrum.sum())
    assert 1000 < centroid < 4500


# --- where the beats really are ----------------------------------------------------------

from app.services.synth.retempo import _kick_onsets, find_beats  # noqa: E402


def kick_pattern(bpm: float, seconds: float, first: float = 0.0) -> np.ndarray:
    """A kick on every beat, from the dance kit, starting at `first`."""
    out = np.zeros(int(seconds * SR))
    hit = render_voice(KITS["edm"]["kick"], SR)
    for t in np.arange(first, seconds - 0.5, 60.0 / bpm):
        at = int(round(t * SR))
        out[at : at + hit.size] += hit[: max(0, min(hit.size, out.size - at))]
    return out


def test_the_envelope_reports_the_rate_it_is_really_sampled_at():
    """The bug that made two methods agree on a wrong tempo. 44100 // 1000 is 44, which is
    1002.27 Hz; converting at 1000 stretched every time by 0.227% and read a 170 BPM song
    as 169.61. Agreement between methods that share an input is not corroboration."""
    _, rate = _kick_onsets(np.zeros(SR * 2), SR)
    assert rate == pytest.approx(SR / (SR // 1000))
    assert rate != 1000


@pytest.mark.parametrize("bpm", [128.0, 140.0, 170.0, 174.0])
def test_the_tempo_comes_from_the_kick_not_the_estimate(bpm: float):
    """Seeded with an estimate 0.9% out - what the whole-mix estimator gave the pop punk demo
    - and it has to find the real tempo anyway."""
    found, _ = find_beats(kick_pattern(bpm, 12.0), SR, bpm * 0.991)
    assert found == pytest.approx(bpm, abs=0.1)


def test_the_first_beat_is_found_where_the_kick_is():
    """The grid used to start 166 ms into a 469 ms beat. A kick laid on that flams."""
    _, first = find_beats(kick_pattern(128.0, 10.0, first=0.2), SR, 127.0)
    beat = 60.0 / 128.0
    assert min(abs(first - 0.2) % beat, beat - abs(first - 0.2) % beat) < 0.008


def test_no_kick_falls_back_rather_than_inventing_one():
    assert find_beats(np.zeros(SR * 5), SR, 128.0) == (128.0, 0.0)


def test_a_first_beat_just_before_zero_still_gets_its_beat():
    """A kick found at -0.5 ms wrapped to nearly a beat later and lost the song's opening."""
    period = 60.0 / 170.0
    beats = beat_grid(period - 0.0005, 170.0, 3.0)
    assert beats[0] == pytest.approx(0.0, abs=1e-6)


# --- X0R-412: where a hit really starts -----------------------------------------------------

from app.services.synth.retempo import ONSET_LOOKBACK_S, refine_hit_times  # noqa: E402


def struck(at_s: float, seconds: float = 1.0) -> np.ndarray:
    """One kick, starting exactly at `at_s`, in silence."""
    out = np.zeros(int(seconds * SR))
    kick = render_voice(KITS["punchy"]["kick"], SR, seed=0)
    start = int(round(at_s * SR))
    out[start : start + kick.size] = kick[: out.size - start]
    return out


def test_a_late_detection_is_pulled_back_to_the_stroke():
    """Detectors report a hit when it is loud, which is after it starts. Re-struck hits
    placed at the detector's time land late and flam against anything added on the grid."""
    audio = struck(0.5)
    refined = refine_hit_times(audio, SR, [Hit(time_s=0.511, kinds=["kick"])])
    assert abs(refined[0].time_s - 0.5) < 0.002


def test_an_early_detection_is_pushed_forward_to_the_stroke():
    audio = struck(0.5)
    refined = refine_hit_times(audio, SR, [Hit(time_s=0.489, kinds=["kick"])])
    assert abs(refined[0].time_s - 0.5) < 0.002


def test_a_hit_inside_a_ringing_sound_keeps_the_detected_time():
    """If nothing in the window is quiet, there is no start to find. Walking back to the edge
    of the window and calling that the stroke is what once moved a kick 30 ms early."""
    t = np.arange(SR) / SR
    audio = 0.5 * np.sin(2 * np.pi * 110 * t)
    refined = refine_hit_times(audio, SR, [Hit(time_s=0.5, kinds=["kick"])])
    assert refined[0].time_s == 0.5


def test_refining_keeps_what_the_hit_was():
    audio = struck(0.5)
    hit = Hit(time_s=0.51, kinds=["kick", "hihat"], strength=0.7, rises={"kick": 9.0})
    refined = refine_hit_times(audio, SR, [hit])[0]
    assert (refined.kinds, refined.strength, refined.rises) == (hit.kinds, hit.strength, hit.rises)
    assert refined.time_s > hit.time_s - ONSET_LOOKBACK_S
