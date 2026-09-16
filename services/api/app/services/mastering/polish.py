"""The finishing moves a reference match cannot make for you.

Matching answers "what does that record sound like?". It cannot answer "what do I want
this record to sound like?", and three things fall in that gap.

**Air.** The matched tone is whatever the reference dictates. If the reference is dull,
so is the master, and there is no way to ask for more top end. A gentle high shelf is the
dial that a matching curve deliberately is not.

**Width.** Stem matching sets each instrument's width against its counterpart; nothing
sets the width of the finished mix. The widening here is band-limited on purpose — see
`widen_above`.

**Headroom.** Part correction, part preference. The correction is `ceiling_headroom`:
a reference that peaks above this pipeline's ceiling has to be over-driven to match its
loudness number, and the difference is paid in gain reduction. The preference is the
`headroom_db` dial, for sitting below the reference on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.services.mastering.dsp import (
    DEFAULT_N_FFT,
    apply_curve,
    peak_db,
    set_width,
)
from app.services.mastering.loudness_meter import integrated_loudness

#: Where the air shelf starts to lift. Above the presence range, so it adds sheen rather
#: than making vocals and cymbals harsh.
DEFAULT_AIR_HZ = 8000.0

#: Widening below this is the classic way to sound big on headphones and vanish on a
#: phone speaker or a club rig.
DEFAULT_WIDTH_FLOOR_HZ = 250.0

#: Centre of the warmth bell: the body of guitars, snares and male vocals.
DEFAULT_WARMTH_HZ = 450.0

#: A shelf beyond this stops sounding like air and starts sounding like a broken tweeter.
MAX_AIR_DB = 6.0

#: Past this the low mids stop sounding warm and start sounding boxy.
MAX_WARMTH_DB = 4.0

#: Past 1.6 the side channel is loud enough that mono compatibility starts to suffer.
MAX_WIDTH = 1.6
MIN_WIDTH = 0.7


@dataclass(slots=True)
class Polish:
    """What the user asked for on top of the match."""

    #: High-shelf lift in dB. 0 leaves the matched tone exactly as matched.
    air_db: float = 0.0
    air_hz: float = DEFAULT_AIR_HZ
    #: Low-shelf lift in dB. Body, not "less treble" - the two are different requests.
    warmth_db: float = 0.0
    warmth_hz: float = DEFAULT_WARMTH_HZ
    #: Side-channel scale above `width_floor_hz`. 1.0 is untouched.
    width: float = 1.0
    width_floor_hz: float = DEFAULT_WIDTH_FLOOR_HZ
    #: Extra dB to stay under the reference, on top of whatever the guard decides.
    headroom_db: float = 0.0
    #: Aim at the reference's loudness relative to its peak rather than absolutely,
    #: so a reference that peaks above our ceiling is not chased into the limiter.
    protect_dynamics: bool = True

    def wanted(self) -> bool:
        return bool(
            self.air_db or self.warmth_db or self.width != 1.0 or self.headroom_db
        )


@dataclass(slots=True)
class PolishReport:
    """What the finishing stage actually did, in numbers a person can check."""

    air_db: float = 0.0
    warmth_db: float = 0.0
    width_factor: float = 1.0
    width_before: float = 0.0
    width_after: float = 0.0
    headroom_db: float = 0.0
    #: Back-off applied because the reference peaks above our ceiling.
    ceiling_headroom_db: float = 0.0
    reference_crest_db: float = 0.0
    result_crest_db: float = 0.0
    notes: list[str] = field(default_factory=list)


def shelf_ramp(
    n_fft: int,
    sample_rate: int,
    hz: float,
    octaves: float = 1.0,
    kind: str = "high",
) -> np.ndarray:
    """0-to-1 weighting per bin: how much of a shelf's gain each frequency receives.

    Kept separate from the gain so the suggestion engine can ask the question the other
    way round — "what shelf gain would close a gap of N dB in this band?" — by averaging
    the ramp over that band rather than guessing a fudge factor.
    """
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    low = hz / (2.0**octaves)
    high = hz * (2.0**octaves)

    with np.errstate(divide="ignore"):
        position = (np.log2(np.maximum(freqs, 1e-6)) - np.log2(low)) / (
            np.log2(high) - np.log2(low)
        )
    ramp = 0.5 - 0.5 * np.cos(np.pi * np.clip(position, 0.0, 1.0))
    return ramp if kind == "high" else 1.0 - ramp


def shelf_curve(
    n_fft: int,
    sample_rate: int,
    hz: float,
    gain_db: float,
    octaves: float = 1.0,
    kind: str = "high",
) -> np.ndarray:
    """A shelf as a per-bin magnitude curve, for `apply_curve`.

    The transition is a raised cosine across `octaves` either side of `hz` rather than a
    step. A step in the frequency domain is a sinc in the time domain, which smears
    transients — audible as a lisp on cymbals, which is the opposite of the point.
    """
    return 10.0 ** (gain_db * shelf_ramp(n_fft, sample_rate, hz, octaves, kind) / 20.0)


def add_air(
    samples: np.ndarray, sample_rate: int, gain_db: float, hz: float = DEFAULT_AIR_HZ
) -> np.ndarray:
    """Lift the top end by a gentle shelf, leaving everything below it alone."""
    if not gain_db:
        return np.asarray(samples, dtype=np.float64)
    gain_db = float(np.clip(gain_db, -MAX_AIR_DB, MAX_AIR_DB))
    curve = shelf_curve(DEFAULT_N_FFT, sample_rate, hz, gain_db)
    return apply_curve(samples, curve)


def bell_ramp(
    n_fft: int, sample_rate: int, hz: float, octaves: float = 0.7
) -> np.ndarray:
    """0-to-1 weighting for a bell centred on `hz`, Gaussian in log frequency.

    A shelf is the wrong shape for warmth. Every shelf lifts *everything* below its
    corner, so a shelf placed to cover 250-800 Hz also lifts 40 Hz by the same amount and
    the result is boomy rather than warm. A bell leaves the bottom octave where it is.
    """
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    with np.errstate(divide="ignore"):
        distance = (np.log2(np.maximum(freqs, 1e-6)) - np.log2(hz)) / octaves
    return np.exp(-0.5 * distance**2)


def bell_curve(
    n_fft: int, sample_rate: int, hz: float, gain_db: float, octaves: float = 0.7
) -> np.ndarray:
    """A bell as a per-bin magnitude curve, for `apply_curve`."""
    return 10.0 ** (gain_db * bell_ramp(n_fft, sample_rate, hz, octaves) / 20.0)


def add_warmth(
    samples: np.ndarray, sample_rate: int, gain_db: float, hz: float = DEFAULT_WARMTH_HZ
) -> np.ndarray:
    """Lift the low mids, leaving both the top and the bottom alone.

    "Warmer" is not the same as "less bright". Turning the treble down makes a mix dull;
    what people mean is more body around 250-800 Hz, where the weight of guitars, snares
    and male vocals lives. A bell rather than a shelf, so the bottom octave is not dragged
    up with it - see `bell_ramp`.
    """
    if not gain_db:
        return np.asarray(samples, dtype=np.float64)
    gain_db = float(np.clip(gain_db, -MAX_WARMTH_DB, MAX_WARMTH_DB))
    return apply_curve(samples, bell_curve(DEFAULT_N_FFT, sample_rate, hz, gain_db))


def widen_above(
    samples: np.ndarray,
    sample_rate: int,
    factor: float,
    crossover_hz: float = DEFAULT_WIDTH_FLOOR_HZ,
) -> np.ndarray:
    """Widen only above a crossover, leaving the low end exactly where it was.

    Widening everything is the naive version and it has a specific failure: side-channel
    content cancels when the two channels sum to mono, and low frequencies carry most of
    a mix's energy. A fully-widened mix sounds huge on headphones and loses its bass on a
    phone speaker, a club rig, or anything summing to mono.

    The split is zero-phase, so low + high reconstructs the input sample for sample and a
    factor of 1.0 is genuinely a no-op rather than approximately one.
    """
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    if factor == 1.0:
        return audio

    from scipy.signal import butter, sosfiltfilt

    factor = float(np.clip(factor, MIN_WIDTH, MAX_WIDTH))
    nyquist = sample_rate / 2.0
    sos = butter(4, min(crossover_hz / nyquist, 0.99), btype="low", output="sos")
    low = sosfiltfilt(sos, audio, axis=0)
    return low + set_width(audio - low, factor)


def crest_db(samples: np.ndarray, sample_rate: int) -> float:
    """Peak minus perceived loudness: how much dynamic range a render has left."""
    loudness, _ = integrated_loudness(samples, sample_rate)
    if not np.isfinite(loudness):
        return 0.0
    return float(peak_db(samples) - loudness)


def ceiling_headroom(
    reference: np.ndarray, sample_rate: int, ceiling_db: float = -1.0
) -> tuple[float, float]:
    """How far under the reference's loudness to stop. Returns (back_off_db, ref_crest).

    Matching a reference's *absolute* loudness is the wrong target when the two renders
    do not peak in the same place. A commercial master typically peaks at or just above
    0 dBFS - MP3 decoding overshoots, so measured peaks above full scale are normal - and
    this pipeline limits to -1 dBFS. Chasing the reference's LUFS number from a lower
    ceiling means driving that much harder into the limiter to get there, and the extra
    is paid for entirely in gain reduction.

    So the target is the reference's loudness *relative to its own peak*, and the back-off
    is simply how far its peak sits above our ceiling. Written that way the result is an
    identity worth knowing: a master that peaks at the ceiling ends up with exactly the
    reference's crest factor, because

        crest_out = ceiling - (ref_lufs - back_off)
                  = ceiling - ref_lufs + (ref_peak - ceiling)
                  = ref_peak - ref_lufs
                  = ref_crest

    Measured on a real pair: the reference peaked at +0.31 dBFS and sat at -8.72 LUFS, a
    9.03 dB crest. Matching it outright gave a 7.91 dB crest with the limiter working on
    31% of the track. Backing off the 1.31 dB gives 9.08 dB and 6%.

    Note what this does *not* do: it will not make a master more dynamic than its
    reference. If the reference is squashed, matching it faithfully means being squashed
    too. Wanting to sit above that is a preference, not a correction, and it belongs on
    the `headroom_db` dial.
    """
    loudness, _ = integrated_loudness(reference, sample_rate)
    if not np.isfinite(loudness):
        return 0.0, 0.0
    reference_crest = float(peak_db(reference) - loudness)
    return max(0.0, float(peak_db(reference)) - ceiling_db), reference_crest
