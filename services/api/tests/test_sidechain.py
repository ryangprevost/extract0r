"""The duck, applied and then measured back by the detector that asked for it.

The round-trip is the test that matters. `fingerprint.kick_duck` and
`sidechain.gain_envelope` are two halves of one claim - that this application can tell how
far a bass gets out of a kick's way, and put that much of it back. If they disagree, one
of them is wrong and no amount of testing either alone would say which.

Everything else here is the asymmetry: a duck can be added and cannot be taken away, and
the comparison has to say so rather than offering a control that would be a lie.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.analysis.fingerprint import (
    BeatGrid,
    DuckMeasurement,
    Figure,
    envelope_db,
    kick_duck,
)
from app.services.mastering import sidechain

RATE = 44100
TEMPO = 120.0
BEAT = 60.0 / TEMPO
SECONDS = 24.0


def grid() -> BeatGrid:
    return BeatGrid(
        tempo_bpm=TEMPO,
        beats_per_bar=4,
        first_beat_s=0.0,
        confidence=0.9,
        duration_s=SECONDS,
    )


def kicks() -> list[float]:
    """Four on the floor, which is where sidechain lives."""
    return [round(n * BEAT, 4) for n in range(int(SECONDS / BEAT))]


def held_bass() -> np.ndarray:
    """A bass that plays continuously, so any dip measured is the duck and not a note.

    Deliberately not plucked. A plucked bass has an envelope of its own, the control in
    `kick_duck` exists precisely to subtract it, and testing both at once would leave a
    failure ambiguous.
    """
    t = np.arange(int(RATE * SECONDS)) / RATE
    return 0.3 * np.sin(2 * np.pi * 55.0 * t)


def measure(samples: np.ndarray) -> DuckMeasurement:
    stereo = np.stack([samples, samples], axis=-1)
    env, times = envelope_db(stereo, RATE)
    return kick_duck(env, times, kicks(), grid())


# --- the envelope ------------------------------------------------------------------------


def test_no_depth_is_exactly_no_change():
    """A control at rest must be inaudible, not nearly inaudible."""
    bass = held_bass()
    assert sidechain.apply(bass, RATE, kicks(), 0.0) is bass


def test_the_gain_reaches_the_depth_asked_for():
    gain = sidechain.gain_envelope(kicks(), int(RATE * SECONDS), RATE, 6.0)
    deepest = 20 * np.log10(gain.min())
    assert deepest == pytest.approx(-6.0, abs=0.1)


def test_the_gain_recovers_to_unity_between_kicks():
    """Half a second of release at 120 BPM would mean the bass never comes back."""
    gain = sidechain.gain_envelope([0.0], RATE, RATE, 6.0)
    just_before_the_next_beat = gain[int(RATE * (BEAT - 0.02))]
    assert just_before_the_next_beat > 0.99


def test_overlapping_kicks_take_the_deepest_not_the_sum():
    """A compressor already holding 3 dB does not add another 3 for the next hit."""
    close = [0.0, 0.05, 0.1]
    gain = sidechain.gain_envelope(close, RATE, RATE, 6.0)
    assert 20 * np.log10(gain.min()) == pytest.approx(-6.0, abs=0.1)


def test_a_kick_past_the_end_is_ignored():
    gain = sidechain.gain_envelope([0.5, 99.0], RATE, RATE, 6.0)
    assert gain.size == RATE
    assert gain.min() < 1.0


def test_stereo_is_ducked_on_both_channels_alike():
    bass = held_bass()
    stereo = np.stack([bass, bass * 0.5], axis=-1)
    out = sidechain.apply(stereo, RATE, kicks(), 6.0)
    ratio = out[:, 0] / np.where(stereo[:, 0] == 0, 1e-12, stereo[:, 0])
    other = out[:, 1] / np.where(stereo[:, 1] == 0, 1e-12, stereo[:, 1])
    assert np.allclose(ratio, other, atol=1e-6)


# --- the round trip ----------------------------------------------------------------------


def plucked_bass(hz: float = 55.0) -> np.ndarray:
    """Notes restarting on the beat, which is the hard case and the common one.

    Its unducked reading is about -8 dB, because the kick positions catch a note's attack
    while the control positions catch a decay. Nothing is wrong with it; it is why only
    the slope of the reading is ever used and never its absolute value.
    """
    out = np.zeros(int(RATE * SECONDS))
    step = int(RATE * BEAT / 2)
    env = np.exp(-np.arange(step) / (RATE * 0.18))
    for start in range(0, len(out) - step, step):
        out[start : start + step] += env * np.sin(2 * np.pi * hz * np.arange(step) / RATE)
    return 0.3 * out


def test_the_detector_does_not_read_back_the_gain_applied():
    """The finding that made calibration necessary, pinned so nobody assumes otherwise.

    Applying 6 dB of gain reduction does not produce a 6 dB reading. It never did, and a
    version of this feature that assumed it would have under-delivered every suggestion
    by a third without anything failing.
    """
    reading = measure(sidechain.apply(held_bass(), RATE, kicks(), 6.0)).excess_db.value
    assert 3.0 < reading < 5.0


@pytest.mark.parametrize("wanted", [1.5, 3.0])
@pytest.mark.parametrize("bass", ["held", "plucked"])
def test_calibration_lands_the_reading_it_was_asked_for(wanted, bass):
    """The claim both halves of this feature rest on.

    Not "the gain equals the reading" - it does not - but "asking for a reading produces
    that reading, on this bass". Measured across five synthetic basses while this was
    built, every one landed within 0.11 dB.
    """
    samples = held_bass() if bass == "held" else plucked_bass()
    gain = sidechain.gain_for_excess(samples, RATE, kicks(), grid(), wanted)
    assert gain is not None

    at_rest = sidechain.measured_excess(samples, RATE, kicks(), grid())
    after = sidechain.measured_excess(
        sidechain.apply(samples, RATE, kicks(), gain), RATE, kicks(), grid()
    )
    assert after - at_rest == pytest.approx(wanted, abs=0.3)


def test_the_slope_is_measured_per_bass_and_not_assumed():
    """A held 41 Hz bass needs materially more gain than a held 82 Hz one for the same
    reading. A single constant would be wrong for one of them."""
    low = sidechain.gain_for_excess(
        _sine(41.2), RATE, kicks(), grid(), 3.0
    )
    high = sidechain.gain_for_excess(_sine(82.0), RATE, kicks(), grid(), 3.0)
    assert low is not None and high is not None
    assert low > high * 1.05


def _sine(hz: float) -> np.ndarray:
    t = np.arange(int(RATE * SECONDS)) / RATE
    return 0.3 * np.sin(2 * np.pi * hz * t)


def test_asking_for_nothing_applies_nothing():
    assert sidechain.gain_for_excess(held_bass(), RATE, kicks(), grid(), 0.0) == 0.0


def test_the_applied_gain_has_a_hard_ceiling():
    """Past this it is an effect, and a solve that lands here means the measurement is
    struggling rather than that eleven decibels are wanted."""
    gain = sidechain.gain_for_excess(plucked_bass(), RATE, kicks(), grid(), 12.0)
    assert gain is not None
    assert gain <= sidechain.MAX_APPLIED_DB


def test_a_bass_that_cannot_be_read_calibrates_to_nothing():
    silence = np.zeros(int(RATE * SECONDS))
    assert sidechain.gain_for_excess(silence, RATE, kicks(), grid(), 3.0) is None


def test_an_unducked_bass_measures_as_not_ducked():
    """The other half: a held tone with no sidechain on it must read as nothing.

    This is the control doing its job. Before `kick_duck` had one, the first version of
    that function reported 16.2 dB on a track with no sidechain at all.
    """
    measured = measure(held_bass())
    assert abs(measured.excess_db.value) < 1.0


def test_the_reading_rises_with_the_depth_applied():
    readings = [
        measure(sidechain.apply(held_bass(), RATE, kicks(), depth)).excess_db.value
        for depth in (2.0, 5.0, 8.0)
    ]
    assert readings == sorted(readings)


# --- the comparison ----------------------------------------------------------------------


def figure(value: float, confidence: float = 0.8, caveat: str = "") -> Figure:
    return Figure(value=value, confidence=confidence, unit=" dB", basis="test", caveat=caveat)


def measurement(excess: float, *, examined: int = 20, silent: int = 0, total: int = 20,
                confidence: float = 0.8) -> DuckMeasurement:
    return DuckMeasurement(
        dip_db=figure(excess + 6.0),
        control_dip_db=figure(6.0),
        excess_db=figure(excess, confidence),
        kicks_examined=examined,
        kicks_bass_silent=silent,
        kicks_total=total,
    )


def test_a_reference_that_ducks_more_offers_a_share_of_the_gap():
    moves = sidechain.compare(measurement(1.0), measurement(7.0))
    assert len(moves) == 1
    move = moves[0]
    assert move.control == "sidechain_db"
    assert move.measured == pytest.approx(6.0)
    # A share, never the whole gap - the rule the rest of this application runs on.
    assert move.suggested == pytest.approx(3.0)
    assert move.suggested < move.measured


def test_the_suggestion_is_capped():
    moves = sidechain.compare(measurement(0.0), measurement(40.0))
    assert moves[0].suggested == pytest.approx(sidechain.MAX_SIDECHAIN_DB)


def test_ducking_harder_than_the_reference_offers_no_control():
    """The asymmetry. A duck can be added; it cannot be taken away."""
    moves = sidechain.compare(measurement(8.0), measurement(1.0))
    assert moves[0].control == ""
    assert "cannot be taken away" in moves[0].detail
    assert moves[0].measured < 0


def test_two_sides_that_agree_say_so_rather_than_nothing():
    moves = sidechain.compare(measurement(3.0), measurement(3.2))
    assert moves[0].severity == "match"
    assert moves[0].control == ""


def test_a_gap_too_small_to_apply_is_not_offered():
    moves = sidechain.compare(measurement(3.0), measurement(3.55))
    assert moves[0].control == ""
    assert moves[0].severity == "match"


def test_a_real_seven_decibel_duck_is_not_dismissed_as_noise():
    """The case that forced the threshold down.

    End to end, a reference whose bass had been ducked 7 dB before mixing measured 1.39
    against the source's 0.48 - a 0.91 gap, because separation fills four fifths of a duck
    back in. At the old 0.5 dB floor the suggestion came to 0.45 and the comparison said
    "not worth applying" about a sidechain anybody would hear.
    """
    moves = sidechain.compare(measurement(0.48), measurement(1.39))
    assert moves[0].control == "sidechain_db"
    assert moves[0].suggested > 0


def test_the_wording_does_not_claim_the_gap_is_the_record_s():
    """Both figures come off separated stems, and the sentence has to say so."""
    detail = sidechain.compare(measurement(1.0), measurement(7.0))[0].detail
    assert "floor rather than a measurement of the record" in detail
    assert "separated stems" in detail


# --- abstention, which is the common path ------------------------------------------------


def test_an_unmeasured_side_produces_a_finding_not_silence():
    """A silent abstention is indistinguishable from a broken feature."""
    unmeasurable = DuckMeasurement(
        dip_db=figure(0.0),
        control_dip_db=figure(0.0),
        excess_db=Figure.unmeasured("too few kicks"),
        kicks_examined=2,
        kicks_bass_silent=0,
        kicks_total=4,
    )
    moves = sidechain.compare(unmeasurable, measurement(5.0))
    assert len(moves) == 1
    assert moves[0].control == ""
    assert not moves[0].confident
    assert "could not be compared" in moves[0].headline


def test_a_bass_arranged_around_the_kick_is_named_as_that():
    """Not a failure to measure - an arrangement fact, and worth saying out loud."""
    arranged = measurement(0.0, examined=2, silent=30, total=32)
    moves = sidechain.compare(arranged, measurement(5.0))
    assert "was not playing through 30" in moves[0].detail
    assert "looks exactly like a ducked one" in moves[0].detail


def test_no_measurement_at_all_explains_what_it_needs():
    moves = sidechain.compare(None, measurement(5.0))
    assert "needs the drums split and a bass" in moves[0].detail


def test_a_wobbly_measurement_on_either_side_is_not_confident():
    """The two confidences multiply: a weak reading anywhere is a weak suggestion."""
    moves = sidechain.compare(
        measurement(1.0, confidence=0.3), measurement(7.0, confidence=0.4)
    )
    assert moves[0].control == "sidechain_db"
    assert not moves[0].confident


def test_every_path_returns_exactly_one_finding():
    """So the comparison screen can count on a row existing, whatever the answer is."""
    cases = [
        (measurement(1.0), measurement(7.0)),
        (measurement(8.0), measurement(1.0)),
        (measurement(3.0), measurement(3.1)),
        (None, measurement(5.0)),
        (measurement(5.0), None),
    ]
    for mine, theirs in cases:
        assert len(sidechain.compare(mine, theirs)) == 1
