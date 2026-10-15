"""The club finish: loud enough to play out, and honest about what that cost. Sprint 23."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering import club
from app.services.mastering.loudness_meter import integrated_loudness

RATE = 22050


def _mix(seconds: float = 6.0, peak: float = 0.3):
    """Something with transients to clip: a kick-ish thump every half second under a tone."""
    t = np.arange(int(seconds * RATE)) / RATE
    tone = 0.2 * np.sin(2 * np.pi * 110 * t)
    hits = np.zeros_like(t)
    for at in np.arange(0, seconds, 0.5):
        i = int(at * RATE)
        n = int(0.05 * RATE)
        hits[i: i + n] += np.exp(-np.arange(n) / (0.01 * RATE)) * peak * 3
    mono = np.clip(tone + hits, -1, 1)
    return np.stack([mono, mono], axis=1)


def test_it_lands_on_the_target_under_the_ceiling():
    out, report = club.finish(_mix(), RATE, target_lufs=-9.5)
    got, _ = integrated_loudness(out, RATE)
    assert got == pytest.approx(-9.5, abs=0.3)
    assert report.true_peak_dbtp <= club.CEILING_DBTP + 0.05
    assert np.max(np.abs(out)) <= 1.0


def test_a_quieter_target_is_quieter_and_limits_less():
    loud, loud_report = club.finish(_mix(), RATE, target_lufs=-8.0)
    gentle, gentle_report = club.finish(_mix(), RATE, target_lufs=-14.0)
    assert integrated_loudness(gentle, RATE)[0] < integrated_loudness(loud, RATE)[0] - 4
    assert gentle_report.clipped_share <= loud_report.clipped_share


def test_the_clipper_rounds_the_tips_and_leaves_the_rest_alone():
    quiet = np.linspace(-0.5, 0.5, 2000)[:, None] * np.ones((1, 2))
    assert np.max(np.abs(club.soft_clip(quiet) - quiet)) < 1e-6      # under the knee
    # Over the ceiling it settles exactly there - away from the array's ends, where the
    # resampler rings; holding the ceiling for real is the limiter's job, tested above.
    loud = np.ones((2000, 2)) * 2.0
    assert np.max(np.abs(club.soft_clip(loud)[100:-100])) <= 10 ** (club.CEILING_DBTP / 20) + 1e-4
    sine = np.stack([1.5 * np.sin(2 * np.pi * 110 * np.arange(RATE) / RATE)] * 2, axis=1)
    assert np.max(np.abs(club.soft_clip(sine)[200:-200])) <= 10 ** (club.CEILING_DBTP / 20) + 1e-3


def test_it_says_what_the_limiting_cost():
    out, report = club.finish(_mix(), RATE, target_lufs=-8.0)
    said = " ".join(report.said())
    assert "LUFS" in said and "dBTP" in said
    assert "clipper" in said or "limiter" in said
    assert report.to_dict()["after_lufs"] == pytest.approx(-8.0, abs=0.3)


def test_matching_a_reference_never_lifts_the_top():
    """A bright reference must not turn a gritty mix brighter - only cuts apply up there."""
    t = np.arange(RATE * 4) / RATE
    bright = np.stack([0.2 * np.sin(2 * np.pi * 6000 * t)] * 2, axis=1)
    dull = _mix(4.0)
    toned, said = club._toned(dull, bright, RATE)

    def top(x):
        """Energy above 3 kHz - absolute, not a share: the curve may cut the lows, which
        would raise a share without lifting anything up here."""
        power = np.abs(np.fft.rfft(x[:, 0] * np.hanning(len(x)))) ** 2
        freqs = np.fft.rfftfreq(len(x), 1 / RATE)
        return power[freqs > 3000].sum()

    assert top(toned) <= top(dull) * 1.02
    assert isinstance(said, str) and said
