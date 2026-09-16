"""The envelope has to mean the same thing on both pages that draw it.

The stem lanes and the mastering before/after now share one definition. These tests pin
the properties the drawing relies on: an absolute scale (so two files can be compared),
a floor (so a rest looks like a rest), and a difference that ignores silence.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.services.waveform import (
    QUIET_DB,
    SILENCE_FLOOR_DB,
    difference_db,
    measure,
)

SR = 44100


def write(path: Path, samples, sr=SR) -> Path:
    audio = np.asarray(samples, dtype="float32")
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    sf.write(str(path), audio, sr)
    return path


def tone(seconds=2.0, amp=0.3, freq=220.0):
    t = np.arange(int(seconds * SR)) / SR
    return amp * np.sin(2 * np.pi * freq * t)


def test_a_louder_file_measures_louder(tmp_path: Path):
    """The scale is absolute, not per-file. Without this, before/after is meaningless.

    Both files would normalise to the same shape and the picture would show a level change
    as no change at all.
    """
    quiet = measure(write(tmp_path / "q.wav", tone(amp=0.1)), buckets=100)
    loud = measure(write(tmp_path / "l.wav", tone(amp=0.4)), buckets=100)

    assert max(loud.peaks) > max(quiet.peaks)
    # Four times the amplitude is +12 dB, wherever it sits on the scale.
    assert np.mean(loud.db) - np.mean(quiet.db) == pytest.approx(12.0, abs=0.2)


def test_silence_draws_as_silence(tmp_path: Path):
    path = write(tmp_path / "s.wav", np.zeros(SR))
    envelope = measure(path, buckets=64)
    assert envelope.silent
    assert max(envelope.peaks) == 0.0
    assert min(envelope.db) == QUIET_DB


def test_near_silence_is_still_silence(tmp_path: Path):
    """Separation artefacts sit well below the floor and must not draw as spikes."""
    path = write(tmp_path / "a.wav", tone(amp=0.0005))
    assert measure(path, buckets=64).silent


def test_the_envelope_reports_real_time(tmp_path: Path):
    path = write(tmp_path / "t.wav", tone(seconds=3.0))
    envelope = measure(path, buckets=200)
    assert envelope.duration_s == pytest.approx(3.0, abs=0.05)
    assert envelope.sample_rate == SR
    assert len(envelope.peaks) == len(envelope.db) == 200


def test_the_difference_is_the_gain_between_two_renders(tmp_path: Path):
    before = measure(write(tmp_path / "b.wav", tone(amp=0.2)), buckets=80)
    after = measure(write(tmp_path / "a.wav", tone(amp=0.4)), buckets=80)

    delta = difference_db(before, after)
    assert len(delta) == 80
    assert np.mean(delta) == pytest.approx(6.0, abs=0.2)


def test_the_difference_between_two_silences_is_zero(tmp_path: Path):
    """Not the difference between two floors, which is noise dressed as a measurement."""
    before = measure(write(tmp_path / "b.wav", np.zeros(SR)), buckets=40)
    after = measure(write(tmp_path / "a.wav", np.full(SR, 1e-7, dtype="float32")), buckets=40)

    assert all(d == 0.0 for d in difference_db(before, after))


def test_a_quiet_passage_and_a_loud_one_move_independently(tmp_path: Path):
    """What the difference strip exists to show: where mastering did most of its work."""
    quiet_half = tone(seconds=1.0, amp=0.05)
    loud_half = tone(seconds=1.0, amp=0.5)
    before = measure(
        write(tmp_path / "b.wav", np.concatenate([quiet_half, loud_half])), buckets=100
    )
    # The quiet half comes up, the loud half is held where it was - a limiter, roughly.
    after = measure(
        write(tmp_path / "a.wav", np.concatenate([quiet_half * 4, loud_half])),
        buckets=100,
    )

    delta = difference_db(before, after)
    first, second = np.mean(delta[:45]), np.mean(delta[55:])
    assert first == pytest.approx(12.0, abs=0.5)
    assert second == pytest.approx(0.0, abs=0.5)


def test_the_floor_is_where_the_drawing_starts(tmp_path: Path):
    """A bucket exactly at the floor draws at zero height, not at a visible sliver."""
    amplitude = 10 ** (SILENCE_FLOOR_DB / 20) * np.sqrt(2)
    path = write(tmp_path / "f.wav", tone(amp=float(amplitude)))
    envelope = measure(path, buckets=50)
    assert max(envelope.peaks) == pytest.approx(0.0, abs=0.02)
