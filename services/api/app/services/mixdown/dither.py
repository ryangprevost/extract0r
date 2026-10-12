"""Turning float samples into integers without lying about the quiet parts.

Every export ends with the same step: a float64 sample between -1 and 1 becomes a 16-bit
integer. There are 65,536 integers available and infinitely many floats, so something has
to be thrown away, and *how* it is thrown away is audible in exactly one place - the quiet
parts, where the discarded amount is a large fraction of what was there.

Three ways to do it, in order of how good they sound.

**Truncation**, which is what this project did until now, simply drops the fraction. The
error it makes is not random: it depends on the signal, so a quiet sine comes out as a
stepped waveform whose steps are harmonics of the sine. That is distortion, not noise, and
the ear is far better at hearing a harmonic than a hiss of the same size. On a fade-out it
is the gritty, granular edge that appears as the tail disappears.

**Dither** adds a small random amount before rounding. This sounds like it should make
things worse and makes them better: the error stops correlating with the signal and
becomes plain noise, which the ear hears as a faint constant hiss rather than as
distortion that comes and goes with the music. TPDF - triangular probability density, made
by adding two independent uniform randoms - is the standard choice, because it also
removes the *modulation* of the noise by the signal that a single uniform random leaves
behind. It costs about 4.8 dB of noise floor and buys the removal of all signal-dependent
distortion, which is a trade everyone makes.

**Noise shaping** then moves that noise where the ear is least sensitive. The error from
each sample is fed back into the next, filtered, so the total noise power goes *up* - by
7.8 dB - while its spectrum tilts out of the midrange and into the top octave. Measured
against the transfer function in `test_dither`: 15.7 dB quieter across 1-4 kHz where the
ear is sharpest, 5.4 dB quieter across 100 Hz-8 kHz, and 11.5 dB louder above 16 kHz,
which is the price and is paid where it is least likely to be heard.

None of this applies above 16 bits. The 24-bit WAV path is left alone deliberately: its
noise floor sits near -144 dBFS, which is below the self-noise of any room, converter or
listener, and dithering it would be adding audible-in-principle noise to fix an error
nobody can hear.
"""

from __future__ import annotations

import numpy as np

#: Error-feedback coefficients, applied to the last two quantisation errors.
#:
#: This is a second-order shaper: the error is filtered by (1 - z^-1)^2, which puts a null
#: at DC and rises towards Nyquist. Modest on purpose. Aggressive shapers (the
#: nine-coefficient psychoacoustic ones) buy another handful of decibels in the midrange
#: and pile it all above 15 kHz, which is fine for a finished CD and wrong here: an
#: extract0r master is frequently re-imported, re-encoded to a lossy format, or run
#: through this tool again, and each of those treats shaped ultrasonic noise less kindly
#: than it treats a flat floor.
SHAPER = (-2.0, 1.0)

#: 16-bit full scale. Chosen over 32768 so that +1.0 and -1.0 map symmetrically and
#: neither can produce a value the format cannot hold.
FULL_SCALE_16 = 32767.0


def to_int16(
    samples: np.ndarray,
    dither: bool = True,
    noise_shaping: bool = True,
    seed: int | None = None,
) -> np.ndarray:
    """Quantise float samples in [-1, 1] to 16-bit integers.

    `dither=False` gives the old behaviour, rounded rather than truncated, for anyone who
    wants a bit-exact round trip or is about to process the result again. Dithering twice
    is not harmful but it is not free either, and a file that will be re-imported into
    this tool is better off without it.

    `seed` is for tests. Left alone, the noise is drawn fresh each time, which is correct:
    a deterministic dither applied to two takes of the same passage would add the *same*
    noise to both, which is a correlated signal rather than noise.
    """
    audio = np.asarray(samples, dtype=np.float64)
    scaled = audio * FULL_SCALE_16

    if not dither:
        # Rounded, not truncated. Truncation biases every sample towards zero by up to a
        # whole LSB and is what produced the distortion this module exists to remove;
        # there is no reading under which it was the better choice, so the undithered
        # path does not reproduce it.
        return np.clip(np.rint(scaled), -FULL_SCALE_16, FULL_SCALE_16).astype("<i2")

    rng = np.random.default_rng(seed)
    # TPDF: the sum of two independent uniforms over half an LSB each, giving a triangular
    # distribution two LSBs wide. One uniform random would decorrelate the error from the
    # signal but leave its *variance* modulated by the signal, which is audible on a fade
    # as a hiss that breathes.
    noise = rng.random(scaled.shape) - rng.random(scaled.shape)

    if not noise_shaping:
        return np.clip(np.rint(scaled + noise), -FULL_SCALE_16, FULL_SCALE_16).astype("<i2")

    return _shaped(scaled, noise)


def _shaped(scaled: np.ndarray, noise: np.ndarray) -> np.ndarray:
    """Quantise with error feedback, so the noise is tilted away from the midrange.

    Sample by sample, because each output depends on the error made by the one before it -
    that recursion is the whole mechanism and cannot be vectorised away.

    **Compiled when it can be.** This was a plain loop on the belief that it cost "a fraction
    of a second against a separation that takes minutes". Measured on a six-minute remix
    bounce (Sprint 14) it took three and a half minutes, and because it held the
    interpreter the whole time, every other request - the mixer, the audio it streams -
    waited behind it, which is what Ryan saw as the site timing out while he mixed. With
    numba (installed with the ML extras) the same loop is compiled and lets go of the
    interpreter; without it, a loop over plain floats does the same arithmetic several
    times faster than indexing numpy arrays element by element.
    """
    if scaled.ndim == 1:
        scaled = scaled[:, None]
        noise = noise[:, None]
        flatten = True
    else:
        flatten = False

    scaled = np.ascontiguousarray(scaled, dtype=np.float64)
    noise = np.ascontiguousarray(noise, dtype=np.float64)
    loop = _compiled_loop() or _feedback_loop_plain
    out = loop(scaled, noise, SHAPER[0], SHAPER[1])

    if flatten:
        out = out[:, 0]
    return np.clip(out, -FULL_SCALE_16, FULL_SCALE_16).astype("<i2")


def _feedback_loop(scaled, noise, s0, s1):
    """The error-feedback quantiser itself, written so numba can compile it.

    One error history per channel. Sharing it across channels would couple left and right
    and put a correlated - therefore centered and audible - noise in the middle.

    The feedback is *added*, not subtracted: the noise that reaches the output is the error
    filtered by `1 + s0 z^-1 + s1 z^-2`, so the feedback carries the coefficients' own signs.
    Negating it produced `1 + 2z^-1 - z^-2`, a *low*-pass on the error that piled the noise
    into the midrange and measured 3.9 dB worse than no shaping at all.

    The error fed back is measured against the input *before* the dither, so it carries the
    dither as well as the rounding error and the shaper works on both. Measuring it after
    the dither shapes only the rounding error and lets two thirds of the noise through flat
    (-1.2 dB across 100 Hz-8 kHz where the transfer function predicts -5.3). Nothing is lost
    by including it: the quantiser still sees a fresh, independent random value, because
    the feedback depends on past samples only.
    """
    frames, channels = scaled.shape
    out = np.empty((frames, channels), dtype=np.float64)
    for c in range(channels):
        h0 = 0.0
        h1 = 0.0
        for i in range(frames):
            shifted = scaled[i, c] + (s0 * h0 + s1 * h1)
            quantised = np.rint(shifted + noise[i, c])
            h1 = h0
            h0 = quantised - shifted
            out[i, c] = quantised
    return out


def _feedback_loop_plain(scaled, noise, s0, s1):
    """`_feedback_loop` without numba: the same arithmetic over Python floats, which is
    several times faster than reading and writing numpy arrays one element at a time.
    Python's `round` rounds half to even, as `np.rint` does."""
    frames, channels = scaled.shape
    out = np.empty((frames, channels), dtype=np.float64)
    for c in range(channels):
        column = scaled[:, c].tolist()
        dither = noise[:, c].tolist()
        result = [0.0] * frames
        h0 = 0.0
        h1 = 0.0
        for i in range(frames):
            shifted = column[i] + (s0 * h0 + s1 * h1)
            quantised = float(round(shifted + dither[i]))
            h1 = h0
            h0 = quantised - shifted
            result[i] = quantised
        out[:, c] = result
    return out


_COMPILED: list = []


def _compiled_loop():
    """`_feedback_loop` compiled by numba - `nogil`, so the server keeps answering while a
    long file is quantised - or None where numba is not installed (the CI image)."""
    if not _COMPILED:
        try:
            from numba import njit

            _COMPILED.append(njit(cache=True, nogil=True)(_feedback_loop))
        except Exception:  # noqa: BLE001 - no numba, or it cannot compile here: use the plain loop
            _COMPILED.append(None)
    return _COMPILED[0]


def describe(dither: bool, noise_shaping: bool) -> str:
    """One line for the export report, so the file says how it was made."""
    if not dither:
        return "16-bit, rounded, no dither"
    if not noise_shaping:
        return "16-bit with TPDF dither"
    return "16-bit with TPDF dither and noise shaping"
