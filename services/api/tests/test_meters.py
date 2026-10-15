"""Meters over time, and the loudness-matched A/B. Sprint 24 (X0R-1205, X0R-804)."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering import meters

RATE = 16000


def _stereo(left, right):
    return np.stack([left, right], axis=1)


def _tone(seconds, hz=220, amp=0.3):
    t = np.arange(int(seconds * RATE)) / RATE
    return amp * np.sin(2 * np.pi * hz * t)


def test_correlation_knows_agreement_from_cancellation():
    same = _tone(1.0)
    assert meters.correlation(_stereo(same, same)) == pytest.approx(1.0, abs=1e-6)
    assert meters.correlation(_stereo(same, -same)) == pytest.approx(-1.0, abs=1e-6)
    assert abs(meters.correlation(_stereo(same, _tone(1.0, 331)))) < 0.2
    assert meters.correlation(np.zeros((100, 2))) == 1.0      # silence is not fighting


def test_a_mix_that_cancels_in_mono_is_called_out():
    quiet, loud = _tone(4.0), _tone(4.0)
    out = meters.over_time(_stereo(np.concatenate([quiet, loud]),
                                   np.concatenate([quiet, -loud])), RATE)
    assert out["fighting"], "the out-of-phase half should be reported"
    start, end = out["fighting"][0]
    assert start >= 3.0 and end >= 7.0
    assert any("mono" in line for line in out["said"])


def test_a_mix_that_agrees_is_not_called_out():
    same = _tone(8.0)
    out = meters.over_time(_stereo(same, same), RATE)
    assert out["fighting"] == []
    assert min(out["correlation"]) > 0.9


def test_the_series_follow_the_song_and_the_range_is_measured():
    """Three levels within the gate window - a verse, a chorus and a bigger chorus."""
    song = np.concatenate([_tone(4.0, amp=0.08), _tone(4.0, amp=0.2), _tone(4.0, amp=0.5)])
    out = meters.over_time(_stereo(song, song), RATE)
    assert len(out["times"]) == len(out["short_term"]) == len(out["momentary"])
    assert out["short_term"][-2] > out["short_term"][1] + 10
    assert out["loudness_range_lu"] > 5
    assert out["true_peak_dbtp"] > -12


def test_a_quiet_intro_is_gated_out_of_the_range_as_ebu_gates_it():
    """A passage far under the song's own loudness is an intro, not part of its range."""
    song = np.concatenate([_tone(4.0, amp=0.02), _tone(8.0, amp=0.5)])
    out = meters.over_time(_stereo(song, song), RATE)
    assert out["loudness_range_lu"] < 3


def test_a_series_too_short_to_measure_says_so_rather_than_zero():
    assert meters.loudness_range([-9.0, -9.0]) is None
    assert meters.loudness_range([-9.0] * 8) == 0.0


def test_an_even_song_has_little_range():
    steady = _tone(10.0, amp=0.3)
    out = meters.over_time(_stereo(steady, steady), RATE)
    assert out["loudness_range_lu"] < 2
    assert any("even" in line for line in out["said"])
