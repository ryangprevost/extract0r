"""Chops and stabs. Sprint 19."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.synth.chop import Chop, apply
from app.services.synth.edit import BeatNote, stabs

RATE = 8000
BEATS = np.arange(0, 16) * 0.5            # 120 BPM, four bars


def _audio():
    t = np.arange(int(8 * RATE)) / RATE
    return np.stack([np.sin(2 * np.pi * 110 * t), np.cos(2 * np.pi * 110 * t)], axis=1)


def test_no_chops_is_the_audio_unchanged():
    a = _audio()
    assert np.array_equal(apply(a, RATE, BEATS, []), a)


def test_chops_are_linear_so_layers_still_add_up():
    a, b = _audio(), _audio()[::-1].copy()
    chops = [Chop(2, 3, 1, "stutter"), Chop(3, 2, 2, "gate"), Chop(4, 3, 1, "stop")]
    together = apply(a + b, RATE, BEATS, chops)
    apart = apply(a, RATE, BEATS, chops) + apply(b, RATE, BEATS, chops)
    assert np.max(np.abs(together - apart)) < 1e-9


def test_a_stop_is_silent_and_a_stutter_repeats_its_first_slice():
    a = _audio()
    out = apply(a, RATE, BEATS, [Chop(4, 3, 1, "stop"), Chop(2, 0, 1, "stutter")])
    start = int(BEATS[15] * RATE) + 50
    assert np.max(np.abs(out[start: start + 1000])) < 1e-9
    eighth = int(0.25 * RATE)              # half a beat at 120 BPM
    s = int(BEATS[4] * RATE)
    assert np.allclose(out[s + 100: s + 500], out[s + eighth + 100: s + eighth + 500])


def test_stabs_cut_the_chords_on_the_rhythm():
    chords = [BeatNote(0, 4, 60, 90), BeatNote(0, 4, 64, 90)]
    cut = stabs(chords, ("..x.............",))
    assert [(n.beat, n.pitch) for n in cut] == [(0.5, 60), (0.5, 64)]
    assert all(n.length == 0.2 for n in cut)


def test_a_part_chop_is_only_in_that_part():
    a = _audio()
    lead = Chop(2, 0, 1, "stutter", ("piano",))
    assert np.array_equal(apply(a, RATE, BEATS, [lead]), a)                  # the mix: not here
    assert np.array_equal(apply(a, RATE, BEATS, [lead], layer="bass"), a)    # another part: no
    assert not np.array_equal(apply(a, RATE, BEATS, [lead], layer="piano"), a)


def test_a_rise_climbs_a_semitone_a_sixteenth():
    t = np.arange(int(8 * RATE)) / RATE
    tone = np.sin(2 * np.pi * 440 * t)
    out = apply(tone, RATE, BEATS, [Chop(2, 0, 1, "rise")])
    sixteenth = int(0.125 * RATE)
    s = int(BEATS[4] * RATE)

    def pitch(x):
        spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x)), 8 * len(x)))
        return np.argmax(spectrum) * RATE / (8 * len(x))

    first = pitch(out[s + 50: s + sixteenth - 150])
    third = pitch(out[s + 2 * sixteenth + 50: s + 3 * sixteenth - 250])
    assert 12 * np.log2(third / first) == pytest.approx(2, abs=0.3)


def test_a_tape_stop_slows_to_silence():
    a = _audio()
    out = apply(a, RATE, BEATS, [Chop(3, 0, 2, "tape")])
    s, e = int(BEATS[8] * RATE), int(BEATS[10] * RATE)
    assert np.max(np.abs(out[e - 5: e])) < 0.2
    # It starts at full speed: the first few samples barely drift.
    assert np.max(np.abs(out[s: s + 40] - a[s: s + 40])) < 0.05
