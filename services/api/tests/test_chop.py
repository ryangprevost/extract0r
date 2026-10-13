"""Chops and stabs. Sprint 19."""

from __future__ import annotations

import numpy as np

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
