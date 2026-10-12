"""Reading a reference remix's essential elements. Sprint 4.

Each element has a way of being read wrongly that was found on the first reference this
application read - a house track built here at 124 BPM with every ingredient known - and
each test holds one of those down: a tempo read at 3:2, an offbeat bass read as a 12 dB
pump, a kit that does not match itself.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.notes import NoteEvent
from app.services.drums.kit import KITS, render_voice
from app.services.synth import recipe as r
from app.services.synth.retempo import beat_grid, pump
from app.services.synth.voice import render_notes

SR = 22050


def tone(seconds: float = 8.0) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return 0.3 * np.sin(2 * np.pi * 220 * t)


@pytest.mark.parametrize("depth", [3.0, 6.0, 9.0])
def test_a_pump_is_measured_close_to_how_deep_it_went(depth):
    beats = beat_grid(0.0, 128.0, 8.0)
    measured = r.measure_pump(pump(tone(), SR, beats, 128.0, depth), SR, beats)
    assert depth * 0.85 <= measured <= depth * 1.05


def test_a_steady_part_does_not_pump():
    assert r.measure_pump(tone(), SR, beat_grid(0.0, 128.0, 8.0)) == 0.0


def test_a_bass_on_the_beat_is_not_a_pump():
    """Loudest at the start of the beat is the opposite shape."""
    beats = beat_grid(0.0, 128.0, 8.0)
    bass = render_notes([NoteEvent(b, b + 0.2, 40, 100) for b in beats], SR, "808",
                        duration_s=8.0)
    assert r.measure_pump(bass, SR, beats) == 0.0


def test_an_offbeat_bass_is_a_rhythm_not_a_pump():
    """The house bassline - silent on the beat, playing between. On the test reference this
    read 12 dB and up against a real pump of 6."""
    beats = beat_grid(0.0, 124.0, 8.0)
    half = 30.0 / 124.0
    bass = render_notes([NoteEvent(b + half, b + 2 * half * 0.95, 33, 110) for b in beats],
                        SR, "808", duration_s=8.0)
    assert r.measure_pump(bass, SR, beats) == 0.0


@pytest.mark.parametrize("kit", list(KITS))
def test_every_kit_s_kick_is_matched_to_itself(kit):
    features = r.kick_features(render_voice(KITS[kit]["kick"], SR, seed=0), SR)
    assert r.nearest_kit(features, SR)[0] == kit


def floor(bpm: float, seconds: float = 20.0) -> np.ndarray:
    out = np.zeros(int(seconds * SR))
    kick = render_voice(KITS["roomy"]["kick"], SR, seed=0)
    for t in np.arange(0.0, seconds - 1.0, 60.0 / bpm):
        at = int(t * SR)
        out[at: at + kick.size] += kick[: out.size - at]
    return np.stack([out, out], axis=1)


@pytest.mark.parametrize("estimate", [124.0, 186.0, 93.0, 62.0, 248.0, 165.3])
def test_a_reference_s_tempo_survives_the_estimator_s_usual_mistakes(estimate):
    bpm, first = r.dance_tempo(floor(124.0), SR, estimate)
    assert bpm == pytest.approx(124.0, abs=0.2)
    # A kick a hair before zero comes back as almost a whole beat later; same beat.
    period = 60.0 / bpm
    assert min(first, period - first) < 0.03


def test_the_tempo_line_says_when_it_had_to_halve():
    assert "half speed" in r.tempo_line(260.0, 170.0, 130.0)
    assert "moves to theirs" in r.tempo_line(124.0, 170.0, 124.0)


def test_no_pump_is_said_plainly():
    assert r.pump_line(0.0).startswith("No pump")
    assert "6 dB" in r.pump_line(6.0)
