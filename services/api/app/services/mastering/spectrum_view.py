"""Three songs on one pair of axes: where you started, where you ended, what you aimed at.

Everything else in this package *decides* something about tone - what to correct, by how
much, whether a gap is worth mentioning. This module decides nothing. It measures three
recordings the same way and hands back three curves, so the question "is my master
actually moving toward the reference?" can be answered by looking rather than by trusting
a paragraph of prose.

Two choices make the picture honest, and both are easy to get wrong.

**Level is matched, not shown.** Three songs mastered to three different loudnesses sit at
three different heights, and the eye reads that vertical offset as a tonal difference when
it is nothing of the kind - the loudest curve looks like it has more of everything. Each
curve is therefore shifted by its own integrated loudness, which is what an engineer does
by hand before any A/B worth trusting. What is left on screen is *balance*: the shape of a
song independent of how loud it was made. The shift applied is reported per curve so the
loudness difference is still available as a number, just not as a slope.

**Smoothing matches the matcher.** A raw FFT of a song is a picket fence of whatever notes
were played, and comparing two picket fences tells you about the chords rather than the
production. These are smoothed to a third of an octave - the same width `matching_curve`
uses - so what is drawn is what the correction engine is looking at. A difference visible
here is a difference the tool can act on, and one that is not, is not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.services.mastering.dsp import (
    MatchSettings,
    average_spectrum,
    smooth_log_frequency,
)
from app.services.mastering.loudness_meter import integrated_loudness

log = logging.getLogger(__name__)

#: The axis every curve is resampled onto, log-spaced because hearing is.
#:
#: 160 points across ten octaves is about sixteen per octave, comfortably finer than the
#: third-octave smoothing underneath it, so the line is limited by the measurement rather
#: than by the sampling. Stored profiles hold 96 and are interpolated up; that is a real
#: loss of resolution but not a visible one, since both numbers are well past the point
#: where the smoothing dominates.
CURVE_POINTS = 160

#: The band the panel covers — and the *only* band, because it is drawn and scaled alike.
#:
#: This started as two ranges: 20 Hz to 20 kHz drawn, 25 Hz to 18 kHz fitted, on the
#: reasoning that rumble and codec noise should not decide the scale. That is sound
#: reasoning and the implementation of it was a bug. Everything between 18 and 20 kHz was
#: drawn against a scale that had never seen it, so on a real comparison a difference
#: curve reached +51.8 dB inside a chart fitted to ±4 and the right-hand sixth of the
#: panel was simply empty.
#:
#: Narrowed to what the tool actually matches on rather than widened to fit the strays.
#: Above 16 kHz an MP3 lowpass can put two records 40-50 dB apart for reasons no listener
#: can hear and no control here can change, so those points were never advice — they were
#: an artefact dragging the scale around. 16 kHz is also where `BANDS` stops and where
#: `matching_curve` stops counting tilt, so the panel now shows the band the engine works
#: in. One range, used for both jobs, and no way for them to disagree again.
LOW_HZ = 20.0
HIGH_HZ = 16000.0

#: The slope subtracted from every curve before drawing, in dB per octave.
#:
#: Music is not flat. A mix falls away roughly like pink noise, so a true spectrum of one
#: spans about 62 dB from its bass to its top octave - and the differences this panel
#: exists to show are one to five. On a 240-pixel chart that is four pixels for a
#: difference worth acting on, which is a picture of a spectrum rather than a usable
#: measurement.
#:
#: Tilting the axis by the slope music already has puts a typical mix roughly level and
#: spends the vertical range on the departures from it instead. Measured on a real pair:
#: 62 dB of range at no tilt, 40.7 at 4.5 dB/octave, and 51 at 6 - so this is close to the
#: bottom of the curve rather than a round number, and going further starts stretching the
#: top octaves back out again.
#:
#: This is a change of axis, not of data. Every curve gets the same slope, so the distance
#: between two of them at any frequency is exactly what it was - which is why the
#: difference figures are computed from the untilted curves and come out identical either
#: way.
DISPLAY_TILT_DB_PER_OCTAVE = 4.5

#: The frequency the tilt pivots around, so "0 dB of tilt" happens somewhere musically
#: central rather than at 20 Hz where it would push the whole picture off the top.
TILT_PIVOT_HZ = 1000.0


def tilt() -> np.ndarray:
    """The slope added to each curve for display, per point on the shared axis."""
    return DISPLAY_TILT_DB_PER_OCTAVE * np.log2(axis() / TILT_PIVOT_HZ)


@dataclass(slots=True)
class Curve:
    """One recording's tonal balance, level-matched and ready to draw."""

    key: str
    label: str
    #: Level-matched and tilted, ready to draw as-is.
    db: list[float] = field(default_factory=list)
    #: The same curve without the display tilt - a real spectrum, for anything that wants
    #: to compute with it rather than draw it.
    flat_db: list[float] = field(default_factory=list)
    #: Integrated loudness before matching, and the shift that matching applied. Kept so
    #: the page can say "these are shown level-matched; the master is 3.1 dB louder".
    lufs: float = 0.0
    shifted_db: float = 0.0
    #: "audio" or "profile" - a profile's curve is 96 stored points rather than a fresh
    #: measurement, and a viewer is entitled to know which they are looking at.
    source: str = "audio"


def axis() -> np.ndarray:
    """The shared frequency axis. One definition, so every curve lines up."""
    return np.geomspace(LOW_HZ, HIGH_HZ, CURVE_POINTS)


def _resample(
    spectrum: np.ndarray, sample_rate: int, settings: MatchSettings
) -> np.ndarray:
    """A measured spectrum, smoothed and sampled onto the shared axis, in dB."""
    smoothed = smooth_log_frequency(spectrum, sample_rate, settings.smoothing_octaves)
    freqs = np.fft.rfftfreq(settings.n_fft, d=1.0 / sample_rate)
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(np.maximum(smoothed, 1e-20))
    # Interpolated in log frequency, matching the axis it lands on. Held flat past the
    # top: a 44.1 kHz file has nothing above 22 kHz, and letting the interpolation run to
    # the -400 dB of an empty bin would draw a cliff that is an artefact of the format.
    return np.interp(np.log2(axis()), np.log2(np.maximum(freqs, 1e-6)), db)


def measure(
    samples: np.ndarray,
    sample_rate: int,
    key: str,
    label: str,
    settings: MatchSettings | None = None,
) -> Curve:
    """Measure one recording onto the shared axis, level-matched to 0 LUFS."""
    settings = settings or MatchSettings()
    audio = np.asarray(samples, dtype=np.float64)

    db = _resample(average_spectrum(audio, settings.n_fft, settings.hop), sample_rate, settings)
    loudness, _ = integrated_loudness(audio, sample_rate)
    return _levelled(db, float(loudness), key, label, "audio")


def from_profile(profile, key: str = "reference", label: str = "") -> Curve:
    """The same curve from a saved profile, which stores one already.

    Interpolated from the profile's own 96 points rather than remeasured, because there is
    nothing left to measure - this is the whole premise of a profile. Held flat outside the
    stored range for the same reason `ReferenceProfile.spectrum` does: a curve extrapolated
    past its data runs away exactly where the display has least to say.
    """
    hz = np.asarray(profile.curve_hz, dtype=np.float64)
    stored = np.asarray(profile.curve_db, dtype=np.float64)
    if hz.size == 0:
        return Curve(key=key, label=label or profile.name, source="profile")

    db = np.interp(
        np.log2(axis()), np.log2(hz), stored,
        left=float(stored[0]), right=float(stored[-1]),
    )
    return _levelled(db, float(profile.lufs), key, label or profile.name, "profile")


def _levelled(db: np.ndarray, lufs: float, key: str, label: str, source: str) -> Curve:
    """Shift a curve so it is drawn as if played at the same loudness as the others.

    The shift is the recording's own integrated loudness, so every curve ends up
    normalised to 0 LUFS and the vertical distance between two of them is a real
    difference in balance rather than a difference in mastering level.

    An unmeasurable loudness - silence, or a build without the loudness meter - leaves the
    curve where it is rather than shifting it by a made-up number. It will sit at the wrong
    height, which is visible and therefore fixable; a silent fudge would not be.
    """
    shift = -lufs if np.isfinite(lufs) else 0.0
    flat = db + shift
    return Curve(
        key=key,
        label=label,
        db=[round(float(v), 2) for v in (flat + tilt())],
        flat_db=[round(float(v), 2) for v in flat],
        lufs=round(float(lufs), 2) if np.isfinite(lufs) else -120.0,
        shifted_db=round(float(shift), 2),
        source=source,
    )


def window(curves: list[Curve]) -> tuple[float, float]:
    """A shared vertical range that fits every point of every curve, in dB.

    Shared is the point. Three curves each auto-scaled to themselves would all fill the
    box and look identical, which is the one thing this picture must not do.

    *Every point* is the other half, and it used to be a claim this function did not
    honour. It discarded whatever sat more than 60 dB under a curve's own peak before
    measuring — so the quietest part of a curve was outside the window by construction,
    and a reference with a steep top end ran off the bottom of the chart. There is no
    floor here now. The axis covers the band the panel draws, the whole of it, which is
    what makes the docstring above true rather than aspirational.
    """
    values = [
        np.asarray(curve.db, dtype=np.float64) for curve in curves if curve.db
    ]
    if not values:
        return -60.0, 0.0

    everything = np.concatenate(values)
    low = float(everything.min())
    high = float(everything.max())
    if high - low < 12.0:  # a very even mix; give it something to sit in
        middle = (high + low) / 2.0
        low, high = middle - 6.0, middle + 6.0
    # Rounded outward, never inward: rounding a bound the wrong way is how a curve ends
    # up a pixel outside a window that was computed to hold it.
    return float(np.floor(low - 2.0)), float(np.ceil(high + 2.0))


def difference(a: Curve, b: Curve) -> list[float]:
    """`a - b` per point, for drawing the gap that remains rather than inferring it.

    Taken from the untilted curves. The tilt cancels in a subtraction, so this would give
    the same answer either way - but saying which one it came from is the difference
    between that being true and it being a coincidence that survives until someone changes
    the tilt to something frequency-dependent.
    """
    if not a.flat_db or not b.flat_db:
        return []
    return [
        round(float(x - y), 2)
        for x, y in zip(np.asarray(a.flat_db), np.asarray(b.flat_db), strict=True)
    ]


def read(path: Path | None):
    """Read a file for measurement, or None if there is not one to read.

    Local to this module and deliberately forgiving: a missing or unreadable file means one
    curve fewer on a picture, which is a worse picture and not an error. The panel is a
    diagnostic - refusing to draw the two curves that *are* available because a third is
    missing would be exactly backwards.

    `None` is an ordinary input, not a mistake: `TrackStorage.reference_path` returns it for
    a track that has no reference, which is most of them. The logging line takes the path it
    was given rather than deriving a name from it, because a handler that can itself throw
    turns a missing file into a 500 - which is how this was first written.
    """
    from app.services.mixdown.encode import read_audio

    if path is None:
        return None
    try:
        if not Path(path).exists():
            return None
        return read_audio(Path(path))
    except Exception:
        log.info("could not read %s for the spectrum view", path, exc_info=True)
        return None
