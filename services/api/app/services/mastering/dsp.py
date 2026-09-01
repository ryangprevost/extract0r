"""The signal processing behind reference mastering.

Pure functions over numpy arrays: no files, no I/O, no global state, so the maths can be
tested directly. It lives here rather than in ``app/domain`` because it needs numpy and
scipy, and ADR-0002 keeps the domain layer on the standard library alone — but everything
here is side-effect free and unit tested all the same.

**No ffmpeg.** Phase 2 was originally written against ffmpeg for both filtering and
encoding, which meant mastering could not run at all on a machine that had Phase 1
working. numpy and scipy do the processing, `lameenc` does the MP3, and both were already
installed. See `encode.py`.

What "matching a reference" actually means here:

1. Take the long-term average magnitude spectrum of both tracks.
2. Smooth both across log frequency — the raw ratio of two spectra is far too spiky to
   use as a filter, and would fit noise rather than tone.
3. Divide them to get a correction curve, then **clamp it**. An unclamped curve tries to
   turn any mix into any other and produces something that sounds broken; the clamp is
   what makes this "in the direction of the reference" rather than a bad transplant.
4. Apply the curve, then match loudness, then stop the result clipping.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# 4096 at 44.1 kHz is ~93 ms: long enough to resolve the low end where tonal balance is
# decided, short enough that the average is not smeared across a whole song section.
DEFAULT_N_FFT = 4096
DEFAULT_HOP = 1024


@dataclass(frozen=True, slots=True)
class MatchSettings:
    """How aggressively to move the target towards the reference."""

    n_fft: int = DEFAULT_N_FFT
    hop: int = DEFAULT_HOP
    #: Smoothing width in octaves. Below ~1/6 the curve starts fitting individual
    #: partials of whatever note happened to be playing.
    smoothing_octaves: float = 1.0 / 3.0
    #: Boost is capped harder than cut: lifting a band the target barely contains
    #: amplifies noise and separation artefacts, while cutting one is comparatively safe.
    max_boost_db: float = 6.0
    max_cut_db: float = 12.0
    #: 0 = no correction, 1 = the full clamped curve. A dial, because "as much of the
    #: reference as possible" is rarely what a person actually wants.
    strength: float = 1.0


def to_mono(samples: np.ndarray) -> np.ndarray:
    """Average channels. Shape (n,) or (n, channels) both accepted."""
    return samples if samples.ndim == 1 else samples.mean(axis=1)


def average_spectrum(
    samples: np.ndarray, n_fft: int = DEFAULT_N_FFT, hop: int = DEFAULT_HOP
) -> np.ndarray:
    """Long-term average magnitude spectrum, one value per rFFT bin.

    Averaging over the whole track is the point: an instantaneous spectrum describes one
    chord, whereas tonal balance is a property of the mix.
    """
    mono = to_mono(np.asarray(samples, dtype=np.float64))
    if mono.size < n_fft:
        mono = np.pad(mono, (0, n_fft - mono.size))

    window = np.hanning(n_fft)
    frames = 1 + (mono.size - n_fft) // hop
    if frames <= 0:
        return np.zeros(n_fft // 2 + 1)

    total = np.zeros(n_fft // 2 + 1)
    for index in range(frames):
        start = index * hop
        total += np.abs(np.fft.rfft(mono[start : start + n_fft] * window))
    return total / frames


def smooth_log_frequency(
    spectrum: np.ndarray, sample_rate: int, octaves: float = 1.0 / 3.0
) -> np.ndarray:
    """Smooth a spectrum over a constant fraction of an octave.

    Constant-octave rather than constant-Hz because hearing is logarithmic: 100 Hz of
    smoothing is nothing at 10 kHz and destroys everything below 200 Hz.
    """
    spectrum = np.asarray(spectrum, dtype=np.float64)
    bins = spectrum.size
    freqs = np.fft.rfftfreq((bins - 1) * 2, d=1.0 / sample_rate)

    out = np.empty_like(spectrum)
    factor = 2.0 ** (octaves / 2.0)
    # A running sum makes this linear rather than quadratic in the number of bins.
    cumulative = np.concatenate([[0.0], np.cumsum(spectrum)])

    for index in range(bins):
        centre = freqs[index]
        if centre <= 0:
            out[index] = spectrum[index]
            continue
        low = np.searchsorted(freqs, centre / factor, side="left")
        high = np.searchsorted(freqs, centre * factor, side="right")
        high = max(high, low + 1)
        out[index] = (cumulative[high] - cumulative[low]) / (high - low)
    return out


def matching_curve(
    target_spectrum: np.ndarray,
    reference_spectrum: np.ndarray,
    sample_rate: int,
    settings: MatchSettings | None = None,
) -> np.ndarray:
    """Per-bin gain that moves the target's tonal balance towards the reference.

    Returned as a linear multiplier, clamped and strength-scaled. Deliberately normalised
    so the curve has no net level change — loudness is matched separately, and letting an
    EQ curve also move the level makes both harder to reason about.
    """
    settings = settings or MatchSettings()
    target = smooth_log_frequency(target_spectrum, sample_rate, settings.smoothing_octaves)
    reference = smooth_log_frequency(
        reference_spectrum, sample_rate, settings.smoothing_octaves
    )

    # Guard the division: silent bins in either track carry no tonal information.
    floor = max(float(target.max()), float(reference.max())) * 1e-6
    if floor <= 0:
        return np.ones_like(target)
    ratio = np.maximum(reference, floor) / np.maximum(target, floor)

    db = 20.0 * np.log10(ratio)

    # Centre FIRST, then clamp. The order is not cosmetic.
    #
    # Clamping first and centring after means the clamp no longer bounds anything: with a
    # much brighter reference, every band above ~500 Hz pins to the boost ceiling, the
    # median becomes that ceiling, and subtracting it flattens all of them to 0 dB while
    # pushing the low end to -(max_cut + max_boost). Observed on a real track: a curve
    # that reported -18 dB at 60 Hz against a stated -12 dB limit, and exactly 0.00 dB
    # everywhere above 500 Hz. That is not a tonal match, it is a low-end delete.
    #
    # Centring first makes the correction relative - "how does this band compare with the
    # rest of the mix" - which is what a matching EQ is actually for, and the clamp then
    # means what it says.
    db -= float(np.median(db))
    db = np.clip(db, -settings.max_cut_db, settings.max_boost_db)
    db *= float(np.clip(settings.strength, 0.0, 1.0))
    return 10.0 ** (db / 20.0)


def apply_curve(
    samples: np.ndarray,
    curve: np.ndarray,
    n_fft: int = DEFAULT_N_FFT,
    hop: int = DEFAULT_HOP,
) -> np.ndarray:
    """Filter audio by a per-bin magnitude curve, via overlap-add STFT.

    Channels are processed with the same curve so the stereo image is untouched — a
    matching EQ should change tone, not width.
    """
    audio = np.asarray(samples, dtype=np.float64)
    single = audio.ndim == 1
    if single:
        audio = audio[:, None]

    window = np.hanning(n_fft)
    # Weighted overlap-add: window going in *and* coming out.
    #
    # The synthesis window is not optional once the spectrum has been modified - without
    # it, each frame's edges land in the output discontinuously and the result buzzes.
    # It also has to be matched by the normalisation: analysis-only windowing divides by
    # the sum of windows, analysis-plus-synthesis by the sum of their squares. Getting
    # that pair wrong is silent - it just scales everything. Mixing them here made the
    # output exactly 4/3 too loud, which a reconstruction test caught.
    step = n_fft // 4
    padded = np.pad(audio, ((n_fft, n_fft), (0, 0)))
    out = np.zeros_like(padded)
    weight = np.zeros(padded.shape[0])

    for start in range(0, padded.shape[0] - n_fft, step):
        chunk = padded[start : start + n_fft] * window[:, None]
        spectrum = np.fft.rfft(chunk, axis=0) * curve[:, None]
        out[start : start + n_fft] += np.fft.irfft(spectrum, n=n_fft, axis=0) * window[:, None]
        weight[start : start + n_fft] += window**2

    weight = np.maximum(weight, 1e-9)
    out /= weight[:, None]
    result = out[n_fft : n_fft + audio.shape[0]]
    return result[:, 0] if single else result


def peak_db(samples: np.ndarray) -> float:
    peak = float(np.max(np.abs(samples))) if np.size(samples) else 0.0
    return 20.0 * np.log10(peak) if peak > 0 else -np.inf


def apply_gain_db(samples: np.ndarray, gain_db: float) -> np.ndarray:
    return np.asarray(samples, dtype=np.float64) * (10.0 ** (gain_db / 20.0))


def normalise_peak(samples: np.ndarray, ceiling_db: float = -1.0) -> np.ndarray:
    """Scale the whole signal so its loudest sample sits at the ceiling.

    Transparent, but it trades away loudness: one stray transient pulls the entire track
    down with it. Useful when nothing may be altered dynamically; `limit` is what the
    mastering chain actually uses.
    """
    audio = np.asarray(samples, dtype=np.float64)
    ceiling = 10.0 ** (ceiling_db / 20.0)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= ceiling or peak == 0:
        return audio
    return audio * (ceiling / peak)


def limit(
    samples: np.ndarray,
    sample_rate: int,
    ceiling_db: float = -1.0,
    attack_ms: float = 2.0,
    release_ms: float = 80.0,
) -> np.ndarray:
    """Hold peaks under a ceiling by riding the gain, not by scaling the whole track.

    The difference matters more than it sounds. Matching a modern master means pushing a
    mix to roughly its own peak ceiling; with a static scale, a single transient decides
    the level of the entire song, and the result lands 10 dB below the reference no matter
    what the loudness stage asked for. Riding the gain gives that back.

    A one-pole envelope: fast down so a transient is caught, slow up so the gain does not
    audibly pump between hits. Not a lookahead limiter — a few samples of a sharp attack
    can still poke through, which is why the ceiling defaults below 0 dBFS rather than at
    it.
    """
    audio = np.asarray(samples, dtype=np.float64)
    if audio.size == 0:
        return audio

    ceiling = 10.0 ** (ceiling_db / 20.0)
    mono_peak = np.abs(audio).max(axis=1) if audio.ndim > 1 else np.abs(audio)
    if float(mono_peak.max()) <= ceiling:
        return audio

    # Gain each sample would need on its own.
    with np.errstate(divide="ignore", invalid="ignore"):
        wanted = np.where(mono_peak > ceiling, ceiling / np.maximum(mono_peak, 1e-12), 1.0)

    attack = _one_pole_coefficient(attack_ms, sample_rate)
    release = _one_pole_coefficient(release_ms, sample_rate)

    smoothed = np.empty_like(wanted)
    gain = 1.0
    for index, target in enumerate(wanted):
        # Attack when the required gain drops, release when it recovers.
        coefficient = attack if target < gain else release
        gain = coefficient * gain + (1.0 - coefficient) * target
        smoothed[index] = gain

    out = audio * (smoothed[:, None] if audio.ndim > 1 else smoothed)
    # The envelope lags by design, so a sample or two can still exceed the ceiling.
    return np.clip(out, -ceiling, ceiling)


def _one_pole_coefficient(time_ms: float, sample_rate: int) -> float:
    if time_ms <= 0:
        return 0.0
    return float(np.exp(-1.0 / (max(time_ms, 0.01) * 0.001 * sample_rate)))
