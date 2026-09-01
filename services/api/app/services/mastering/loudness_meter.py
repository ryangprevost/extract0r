"""Loudness measurement, to EBU R128 where possible.

LUFS rather than RMS or peak, because that is what "as loud as the reference" actually
means to a listener and to every streaming platform. `pyloudnorm` implements the ITU-R
BS.1770 K-weighting; when it is absent this falls back to RMS and says so, because a
number labelled LUFS that is really RMS is worse than no number.
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

# Long enough for BS.1770's 400 ms gating blocks to mean anything.
MIN_SECONDS_FOR_LUFS = 0.5


def loudness_backend() -> str:
    try:
        import pyloudnorm  # noqa: F401
    except ImportError:
        return "rms"
    return "bs1770"


def integrated_loudness(samples: np.ndarray, sample_rate: int) -> tuple[float, str]:
    """Return (loudness, backend). Loudness is LUFS for bs1770, dBFS RMS otherwise."""
    audio = np.asarray(samples, dtype=np.float64)
    if audio.size == 0:
        return -np.inf, "empty"

    if audio.ndim == 1:
        audio = audio[:, None]

    duration = audio.shape[0] / sample_rate
    if duration >= MIN_SECONDS_FOR_LUFS:
        try:
            import pyloudnorm

            meter = pyloudnorm.Meter(sample_rate)
            value = float(meter.integrated_loudness(audio))
            # Digital silence measures as -inf, which is correct but unusable downstream.
            if np.isfinite(value):
                return value, "bs1770"
        except ImportError:
            pass
        except Exception:
            log.debug("BS.1770 metering failed; falling back to RMS", exc_info=True)

    mono = audio.mean(axis=1)
    rms = float(np.sqrt(np.mean(mono**2)))
    return (20.0 * np.log10(rms) if rms > 0 else -np.inf), "rms"


def gain_to_match(
    target: np.ndarray, reference: np.ndarray, sample_rate: int, max_gain_db: float = 24.0
) -> tuple[float, dict]:
    """How much gain moves ``target`` to the reference's loudness, and the measurements.

    Clamped: a huge correction means the two tracks are not comparable — a quiet demo
    against a mastered single — and applying it wholesale would only wreck the demo.
    """
    target_loudness, backend = integrated_loudness(target, sample_rate)
    reference_loudness, _ = integrated_loudness(reference, sample_rate)

    if not (np.isfinite(target_loudness) and np.isfinite(reference_loudness)):
        return 0.0, {
            "target": target_loudness,
            "reference": reference_loudness,
            "backend": backend,
            "clamped": False,
        }

    wanted = reference_loudness - target_loudness
    applied = float(np.clip(wanted, -max_gain_db, max_gain_db))
    return applied, {
        "target": round(target_loudness, 2),
        "reference": round(reference_loudness, 2),
        "backend": backend,
        "wanted_db": round(wanted, 2),
        # bool(), not a numpy scalar: this crosses into JSON and into assertions.
        "clamped": bool(abs(wanted - applied) > 0.01),
    }
