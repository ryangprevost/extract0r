"""Keeping the vocal where a listener expects it.

Two separate problems, and conflating them is why vocals end up buried.

**Placement.** Reference matching sets each instrument's level from the reference, which
is right in principle but has no opinion about what a vocal *should* do. If the reference
has no vocal, or separation under-recovers one, the vocal inherits whatever falls out of
the arithmetic. Measured on a real track: vocals at -6.8 LU below the mix, against the
-3 to -5 LU a modern pop or rock master typically places them at. So there is a floor —
after matching, the vocal is lifted if it sits further back than the chosen presence.

**Masking.** A vocal can be at the right level and still be hard to hear, because guitars
and keys occupy the same 1-4 kHz band. The mixing answer is not to turn the vocal up
until it wins - that just makes everything loud - it is to move the competing parts out
of the way while the vocal is singing. That is what ducking does here, and only in the
band where the collision happens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from app.domain.notes import StemKind

log = logging.getLogger(__name__)

#: Where a vocal sits, in LU relative to the full mix. These are conventions, not laws -
#: but a tool that has no opinion produces mixes with buried vocals, which is worse.
class VocalPresence(StrEnum):
    BACK = "back"        # blended, indie / shoegaze
    NATURAL = "natural"  # the usual rock/pop placement
    FORWARD = "forward"  # pop, hip-hop, anything vocal-led


PRESENCE_TARGETS = {
    VocalPresence.BACK: -7.0,
    VocalPresence.NATURAL: -4.5,
    VocalPresence.FORWARD: -2.5,
}

#: The band where vocals and guitars/keys collide. Ducking outside it would just make the
#: backing quieter, which is not the same thing as making the vocal clearer.
VOCAL_BAND_HZ = (900.0, 5000.0)

#: Stems that compete with a lead vocal. Bass and drums mostly do not - they live above
#: and below it - and ducking them audibly pumps.
COMPETES_WITH_VOCAL = (StemKind.GUITAR, StemKind.PIANO, StemKind.OTHER)

#: How far a vocal may be lifted to reach its target. A vocal that needs more than this
#: was not really recovered by separation, and pushing further only amplifies artefacts.
MAX_VOCAL_LIFT_DB = 6.0


@dataclass(slots=True)
class VocalReport:
    """What was done to place the vocal, in terms a person can check."""

    measured_lu: float = 0.0
    target_lu: float = 0.0
    lift_db: float = 0.0
    #: The user's own vocal fader, which rides on top of the lift rather than into it.
    user_gain_db: float = 0.0
    ducked_stems: list[str] = field(default_factory=list)
    duck_depth_db: float = 0.0
    notes: list[str] = field(default_factory=list)


def vocal_lift_db(
    vocal_relative_lu: float,
    presence: VocalPresence = VocalPresence.NATURAL,
    max_lift_db: float = MAX_VOCAL_LIFT_DB,
) -> tuple[float, str | None]:
    """How much to raise a vocal so it reaches its target placement.

    Only ever lifts. If matching has already put the vocal forward of the target, that is
    a deliberate-sounding mix and pulling it back would be this module second-guessing a
    decision it has no basis to overrule.
    """
    target = PRESENCE_TARGETS[presence]
    if vocal_relative_lu >= target:
        return 0.0, None

    wanted = target - vocal_relative_lu
    applied = float(min(wanted, max_lift_db))
    note = None
    if wanted > max_lift_db:
        note = (
            f"vocal wanted {wanted:.1f} dB to reach {target:.1f} LU but was lifted "
            f"{applied:.1f} dB - separation may not have recovered it cleanly"
        )
    return applied, note


def vocal_envelope(
    vocals: np.ndarray,
    sample_rate: int,
    attack_ms: float = 15.0,
    release_ms: float = 220.0,
    floor_db: float = -45.0,
) -> np.ndarray:
    """A 0..1 signal that follows where the vocal is singing.

    Slow release on purpose: a duck that snaps back between syllables is audible as
    pumping, whereas one that stays down across a phrase is not noticed at all.
    """
    audio = np.asarray(vocals, dtype=np.float64)
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    if mono.size == 0:
        return np.zeros(0)

    level = np.abs(mono)
    peak = float(level.max())
    if peak <= 0:
        return np.zeros_like(level)

    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(np.maximum(level / peak, 1e-9))
    presence = np.clip((db - floor_db) / (0.0 - floor_db), 0.0, 1.0)

    attack = float(np.exp(-1.0 / max(attack_ms * 0.001 * sample_rate, 1.0)))
    release = float(np.exp(-1.0 / max(release_ms * 0.001 * sample_rate, 1.0)))

    smoothed = np.empty_like(presence)
    value = 0.0
    for index, target in enumerate(presence):
        coefficient = attack if target > value else release
        value = coefficient * value + (1.0 - coefficient) * target
        smoothed[index] = value
    return smoothed


def duck_under_vocal(
    samples: np.ndarray,
    envelope: np.ndarray,
    sample_rate: int,
    depth_db: float = 3.0,
    band_hz: tuple[float, float] = VOCAL_BAND_HZ,
) -> np.ndarray:
    """Pull a stem down inside the vocal band, only while the vocal is present.

    Band-limited rather than broadband: the point is to clear space where the vocal
    actually lives. Ducking a guitar's whole spectrum makes the arrangement quieter
    without making the vocal any easier to follow, and it is far more audible as an
    effect.
    """
    audio = np.asarray(samples, dtype=np.float64)
    if depth_db <= 0 or envelope.size == 0:
        return audio

    single = audio.ndim == 1
    if single:
        audio = audio[:, None]

    length = min(audio.shape[0], envelope.size)
    gain = 1.0 - (1.0 - 10.0 ** (-abs(depth_db) / 20.0)) * envelope[:length]

    band = _band_split(audio[:length], sample_rate, band_hz)
    rest = audio[:length] - band

    out = audio.copy()
    out[:length] = rest + band * gain[:, None]
    return out[:, 0] if single else out


def _band_split(
    samples: np.ndarray, sample_rate: int, band_hz: tuple[float, float]
) -> np.ndarray:
    """The part of a signal inside a frequency band, via a zero-phase bandpass.

    Zero-phase (filtfilt) so subtracting the band from the whole leaves no phase smear
    at the crossover - the two halves have to add back to the original exactly.
    """
    from scipy.signal import butter, sosfiltfilt

    nyquist = sample_rate / 2.0
    low = max(band_hz[0] / nyquist, 1e-4)
    high = min(band_hz[1] / nyquist, 0.99)
    if low >= high:
        return np.zeros_like(samples)

    sos = butter(2, [low, high], btype="bandpass", output="sos")
    return sosfiltfilt(sos, samples, axis=0)


def should_duck(stem: StemKind) -> bool:
    return stem in COMPETES_WITH_VOCAL
