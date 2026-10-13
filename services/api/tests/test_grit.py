"""Grit: driving a part into distortion in the version. Sprint 16."""

from __future__ import annotations

import numpy as np

from app.services.synth import grit

RATE = 22050


def _saw(seconds: float = 1.0) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return 0.5 * (2 * ((110 * t) % 1) - 1)


def _crest(x: np.ndarray) -> float:
    return float(np.max(np.abs(x)) / np.sqrt(np.mean(x ** 2)))


def test_no_grit_is_the_part_unchanged():
    saw = _saw()
    assert np.array_equal(grit.drive(saw, RATE, 0.0), saw)


def test_grit_squashes_the_wave_without_making_it_louder():
    saw = _saw()
    driven = grit.drive(saw, RATE, 0.7)
    assert driven.shape == saw.shape
    level = np.sqrt(np.mean(driven ** 2)) / np.sqrt(np.mean(saw ** 2))
    assert abs(level - 1) < 1e-6
    # Squashed: peaks nearer the body. Not as far as a bare clip - the low-pass after it
    # rings a little on the squared edges.
    assert _crest(driven[RATE // 10:]) < _crest(saw[RATE // 10:]) * 0.95


def test_grit_adds_harmonics_above_the_saws():
    saw = np.sin(2 * np.pi * 220 * np.arange(RATE) / RATE) * 0.5
    driven = grit.drive(saw, RATE, 0.8)
    spectrum = np.abs(np.fft.rfft(driven * np.hanning(RATE)))
    freqs = np.fft.rfftfreq(RATE, 1 / RATE)
    second = spectrum[np.argmin(np.abs(freqs - 440))]
    third = spectrum[np.argmin(np.abs(freqs - 660))]
    first = spectrum[np.argmin(np.abs(freqs - 220))]
    # A sine has no harmonics; driven asymmetrically it gains even and odd ones.
    assert second > first * 0.01 and third > first * 0.05


def test_stereo_parts_keep_both_channels():
    saw = _saw()
    stereo = np.stack([saw, saw * 0.5], axis=1)
    driven = grit.drive(stereo, RATE, 0.5)
    assert driven.shape == stereo.shape
