"""Three songs on one pair of axes.

The panel this backs is a diagnostic, so the thing it must never do is *look* like an
answer while being one. Two ways it could:

Level could leak into shape. Three songs mastered to three loudnesses sit at three heights
and the eye reads the offset as tone - the loudest curve appears to have more of
everything. The first group of tests puts the same recording on screen twice at different
gains and demands one line.

Or the axis could hide the difference. Curves each fitted to their own range all fill the
box and look alike, which is precisely the comparison the picture exists to make. The
window tests hold every curve to one scale.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.dsp import MatchSettings
from app.services.mastering.profile import capture
from app.services.mastering.spectrum_view import (
    CURVE_POINTS,
    HIGH_HZ,
    LOW_HZ,
    axis,
    difference,
    from_profile,
    measure,
    window,
)

SR = 44100


def _music(seconds: float = 6.0, seed: int = 3, tilt: float = 0.0) -> np.ndarray:
    """Broadband stereo with a controllable spectral tilt, so two curves can differ."""
    from scipy.signal import butter, sosfilt

    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    white = rng.standard_normal((n, 2))
    sos = butter(1, 400 / (SR / 2), btype="low", output="sos")
    audio = sosfilt(sos, white, axis=0) * (4.0 - tilt) + white * (0.2 + tilt * 0.4)
    t = np.arange(n) / SR
    for hz in (60, 220, 900, 4500, 11000):
        audio[:, 0] += 0.12 * np.sin(2 * np.pi * hz * t)
        audio[:, 1] += 0.11 * np.sin(2 * np.pi * hz * t + 0.5)
    return audio / np.abs(audio).max() * 0.5


def _at(curve, hz: float) -> float:
    """One curve's value at a frequency, off the shared axis."""
    return float(np.interp(np.log2(hz), np.log2(axis()), np.asarray(curve.db)))


# --- the axis ---------------------------------------------------------------------------


def test_every_curve_lands_on_the_same_axis():
    """Three arrays of different lengths could not be drawn on one chart, and three of the
    same length sampled at different frequencies would silently misalign - which is worse,
    because it would look right."""
    a = measure(_music(seed=1), SR, "a", "A")
    b = measure(_music(seed=2, tilt=1.2), SR, "b", "B")
    assert len(a.db) == len(b.db) == CURVE_POINTS == len(axis())
    assert axis()[0] == pytest.approx(LOW_HZ)
    assert axis()[-1] == pytest.approx(HIGH_HZ)


def test_the_axis_is_logarithmic():
    """Even in log frequency, which is how the ear spaces things and how the curve is
    smoothed. A linear axis would spend half its width on 10-20 kHz."""
    hz = axis()
    ratios = hz[1:] / hz[:-1]
    assert np.allclose(ratios, ratios[0], rtol=1e-9)


# --- level must not leak into shape -----------------------------------------------------


def test_the_same_song_at_two_levels_draws_one_line():
    """The test this module exists for.

    A master is almost always louder than the mix it came from. If that showed up as
    vertical offset, every master would appear to have more of every frequency than its own
    source, and the picture would confirm an improvement that had not happened.
    """
    audio = _music()
    quiet = measure(audio * 0.1, SR, "quiet", "Quiet")
    loud = measure(audio, SR, "loud", "Loud")

    assert loud.lufs - quiet.lufs == pytest.approx(20.0, abs=0.5)  # the gain really is there
    for a, b in zip(quiet.db, loud.db, strict=True):
        assert a == pytest.approx(b, abs=0.05)


def test_the_loudness_difference_is_reported_rather_than_discarded():
    """Level-matching is a drawing decision, not a claim that the levels are equal. The
    numbers stay, so the page can say "shown level-matched; the master is 3 dB louder"."""
    audio = _music()
    quiet = measure(audio * 0.1, SR, "quiet", "Quiet")
    loud = measure(audio, SR, "loud", "Loud")

    assert quiet.shifted_db - loud.shifted_db == pytest.approx(20.0, abs=0.5)
    assert quiet.shifted_db == pytest.approx(-quiet.lufs, abs=0.01)


def test_a_real_tonal_difference_survives_the_level_match():
    """The other half of the same claim: matching level must not also flatten tone.

    A brighter mix has to *stay* brighter, or the panel would report every song as
    identical, which is a much quieter failure than reporting them all as different.
    """
    dark = measure(_music(tilt=0.0), SR, "dark", "Dark")
    bright = measure(_music(tilt=1.5), SR, "bright", "Bright")

    tilt_dark = _at(dark, 8000) - _at(dark, 80)
    tilt_bright = _at(bright, 8000) - _at(bright, 80)
    assert tilt_bright > tilt_dark + 3.0


def test_silence_is_left_where_it_is_rather_than_shifted_by_a_guess():
    """An unmeasurable loudness produces a curve at the wrong height, which is visible.
    Inventing a shift would produce one at a plausible height, which is not."""
    quiet = measure(np.zeros((SR * 2, 2)), SR, "nothing", "Nothing")
    assert quiet.shifted_db == 0.0
    assert quiet.lufs <= -100.0


# --- the shared window ------------------------------------------------------------------


def test_one_vertical_range_covers_every_point_of_every_curve():
    """Three curves each fitted to themselves would all fill the box and look the same.

    *Every point* is the half this got wrong. `window` used to discard whatever sat more
    than 60 dB under a curve's own peak before measuring, so the quietest part of a curve
    was outside the chart by construction — QA found a reference diving to -53 dB against
    a -9.6 floor and disappearing for the last tenth of the panel. There is no sampling,
    no percentile and no floor here now: the assertion is over the whole array, because
    that is what the function promises.
    """
    curves = [
        measure(_music(seed=1), SR, "a", "A"),
        measure(_music(seed=2, tilt=1.5), SR, "b", "B"),
    ]
    low, high = window(curves)
    for curve in curves:
        db = np.asarray(curve.db)
        assert db.min() >= low, f"{curve.key} dips {low - db.min():.1f} dB below the floor"
        assert db.max() <= high, f"{curve.key} exceeds the ceiling by {db.max() - high:.1f} dB"


def test_a_steep_top_end_does_not_fall_out_of_the_chart():
    """The specific shape that broke it: a song rolled off hard at the top, against one
    that is not. Before the fix the rolled-off curve left the frame."""
    from scipy.signal import butter, sosfilt

    bright = _music(seed=4)
    rolled = sosfilt(butter(6, 6000 / (SR / 2), btype="low", output="sos"), bright, axis=0)

    curves = [
        measure(bright, SR, "reference", "Bright"),
        measure(rolled, SR, "master", "Rolled off"),
    ]
    low, high = window(curves)
    for curve in curves:
        db = np.asarray(curve.db)
        assert db.min() >= low and db.max() <= high


def test_the_panel_draws_only_the_band_the_tool_matches_on():
    """One range for drawing and scaling alike.

    Two ranges is what produced the defect: points between 18 and 20 kHz were drawn
    against a scale that had never seen them. The band now stops at 16 kHz, where `BANDS`
    stops and where an MP3 lowpass starts separating two records by 40-50 dB for reasons
    no control here can change.
    """
    from app.services.mastering.instrument import BANDS

    assert HIGH_HZ == max(high for _, _, high in BANDS)
    hz = axis()
    assert hz.min() == pytest.approx(LOW_HZ)
    assert hz.max() == pytest.approx(HIGH_HZ)


def test_a_very_even_mix_still_gets_a_range_to_sit_in():
    """A curve with almost no variation would otherwise collapse to a zero-height window,
    and dividing by that range is how a chart becomes a blank box or a stack of NaNs."""
    flat = measure(np.random.default_rng(0).standard_normal((SR * 3, 2)) * 0.2, SR, "f", "F")
    low, high = window([flat])
    assert high - low >= 12.0


def test_an_empty_curve_does_not_take_the_window_with_it():
    """One unreadable file should cost its own line, not the whole picture."""
    from app.services.mastering.spectrum_view import Curve

    real = measure(_music(), SR, "a", "A")
    low, high = window([real, Curve(key="gone", label="Gone")])
    assert high > low


# --- the difference the panel is for ----------------------------------------------------


def test_the_gap_is_zero_against_yourself():
    one = measure(_music(), SR, "a", "A")
    assert max(abs(v) for v in difference(one, one)) == pytest.approx(0.0, abs=0.01)


def test_the_gap_points_the_way_round_the_label_says():
    """`difference(master, reference)` positive means the master has *more* there. Getting
    this backwards would draw every correction in the wrong direction."""
    bright = measure(_music(tilt=1.5), SR, "bright", "Bright")
    dark = measure(_music(tilt=0.0), SR, "dark", "Dark")

    gap = difference(bright, dark)
    hz = axis()
    top = float(np.mean([g for g, f in zip(gap, hz, strict=True) if f > 6000]))
    bottom = float(np.mean([g for g, f in zip(gap, hz, strict=True) if f < 120]))
    assert top > 0 > bottom


def test_a_gap_against_a_missing_curve_is_empty_rather_than_wrong():
    from app.services.mastering.spectrum_view import Curve

    real = measure(_music(), SR, "a", "A")
    assert difference(real, Curve(key="gone", label="Gone")) == []


# --- a profile draws the same line as the audio it came from ----------------------------


def test_a_saved_profile_draws_what_its_audio_would_have():
    """The premise of a profile, applied to the picture as well as to the match.

    Not exact: a profile stores 96 points where this axis has 160, so the interpolation
    between them is the error. The size of that error is asserted rather than waved at,
    because it is the difference between "the same curve by a shorter route" and "a curve
    that looks about right".
    """
    audio = _music()
    from_audio = measure(audio, SR, "reference", "Reference")
    saved = from_profile(capture(audio, SR, "Saved"), label="Saved")

    hz = axis()
    inside = (hz >= 30.0) & (hz <= 16000.0)
    gap = np.abs(np.asarray(from_audio.db) - np.asarray(saved.db))[inside]

    assert gap.max() < 1.5, f"worst point {gap.max():.2f} dB out"
    assert float(np.sqrt(np.mean(gap**2))) < 0.4
    assert saved.source == "profile"
    assert from_audio.source == "audio"


def test_a_profile_with_no_curve_yields_an_empty_line_rather_than_an_exception():
    from app.services.mastering.profile import ReferenceProfile

    empty = from_profile(ReferenceProfile(name="Nothing"))
    assert empty.db == []
    assert empty.source == "profile"


# --- what is drawn is what the matcher sees ---------------------------------------------


def test_the_curve_is_smoothed_to_the_width_the_matcher_works_at():
    """A raw spectrum of a song is a picket fence of whichever notes were played. If the
    display were unsmoothed it would show differences of arrangement as differences of
    production, and invite corrections for a chord change."""
    tones = np.zeros((SR * 4, 2))
    t = np.arange(SR * 4) / SR
    for hz in (300, 1000, 3000):
        tones[:, 0] += np.sin(2 * np.pi * hz * t)
        tones[:, 1] += np.sin(2 * np.pi * hz * t)
    tones += np.random.default_rng(1).standard_normal(tones.shape) * 0.02

    curve = measure(tones / np.abs(tones).max() * 0.5, SR, "a", "A")
    db = np.asarray(curve.db)

    # A third of an octave of smoothing averages each point over the sixth of an octave
    # either side of it, so the width can be pinned from both directions at once.
    peak = _at(curve, 1000)

    # Inside the window: a twelfth of an octave away still sees the tone, so it cannot
    # have fallen away. On an unsmoothed spectrum it would already be in the noise.
    assert _at(curve, 1000 * 2 ** (1 / 12)) > peak - 3.0
    assert _at(curve, 1000 * 2 ** (-1 / 12)) > peak - 3.0

    # Outside it: a full third of an octave away the tone is gone from the average
    # entirely. This is the half that matters - smoothing wide enough to hide a real
    # difference between two mixes would make the panel agree with everything.
    assert _at(curve, 1000 * 2 ** (1 / 3)) < peak - 20.0
    assert np.isfinite(db).all()


def test_the_settings_the_display_uses_are_the_matchers_own():
    """If these ever drift apart, the panel starts showing a difference the correction
    engine cannot see, or hiding one it acts on."""
    from app.services.mastering.spectrum_view import _resample

    settings = MatchSettings()
    assert settings.smoothing_octaves == pytest.approx(1.0 / 3.0)
    curve = _resample(
        np.abs(np.fft.rfft(np.hanning(settings.n_fft))), SR, settings
    )
    assert curve.shape == (CURVE_POINTS,)


# --- reading files that may not be there ------------------------------------------------
#
# `TrackStorage.reference_path` returns None for a track with no reference, which is most
# of them. The first version of `read` called `Path(None)`, caught the TypeError, and then
# threw a second one out of the logging line while trying to name the file - turning the
# ordinary case of "no reference yet" into a 500 on the endpoint.


def test_a_track_with_no_reference_is_an_ordinary_answer_and_not_an_error():
    from app.services.mastering.spectrum_view import read

    assert read(None) is None


def test_a_path_that_is_not_there_is_an_ordinary_answer_too(tmp_path):
    from app.services.mastering.spectrum_view import read

    assert read(tmp_path / "never-written.wav") is None


def test_a_file_that_is_not_audio_costs_its_own_curve_and_nothing_else(tmp_path):
    from app.services.mastering.spectrum_view import read

    junk = tmp_path / "not-audio.wav"
    junk.write_bytes(b"this is not a wav file, whatever the extension says")
    assert read(junk) is None


# --- the display tilt -------------------------------------------------------------------
#
# Music falls away roughly like pink noise, so an untilted spectrum of a real mix spans
# about 62 dB while the differences this panel exists to show are one to five. Tilting the
# axis by the slope music already has spends the vertical range on the departures instead.
#
# The whole claim is that this changes the axis and not the measurement, so that is what
# gets asserted: the distance between any two curves, at any frequency, has to survive it.


def test_the_tilt_does_not_change_the_distance_between_two_curves():
    """The property everything else here depends on. If the tilt were applied unevenly the
    picture would exaggerate a gap at one end of the spectrum and hide it at the other,
    which is a lie told in the one direction nobody would check."""
    a = measure(_music(seed=1), SR, "a", "A")
    b = measure(_music(seed=2, tilt=1.5), SR, "b", "B")

    tilted = np.asarray(a.db) - np.asarray(b.db)
    flat = np.asarray(a.flat_db) - np.asarray(b.flat_db)
    assert np.allclose(tilted, flat, atol=0.02)


def test_the_reported_difference_comes_from_the_untilted_curves():
    a = measure(_music(seed=1), SR, "a", "A")
    b = measure(_music(seed=2, tilt=1.5), SR, "b", "B")

    reported = np.asarray(difference(a, b))
    flat = np.asarray(a.flat_db) - np.asarray(b.flat_db)
    assert np.allclose(reported, flat, atol=0.01)


def test_the_tilt_pivots_where_it_says_it_does():
    """At the pivot the two curves are the same number, which is what makes the tilted
    axis readable as dB rather than as an arbitrary unit."""
    from app.services.mastering.spectrum_view import TILT_PIVOT_HZ

    one = measure(_music(), SR, "a", "A")
    hz = axis()
    at_pivot = float(np.interp(np.log2(TILT_PIVOT_HZ), np.log2(hz), np.asarray(one.db)))
    flat_at_pivot = float(
        np.interp(np.log2(TILT_PIVOT_HZ), np.log2(hz), np.asarray(one.flat_db))
    )
    assert at_pivot == pytest.approx(flat_at_pivot, abs=0.05)


def test_the_tilt_actually_flattens_real_music():
    """The reason for the number. A mix drawn untilted is a ski slope; the point of the
    tilt is that what remains on screen is what the mix does differently from pink noise,
    not the fact that it is music."""
    one = measure(_music(), SR, "a", "A")
    hz = axis()
    inside = (hz >= 50.0) & (hz <= 12000.0)

    flat = np.asarray(one.flat_db)[inside]
    tilted = np.asarray(one.db)[inside]
    assert tilted.max() - tilted.min() < flat.max() - flat.min()
