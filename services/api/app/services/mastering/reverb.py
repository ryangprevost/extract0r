"""Putting a dry stem into a space, and working out how much space it needs.

The comparison could already say a stem was drier than the reference's and had nothing to
offer about it. This is the missing half.

**Why a convolution and not a feedback network.** A Schroeder or FDN reverb is cheaper,
but its decay time falls out of the comb delays and feedback gains rather than being set
directly, so "give this vocal 1.4 seconds" becomes a tuning exercise. The whole point here
is that the decay time is *measured* from the reference, so the processor is parameterised
the same way the estimate is: build an impulse response that decays by 60 dB in exactly
the requested time, and convolve. What comes back is what was asked for, and the round
trip can be tested — apply 1.2 s, measure, get 1.2 s back.

The tail is shaped rather than raw noise, because raw noise sounds like noise:

- **High frequencies decay faster than low.** Air and soft surfaces absorb treble, so a
  real tail darkens as it fades. Without this it hisses.
- **A short pre-delay** keeps the onset of a note clear of its own reverb, which is what
  stops a wet vocal turning to mush.
- **Left and right get uncorrelated noise**, so the tail is wide even when the source is
  centred. This is the part that makes a reverb sound like a room rather than an effect.
"""

from __future__ import annotations

import numpy as np

#: Reverb times outside this are either inaudible or a special effect, not a mix decision.
MIN_SECONDS = 0.15
MAX_SECONDS = 4.0

#: Wet fraction. 1.0 would be the tail alone with none of the source.
MAX_MIX = 0.6

#: Gap between the note and the start of its tail. Long enough to keep transients clear,
#: short enough not to read as a slapback echo.
PRE_DELAY_S = 0.02

#: How much darker the tail is by the end of its decay. Treble dies first in any real
#: space, and a tail that keeps its top end sounds like hiss rather than a room.
TAIL_DAMPING_DB = 18.0

#: Damping and truncation both steepen the decay, so a response built to the requested
#: length actually falls faster than it was asked to. Measured by Schroeder integration
#: over the finished response it came out at 0.86x the nominal time, and at the same
#: 0.86 for every length from 0.4 s to 3.0 s - a constant, so it divides out exactly.
#: Without this, asking for the reference's 1.4 s would deliver 1.2 s.
DAMPING_SHORTENS_BY = 0.86


def impulse_response(
    seconds: float, sample_rate: int, seed: int = 0
) -> np.ndarray:
    """A stereo impulse response decaying by 60 dB over `seconds`.

    Built rather than sampled, so no audio from anywhere else ends up in anyone's master -
    which matters here for the same reason the reference is analysed and never sampled.
    """
    seconds = float(np.clip(seconds, MIN_SECONDS, MAX_SECONDS))
    rng = np.random.default_rng(seed)

    # Build it longer than asked, so that after damping it decays over the time asked.
    built = seconds / DAMPING_SHORTENS_BY
    length = int(built * sample_rate)
    t = np.arange(length) / sample_rate
    envelope = 10.0 ** (-3.0 * t / built)  # -60 dB at t = built

    # Independent noise per side: a correlated tail collapses to the centre and sounds
    # like a filter rather than a space.
    tail = rng.normal(0.0, 1.0, (length, 2)) * envelope[:, None]

    # Progressive darkening, done as a one-pole whose coefficient grows along the tail.
    # Cheaper than filtering in bands and it is the shape that matters, not exactness.
    damping = np.linspace(0.0, 1.0, length) ** 0.5
    alpha = damping * (1.0 - 10.0 ** (-TAIL_DAMPING_DB / 20.0))
    for channel in range(2):
        smoothed = np.empty(length)
        running = 0.0
        column = tail[:, channel]
        for index in range(length):
            a = alpha[index]
            running = a * running + (1.0 - a) * column[index]
            smoothed[index] = running
        tail[:, channel] = smoothed

    pre_delay = int(PRE_DELAY_S * sample_rate)
    if pre_delay:
        tail = np.vstack([np.zeros((pre_delay, 2)), tail])

    # Unit energy, so the wet/dry balance means the same thing at any decay time.
    energy = float(np.sqrt((tail**2).sum()))
    return tail / energy if energy > 0 else tail


def apply_reverb(
    samples: np.ndarray,
    sample_rate: int,
    seconds: float,
    mix: float,
    seed: int = 0,
) -> np.ndarray:
    """Blend a stem with its own tail. `mix` is the wet fraction, 0 leaves it untouched."""
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    mix = float(np.clip(mix, 0.0, MAX_MIX))
    if mix <= 0.0:
        return audio

    from scipy.signal import fftconvolve

    ir = impulse_response(seconds, sample_rate, seed)
    wet = np.empty_like(audio)
    for channel in range(audio.shape[1]):
        # Each side convolved with its own half of the response, keeping them decorrelated.
        tail = fftconvolve(audio[:, channel], ir[:, channel])[: audio.shape[0]]
        wet[:, channel] = tail

    # Match the wet signal's level to the dry before blending, so `mix` is a balance rather
    # than a volume: a longer tail should not also be a louder one.
    dry_rms = float(np.sqrt((audio**2).mean()))
    wet_rms = float(np.sqrt((wet**2).mean()))
    if wet_rms > 1e-12 and dry_rms > 1e-12:
        wet *= dry_rms / wet_rms

    return (1.0 - mix) * audio + mix * wet


def mix_for_gap(yours_s: float | None, theirs_s: float | None) -> tuple[float, float]:
    """How much reverb to add so a dry stem sits in a space like the reference's.

    Returns (seconds, mix). The time is the reference's own decay; the amount is scaled by
    how far apart the two already are, so a stem that is nearly there gets a little and a
    bone-dry one gets more.

    Deliberately conservative. Reverb cannot be taken off a stem that already has it, the
    estimate behind these numbers is an estimate, and too much is far more obvious than
    too little.
    """
    if not yours_s or not theirs_s or theirs_s <= yours_s * 1.15:
        return 0.0, 0.0

    seconds = float(np.clip(theirs_s, MIN_SECONDS, MAX_SECONDS))
    # A ratio of 2 (theirs twice as long) lands around a third wet; it tapers from there.
    shortfall = min((theirs_s - yours_s) / theirs_s, 1.0)
    return round(seconds, 2), round(float(np.clip(shortfall * 0.5, 0.0, MAX_MIX)), 2)
