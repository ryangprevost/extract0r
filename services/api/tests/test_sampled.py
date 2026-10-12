"""Sampling a sound from the reference (Sprint 15) and fitting styles to a song's tempo."""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.domain.notes import NoteEvent
from app.services.synth import sampled, styles

RATE = 22050


def _saw(midi: int, seconds: float, cents: float = 0.0) -> np.ndarray:
    hz = 440.0 * 2 ** ((midi - 69 + cents / 100) / 12)
    t = np.arange(int(seconds * RATE)) / RATE
    wave = sum(np.sin(2 * np.pi * k * hz * t) / k for k in range(1, 12))
    envelope = np.minimum(1.0, t / 0.005) * np.exp(-t * 0.3)
    return 0.3 * wave * envelope


def _stem() -> tuple[np.ndarray, list[NoteEvent]]:
    """Three clean notes 20 cents sharp, then a chord: two pitches at once."""
    audio = np.zeros(int(6.0 * RATE))
    notes = []
    for i, midi in enumerate((45, 52, 57)):
        at = 0.2 + i * 1.2
        piece = _saw(midi, 0.9, cents=20)
        audio[int(at * RATE): int(at * RATE) + piece.size] += piece
        notes.append(NoteEvent(at, at + 0.9, midi, 100))
    at = 4.0
    for midi in (60, 64, 67):
        piece = _saw(midi, 1.2)
        audio[int(at * RATE): int(at * RATE) + piece.size] += piece
        notes.append(NoteEvent(at, at + 1.2, midi, 100))
    return np.stack([audio, audio], axis=1), notes


def test_clean_notes_are_found_and_chords_are_not():
    audio, notes = _stem()
    found = sampled.find_candidates(audio, RATE, notes)
    assert sorted(c.pitch for c in found) == [45, 52, 57]
    for c in found:
        assert c.cents == pytest.approx(20, abs=4)
        assert c.harmonicity > 0.8 and c.overlaps == 0


def test_a_cut_is_tuned_to_the_note_and_held():
    audio, notes = _stem()
    c = next(c for c in sampled.find_candidates(audio, RATE, notes) if c.pitch == 57)
    note = sampled.cut(audio, RATE, c)
    hz = 440.0 * 2 ** ((57 - 69) / 12)
    got = sampled.refine_hz(note[int(0.2 * RATE): int(0.3 * RATE)], RATE, hz)
    assert 1200 * np.log2(got / hz) == pytest.approx(0, abs=4)
    # Held past the 0.9 s it was played for, by looping its steady middle.
    assert len(note) / RATE > 1.5
    assert np.max(np.abs(note)) == pytest.approx(0.9, abs=1e-6)


def test_an_instrument_is_named_for_the_reference_and_goes_with_its_track(tmp_path):
    from app.services.synth import instruments

    audio, notes = _stem()
    found = sampled.find_candidates(audio, RATE, notes)
    picks = [(c, sampled.cut(audio, RATE, c)) for c in found]
    storage = tmp_path / "storage"
    (storage / "track1").mkdir(parents=True)
    made = sampled.make_instrument(tmp_path / "samples", "their bass", "bass", "ref.mp3", picks,
                                   RATE, "notice", "track1")
    found_again = instruments.find(made, tmp_path / "samples")
    assert found_again is not None and found_again.origin == "reference"
    assert sorted(found_again.notes) == [45, 52, 57]
    meta = json.loads((found_again.folder / "instrument.json").read_text("utf-8"))
    assert "ref.mp3" in meta["about"] and meta["track_id"] == "track1"

    assert sampled.forget_missing(tmp_path / "samples", storage) == []
    (storage / "track1").rmdir()
    assert sampled.forget_missing(tmp_path / "samples", storage) == [made]
    assert instruments.find(made, tmp_path / "samples") is None


def test_a_fast_song_is_offered_the_styles_that_keep_its_speed():
    assert styles.suggested(169.0) == ["Drum and bass", "Half-time"]
    house = styles.fit("House", 169.0)
    assert house["tempo"] == 126 and house["change"] == pytest.approx(-0.254, abs=0.001)
    assert "drags" in house["fit"]
    inside = styles.fit("Half-time", 169.04)
    assert inside["tempo"] == pytest.approx(169.04) and inside["keeps_speed"]
    assert styles.fit("House", 0)["tempo"] == 124


def test_a_tempo_a_hair_from_the_songs_is_the_songs(monkeypatch):
    from app.api import routes_master

    monkeypatch.setattr(routes_master, "_tempo_of", lambda track_id, registry: 169.04)
    assert routes_master._as_asked("t", None, 169.0) == 169.04
    assert routes_master._as_asked("t", None, 172.0) == 172.0
    assert routes_master._as_asked("t", None, None) is None
