"""Stereo width, per band, matched to a reference.

The single-band version widens everything above a crossover by one factor. Measured
against a real record that turns out to be the wrong shape entirely. Comparing a home
master of a pop-punk song against the commercial reference it was aimed at, band by band:

    band        yours   reference   factor needed
    0-120       0.153   0.144       0.94
    120-250     0.474   0.232       0.49   <- the home mix is twice as wide
    250-500     0.375   0.591       1.58
    500-1k      0.384   0.739       1.93
    1-2k        0.449   0.728       1.62
    2-4k        0.582   0.842       1.45
    4-8k        0.497   0.833       1.68
    8k+         0.292   0.776       2.66   <- and a third as wide

The record is *tighter* than the home mix at the bottom and far wider everywhere above
it. One factor cannot do both, and the crossover version cannot narrow anything at all.
That shape - bass held to the centre, everything above it opened out - is most of what
"produced" sounds like, and it is a different thing from tone, which reference matching
already handles well.

Widening is not free: side content cancels when a phone speaker or a club PA sums the
channels. So the cap is set from measurement rather than taste, and the result is checked
against the reference's own mono behaviour, on the principle that a master may not give
up more than the record it is matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Crossovers for a filterbank whose bands sum back to the input sample for sample. Each
#: band is the difference between two zero-phase lowpasses, so the sum telescopes.
CROSSOVERS: tuple[float, ...] = (120.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0)

BAND_NAMES: tuple[str, ...] = (
    "sub",
    "low",
    "low mid",
    "body",
    "mid",
    "upper mid",
    "presence",
    "top",
)

#: How far one band may be pushed. The largest factor any real comparison has asked for
#: is 2.66; past about this the change stops being a match and starts being an effect.
MAX_FACTOR = 2.5

#: And how far it may be pulled in. Narrowing is the safer direction - it moves energy
#: towards the centre - but collapsing a band entirely would be audible as a hole.
MIN_FACTOR = 0.4

#: A band holding this little side content has no stereo to scale, and multiplying noise
#: by 2.5 is how a matching tool invents an image that was never recorded.
NO_IMAGE = 0.02

#: How much more level than the reference the result may give up when summed to mono.
MONO_ALLOWANCE_DB = 0.35


@dataclass
class WidthReport:
    factors: dict[str, float] = field(default_factory=dict)
    mono_loss_db: float = 0.0
    reference_mono_loss_db: float = 0.0
    pulled_back: bool = False
    notes: list[str] = field(default_factory=list)


def split_bands(samples: np.ndarray, sample_rate: int) -> list[np.ndarray]:
    """Split into bands that sum back to the input exactly.

    Zero-phase, and built as differences of lowpasses rather than as bandpasses, because
    independent bandpass filters do not reconstruct: their overlaps and gaps would show up
    as comb filtering the moment the bands were summed again.
    """
    from scipy.signal import butter, sosfiltfilt

    audio = np.asarray(samples, dtype=np.float64)
    bands: list[np.ndarray] = []
    previous = np.zeros_like(audio)
    for hz in CROSSOVERS:
        sos = butter(4, min(hz / (sample_rate / 2.0), 0.99), btype="low", output="sos")
        low = sosfiltfilt(sos, audio, axis=0)
        bands.append(low - previous)
        previous = low
    bands.append(audio - previous)
    return bands


def side_to_mid(band: np.ndarray) -> float:
    """Side energy against mid energy. 0 is mono, 1 is as much side as mid."""
    audio = np.asarray(band, dtype=np.float64)
    if audio.ndim == 1 or audio.shape[1] < 2:
        return 0.0
    mid = (audio[:, 0] + audio[:, 1]) / 2.0
    side = (audio[:, 0] - audio[:, 1]) / 2.0
    energy = float(np.sqrt(np.mean(mid**2)))
    return float(np.sqrt(np.mean(side**2))) / (energy + 1e-12)


def width_profile(samples: np.ndarray, sample_rate: int) -> dict[str, float]:
    """Side-to-mid in every band, named."""
    return {
        name: side_to_mid(band)
        for name, band in zip(BAND_NAMES, split_bands(samples, sample_rate), strict=True)
    }


def mono_loss_db(samples: np.ndarray) -> float:
    """Level given up when the two channels are summed. Negative; nearer 0 is safer."""
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1 or audio.shape[1] < 2:
        return 0.0
    stereo = float(np.sqrt(np.mean(audio**2)))
    mono = float(np.sqrt(np.mean(((audio[:, 0] + audio[:, 1]) / 2.0) ** 2)))
    return float(20 * np.log10(mono / (stereo + 1e-12) + 1e-12))


def _apply(bands: list[np.ndarray], factors: list[float]) -> np.ndarray:
    """Recombine the bands with each one's side channel scaled.

    Summing the split and resumming it is only accurate to floating point, so when
    nothing is being changed the caller is handed its own array back instead. Doing
    nothing should cost nothing, exactly as it does for the single-band widener.
    """
    out = np.zeros_like(bands[0])
    for band, factor in zip(bands, factors, strict=True):
        if factor == 1.0:
            out += band
            continue
        mid = (band[:, 0] + band[:, 1]) / 2.0
        side = (band[:, 0] - band[:, 1]) / 2.0 * factor
        out += np.stack([mid + side, mid - side], axis=1)
    return out


def match_profile(
    samples: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    strength: float = 1.0,
) -> tuple[np.ndarray, WidthReport]:
    """Move each band's width towards the reference's, without breaking mono.

    ``strength`` scales every factor towards 1.0, so half strength makes half the move.

    The mono check is the part that matters. Widening sounds better on headphones
    whatever it does, so the guard cannot be "does this sound wide" - it has to be
    "does this survive being summed". The result is allowed to give up a little more than
    the reference does and no more; past that every factor is eased back towards 1.0 and
    the report says so, rather than shipping a master that disappears on a phone.
    """
    audio = np.asarray(samples, dtype=np.float64)
    report = WidthReport()
    if audio.ndim == 1 or audio.shape[1] < 2:
        report.notes.append("mono input; there is no image to match")
        return audio, report

    target = np.asarray(reference, dtype=np.float64)
    if target.ndim == 1 or target.shape[1] < 2:
        report.notes.append("the reference is mono; width left alone")
        return audio, report

    return match_to(
        audio, sample_rate, width_profile(target, sample_rate), mono_loss_db(target), strength
    )


def match_to(
    samples: np.ndarray,
    sample_rate: int,
    reference_width: dict[str, float],
    reference_mono_loss_db: float,
    strength: float = 1.0,
) -> tuple[np.ndarray, WidthReport]:
    """`match_profile`, given the reference's measurements rather than its audio.

    Split out because a saved reference profile has these nine numbers and no waveform -
    eight band widths and what the reference gives up in mono - and they are the whole of
    what the match ever reads from it.
    """
    audio = np.asarray(samples, dtype=np.float64)
    report = WidthReport()
    if audio.ndim == 1 or audio.shape[1] < 2:
        report.notes.append("mono input; there is no image to match")
        return audio, report

    bands = split_bands(audio, sample_rate)

    factors: list[float] = []
    for name, mine in zip(BAND_NAMES, bands, strict=True):
        here = side_to_mid(mine)
        want = float(reference_width.get(name, here))
        if here < NO_IMAGE:
            factors.append(1.0)
            report.notes.append(f"{name} is effectively mono; left as it is")
            continue
        factor = float(np.clip(want / here, MIN_FACTOR, MAX_FACTOR))
        factor = 1.0 + (factor - 1.0) * float(np.clip(strength, 0.0, 1.0))
        factors.append(factor)

    report.reference_mono_loss_db = round(reference_mono_loss_db, 2)
    report.factors = {n: round(f, 2) for n, f in zip(BAND_NAMES, factors, strict=True)}

    if all(f == 1.0 for f in factors):
        # Nothing to do, so hand back the original rather than a rebuilt copy of it.
        report.mono_loss_db = round(mono_loss_db(audio), 2)
        return audio, report

    out = _apply(bands, factors)
    report.mono_loss_db = round(mono_loss_db(out), 2)

    allowed = report.reference_mono_loss_db - MONO_ALLOWANCE_DB
    if report.mono_loss_db < allowed:
        # Ease everything back by the same proportion. Backing off only the widest band
        # would leave the others in a balance that was never measured.
        eased = [1.0 + (f - 1.0) * 0.5 for f in factors]
        out = _apply(bands, eased)
        factors = eased
        report.pulled_back = True
        report.mono_loss_db = round(mono_loss_db(out), 2)
        report.notes.append(
            "eased back: matching the reference's image fully would have cost more in "
            "mono than the reference itself gives up"
        )

    report.factors = {n: round(f, 2) for n, f in zip(BAND_NAMES, factors, strict=True)}
    return out, report
