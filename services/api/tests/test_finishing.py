"""Suggesting the finishing moves from measurements of both files.

Each of these asks something the tonal match cannot, because none of them is a level:
whether there is any top end to lift, whether the bass is spread, and whether there
is rumble under the music.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.finishing import continuity_db, suggest

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
    assert not any(
        "ambience" in f.get("action", {}).get("dials", {}) for f in findings
    )


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
        "saturation": (0.5, 4.0),
        "parallel": (5.0, 25.0),
    }
    seen = 0
    for finding in findings:
        # Continuity offers no dial, so there are no units to be wrong about.
        for key, value in finding.get("action", {}).get("dials", {}).items():
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


def test_every_finding_either_offers_a_dial_or_is_honest_that_there_is_none():
    """Continuity deliberately offers nothing. Every other finding must offer something,
    or it is describing a problem the tool cannot help with and should say so."""
    findings = suggest(_mix(air=0.001, bass_width=0.30), _mix(air=0.08, bass_width=0.05), SR)
    assert findings
    for finding in findings:
        assert finding["clause"]
        if finding["area"] == "finish:continuity":
            assert "action" not in finding
            continue
        assert finding["action"]["dials"], f"{finding['area']} offers nothing"
        assert finding["action"]["label"]


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


# --- continuity -----------------------------------------------------------------------


def _gappy_top(seconds: float = 20.0, continuous: bool = False) -> np.ndarray:
    """A mix whose top octave is either always there or only on hits."""
    t = np.arange(int(SR * seconds)) / SR
    body = sum(0.15 * np.sin(2 * np.pi * hz * t) for hz in (180, 900, 2600))
    hits = ((t * 4) % 1.0 < 0.06).astype(float)
    top = 0.05 * np.sin(2 * np.pi * 12000 * t) * hits
    if continuous:
        # A bed underneath the hits, which is what a record has and a home mix often
        # does not.
        top = top + 0.02 * np.sin(2 * np.pi * 11000 * t)
    signal = body + top
    return np.stack([signal, signal * 0.99], axis=1)


def test_a_top_end_that_only_arrives_on_hits_measures_lower():
    """The measure the whole finding rests on."""
    assert continuity_db(_gappy_top(), SR) < continuity_db(_gappy_top(continuous=True), SR)


def test_a_mix_with_gaps_against_a_continuous_reference_is_told_so():
    findings = suggest(_gappy_top(), _gappy_top(continuous=True), SR)
    found = _find(findings, "finish:continuity")

    assert found["delta_db"] > 0
    assert "always there" in found["headline"]
    # It must not sell sparkle as the answer - measured, exciting each stem moved this
    # by under a decibel and two of them made it worse.
    assert "will not close this" in found["detail"]
    assert "action" not in found


def test_a_mix_as_continuous_as_its_reference_is_left_alone():
    both = _gappy_top(continuous=True)
    assert "finish:continuity" not in _areas(suggest(both, both, SR))


def test_a_sustained_but_quiet_part_is_the_one_named():
    """The actionable half: which fader to move. A part that plays continuously up top
    but is turned down is the thing to raise - the character is already right."""
    from app.services.mastering.finishing import _sustained_but_buried

    t = np.arange(SR * 20) / SR
    hits = ((t * 4) % 1.0 < 0.06).astype(float)
    loud_and_gappy = np.stack([0.3 * np.sin(2 * np.pi * 12000 * t) * hits] * 2, axis=1)
    # About 30 dB down: quiet enough to count as buried, loud enough not to be absent.
    quiet_and_sustained = np.stack([0.002 * np.sin(2 * np.pi * 11000 * t)] * 2, axis=1)
    quiet_and_gappy = np.stack([0.002 * np.sin(2 * np.pi * 12000 * t) * hits] * 2, axis=1)

    named = _sustained_but_buried(
        {
            "drums": loud_and_gappy,
            "guitar": quiet_and_sustained,
            "shaker": quiet_and_gappy,
        },
        SR,
    )
    assert "guitar" in named
    # The loud one is not buried, and the quiet gappy one is not sustained.
    assert "drums" not in named
    assert "shaker" not in named


def test_nothing_is_named_when_there_are_no_stems():
    from app.services.mastering.finishing import _sustained_but_buried

    assert _sustained_but_buried({}, SR) == []


def test_one_buried_part_reads_as_singular():
    '''Two things at once. "the only parts are guitar, and they are turned down" is how a
    tool stops sounding like it was written by anyone - and it has to say "the guitar
    stem", not "the guitar", because separation sorts a track into six buckets and a
    synth lands in whichever is nearest.'''
    gappy = _gappy_top()
    quiet = np.stack([0.006 * np.sin(2 * np.pi * 11000 * np.arange(SR * 20) / SR)] * 2, axis=1)

    findings = suggest(
        gappy, _gappy_top(continuous=True), SR,
        source_stems={"drums": gappy, "guitar": quiet},
    )
    detail = _find(findings, "finish:continuity")["detail"]
    assert "the only part playing" in detail
    assert "is the guitar stem" in detail
    assert "are guitar" not in detail


def test_continuity_survives_silence_and_short_input():
    assert continuity_db(np.zeros((SR * 2, 2)), SR) == 0.0
    assert continuity_db(np.zeros((100, 2)), SR) == 0.0


def test_a_part_that_barely_plays_is_not_called_continuous():
    """Continuity is a ratio of percentiles, so a stem that is silent for most of a song
    has both percentiles near zero and reads as perfectly continuous. On a real track a
    synth playing in 4% of the song scored -6 dB and was named as the part playing
    continuously up top - advice to raise something that is barely in the song.
    """
    from app.services.mastering.finishing import _active_share, _sustained_but_buried

    t = np.arange(SR * 20) / SR
    hits = ((t * 4) % 1.0 < 0.06).astype(float)
    loud = np.stack([0.3 * np.sin(2 * np.pi * 12000 * t) * hits] * 2, axis=1)

    # Quiet and sustained, but only present for a tenth of the track.
    rare = np.stack([0.002 * np.sin(2 * np.pi * 11000 * t)] * 2, axis=1)
    rare[int(len(rare) * 0.1):] = 0.0

    # Quiet, sustained, and there throughout.
    always = np.stack([0.002 * np.sin(2 * np.pi * 11000 * t)] * 2, axis=1)

    assert _active_share(rare, SR) < 0.2
    assert _active_share(always, SR) > 0.9

    assert "rare" not in _sustained_but_buried({"drums": loud, "rare": rare}, SR)
    assert "always" in _sustained_but_buried({"drums": loud, "always": always}, SR)


def test_the_finding_still_fires_without_naming_anything():
    """When nothing qualifies there is still a real gap to report - it just has no
    instrument to point at, and inventing one would be worse than staying quiet."""
    findings = suggest(_gappy_top(), _gappy_top(continuous=True), SR, source_stems={})
    found = _find(findings, "finish:continuity")
    assert "the only part" not in found["detail"]
    assert found["delta_db"] > 0


# --- body and movement ------------------------------------------------------------------


def test_a_thin_body_is_offered_saturation():
    """Saturation adds harmonics in 300 Hz - 2 kHz, which is where a record feels solid
    and where sparkle - which only works above 6 kHz - cannot reach."""
    t = np.arange(SR * 20) / SR

    def mix(body: float) -> np.ndarray:
        signal = (0.2 * np.sin(2 * np.pi * 110 * t)
                  + body * np.sin(2 * np.pi * 700 * t)
                  + 0.05 * np.sin(2 * np.pi * 9000 * t))
        return np.stack([signal, signal * 0.99], axis=1)

    found = _find(suggest(mix(0.03), mix(0.25), SR), "finish:saturation")
    assert found["action"]["dials"]["saturation"] > 0
    assert "sparkle" in found["detail"]


def test_a_body_as_full_as_the_reference_is_left_alone():
    t = np.arange(SR * 20) / SR
    signal = 0.2 * np.sin(2 * np.pi * 110 * t) + 0.2 * np.sin(2 * np.pi * 700 * t)
    same = np.stack([signal, signal * 0.99], axis=1)
    assert "finish:saturation" not in _areas(suggest(same, same, SR))


def test_a_mix_that_moves_more_than_its_reference_is_offered_glue():
    t = np.arange(SR * 20) / SR
    tone = sum(0.2 * np.sin(2 * np.pi * hz * t) for hz in (110, 700))

    # Loud and quiet stretches against something at a constant level.
    swinging = tone * np.where((t % 4.0) < 1.0, 1.0, 0.15)
    steady = tone

    found = _find(
        suggest(
            np.stack([swinging, swinging * 0.99], axis=1),
            np.stack([steady, steady * 0.99], axis=1),
            SR,
        ),
        "finish:parallel",
    )
    assert 5 <= found["action"]["dials"]["parallel"] <= 25
    assert "without touching the attacks" in found["detail"]


def test_glue_is_not_offered_to_a_mix_that_already_moves_less():
    """An unmastered mix having more range than a commercial master is normal. Having
    less is not a problem this can fix, and offering to compress it further would be
    actively wrong."""
    t = np.arange(SR * 20) / SR
    tone = sum(0.2 * np.sin(2 * np.pi * hz * t) for hz in (110, 700))
    steady = np.stack([tone, tone * 0.99], axis=1)
    swinging_tone = tone * np.where((t % 4.0) < 1.0, 1.0, 0.15)
    swinging = np.stack([swinging_tone, swinging_tone * 0.99], axis=1)

    assert "finish:parallel" not in _areas(suggest(steady, swinging, SR))
