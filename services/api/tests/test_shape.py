"""Shaping the sounds. Sprint 8.

The rules: every knob at 0 is the stock sound exactly; each knob does the thing its name
says, measured; a shaped voice still plays the note it is asked for, at every extreme; and a
saved sound plays wherever a built-in one does.
"""

from __future__ import annotations

import io
import itertools

import numpy as np
import pytest
import soundfile as sf

from app.services.drums.kit import DRUMS, KITS, render_voice
from app.services.synth import shape
from app.services.synth.voice import VOICES, hz, render_note

SR = 22050
PITCHES = [36, 48, 60, 72]


def peak_hz(audio: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(audio.size)))
    return float(np.fft.rfftfreq(audio.size, 1 / SR)[int(np.argmax(spectrum))])


def centroid(audio: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(audio.size, 1 / SR)
    return float((spectrum * freqs).sum() / spectrum.sum())


@pytest.mark.parametrize("name", sorted(VOICES))
def test_every_knob_at_zero_is_the_stock_voice(name):
    assert shape.shape_voice(VOICES[name], {}) == VOICES[name]
    assert shape.shape_voice(VOICES[name], {k: 0 for k in shape.VOICE_KNOBS}) == VOICES[name]


@pytest.mark.parametrize("kit", list(KITS))
def test_every_knob_at_zero_is_the_stock_kit(kit):
    assert shape.shape_kit(kit, {}) == {d: KITS[kit][d] for d in DRUMS}


EXTREMES = [{k: v for k in shape.VOICE_KNOBS} for v in (-1.0, 1.0)] + [
    {k: v} for k, v in itertools.product(shape.VOICE_KNOBS, (-1.0, 1.0))]


@pytest.mark.parametrize("name", sorted(VOICES))
@pytest.mark.parametrize("knobs", EXTREMES,
                         ids=lambda k: ",".join(f"{a}{b:+.0f}" for a, b in k.items()))
def test_a_shaped_voice_still_plays_its_note(name, knobs):
    """`test_synth`'s rule for the built-ins, at every extreme: the loudest partial is the
    note asked for, within 3% - an octave, a fifth or a tone would all fail.

    A 1.2 s note, where `test_synth` uses 0.6: the reese's two copies sit 1.3% either side
    of the note, and at 65 Hz a 0.6 s window's bins are too coarse to tell them from it -
    a shortened reese read 0.966 there, which is bin spacing, not a wrong note."""
    patch = shape.shape_voice(VOICES[name], knobs)
    for pitch in PITCHES:
        audio = render_note(patch, pitch, 1.2, SR)
        ratio = peak_hz(audio) / hz(pitch)
        assert 0.97 < ratio < 1.03, f"{name} {knobs} at {pitch}: {ratio:.3f}"


def test_brightness_is_brighter():
    dark = render_note(shape.shape_voice(VOICES["supersaw"], {"brightness": -1}), 48, 0.6, SR)
    bright = render_note(shape.shape_voice(VOICES["supersaw"], {"brightness": 1}), 48, 0.6, SR)
    assert centroid(bright) > 1.5 * centroid(dark)


def test_length_and_attack_change_the_envelope():
    long = shape.shape_voice(VOICES["pluck"], {"length": 1})
    soft = shape.shape_voice(VOICES["pluck"], {"attack": 1})
    assert long.decay_s == pytest.approx(VOICES["pluck"].decay_s * 3)
    assert soft.attack_s == pytest.approx(VOICES["pluck"].attack_s * 6)


def test_width_adds_copies_and_spread():
    wide = shape.shape_voice(VOICES["808"], {"width": 1})
    assert wide.stack == 2 and wide.detune_cents > 0
    assert shape.shape_voice(VOICES["supersaw"], {"width": -1}).detune_cents == 0


def test_weight_never_passes_the_sub_ceiling():
    heavy = shape.shape_voice(VOICES["subbass"], {"weight": 1})
    assert heavy.sub_level <= shape.MAX_SUB


def test_tune_moves_a_kick_an_octave():
    stock = shape.shape_drum(KITS["tight"]["kick"], {})
    up = shape.shape_drum(KITS["tight"]["kick"], {"tune": 1})
    assert up.pitch_to == pytest.approx(2 * stock.pitch_to)
    low = render_voice(shape.shape_drum(KITS["tight"]["kick"], {"tune": -1}), SR)
    assert peak_hz(low) < peak_hz(render_voice(stock, SR))


def test_length_and_snap_on_a_snare():
    snare = KITS["tight"]["snare"]
    longer = render_voice(shape.shape_drum(snare, {"length": 1}), SR)
    assert len(longer) == pytest.approx(2 * len(render_voice(snare, SR)), abs=2)
    assert shape.shape_drum(snare, {"snap": 1}).noise_level == pytest.approx(
        min(1.0, snare.noise_level * 3))


def test_a_shaped_sound_is_described_in_words():
    assert shape.describe("voice", "808", {"brightness": 0.5, "length": 0.8}) == \
        "the 808, brighter, longer"
    assert shape.describe("kit", "edm", {"kick": {"tune": -0.6}}) == "the edm kit, kick lower"
    assert shape.describe("voice", "pad", {}) == "the pad"


# --- through the API ---------------------------------------------------------------------------


def test_the_knobs_are_listed(client):
    body = client.get("/api/v1/tracks/sounds").json()
    assert "brightness" in body["voice_knobs"] and "tune" in body["drum_knobs"]
    assert body["yours"] == []


@pytest.mark.parametrize("body", [
    {"kind": "voice", "base": "808", "knobs": {"brightness": 0.6}},
    {"kind": "kit", "base": "edm", "knobs": {"kick": {"tune": -0.5}, "hihat": {"tone": 1}}},
])
def test_a_sound_can_be_heard_before_it_is_kept(client, body):
    response = client.post("/api/v1/tracks/sounds/preview", json=body)
    assert response.status_code == 200 and response.headers["content-type"] == "audio/wav"
    audio, _ = sf.read(io.BytesIO(response.content))
    assert np.max(np.abs(audio)) > 0.5


def test_a_kept_sound_is_in_the_voice_list_and_plays(client):
    saved = client.post("/api/v1/tracks/sounds", json={
        "kind": "voice", "base": "pluck", "knobs": {"length": 0.7}, "name": "long pluck"})
    assert saved.status_code == 201, saved.text
    assert saved.json()["about"] == "the pluck, longer"
    voices = {v["id"]: v for v in client.get("/api/v1/tracks/voices").json()["voices"]}
    assert voices["long pluck"]["label"] == "long pluck (yours)"
    preview = client.get("/api/v1/tracks/library/voices/long pluck/preview")
    assert preview.status_code == 200
    assert client.delete("/api/v1/tracks/sounds/long pluck").status_code == 204


@pytest.mark.parametrize("body, code", [
    ({"kind": "voice", "base": "kazoo", "name": "x"}, 400),
    ({"kind": "drum", "base": "edm", "name": "x"}, 422),
    ({"kind": "voice", "base": "808", "name": "../x"}, 400),
    ({"kind": "voice", "base": "808", "name": "pad"}, 409),
    ({"kind": "voice", "base": "808", "name": "edm"}, 409),
])
def test_a_bad_sound_is_refused_with_the_reason(client, body, code):
    assert client.post("/api/v1/tracks/sounds", json=body).status_code == code
