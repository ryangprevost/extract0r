"""Suggesting the finishing moves from measurements of both files.

Each of these asks something the tonal match cannot, because none of them is a level:
whether there is any top end to lift, whether the bass is spread, and whether there
is rumble under the music.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.finishing import suggest

SR = 44100


def _mix(
    seconds: float = 20.0,
    air: float = 0.05,
    bass_width: float = 0.1,
    rumble: float = 0.0,
    gaps: bool = False,
) -> np.ndarray:
    """A crude mix with each property dialled independently."""
    t = np.arange(int(SR * seconds)) / SR
    mid = sum(0.15 * np.sin(2 * np.pi * hz * t) for hz in (180, 900, 2600))
    top = air * np.sin(2 * np.pi * 11000 * t)
    low = 0.25 * np.sin(2 * np.pi * 170 * t)
    side = bass_width * np.sin(2 * np.pi * 205 * t + 0.7)
    if rumble:
        mid = mid + rumble * np.sin(2 * np.pi * 25 * t)
    signal = mid + top + low
    if gaps:
        # Hard on/off, so the level really does fall between hits.
        envelope = ((t * 4) % 1.0 < 0.45).astype(float)
        signal = signal * envelope
        side = side * envelope
    return np.stack([signal + side, signal - side], axis=1)


def _areas(findings):
    return {f["area"] for f in findings}


def _find(findings, area):
    return next(f for f in findings if f["area"] == area)


# --- each measure fires on its own property -------------------------------------------


def test_a_dark_mix_is_offered_sparkle():
    """A shelf can only lift what is there; this is the case where nothing is."""
    dark = _mix(air=0.001)
    bright = _mix(air=0.08)

    found = _find(suggest(dark, bright, SR), "finish:sparkle")
    assert found["action"]["dials"]["sparkle"] > 0
    assert "synth patch" in found["detail"] or "DI" in found["detail"]


def test_a_mix_as_bright_as_its_reference_is_not():
    same = _mix(air=0.05)
    assert "finish:sparkle" not in _areas(suggest(same, _mix(air=0.05), SR))


def test_spread_bass_is_offered_centring():
    wide = _mix(bass_width=0.30)
    tight = _mix(bass_width=0.05)

    found = _find(suggest(wide, tight, SR), "finish:bass-width")
    assert found["action"]["dials"]["centreBass"] > 0
    assert "mono" in found["detail"]


def test_bass_already_as_tight_as_the_reference_is_left_alone():
    assert "finish:bass-width" not in _areas(
        suggest(_mix(bass_width=0.1), _mix(bass_width=0.1), SR)
    )


def test_rumble_is_offered_a_cut():
    found = _find(suggest(_mix(rumble=0.25), _mix(rumble=0.0), SR), "finish:subsonic")
    assert found["action"]["dials"]["subsonic"] == 30


def test_no_rumble_no_offer():
    assert "finish:subsonic" not in _areas(suggest(_mix(), _mix(), SR))


def test_room_is_no_longer_offered():
    """A short room across the mix was offered here and has been removed. The measure said
    it was closing the gaps between hits; the ear said there was obvious reverb on the
    drums, which is audible long before it shows up as reduced crest. An exciter gives the
    brightness and presence that "cohesion" turned out to mean, without filling the gaps.
    """
    findings = suggest(_mix(gaps=True), _mix(gaps=False), SR)
    assert not any(f["area"] == "finish:ambience" for f in findings)
    assert not any("ambience" in f["action"]["dials"] for f in findings)


def test_a_mix_that_already_matches_gets_no_advice_at_all():
    """Silence is the right answer when there is nothing to say."""
    assert suggest(_mix(), _mix(), SR) == []


# --- the numbers reaching the dials ---------------------------------------------------


def test_every_offer_is_in_the_units_its_slider_reads():
    """The bug this guards against shipped once and was caught a second time before it
    could. A width offer sent as a factor set the slider to its minimum, so the button
    marked "Widen" narrowed the mix. Every offer here reads in the units of its own
    control."""
    findings = suggest(
        _mix(air=0.001, bass_width=0.30, rumble=0.25, gaps=True),
        _mix(air=0.08, bass_width=0.05, rumble=0.0, gaps=False),
        SR,
    )
    ranges = {
        "sparkle": (0.0, 6.0),
        "centreBass": (60.0, 300.0),
        "subsonic": (15.0, 60.0),
    }
    seen = 0
    for finding in findings:
        for key, value in finding["action"]["dials"].items():
            low, high = ranges[key]
            assert low <= value <= high, f"{key}={value} is outside its slider"
            seen += 1
    assert seen >= 3, "the fixture should have triggered most of them"


def test_findings_lead_with_the_biggest_difference():
    findings = suggest(
        _mix(air=0.001, bass_width=0.30, rumble=0.25, gaps=True),
        _mix(air=0.08, bass_width=0.05, rumble=0.0, gaps=False),
        SR,
    )
    deltas = [abs(f["delta_db"]) for f in findings]
    assert deltas == sorted(deltas, reverse=True)


def test_every_finding_carries_a_dial_that_answers_it():
    findings = suggest(_mix(air=0.001, bass_width=0.30), _mix(air=0.08, bass_width=0.05), SR)
    assert findings
    for finding in findings:
        assert finding["action"]["dials"], f"{finding['area']} offers nothing"
        assert finding["action"]["label"]
        assert finding["clause"]


def test_a_mono_mix_does_not_produce_a_bass_width_finding():
    mono = _mix(bass_width=0.0)
    assert "finish:bass-width" not in _areas(suggest(mono, _mix(bass_width=0.05), SR))


def test_silence_is_survived():
    quiet = np.zeros((SR * 2, 2))
    assert suggest(quiet, quiet, SR) == []


def test_differing_sample_rates_are_handled():
    """A 48 kHz reference against a 44.1 kHz mix is ordinary, not an error."""
    findings = suggest(_mix(air=0.001), _mix(air=0.08), SR, reference_rate=SR)
    assert isinstance(findings, list)


@pytest.mark.parametrize("area", ["finish:sparkle", "finish:bass-width"])
def test_the_detail_quotes_the_measurement_behind_it(area):
    findings = suggest(
        _mix(air=0.001, bass_width=0.30), _mix(air=0.08, bass_width=0.05), SR
    )
    detail = _find(findings, area)["detail"]
    assert any(character.isdigit() for character in detail)
