"""Width: spread a part across the stereo field, mono-safe. Sprint 17.

Ryan, on the gritty remix: *"can you redo it with a punchier kick and some stereo
wideness?"* The sampled and multisampled synths render in mono, so every synth part sat in
the middle, on top of the vocal and the kick.

### Mid/side, so mono is untouched

The part's mono sum stays the middle. A **side** signal is made from two copies of it
through short delays (8 and 11 ms) that drift slowly (0.31 and 0.37 Hz, 1 ms deep) - a
chorus, the way a stereo synth patch spreads one oscillator - and their difference is added
to the left and taken from the right. Summed to mono, the side cancels exactly: a club's mono
system, or a phone, hears the part as it was, never the comb-filtered smear a plain Haas
delay leaves.

The side is **high-passed at 150 Hz**: low end stays in the middle, where a club system's
subs are and where the kick and bass need it.
"""

from __future__ import annotations

import numpy as np

#: The two drifting delays, in seconds, their drift rates in Hz, and how far they drift.
DELAYS_S = (0.008, 0.011)
RATES_HZ = (0.31, 0.37)
DEPTH_S = 0.001
#: Below this the side is removed - the low end stays centered.
SIDE_FROM_HZ = 150.0
#: At amount 1 the side is this loud against the middle.
MAX_SIDE = 1.0


def _drifting_delay(x: np.ndarray, sample_rate: int, base_s: float, rate_hz: float,
                    phase: float) -> np.ndarray:
    n = np.arange(x.size, dtype=np.float64)
    delay = (base_s + DEPTH_S * np.sin(2 * np.pi * rate_hz * n / sample_rate + phase))
    return np.interp(n - delay * sample_rate, n, x, left=0.0)


def widen(audio: np.ndarray, sample_rate: int, amount: float) -> np.ndarray:
    """The part, stereo, `amount` (0 to 1) wide. 0 returns it unchanged. Its mono sum is the
    part's own mono sum whatever the amount."""
    amount = float(np.clip(amount, 0.0, 1.0))
    x = np.asarray(audio, dtype=np.float64)
    if amount <= 0.0 or x.size == 0:
        return x
    from scipy.signal import butter, sosfilt

    stereo = x if x.ndim == 2 else np.stack([x, x], axis=1)
    mid = stereo.mean(axis=1)
    a = _drifting_delay(mid, sample_rate, DELAYS_S[0], RATES_HZ[0], 0.0)
    b = _drifting_delay(mid, sample_rate, DELAYS_S[1], RATES_HZ[1], np.pi / 2)
    hp = butter(2, SIDE_FROM_HZ / (sample_rate / 2), btype="high", output="sos")
    side = sosfilt(hp, (a - b) * 0.5) * (MAX_SIDE * amount)
    # The part's own stereo, if it had any, is kept; the new side is added on top.
    left = stereo[:, 0] + side
    right = stereo[:, 1] - side
    return np.stack([left, right], axis=1)
