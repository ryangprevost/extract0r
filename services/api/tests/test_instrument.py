"""Comparing one instrument with the same instrument on a record, and acting on it.

Two things are worth stating before the assertions, because both look like failures when
you first read the numbers.

The tone bands are *shares*: each band is measured against its own stem's total, so the
five of them are not independent and lifting one necessarily lowers the rest. Every tone
test here asserts the gap between the moved band and the others, never the moved band on
its own.

And the comparison is deliberately mute about things it cannot measure. There is no
saturation dimension, because harmonics added by distortion cannot be told apart from
harmonics that were played without the undistorted signal to compare against. A tool that
reported one anyway would be inventing numbers, which is worse than a gap in the table.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.notes import StemKind
from app.services.mastering.dsp import DEFAULT_HOP, DEFAULT_N_FFT, average_spectrum
from app.services.mastering.instrument import (
    BANDS,
    MAX_BAND_DB,
    TONE_BUDGET_DB,
    tone_curve,
    tone_filter_gains,
    within_budget,
    MAX_LEVEL_DB,
    WIDTH_LIMITS,
    InstrumentProfile,
    StemShape,
    apply_shape,
    balance,
    band_levels,
    compare,
    profile,
    shape_tone,
)

SR = 44100


def _broadband(seconds: float = 6.0, seed: int = 7) -> np.ndarray:
    """Noise with content in every band, so a tone move has something to move."""
    from scipy.signal import butter, sosfilt

    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    white = rng.standard_normal((n, 2))
    sos = butter(1, 300 / (SR / 2), btype="low", output="sos")
    audio = sosfilt(sos, white, axis=0) * 4 + white * 0.2

    t = np.arange(n) / SR
    for hz in (80, 220, 900, 4500, 11000):
        audio[:, 0] += 0.15 * np.sin(2 * np.pi * hz * t)
        audio[:, 1] += 0.14 * np.sin(2 * np.pi * hz * t + 0.4)
    return audio / np.abs(audio).max() * 0.5


def _levels(audio: np.ndarray) -> dict[str, float]:
    return band_levels(average_spectrum(audio, DEFAULT_N_FFT, DEFAULT_HOP), SR)


def _relative_move(before: dict, after: dict, band: str) -> float:
    """How far a band moved against the other four - the number a tone dial promises."""
    others = [after[b] - before[b] for b, _, _ in BANDS if b != band]
    return (after[band] - before[band]) - float(np.mean(others))


# --- measuring --------------------------------------------------------------------------


def test_tone_is_measured_as_shape_and_not_as_level():
    """The same part at two fader positions is the same tone. If this failed, every tone
    comparison would really be a level comparison wearing a different name."""
    audio = _broadband()
    quiet = _levels(audio * 0.1)
    loud = _levels(audio)
    for band, _, _ in BANDS:
        assert quiet[band] == pytest.approx(loud[band], abs=0.01)


def test_balance_finds_which_side_a_part_is_on():
    audio = _broadband()
    left = audio.copy()
    left[:, 1] *= 0.3
    assert balance(left) < -0.3
    assert balance(audio) == pytest.approx(0.0, abs=0.15)
    assert balance(np.stack([audio[:, 0], audio[:, 0]], axis=1)) == pytest.approx(0.0, abs=0.01)


def test_a_profile_fills_in_every_dimension():
    one = profile(_broadband(), SR, StemKind.GUITAR)
    assert set(one.bands) == {name for name, _, _ in BANDS}
    assert one.crest_db > 0
    assert one.width > 0
    assert one.loudness_lufs < 0


# --- tone: does the dial read true --------------------------------------------------------


@pytest.mark.parametrize("band", [name for name, _, _ in BANDS])
def test_a_band_request_moves_that_band_and_not_the_others(band: str):
    """Direction and rough size, not exactness - see the next test for why.

    The gains are still solved rather than set to the gap directly: a bell at 250 Hz
    covers less than the 120-500 Hz band it is responsible for, and the five filters
    overlap, so five independent guesses are five wrong answers that depend on each other.
    What changed is that the solve is damped, so it lands near the request instead of on
    it. Around two thirds, measured.
    """
    audio = _broadband()
    spectrum = average_spectrum(audio, DEFAULT_N_FFT, DEFAULT_HOP)
    before = _levels(audio)

    for wanted in (3.0, -3.0):
        moved = _relative_move(before, _levels(shape_tone(audio, SR, {band: wanted}, spectrum)), band)
        assert moved * wanted > 0, "moved the wrong way"
        assert 0.45 <= moved / wanted <= 1.05, f"asked {wanted}, moved {moved:.2f}"


@pytest.mark.parametrize("band", [name for name, _, _ in BANDS])
def test_neighbouring_filters_are_not_set_against_each_other(band: str):
    """The test that exists because of a specific complaint: masters that came back
    "swirly", "hollow" and "muddy".

    An exact solve hits its band targets by setting overlapping filters in opposition -
    asking for +3 dB of presence produced +3.55 on the presence bell against -2.02 on the
    air shelf, a 5.6 dB swing between two filters whose skirts overlap, which is a crude
    comb and sounds like one. Damping the solve is what fixed it, and this is what stops
    anyone undoing that in the name of accuracy.
    """
    audio = _broadband()
    spectrum = average_spectrum(audio, DEFAULT_N_FFT, DEFAULT_HOP)
    gains = tone_filter_gains({band: 3.0}, SR, spectrum)

    order = [name for name, _, _ in BANDS]
    swings = [abs(gains[order[i]] - gains[order[i + 1]]) for i in range(len(order) - 1)]
    assert max(swings) < 4.5, f"filters fighting: {gains}"


def test_a_stem_cannot_be_asked_to_re_eq_every_band_at_once():
    """A real drum stem asked for +3 dB in four bands simultaneously, which is not an EQ
    move, it is a different drum sound. Over budget, the whole request scales down
    together so its shape survives and only its size changes."""
    asked = {"low": -0.79, "low_mid": 3.0, "high_mid": 3.0, "presence": 3.0, "air": 3.0}
    budgeted = within_budget(asked)

    assert sum(abs(v) for v in budgeted.values()) <= TONE_BUDGET_DB + 0.05
    # The shape is preserved: every band keeps its sign and their ratios hold.
    for band in asked:
        assert budgeted[band] * asked[band] >= 0
    assert budgeted["low_mid"] == pytest.approx(budgeted["air"], abs=0.02)


def test_a_modest_request_is_left_alone_by_the_budget():
    asked = {"air": 1.2}
    assert within_budget(asked) == asked


def test_a_flat_request_is_a_true_no_op():
    audio = _broadband()
    assert np.array_equal(shape_tone(audio, SR, dict.fromkeys(["low", "air"], 0.0)), audio)


def test_two_bands_at_once_both_move():
    """Independently-set filters overlap, so setting two at once changes both answers.
    The solve is what keeps them addable, damping or not."""
    audio = _broadband()
    spectrum = average_spectrum(audio, DEFAULT_N_FFT, DEFAULT_HOP)
    before = _levels(audio)
    after = _levels(shape_tone(audio, SR, {"low": 3.0, "air": 3.0}, spectrum))

    assert _relative_move(before, after, "low") > 1.2
    assert _relative_move(before, after, "air") > 1.2


# --- comparing ------------------------------------------------------------------------


def _pair(**overrides) -> tuple[InstrumentProfile, InstrumentProfile]:
    flat = {name: -7.0 for name, _, _ in BANDS}
    mine = InstrumentProfile(
        stem=StemKind.GUITAR,
        relative_lufs=-8.0,
        bands=dict(flat),
        dynamic_range_db=8.0,
        crest_db=12.0,
        pan=0.0,
        width=1.0,
    )
    theirs = InstrumentProfile(
        stem=StemKind.GUITAR,
        relative_lufs=-8.0,
        bands=dict(flat),
        dynamic_range_db=8.0,
        crest_db=12.0,
        pan=0.0,
        width=1.0,
    )
    for key, value in overrides.items():
        setattr(theirs, key, value)
    return mine, theirs


def _by(moves, dimension, band=""):
    return next(
        (m for m in moves if m.dimension == dimension and m.band == band), None
    )


def test_two_identical_instruments_produce_no_notes():
    mine, theirs = _pair()
    assert compare(StemKind.GUITAR, mine, theirs) == []


def test_a_quieter_instrument_is_nudged_part_of_the_way_not_all_of_it():
    """The single most important assertion in this file.

    Closing the gap completely is what the comparison used to do, and on a real song it
    produced a master its own author could not recognise: the guitars went up 9 dB while
    the bass came down 4, which is not a correction, it is somebody else's arrangement.
    The measurement is still reported in full; the suggestion is a move toward it.
    """
    mine, theirs = _pair(relative_lufs=-4.0)
    move = _by(compare(StemKind.GUITAR, mine, theirs), "level")
    assert move is not None
    assert move.measured == pytest.approx(4.0, abs=0.01), "the gap is still reported whole"
    assert move.suggested == pytest.approx(2.0, abs=0.01), "but only half of it is offered"
    assert move.control == "gain_db"


def test_a_huge_level_gap_is_treated_as_arrangement_rather_than_a_mistake():
    """A real pair measured 9.3 dB apart on the guitars, because the reference is a
    doubled-guitar record and separation had filed part of the user's lead under `other`.
    Copying that is not a mix note."""
    mine, theirs = _pair(relative_lufs=1.0)  # 9 dB hotter than the -8.0 default
    move = _by(compare(StemKind.GUITAR, mine, theirs), "level")
    assert move.confident is False
    assert "arrangement" in move.detail
    assert move.suggested == MAX_LEVEL_DB, "and it is held at the limit"


def test_no_suggestion_ever_exceeds_the_stem_limits():
    """A blanket guard. Whatever the reference measures, one pass may not rewrite a stem."""
    mine, theirs = _pair(relative_lufs=20.0, dynamic_range_db=0.5, width=4.0)
    for band, _, _ in BANDS:
        theirs.bands[band] = 30.0

    for move in compare(StemKind.GUITAR, mine, theirs):
        if move.control == "gain_db":
            assert abs(move.suggested) <= MAX_LEVEL_DB
        elif move.control.startswith("tone_"):
            assert abs(move.suggested) <= MAX_BAND_DB
        elif move.control == "width":
            assert WIDTH_LIMITS[0] <= move.suggested <= WIDTH_LIMITS[1]


def test_level_is_compared_against_each_mix_rather_than_between_them():
    """Both instruments four LU under their own mixes, but one record mastered eight dB
    louder. There is nothing to fix, and an absolute comparison would claim there was."""
    mine, theirs = _pair()
    mine.loudness_lufs, theirs.loudness_lufs = -22.0, -14.0
    assert _by(compare(StemKind.GUITAR, mine, theirs), "level") is None


def test_a_dull_instrument_asks_for_the_band_it_is_short_of():
    mine, theirs = _pair()
    theirs.bands["air"] = -3.0
    move = _by(compare(StemKind.GUITAR, mine, theirs), "tone", "air")
    assert move is not None
    assert move.measured == pytest.approx(4.0, abs=0.01)
    assert move.suggested == pytest.approx(2.0, abs=0.01)
    assert move.control == "tone_air_db"


def test_a_band_move_is_capped_rather_than_followed_off_a_cliff():
    """Separation leaks. A cymbal in the bass stem would otherwise ask for a huge
    correction to something that is not the bass."""
    mine, theirs = _pair()
    theirs.bands["presence"] = 20.0
    move = _by(compare(StemKind.GUITAR, mine, theirs), "tone", "presence")
    assert move.suggested == MAX_BAND_DB


def test_a_part_that_swings_more_than_the_reference_asks_for_compression():
    mine, theirs = _pair(dynamic_range_db=4.0)
    move = _by(compare(StemKind.GUITAR, mine, theirs), "dynamics")
    assert move is not None
    assert move.control == "compress_db"
    assert move.measured == pytest.approx(4.0, abs=0.01)
    assert move.suggested == pytest.approx(2.0, abs=0.01)


def test_a_part_already_flatter_than_the_reference_is_told_so_and_offered_nothing():
    """Honest rather than silent. There is no dial here that puts dynamic range back, and
    a row saying so is more use than a row that is missing."""
    mine, theirs = _pair(dynamic_range_db=14.0)
    move = _by(compare(StemKind.GUITAR, mine, theirs), "dynamics")
    assert move is not None
    assert move.control == ""
    assert move.suggested == 0.0


def test_transient_differences_are_reported_without_a_dial():
    """No control here sharpens an attack that was not played, so punch is a note about
    the recording rather than a setting."""
    mine, theirs = _pair(crest_db=18.0)
    move = _by(compare(StemKind.GUITAR, mine, theirs), "punch")
    assert move is not None
    assert move.control == ""
    assert move.confident is False


def test_panning_is_offered_but_flagged_as_worth_a_listen():
    mine, theirs = _pair(pan=0.4)
    move = _by(compare(StemKind.GUITAR, mine, theirs), "pan")
    assert move is not None
    assert move.suggested == pytest.approx(0.4, abs=0.01)
    assert move.confident is False


def test_the_bass_is_never_asked_to_move_sideways():
    """Widening or panning the low end thins it and breaks mono playback, whatever the
    reference happens to measure."""
    mine, theirs = _pair(pan=0.5, width=1.8)
    mine.stem = theirs.stem = StemKind.BASS
    moves = compare(StemKind.BASS, mine, theirs)
    assert _by(moves, "pan") is None
    assert _by(moves, "width") is None


def test_an_instrument_the_reference_does_not_have_produces_no_notes():
    """A record with no piano yields a piano stem far under its own mix. Matching to it
    would ask for a 40 dB cut and silence a part the user played."""
    mine, theirs = _pair()
    theirs.present = False
    assert compare(StemKind.PIANO, mine, theirs) == []


# --- applying ----------------------------------------------------------------------------


def test_an_empty_shape_returns_the_audio_untouched():
    audio = _broadband()
    assert np.array_equal(apply_shape(audio, SR, StemShape()), audio)


def test_a_shape_applies_its_tone_and_its_level_together():
    audio = _broadband()
    before = _levels(audio)
    shape = StemShape(gain_db=-6.0, tone_air_db=3.0)  # a fader the user set, not a suggestion
    out = apply_shape(audio, SR, shape, average_spectrum(audio, DEFAULT_N_FFT, DEFAULT_HOP))

    assert _relative_move(before, _levels(out), "air") > 1.2
    change = 20 * np.log10(
        float(np.sqrt(np.mean(out**2))) / float(np.sqrt(np.mean(audio**2)))
    )
    assert change == pytest.approx(-6.0, abs=0.7)


def test_a_shape_that_compresses_narrows_the_range():
    from app.services.mastering.dynamics import dynamic_range_db

    t = np.arange(int(SR * 12)) / SR
    level = np.where((t % 6.0) < 3.0, 0.15, 0.6)
    signal = np.sin(2 * np.pi * 220 * t) * level
    audio = np.stack([signal, signal], axis=1)

    out = apply_shape(audio, SR, StemShape(compress_db=4.0))
    assert dynamic_range_db(out, SR) < dynamic_range_db(audio, SR) - 3.0


def test_a_band_gap_survives_renormalisation_rather_than_needing_to_be_level_neutral():
    """Guards a fix that was nearly made and would have been wrong.

    Band levels are shares, so they sum to one, so a request to raise four of the five at
    once looks impossible and looks as though it ought to be made level-neutral first.
    Measured on a real drum stem it is not: with 96% of the energy in the bottom band,
    raising the other four hardly moves the total, and the raw gaps arrive intact.
    Subtracting the mean would have asked for a 9.8 dB low cut against a reference holding
    1.6 dB less low end.
    """
    mine = {"low": -0.16, "low_mid": -16.12, "high_mid": -26.40,
            "presence": -24.31, "air": -23.76}
    gap = {"low": -1.58, "low_mid": 8.28, "high_mid": 12.19,
           "presence": 13.95, "air": 8.28}

    share = {band: 10 ** (level / 10) for band, level in mine.items()}
    total = sum(share[b] * 10 ** (gap[b] / 10) for b in share)
    renormalisation_db = 10 * np.log10(total)

    assert abs(renormalisation_db) < 0.1
    for band in mine:
        assert abs((gap[band] - renormalisation_db) - gap[band]) < 0.1


def test_two_mono_stems_are_not_compared_on_width():
    """A real drum stem measured 0.06 across against a reference's 0.08. The ratio is 1.39
    and the comparison offered "widen by 39%" on the strength of two hundredths of
    absolute width, on two stems that were both mono. There is nothing there to compare.
    """
    mine, theirs = _pair(width=0.08)
    mine.width = 0.06
    assert _by(compare(StemKind.GUITAR, mine, theirs), "width") is None


def test_a_width_difference_between_two_wide_stems_is_still_offered():
    """The guard has to be a floor on the measurement, not a ban on the dimension."""
    mine, theirs = _pair(width=1.6)
    mine.width = 1.0
    move = _by(compare(StemKind.GUITAR, mine, theirs), "width")
    assert move is not None and move.suggested > 1.0


def test_a_capped_band_move_says_what_it_actually_measured():
    """A row reading "+6.0" with nothing else on it looks like the tool guessing rather
    than the tool being held at its limit on purpose."""
    mine, theirs = _pair()
    theirs.bands["presence"] = 6.0  # a 13 dB gap against the -7.0 default
    move = _by(compare(StemKind.GUITAR, mine, theirs), "tone", "presence")
    assert move.suggested == MAX_BAND_DB
    assert "a move in that direction rather than a copy of it" in move.detail
    assert "+13.0" in move.detail, "the whole measured gap is still shown"


def test_a_move_offered_in_full_does_not_explain_itself():
    """Only a suggestion that differs from what was measured needs the sentence. Below
    2 dB of gap the halved value rounds to the gap itself."""
    mine, theirs = _pair()
    theirs.bands["presence"] = -6.95  # a 0.05 dB gap: halved, it is the same number
    move = _by(compare(StemKind.GUITAR, mine, theirs), "tone", "presence")
    assert move is None or "a move in that direction" not in move.detail


def test_plural_instruments_get_plural_verbs():
    """"The reference's guitars hits softer" shipped to the screen on a real comparison."""
    mine, theirs = _pair(crest_db=18.0)
    move = _by(compare(StemKind.GUITAR, mine, theirs, ("guitars", True)), "punch")
    assert "guitars hit harder" in move.headline

    move = _by(compare(StemKind.VOCALS, mine, theirs, ("vocal", False)), "punch")
    assert "vocal hits harder" in move.headline


def test_lifting_a_band_the_stem_has_nothing_in_is_flagged_as_worth_hearing():
    """A real vocal stem held 0.04% of its energy below 120 Hz, which is correct - a vocal
    does not live there. The reference's held 0.35%, so the comparison asked for +9.5 dB,
    and taking it would have raised kick bleed and rumble rather than any voice.
    """
    mine, theirs = _pair()
    mine.bands["low"] = -34.0
    theirs.bands["low"] = -24.0

    move = _by(compare(StemKind.VOCALS, mine, theirs, ("vocal", False)), "tone", "low")
    assert move is not None, "the difference should still be reported"
    assert move.confident is False
    assert "leaked in from the other stems" in move.detail


def test_cutting_a_band_the_stem_has_nothing_in_needs_no_warning():
    """Removing what is not there costs nothing, so the caution would just be noise."""
    mine, theirs = _pair()
    mine.bands["low"] = -34.0
    theirs.bands["low"] = -40.0

    move = _by(compare(StemKind.VOCALS, mine, theirs, ("vocal", False)), "tone", "low")
    assert move.confident is True


def test_a_band_the_instrument_really_occupies_is_not_flagged():
    """The guard is about empty bands, not about boosts. A drum stem's cymbals sit at
    around 0.4% of the stem and lifting them is the whole point of the control."""
    mine, theirs = _pair()
    mine.bands["air"] = -23.0
    theirs.bands["air"] = -18.0

    move = _by(compare(StemKind.DRUMS, mine, theirs, ("drums", True)), "tone", "air")
    assert move.confident is True


def test_the_applied_curve_does_not_boost_and_notch_within_an_octave():
    """The measurement behind "swirly, hollow, muddy".

    What a listener hears is not the filter gains but the curve they add up to, and the
    audible failure is a boost and a notch close together - a crude comb. Asking for +3 dB
    of presence with an exact solve produced a curve running from -1.36 to +3.49 dB with a
    3.56 dB swing inside a single octave. Damped, the same request spans -0.28 to +2.18
    with a worst swing of 1.81 dB: the same move, without the notch beside it.
    """
    audio = _broadband()
    spectrum = average_spectrum(audio, DEFAULT_N_FFT, DEFAULT_HOP)
    curve_db = 20 * np.log10(tone_curve({"presence": 3.0}, SR, spectrum))

    freqs = np.fft.rfftfreq(DEFAULT_N_FFT, 1 / SR)
    audible = (freqs > 40) & (freqs < 16000)
    curve, octaves = curve_db[audible], np.log2(freqs[audible])

    worst = max(
        float(curve[(octaves > low) & (octaves < low + 1)].max()
              - curve[(octaves > low) & (octaves < low + 1)].min())
        for low in np.arange(octaves.min(), octaves.max() - 1, 0.25)
    )
    assert worst < 2.5, f"the curve swings {worst:.2f} dB inside one octave"
    # And it should not have to cut anything to deliver a boost.
    assert curve.min() > -1.0, f"asking for a boost dug a {curve.min():.2f} dB hole"
