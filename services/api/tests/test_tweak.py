"""Tuning a sampled sound: pitch, length, release and EQ, applied when it plays. Sprint 22."""

from __future__ import annotations

import json

import numpy as np
import soundfile as sf

from app.domain.notes import NoteEvent
from app.services.synth import instruments

RATE = 22050


def _instrument(tmp_path, tweak=None):
    folder = tmp_path / "instruments" / "saw"
    folder.mkdir(parents=True)
    t = np.arange(int(2.0 * RATE)) / RATE
    saw = 0.5 * (2 * ((220 * t) % 1) - 1)
    sf.write(str(folder / "57.wav"), saw, RATE)
    meta = {"name": "saw", "kind": "lead", "notes": {"57": "57.wav"}}
    if tweak is not None:
        meta["tweak"] = tweak
    (folder / "instrument.json").write_text(json.dumps(meta), "utf-8")
    return instruments.find("saw", tmp_path)


def _pitch(x):
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x)), 8 * len(x)))
    return np.argmax(spectrum) * RATE / (8 * len(x))


def test_settings_are_cleaned_into_their_ranges():
    assert instruments.clean_tweak({"semitones": 40, "cents": 0, "bogus": 3}) == {"semitones": 12.0}
    assert instruments.clean_tweak({"release_ms": -5}) == {}


def test_no_tuning_is_the_sound_as_sampled(tmp_path):
    plain = _instrument(tmp_path)
    note = [NoteEvent(0.0, 0.5, 57, 100)]
    a, _, _ = instruments.render(note, plain, RATE, 1.0)
    assert np.max(np.abs(a)) > 0.1


def test_pitch_length_and_eq_are_applied(tmp_path):
    tuned = _instrument(tmp_path, {"semitones": 12, "max_s": 0.2, "release_ms": 0,
                                   "high_cut_hz": 1000})
    note = [NoteEvent(0.0, 0.8, 57, 100)]
    a, _, _ = instruments.render(note, tuned, RATE, 1.0)
    assert abs(_pitch(a[1000:4000]) - 440) < 10           # an octave up
    assert np.max(np.abs(a[int(0.25 * RATE):])) < 1e-6     # cut at 0.2 s, no release
    power = np.abs(np.fft.rfft(a[1000:4000])) ** 2
    freqs = np.fft.rfftfreq(3000, 1 / RATE)
    assert power[freqs > 3000].sum() < 0.02 * power.sum()       # the top cut at 1 kHz
