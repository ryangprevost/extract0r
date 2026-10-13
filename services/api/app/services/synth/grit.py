"""Grit: drive a part into distortion, the way an electro record's synths are. Sprint 16.

Ryan, on the first club remix: *"make the synths more like bounce.mp3. i want gritty,
distorted synths."* A clean sampled or multisampled synth is the sound before the pedal; the
records he is pointing at put every synth through one.

### The circuit

- **Oversampled 2x**, because distortion makes harmonics above the original's, and at the
  base rate the ones past Nyquist fold back down as inharmonic fizz.
- **Driven into an asymmetric soft clipper** - `tanh` with its input offset, so one side
  of the wave clips sooner than the other - which adds even harmonics as well as odd: the
  warm, fat grit of an overdriven analog stage rather than the hollow buzz of a symmetric
  clip.
- **A gentle low-pass after**, to take the edge off the very top the clipper adds.
- **Level matched** to the part as it went in. Distortion makes anything louder, and louder
  always sounds "better"; matched, the control is about the sound, not the volume.

### How much - by ear, and why not measured

The first version of this chose the amount by matching the reference part's crest factor,
then its share of energy above 2 kHz. Tried on VaVaVa against MSTRKRFT's "Bounce", neither
told their synths from ours: a separated stem is several layers, leakage and attacks, and
those decide both numbers long before the distortion does - their synth stem read as *less*
squashed and *duller* than a clean pad. So the amount is a control set by ear, and the way to
get their exact sound is to sample it (`sampled.py`), which carries whatever drive their
synth already has.
"""

from __future__ import annotations

import numpy as np

#: How hard the clipper is driven at amount 1, as a gain. 1 + 40 is about +32 dB.
MAX_DRIVE = 40.0
#: The low-pass after the clipper, in Hz.
TOP_HZ = 11000.0


def drive(audio: np.ndarray, sample_rate: int, amount: float) -> np.ndarray:
    """The part with `amount` (0 to 1) of grit. 0 returns it unchanged."""
    amount = float(np.clip(amount, 0.0, 1.0))
    x = np.asarray(audio, dtype=np.float64)
    if amount <= 0.0 or x.size == 0:
        return x
    from scipy.signal import butter, resample_poly, sosfilt

    stereo = x.ndim == 2
    channels = x if stereo else x[:, None]
    gain = 1.0 + MAX_DRIVE * amount ** 1.5
    # The offset is in the input, so it moves where the wave clips rather than vanishing
    # under the gain: one side clips sooner than the other at any drive, which is what
    # makes even harmonics. The DC that leaves behind is filtered out below.
    bias = 0.1 * amount
    peak = float(np.max(np.abs(channels))) or 1.0
    sos = butter(2, TOP_HZ / (sample_rate / 2), btype="low", output="sos")
    dc = butter(1, 20.0 / (sample_rate / 2), btype="high", output="sos")
    out = np.empty_like(channels)
    for c in range(channels.shape[1]):
        up = resample_poly(channels[:, c] / peak, 2, 1)
        clipped = np.tanh(gain * (up + bias)) - np.tanh(gain * bias)
        down = resample_poly(clipped, 1, 2)[: channels.shape[0]]
        out[: down.size, c] = sosfilt(dc, sosfilt(sos, down))
        out[down.size:, c] = 0.0
    # Level matched to what went in, so grit is a sound, not a volume.
    before = float(np.sqrt(np.mean(channels ** 2))) or 1e-12
    after = float(np.sqrt(np.mean(out ** 2))) or 1e-12
    out *= before / after
    return out if stereo else out[:, 0]
