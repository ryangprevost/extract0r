"""Tests for X0R-407: tempo, metre, and key.

The point of `app.domain.timing` is that the *decisions* are pure, so the failure sprint 1
hit — a 100 BPM track and a 200 BPM track both reported ~99.4 — can be tested directly on
onset times, with no audio and no librosa.
"""

from __future__ import annotations

import pytest

from app.domain.timing import (
    MAJOR_PROFILE,
    MINOR_PROFILE,
    KeyEstimate,
    Mode,
    TimingEstimate,
    best_offset,
    choose_tempo,
    detect_beats_per_bar,
    estimate_key,
    octave_variants,
    score_tempo,
    spell_pitch,
)


def beats(bpm: float, count: int, offset: float = 0.0) -> list[float]:
    period = 60.0 / bpm
    return [offset + i * period for i in range(count)]


# ──────────────────────────────── tempo scoring ────────────────────────────────


def test_the_true_tempo_scores_near_perfect():
    assert score_tempo(beats(120, 32), 120) == pytest.approx(1.0, abs=0.05)


def test_double_time_is_penalised_for_the_beats_it_invents():
    """The core of the octave fix: a doubled grid explains every onset but has empty beats."""
    onsets = beats(120, 32)
    assert score_tempo(onsets, 240) < score_tempo(onsets, 120)


def test_half_time_is_penalised_for_the_onsets_it_misses():
    onsets = beats(120, 32)
    assert score_tempo(onsets, 60) < score_tempo(onsets, 120)


def test_an_unrelated_tempo_scores_poorly():
    assert score_tempo(beats(120, 32), 97) < 0.5


def test_scoring_is_safe_on_degenerate_input():
    assert score_tempo([], 120) == 0.0
    assert score_tempo(beats(120, 8), 0) == 0.0


def test_too_few_onsets_yield_no_tempo_evidence():
    """One or two events cannot imply a tempo, and must not look like they do."""
    assert score_tempo([1.0], 120) == 0.0
    assert score_tempo([0.0, 0.5], 120) == 0.0
    assert score_tempo([0.0, 0.5, 1.0], 120) == 0.0
    assert score_tempo([0.0, 0.5, 1.0, 1.5], 120) > 0.0


# ──────────────────────────────── octave choice ────────────────────────────────


@pytest.mark.parametrize("true_bpm", [70, 90, 100, 120, 140, 160])
def test_the_true_tempo_is_recovered_from_a_doubled_reading(true_bpm):
    """Exactly the sprint-1 failure: the tracker reports double, we must undo it."""
    onsets = beats(true_bpm, 40)
    chosen = choose_tempo(onsets, true_bpm * 2)
    assert chosen.bpm == pytest.approx(true_bpm, rel=0.02)


@pytest.mark.parametrize("true_bpm", [80, 100, 120, 150])
def test_the_true_tempo_is_recovered_from_a_halved_reading(true_bpm):
    onsets = beats(true_bpm, 40)
    chosen = choose_tempo(onsets, true_bpm / 2)
    assert chosen.bpm == pytest.approx(true_bpm, rel=0.02)


def test_a_correct_reading_is_left_alone():
    onsets = beats(128, 40)
    assert choose_tempo(onsets, 128).bpm == pytest.approx(128, rel=0.02)


def test_octave_variants_stay_within_musical_range():
    for bpm in octave_variants(120):
        assert 55 <= bpm <= 200
    # 400 is not a tempo anyone plays; its useful variants are the slower ones.
    assert all(v <= 200 for v in octave_variants(400))


def test_ties_resolve_to_the_slower_tempo():
    """A half-time reading is easier to read than a double-time one."""
    # A steady pulse with no accents is genuinely ambiguous; prefer the slower reading.
    onsets = beats(160, 48)
    chosen = choose_tempo(onsets, 160)
    assert chosen.bpm <= 160


def test_offset_finds_where_beat_one_sits():
    onsets = beats(120, 32, offset=0.17)
    offset = best_offset(onsets, 120)
    period = 60.0 / 120
    # The grid phase should line up with 0.17 modulo one beat.
    assert min((offset - 0.17) % period, (0.17 - offset) % period) < 0.01


# ──────────────────────────────── metre ────────────────────────────────────────


def accented(bpm: float, beats_per_bar: int, bars: int = 12):
    """Onsets on every beat, with beat one louder — what a real bar sounds like."""
    period = 60.0 / bpm
    onsets, strengths = [], []
    for beat in range(bars * beats_per_bar):
        onsets.append(beat * period)
        strengths.append(1.0 if beat % beats_per_bar == 0 else 0.4)
    return onsets, strengths


def test_four_four_is_detected_from_accents():
    onsets, strengths = accented(120, 4)
    bars, confidence = detect_beats_per_bar(onsets, 120, 0.0, strengths=strengths)
    assert bars == 4
    assert confidence > 0


def test_three_four_is_detected_from_accents():
    onsets, strengths = accented(120, 3)
    bars, confidence = detect_beats_per_bar(onsets, 120, 0.0, strengths=strengths)
    assert bars == 3
    assert confidence > 0


def test_without_accent_information_it_admits_it_is_guessing():
    """Presence alone cannot tell 3/4 from 4/4, and must not claim otherwise.

    An earlier version scored bar length by whether an onset existed on the downbeat,
    which reported 0.99 confidence on flatly wrong metres for music that plays on every
    beat.
    """
    onsets = beats(120, 48)
    bars, confidence = detect_beats_per_bar(onsets, 120, 0.0)
    assert bars == 4, "4/4 is the safe default"
    assert confidence == 0.0, "no accent evidence must mean no confidence"


def test_flat_accents_give_no_confidence():
    onsets = beats(120, 48)
    bars, confidence = detect_beats_per_bar(
        onsets, 120, 0.0, strengths=[1.0] * len(onsets)
    )
    assert bars == 4
    assert confidence == 0.0


def test_metre_falls_back_safely_on_no_onsets():
    assert detect_beats_per_bar([], 120, 0.0) == (4, 0.0)


# ──────────────────────────────── key ──────────────────────────────────────────


def test_a_c_major_profile_is_read_as_c_major():
    key = estimate_key(list(MAJOR_PROFILE))
    assert key.tonic == "C"
    assert key.mode is Mode.MAJOR


def test_a_rotated_profile_is_read_as_the_rotated_key():
    # Rotate the major profile up by 7 semitones -> G major.
    rotated = [MAJOR_PROFILE[(i - 7) % 12] for i in range(12)]
    key = estimate_key(rotated)
    assert key.tonic == "G"
    assert key.mode is Mode.MAJOR


def test_a_minor_profile_is_read_as_minor():
    rotated = [MINOR_PROFILE[(i - 9) % 12] for i in range(12)]
    key = estimate_key(rotated)
    assert key.tonic == "A"
    assert key.mode is Mode.MINOR


def test_flat_chroma_gives_no_confidence():
    key = estimate_key([1.0] * 12)
    assert key.confidence == 0.0


def test_silence_does_not_crash_key_detection():
    assert estimate_key([0.0] * 12).confidence == 0.0


def test_chroma_must_have_twelve_bins():
    with pytest.raises(ValueError):
        estimate_key([1.0] * 11)


# ──────────────────────────────── spelling ─────────────────────────────────────


def test_sharp_keys_spell_with_sharps():
    key = KeyEstimate(tonic="G", mode=Mode.MAJOR, confidence=1.0)
    assert spell_pitch(61, key) == "C#4"


def test_flat_keys_spell_with_flats():
    key = KeyEstimate(tonic="F", mode=Mode.MAJOR, confidence=1.0)
    assert spell_pitch(61, key) == "Db4"


def test_spelling_without_a_key_defaults_to_sharps():
    assert spell_pitch(61) == "C#4"


# ──────────────────────────────── estimate object ──────────────────────────────


def test_timing_estimate_exposes_a_usable_grid():
    estimate = TimingEstimate(tempo_bpm=90.0, beats_per_bar=3)
    assert estimate.time_signature == (3, 4)
    assert estimate.seconds_per_beat == pytest.approx(60 / 90)


def test_a_zero_tempo_does_not_divide_by_zero():
    assert TimingEstimate(tempo_bpm=0.0).seconds_per_beat > 0


# ──────────────────────────────── overrides ────────────────────────────────────


def test_overrides_replace_detection_and_say_so():
    """Detection gets tempo octaves wrong; the songwriter's answer must win."""
    from app.services.pipeline import apply_timing_overrides

    detected = TimingEstimate(tempo_bpm=99.4, beats_per_bar=4, confidence=0.4,
                              first_beat_s=0.31, source="librosa_timing")
    corrected = apply_timing_overrides(detected, tempo_bpm=160.0, beats_per_bar=3)

    assert corrected.tempo_bpm == 160.0
    assert corrected.beats_per_bar == 3
    assert corrected.confidence == 1.0, "a user-set tempo is certain by definition"
    assert corrected.first_beat_s == 0.0, "the old downbeat means nothing at a new tempo"
    assert "99.4" in corrected.source, "the original reading should stay visible"


def test_no_overrides_leaves_detection_untouched():
    from app.services.pipeline import apply_timing_overrides

    detected = TimingEstimate(tempo_bpm=128.0, beats_per_bar=4, confidence=0.9)
    assert apply_timing_overrides(detected) is detected


def test_a_metre_only_override_keeps_the_detected_tempo():
    from app.services.pipeline import apply_timing_overrides

    detected = TimingEstimate(tempo_bpm=128.0, beats_per_bar=4, confidence=0.9,
                              first_beat_s=0.25)
    corrected = apply_timing_overrides(detected, beats_per_bar=3)

    assert corrected.tempo_bpm == 128.0
    assert corrected.beats_per_bar == 3
    # Tempo was not touched, so its downbeat and confidence still apply.
    assert corrected.first_beat_s == 0.25
    assert corrected.confidence == 0.9
