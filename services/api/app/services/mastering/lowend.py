"""Tightening the bottom: centre the bass, and throw away what is below the music.

Both moves here came out of measuring a home master against the record it was aimed at.
The complaint was that the bass sounded thin and sloppy, and the obvious explanation -
that reference matching had cut it - turned out to be wrong. The levels were already
right, within 0.2 dB in every band from 40 to 200 Hz. Two other things were not:

    band                 home master   reference
    bass body 120-200    0.508         0.197      side-to-mid, so 2.6x as wide
    bass body 120-200    0.590         0.926      channel correlation
    deep 20-40           -18.70        -22.18     dB relative to the mix

Spread, poorly-correlated bass is what "muddy" usually is. It also explains why the same
mix can sound thin: side content cancels when anything sums to mono, so a bass guitar
smeared across the image is loud on headphones and half gone on a phone. Centring it is
not a tonal change - no EQ is applied - but it is heard as more bass, because more of it
survives.

The deep band is a separate problem. Energy below about 30 Hz is rumble, handling noise
and room, not notes: the lowest string on a bass guitar is 41 Hz and a kick's fundamental
sits near 50. It is inaudible on most systems, but the limiter can hear it perfectly
well, so it eats headroom that could have gone to the parts of the mix people can
actually hear.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Where the bass stops being directional. Below roughly this, human hearing localises by
#: level rather than by phase, so stereo information down there is mostly costing
#: headroom and mono compatibility rather than adding width anyone perceives.
DEFAULT_CENTRE_BELOW_HZ = 150.0
MIN_CENTRE_HZ = 60.0
MAX_CENTRE_HZ = 300.0

#: Below the lowest note any normal instrument plays: a bass guitar's E is 41 Hz, a
#: five-string's B is 31. Cutting here removes rumble and leaves the music.
DEFAULT_SUBSONIC_HZ = 30.0
MIN_SUBSONIC_HZ = 15.0
MAX_SUBSONIC_HZ = 60.0


@dataclass
class LowEndReport:
    centred_below_hz: float = 0.0
    centre_amount: float = 0.0
    #: Side-to-mid in the centred range, before and after.
    width_before: float = 0.0
    width_after: float = 0.0
    subsonic_hz: float = 0.0
    #: How much level the subsonic filter removed, in dB. Small is expected and good.
    subsonic_removed_db: float = 0.0
    notes: list[str] = field(default_factory=list)


def _split(samples: np.ndarray, sample_rate: int, hz: float):
    """Low and high halves that sum back to the input exactly.

    Zero-phase, so nothing is smeared in time. That matters more here than elsewhere: a
    minimum-phase crossover at 150 Hz rotates the phase of the kick and the bass relative
    to each other, which is its own kind of loose bottom end.
    """
    from scipy.signal import butter, sosfiltfilt

    audio = np.asarray(samples, dtype=np.float64)
    sos = butter(4, min(hz / (sample_rate / 2.0), 0.99), btype="low", output="sos")
    low = sosfiltfilt(sos, audio, axis=0)
    return low, audio - low


def side_to_mid(samples: np.ndarray) -> float:
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1 or audio.shape[1] < 2:
        return 0.0
    mid = (audio[:, 0] + audio[:, 1]) / 2.0
    side = (audio[:, 0] - audio[:, 1]) / 2.0
    return float(
        np.sqrt(np.mean(side**2)) / (np.sqrt(np.mean(mid**2)) + 1e-12)
    )


def centre_bass(
    samples: np.ndarray,
    sample_rate: int,
    hz: float = DEFAULT_CENTRE_BELOW_HZ,
    amount: float = 1.0,
    report: LowEndReport | None = None,
) -> np.ndarray:
    """Pull everything below `hz` towards the centre. 1.0 is fully mono down there.

    Only the side channel of the low band is touched, so the mid channel - which is
    almost all of the bass - is untouched and no tone changes. What changes is how much
    of it survives being summed.

    The filter provides the taper. There is no hard edge at the crossover, so the image
    closes gradually rather than collapsing at one frequency, which would be audible as a
    step when a bass line crosses it.
    """
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1 or audio.shape[1] < 2 or amount <= 0.0:
        return audio

    hz = float(np.clip(hz, MIN_CENTRE_HZ, MAX_CENTRE_HZ))
    amount = float(np.clip(amount, 0.0, 1.0))
    low, high = _split(audio, sample_rate, hz)

    if report is not None:
        report.centred_below_hz = hz
        report.centre_amount = amount
        report.width_before = round(side_to_mid(low), 3)

    mid = (low[:, 0] + low[:, 1]) / 2.0
    side = (low[:, 0] - low[:, 1]) / 2.0 * (1.0 - amount)
    centred = np.stack([mid + side, mid - side], axis=1)

    if report is not None:
        report.width_after = round(side_to_mid(centred), 3)
        report.notes.append(
            f"bass centred below {hz:.0f} Hz"
            + ("" if amount >= 0.999 else f" ({amount:.0%})")
        )
    return centred + high


def remove_subsonics(
    samples: np.ndarray,
    sample_rate: int,
    hz: float = DEFAULT_SUBSONIC_HZ,
    report: LowEndReport | None = None,
) -> np.ndarray:
    """Cut below `hz`, where there are no notes - only rumble, handling and room.

    Zero-phase again, and gentle: a steep filter here rings at exactly the frequencies it
    is meant to be removing.
    """
    from scipy.signal import butter, sosfiltfilt

    audio = np.asarray(samples, dtype=np.float64)
    if hz <= 0.0:
        return audio

    hz = float(np.clip(hz, MIN_SUBSONIC_HZ, MAX_SUBSONIC_HZ))
    sos = butter(2, min(hz / (sample_rate / 2.0), 0.99), btype="high", output="sos")
    filtered = sosfiltfilt(sos, audio, axis=0)

    if report is not None:
        before = float(np.sqrt(np.mean(audio**2)))
        after = float(np.sqrt(np.mean(filtered**2)))
        report.subsonic_hz = hz
        report.subsonic_removed_db = round(
            float(20 * np.log10((after + 1e-12) / (before + 1e-12))), 2
        )
        report.notes.append(f"cut below {hz:.0f} Hz, where there are no notes")
    return filtered
