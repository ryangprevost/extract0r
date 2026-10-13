"""Width: a part spread in stereo, mono-safe. Sprint 17."""

from __future__ import annotations

import numpy as np

from app.services.synth import width

RATE = 22050


def _part(seconds: float = 2.0) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return 0.3 * np.sign(np.sin(2 * np.pi * 220 * t)) + 0.3 * np.sin(2 * np.pi * 55 * t)


def test_no_width_is_the_part_unchanged():
    part = _part()
    assert np.array_equal(width.widen(part, RATE, 0.0), part)


def test_summed_to_mono_it_is_the_part_as_it_was():
    part = _part()
    wide = width.widen(part, RATE, 1.0)
    assert wide.shape == (part.size, 2)
    assert np.max(np.abs(wide.mean(axis=1) - part)) < 1e-12


def test_it_is_wide_and_the_low_end_stays_in_the_middle():
    part = _part()
    wide = width.widen(part, RATE, 0.7)
    left, right = wide[RATE // 2:, 0], wide[RATE // 2:, 1]
    assert np.corrcoef(left, right)[0, 1] < 0.9
    side = np.abs(np.fft.rfft((left - right) * np.hanning(left.size)))
    freqs = np.fft.rfftfreq(left.size, 1 / RATE)
    low = side[np.argmin(np.abs(freqs - 55))]
    high = side[np.argmin(np.abs(freqs - 220))]
    assert 20 * np.log10(low / high) < -20
