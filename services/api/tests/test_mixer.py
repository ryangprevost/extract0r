"""Mixing each part. Sprint 7.

The mixer's promise is that what is heard in the browser is what is bounced, so most of
these hold its arithmetic to the browser's: Web Audio's stereo pan law, the RBJ biquad that
BiquadFilterNode uses (-3 dB at the cutoff), and a feedback delay's echoes landing a dotted
eighth apart at the feedback level. And that a mixer nobody touches changes nothing.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.synth import mixer
from app.services.synth.mixer import Channel

SR = 22050


def tone(hz: float, seconds: float = 1.0, level: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    mono = level * np.sin(2 * np.pi * hz * t)
    return np.stack([mono, mono], axis=1)


def db(x: np.ndarray) -> float:
    return 10 * np.log10(np.mean(np.asarray(x) ** 2) + 1e-20)


def test_a_mixer_nobody_touched_is_the_plain_sum():
    layers = {"bass": tone(55), "guitar": tone(330)}
    out = mixer.mix(layers, {}, SR, 120.0)
    assert np.allclose(out, layers["bass"] + layers["guitar"])


def test_pan_is_web_audio_s_stereo_panner():
    left, right = np.full(4, 0.5), np.full(4, 0.2)
    stereo = np.stack([left, right], axis=1)
    hard_left = mixer.pan(stereo, -1.0)
    assert np.allclose(hard_left[:, 0], 0.7) and np.allclose(hard_left[:, 1], 0.0)
    assert np.allclose(mixer.pan(stereo, 0.0), stereo)
    # pan 0.5: x = 0.5, gainL = cos(pi/4), gainR = sin(pi/4); outL = L*gL, outR = R + L*gR
    half = mixer.pan(stereo, 0.5)
    g = np.sqrt(0.5)
    assert np.allclose(half[:, 0], 0.5 * g) and np.allclose(half[:, 1], 0.2 + 0.5 * g)


@pytest.mark.parametrize("kind, hz", [("highpass", 200.0), ("lowpass", 2000.0)])
def test_the_filters_are_three_db_down_at_the_cutoff(kind, hz):
    from scipy.signal import freqz

    b, a = mixer._biquad(kind, hz, SR)
    _, response = freqz(b, a, worN=[hz], fs=SR)
    assert 20 * np.log10(abs(response[0])) == pytest.approx(-3.01, abs=0.05)


def test_a_low_cut_takes_the_low_end_out():
    out = mixer.mix({"bass": tone(60)}, {"bass": Channel(low_cut_hz=1000)}, SR, 120.0)
    assert db(out[SR // 4:]) < db(tone(60)) - 30


def test_a_high_cut_takes_the_top_out():
    out = mixer.mix({"hat": tone(8000)}, {"hat": Channel(high_cut_hz=500)}, SR, 120.0)
    assert db(out[SR // 4:]) < db(tone(8000)) - 30


def test_gain_is_in_decibels_and_capped():
    out = mixer.mix({"x": tone(220)}, {"x": Channel(gain_db=-6.0)}, SR, 120.0)
    assert db(out) - db(tone(220)) == pytest.approx(-6.0, abs=0.01)
    loud = mixer.mix({"x": tone(220)}, {"x": Channel(gain_db=40.0)}, SR, 120.0)
    assert db(loud) - db(tone(220)) == pytest.approx(mixer.MAX_GAIN_DB, abs=0.01)


def test_mute_and_solo():
    layers = {"a": tone(110), "b": tone(220), "c": tone(440)}
    muted = mixer.mix(layers, {"b": Channel(mute=True)}, SR, 120.0)
    assert np.allclose(muted, layers["a"] + layers["c"])
    soloed = mixer.mix(layers, {"c": Channel(solo=True)}, SR, 120.0)
    assert np.allclose(soloed, layers["c"])


def test_the_delay_echoes_a_dotted_eighth_apart_at_the_feedback_level():
    click = np.zeros((SR * 4, 2))
    click[0] = 1.0
    wet = mixer.delay(click, SR, 120.0)
    d = int(round(0.75 * 0.5 * SR))
    assert wet[d, 0] == pytest.approx(1.0)
    assert wet[2 * d, 0] == pytest.approx(mixer.DELAY_FEEDBACK)
    assert wet[3 * d, 0] == pytest.approx(mixer.DELAY_FEEDBACK ** 2)
    assert not np.any(wet[:d])


def test_the_reverb_is_the_same_reverb_every_time_and_has_a_tail():
    ir = mixer.impulse(SR)
    assert np.array_equal(ir, mixer.impulse(SR))
    assert len(ir) == int(mixer.REVERB_S * SR)
    assert db(ir[: SR // 4]) > db(ir[-SR // 4:]) + 30         # it fades
    wet = mixer.mix({"x": tone(440, 0.5)}, {"x": Channel(reverb=1.0)}, SR, 120.0)
    assert len(wet) == int(0.5 * SR)                             # the file ends with the music


def test_sends_are_post_fader():
    loud = mixer.mix({"x": tone(440)}, {"x": Channel(reverb=1.0, gain_db=0.0)}, SR, 120.0)
    quiet = mixer.mix({"x": tone(440)}, {"x": Channel(reverb=1.0, gain_db=-20.0)}, SR, 120.0)
    assert db(quiet) == pytest.approx(db(loud) - 20.0, abs=0.1)


def test_the_mix_is_described_in_sentences_and_flat_says_nothing():
    lines = mixer.describe({
        "bass": Channel(gain_db=-3.0), "guitar": Channel(pan=-0.4, reverb=0.3),
        "piano": Channel(), "beat": Channel(mute=True)})
    assert lines == ["Bass: -3.0 dB.", "Guitar: panned 40% left, reverb 30%.",
                     "Added beat: muted."]


def test_the_bottom_of_the_fader_is_off():
    """The page plays silence there and says "off"; the file did -60 dB, which is not off."""
    out = mixer.mix({"x": tone(220), "y": tone(330)}, {"x": Channel(gain_db=-60.0)}, SR, 120.0)
    assert np.allclose(out, tone(330))
