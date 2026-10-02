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

from app.services.drums.detect import Hit, count_by_kind, find_hits, kinds_for
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


# --- a kick is not a snare --------------------------------------------------------------
#
# Reported by ear before any measurement caught it: "i am a little confused by the new
# snare being layered on top of the kick. any drum replacement should happen per-drum."
#
# A loud electronic kick is not a quiet event anywhere. Its transient click lifts the
# rattle band and its harmonics lift the body band, so it satisfied every test the snare
# rule had — and `layer` renders one voice per label, so a snare sample landed on top of
# 27 of a reference's 35 kicks. Measured over three real drum stems, taking
# `kick rise - rattle rise`: a genuine snare sits at -8 to -14 dB, a kick alone at +28 to
# +32, and the false claims at +12. The fix cuts at zero, which is the same "which band
# jumped furthest" test the rule already used against hi-hats.


def electronic_kick(length=0.3):
    """The shape that broke it: a long low body and a hard wideband click.

    Deliberately harsher than `kick_sound`. A club kick is engineered to cut through on
    small speakers, which means a click with real energy well above the body — exactly
    the thing a snare detector is looking for.
    """
    n = int(length * SR)
    t = np.arange(n) / SR
    pitch = 160 * np.exp(-22 * t) + 48
    body = np.sin(2 * np.pi * np.cumsum(pitch) / SR) * np.exp(-9 * t)
    click = np.random.default_rng(7).normal(0, 1, n) * np.exp(-260 * t) * 0.6
    return (body + click) * 0.98


# Rises measured off three real drum stems, in dB. These are the numbers the rule has to
# get right; synthesising audio that produces them turned out to need a filter steep
# enough to ring, and the ringing produced phantom onsets louder than the thing under
# test. Measuring real drums once and pinning the decision is both simpler and closer to
# what actually broke.
ALL_PRESENT = {"kick": True, "snare_body": True, "snare_rattle": True, "hihat": True}

#: A club kick from the reference, which used to be labelled a snare as well. Everything
#: rises, because a loud kick is not a quiet event anywhere — but the low end rises most.
MEASURED_CLUB_KICK = {"kick": 50.1, "snare_body": 54.8, "snare_rattle": 42.7, "hihat": 32.8}

#: A genuine snare from the same stem: the rattle leads and the low end does not.
MEASURED_SNARE = {"kick": 28.8, "snare_body": 40.1, "snare_rattle": 42.7, "hihat": 31.0}

#: A kick with nothing else on it. The high band barely moves — below `RISE_DB`, which
#: is what "nothing else on it" means to this rule.
MEASURED_BARE_KICK = {"kick": 44.0, "snare_body": 30.0, "snare_rattle": 12.5, "hihat": 2.0}


def test_a_club_kick_is_not_also_a_snare():
    """The bug Ryan heard, as the decision that caused it.

    Every snare test passed on this stroke — the rattle jumped 42.7 dB, the body 54.8,
    and the rattle beat the hi-hat. `layer` renders one voice per label, so a snare
    sample landed on top of 27 of the reference's 35 kicks.
    """
    kinds = kinds_for(MEASURED_CLUB_KICK, ALL_PRESENT)
    assert "kick" in kinds
    assert "snare" not in kinds, f"a kick is not a snare: {kinds}"


def test_a_real_snare_is_still_a_snare():
    """The other half. A rule that silenced the false snares by silencing all of them
    would pass the test above and be useless."""
    assert "snare" in kinds_for(MEASURED_SNARE, ALL_PRESENT)


def test_a_bare_kick_is_only_a_kick():
    assert kinds_for(MEASURED_BARE_KICK, ALL_PRESENT) == ["kick"]


def test_the_rule_cuts_where_the_two_populations_separate():
    """Why the threshold is zero and not a tuned constant.

    Measured over three stems as `kick rise - rattle rise`: a genuine snare sits at -8 to
    -14 dB, a kick alone at +28 to +32, and the false claims at +12. The gap between the
    populations is wide and empty, so the cut needs no constant — "whichever band jumped
    furthest wins" is the same test the rule already applied against hi-hats.
    """
    for gap, expect_snare in ((-14.0, True), (-8.0, True), (0.0, True), (+4.0, False),
                              (+12.0, False), (+30.0, False)):
        rises = {"kick": 42.7 + gap, "snare_body": 50.0,
                 "snare_rattle": 42.7, "hihat": 30.0}
        kinds = kinds_for(rises, ALL_PRESENT)
        assert ("snare" in kinds) is expect_snare, (
            f"kick-rattle {gap:+.0f} dB should {'' if expect_snare else 'not '}"
            f"be a snare, got {kinds}"
        )


def test_an_electronic_kick_does_not_trigger_a_snare():
    """The bug, as a test. Bare kicks, no snare anywhere in the signal.

    The pattern starts half a second in rather than at zero: an onset at t=0 has no
    quiet moment before it to rise *from*, so the detector does not see it. That is a
    property of measuring a rise and not something this test is about.
    """
    track = np.zeros((int(SR * 4.0), 2))
    hit = electronic_kick()
    starts = [0.5, 1.0, 1.5, 2.0]
    for when in starts:
        start = int(when * SR)
        track[start : start + len(hit), 0] += hit
        track[start : start + len(hit), 1] += hit

    hits = find_hits(track, SR)
    counts = count_by_kind(hits)
    assert counts.get("kick", 0) >= len(starts) - 1, f"the kicks must still be found: {counts}"
    assert counts.get("snare", 0) == 0, (
        f"a kick on its own is not a snare, found {counts.get('snare', 0)}: {counts}"
    )


def test_a_real_snare_survives_the_new_rule():
    """The other half. A rule that silenced the false snares by silencing all of them
    would pass the test above and be useless."""
    track = np.zeros((int(SR * 4.0), 2))
    snare = snare_sound()
    for beat_index in range(4):
        start = int((beat_index * 1.0 + 0.5) * SR)
        track[start : start + len(snare), 0] += snare
        track[start : start + len(snare), 1] += snare

    counts = count_by_kind(find_hits(track, SR))
    assert counts.get("snare", 0) >= 4, f"real snares must still be found: {counts}"


def test_a_snare_over_a_kick_is_still_a_snare():
    """What the fix is allowed to cost, pinned so it cannot quietly grow.

    The new clause declines a snare whose rattle is quieter than the kick underneath it.
    What it must not do is decline a snare that is plainly there on top of low-end
    energy — so this puts a snare over a kick and demands the snare survives.

    It deliberately does *not* assert that both labels appear. Measured on this signal
    the kick label is the one that drops, and for an unrelated, pre-existing reason: the
    synthetic snare's noise lifts the hi-hat band above the kick band, and the kick rule
    has always rejected a stroke whose top octave out-jumped its low end as a cymbal.
    That behaviour is the same before and after this change. Real drum stems do yield
    both — five of the reference's hits carry kick and snare together, with the rattle
    genuinely ahead — and asserting it here would be testing the fixture, not the rule.
    """
    track = np.zeros((int(SR * 4.0), 2))
    kick, snare = kick_sound(), snare_sound()
    for beat_index in range(4):
        start = int((beat_index * 1.0 + 0.5) * SR)
        for sound in (kick, snare * 1.4):
            track[start : start + len(sound), 0] += sound
            track[start : start + len(sound), 1] += sound

    counts = count_by_kind(find_hits(track, SR))
    assert counts.get("snare", 0) >= 3, (
        f"a snare on top of a kick is still a snare: {counts}"
    )


# --- replacement takes one drum per stroke ----------------------------------------------
#
# A stroke's `kinds` lists everything it contains, which is right for describing it and
# wrong for replacing it. Kick and snare are hard to tell apart on a summed stem, and on
# real material the two measurements sit within a decibel of each other often enough that
# a hard threshold flickers: consecutive kicks measured at -0.5, +5.3 and -0.7 dB, so the
# snare sample landed on the middle one and not its neighbours. Reported by ear as a snare
# that "comes in and out at various kick hits".


def test_a_kick_dominant_stroke_is_replaced_as_a_kick_only():
    from app.services.drums.kit import replaceable

    hit = Hit(time_s=1.0, kinds=["kick", "snare", "hihat"], strength=0.5,
              rises={"kick": 50.1, "snare_rattle": 42.7, "snare_body": 54.8, "hihat": 32.8})
    assert replaceable(hit) == ["kick", "hihat"]
    # The label itself is left alone — it is still true that the stroke contains both.
    assert "snare" in hit.kinds


def test_a_snare_dominant_stroke_is_replaced_as_a_snare_only():
    from app.services.drums.kit import replaceable

    hit = Hit(time_s=1.0, kinds=["kick", "snare"], strength=0.5,
              rises={"kick": 44.5, "snare_rattle": 49.2, "snare_body": 54.8, "hihat": 40.0})
    assert replaceable(hit) == ["snare"]


def test_a_stroke_with_only_one_of_them_is_untouched():
    from app.services.drums.kit import replaceable

    hit = Hit(time_s=1.0, kinds=["snare", "hihat"], strength=0.5, rises={})
    assert replaceable(hit) == ["snare", "hihat"]


def test_no_stroke_ever_gets_both_a_kick_and_a_snare_laid_over_it():
    """The property, over a whole stem rather than a hand-built stroke.

    This is the one that would have caught the original report. Whatever the classifier
    decides, the thing the listener hears must never be both samples on one stroke.
    """
    from app.services.drums.kit import replaceable

    track = np.zeros((int(SR * 4.0), 2))
    kick, snare = kick_sound(), snare_sound()
    for index in range(6):
        start = int((0.4 + index * 0.5) * SR)
        for sound in (kick, snare * 1.2):
            track[start : start + len(sound), 0] += sound
            track[start : start + len(sound), 1] += sound

    for hit in find_hits(track, SR):
        chosen = replaceable(hit)
        assert not ("kick" in chosen and "snare" in chosen), (
            f"stroke at {hit.time_s:.2f}s would get both samples: {chosen}"
        )
