"""Finding individual drums in a drum stem, and laying samples over them.

The detector is checked against a beat whose every hit is known. That matters more here
than usual: the previous classifier scored itself 100% correct on this same beat while
finding none of the 32 kicks and none of the 32 snares, because it only ever named the
hi-hat that was also there. A number is not a check unless it can fail.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
import pytest

from app.services.drums.detect import Hit, count_by_kind, find_hits
from app.services.drums.kit import DRUMS, KITS, layer, render_voice

SR = 44100


def kick_sound(length=0.25):
    n = int(length * SR)
    t = np.arange(n) / SR
    pitch = 120 * np.exp(-28 * t) + 45
    body = np.sin(2 * np.pi * np.cumsum(pitch) / SR) * np.exp(-14 * t)
    click = np.random.default_rng(0).normal(0, 1, n) * np.exp(-450 * t) * 0.25
    return (body + click) * 0.9


def snare_sound(length=0.22):
    from scipy.signal import butter, sosfilt

    n = int(length * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(1)
    body = (np.sin(2 * np.pi * 185 * t) + np.sin(2 * np.pi * 330 * t)) * np.exp(-30 * t)
    rattle = sosfilt(
        butter(2, 1200 / (SR / 2), btype="high", output="sos"),
        rng.normal(0, 1, n) * np.exp(-22 * t),
    )
    return (0.35 * body + 0.75 * rattle) * 0.8


def hihat_sound(length=0.08):
    from scipy.signal import butter, sosfilt

    n = int(length * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(2)
    return (
        sosfilt(
            butter(4, 6000 / (SR / 2), btype="high", output="sos"),
            rng.normal(0, 1, n) * np.exp(-70 * t),
        )
        * 0.5
    )


@pytest.fixture(scope="module")
def beat():
    """Kick on 1 and 3, snare on 2 and 4, hats on every eighth. Every hit is known.

    The kicks and snares all land under a hat on purpose: that overlap is the case the
    old classifier could not see, and it is the ordinary case in real music.
    """
    bars, bpm = 12, 120
    beat_s = 60.0 / bpm
    total = int(bars * 4 * beat_s * SR) + SR
    audio = np.zeros(total)
    truth: list[tuple[float, str]] = []

    def place(sample, at, label):
        start = int(at * SR)
        end = min(start + sample.size, total)
        audio[start:end] += sample[: end - start]
        truth.append((at, label))

    for bar in range(bars):
        base = bar * 4 * beat_s
        for position in (0, 2):
            place(kick_sound(), base + position * beat_s, "kick")
        for position in (1, 3):
            place(snare_sound(), base + position * beat_s, "snare")
        for eighth in range(8):
            place(hihat_sound(), base + eighth * beat_s / 2, "hihat")

    audio = audio / np.abs(audio).max() * 0.7
    return np.stack([audio, audio], axis=1), truth


def score(hits, truth, drum, window=0.04):
    """Recall and false-positive rate for one drum."""
    actual = [at for at, label in truth if label == drum]
    claimed = [h.time_s for h in hits if drum in h.kinds]
    found = sum(1 for at in actual if any(abs(at - c) < window for c in claimed))
    false = sum(1 for c in claimed if not any(abs(at - c) < window for at in actual))
    return found / max(len(actual), 1), false / max(len(claimed), 1)


# ──────────────────────────────── detection ────────────────────────────────


@pytest.mark.parametrize("drum", ["kick", "snare", "hihat"])
def test_every_drum_is_found(beat, drum):
    audio, truth = beat
    recall, _ = score(find_hits(audio, SR), truth, drum)
    assert recall >= 0.9, f"only found {recall:.0%} of the {drum}s"


@pytest.mark.parametrize("drum", ["kick", "snare", "hihat"])
def test_nothing_is_invented(beat, drum):
    """A trigger on a drum that is not there is worse than a missed one: it puts a hit
    into the mix that the drummer never played."""
    audio, truth = beat
    _, false = score(find_hits(audio, SR), truth, drum)
    assert false <= 0.1, f"{false:.0%} of {drum} claims were wrong"


def test_a_kick_under_a_hat_is_still_a_kick(beat):
    """The case the old classifier could not see. Every kick here is under a hat."""
    audio, truth = beat
    counts = count_by_kind(find_hits(audio, SR))
    expected = Counter(label for _, label in truth)
    assert counts.get("kick", 0) >= expected["kick"] * 0.9
    assert counts.get("hihat", 0) >= expected["hihat"] * 0.9


def test_one_stroke_can_be_two_drums(beat):
    audio, _ = beat
    assert any(len(hit.kinds) > 1 for hit in find_hits(audio, SR))


def test_silence_has_no_drums_in_it():
    assert find_hits(np.zeros((SR * 3, 2)), SR) == []


def test_a_bass_line_is_not_a_drum_track():
    """Sustained low notes are what bleeds into a separated drums stem, and what a
    level-based detector calls kicks."""
    t = np.arange(int(SR * 6)) / SR
    bass = 0.4 * np.sin(2 * np.pi * 60 * t)
    hits = find_hits(np.stack([bass, bass], axis=1), SR)
    assert count_by_kind(hits).get("kick", 0) <= 2


def test_hits_carry_how_hard_they_were_struck(beat):
    """Ghost notes have to stay ghost notes when a sample is laid over them."""
    audio, _ = beat
    strengths = [h.strength for h in find_hits(audio, SR)]
    assert all(s >= 0 for s in strengths)
    assert max(strengths) > min(strengths)


# ──────────────────────────────── the kit ────────────────────────────────


@pytest.mark.parametrize("kit", list(KITS))
@pytest.mark.parametrize("drum", DRUMS)
def test_every_voice_renders_something_audible(kit, drum):
    sample = render_voice(KITS[kit][drum], SR)
    assert sample.size > 0
    assert np.abs(sample).max() == pytest.approx(1.0, abs=0.01)
    assert np.isfinite(sample).all()


def test_a_voice_starts_and_ends_at_zero():
    """Anything else is a click, and a click on every hit is worse than the wrong kit."""
    sample = render_voice(KITS["tight"]["snare"], SR)
    assert abs(sample[0]) < 0.01
    assert abs(sample[-1]) < 0.01


def test_the_kits_are_actually_different():
    """Swapping a sample should be audible; that is the entire point."""
    def centroid(sample):
        spectrum = np.abs(np.fft.rfft(sample))
        freqs = np.fft.rfftfreq(sample.size, 1 / SR)
        return float((spectrum * freqs).sum() / spectrum.sum())

    lengths = {k: KITS[k]["kick"].length_s for k in KITS}
    assert max(lengths.values()) / min(lengths.values()) > 1.5

    kicks = {k: centroid(render_voice(KITS[k]["kick"], SR)) for k in KITS}
    assert max(kicks.values()) - min(kicks.values()) > 100


def test_a_kick_is_low_and_a_hat_is_not():
    def peak_hz(sample):
        spectrum = np.abs(np.fft.rfft(sample))
        return float(np.fft.rfftfreq(sample.size, 1 / SR)[int(np.argmax(spectrum))])

    assert peak_hz(render_voice(KITS["tight"]["kick"], SR)) < 200
    assert peak_hz(render_voice(KITS["tight"]["hihat"], SR)) > 5000


# ──────────────────────────────── layering ────────────────────────────────


def test_no_blend_changes_nothing(beat):
    audio, _ = beat
    assert np.array_equal(layer(audio, SR, find_hits(audio, SR), blend=0.0), audio)


def test_no_hits_changes_nothing(beat):
    audio, _ = beat
    assert np.array_equal(layer(audio, SR, [], blend=0.8), audio)


def test_layering_adds_to_what_is_there(beat):
    """It reinforces rather than replaces - the original stem is still underneath."""
    audio, _ = beat
    hits = find_hits(audio, SR)
    out = layer(audio, SR, hits, kit="tight", drums=("kick", "snare"), blend=0.6)
    assert out.shape == audio.shape
    assert not np.array_equal(out, audio)
    assert float(np.sqrt((out**2).mean())) > float(np.sqrt((audio**2).mean()))


def test_more_blend_is_more_sample(beat):
    audio, _ = beat
    hits = find_hits(audio, SR)
    quiet = layer(audio, SR, hits, blend=0.2)
    loud = layer(audio, SR, hits, blend=0.9)
    assert np.abs(loud - audio).mean() > np.abs(quiet - audio).mean()


def test_choosing_drums_selects_what_gets_triggered(beat):
    audio, _ = beat
    hits = find_hits(audio, SR)
    kick_only = layer(audio, SR, hits, drums=("kick",), blend=0.8)
    both = layer(audio, SR, hits, drums=("kick", "snare"), blend=0.8)
    assert np.abs(both - audio).mean() > np.abs(kick_only - audio).mean()


def test_an_unknown_kit_falls_back_rather_than_failing(beat):
    audio, _ = beat
    out = layer(audio, SR, find_hits(audio, SR), kit="does-not-exist", blend=0.5)
    assert np.isfinite(out).all()


def test_the_triggers_land_on_the_hits(beat):
    """A sample a few milliseconds late is heard as a flam, not as the same drum."""
    audio, truth = beat
    hits = [Hit(time_s=2.0, kinds=["kick"], strength=0.5)]
    out = layer(np.zeros_like(audio), SR, hits, drums=("kick",), blend=1.0)

    energy = np.abs(out).sum(axis=1)
    landed = float(np.argmax(energy)) / SR
    assert landed == pytest.approx(2.0, abs=0.01)
