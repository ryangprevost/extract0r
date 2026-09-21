"""Depth: the three things that separate a dry master from a produced one.

An earlier attempt at this put a short room across the whole mix at 8% wet, unfiltered,
and the first thing anyone heard was reverb on the drums. That was not the idea being
wrong, it was the build: the amount was several times too high and there was no filtering
at all. Done properly the wet signal is band-limited before it is blended - high-passed so
it cannot muddy the low end, low-passed so it never reaches the cymbals - and the blend is
counted in fractions of a percent.

Measured on one real mix, with the wet signal limited to 200 Hz - 10 kHz, 2% wet changed
the 10-16 kHz band by -0.17 dB. That band is where the earlier version's tail was audible,
so the filtering is not a refinement; it is what makes the technique usable at all.

Three tools, in the order they are usually reached for:

**Ambience** puts everything in one space. It adds a tail to what is already playing, so
it deepens a dense mix and does very little for a sparse one - a tail of near-silence is
still near-silence.

**Parallel compression** blends a heavily squashed copy underneath, which lifts whatever
is quiet: room, decay, the ends of notes. Level-matched before blending, so the control is
a balance rather than a volume.

**Side air** lifts the high end of the side channel only. The mid channel keeps the
groove anchored and the width comes from what was already wide, which is usually the
ambient content rather than the parts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Where the wet signal is band-limited to. Below 200 Hz a tail is mud; above 10 kHz it
#: is a wash on the cymbals, which is exactly what made the first version unusable.
WET_LOW_HZ = 200.0
WET_HIGH_HZ = 10000.0

#: Tail length. Long enough to be a room rather than a slapback, short enough not to
#: blur a fast song.
DEFAULT_AMBIENCE_S = 1.4

#: Ambience is counted in fractions of a percent. The ceiling is deliberately low: past
#: this it stops being depth and becomes an effect, which is the failure this module was
#: rebuilt to avoid.
MAX_AMBIENCE_MIX = 0.05

#: How much of the squashed copy may be blended in. Past a quarter the mix stops
#: breathing and the technique becomes ordinary over-compression.
MAX_PARALLEL_MIX = 0.25

#: Side-channel shelf. More than this and mono compatibility starts to suffer, because
#: everything added here is by definition what cancels when the channels are summed.
MAX_SIDE_AIR_DB = 4.0
SIDE_AIR_HZ = 6000.0


@dataclass
class DepthReport:
    ambience_mix: float = 0.0
    parallel_mix: float = 0.0
    side_air_db: float = 0.0
    #: What the tail added where the cymbals live. Near zero is the point.
    cymbal_change_db: float = 0.0
    notes: list[str] = field(default_factory=list)


def _band_rms(samples: np.ndarray, sample_rate: int, low: float, high: float) -> float:
    from scipy.signal import butter, sosfiltfilt

    audio = np.asarray(samples, dtype=np.float64)
    high = min(high, sample_rate / 2 * 0.99)
    if low >= high:
        return 0.0
    sos = butter(4, [low, high], btype="band", fs=sample_rate, output="sos")
    return float(np.sqrt(np.mean(sosfiltfilt(sos, audio, axis=0) ** 2)))


def add_ambience(
    samples: np.ndarray,
    sample_rate: int,
    mix: float,
    seconds: float = DEFAULT_AMBIENCE_S,
    report: DepthReport | None = None,
) -> np.ndarray:
    """Blend in a band-limited tail. `mix` is the wet fraction - hundredths, not tenths.

    The wet signal is filtered *before* blending rather than after, so the tail that
    reaches the mix has no content in the two ranges where a room does damage.
    """
    from scipy.signal import butter, fftconvolve, sosfilt

    from app.services.mastering.reverb import impulse_response

    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    mix = float(np.clip(mix, 0.0, MAX_AMBIENCE_MIX))
    if mix <= 0.0:
        return audio

    response = impulse_response(seconds, sample_rate, seed=1)
    wet = np.empty_like(audio)
    for channel in range(audio.shape[1]):
        wet[:, channel] = fftconvolve(audio[:, channel], response[:, channel])[: len(audio)]

    sos = butter(
        2,
        [WET_LOW_HZ, min(WET_HIGH_HZ, sample_rate / 2 * 0.99)],
        btype="band",
        fs=sample_rate,
        output="sos",
    )
    wet = sosfilt(sos, wet, axis=0)

    # Match the tail's level to the dry before blending, so a longer room is not also a
    # louder one and `mix` means the same thing at every setting.
    dry_rms = float(np.sqrt(np.mean(audio**2)))
    wet_rms = float(np.sqrt(np.mean(wet**2)))
    if wet_rms > 1e-12 and dry_rms > 1e-12:
        wet *= dry_rms / wet_rms

    out = (1.0 - mix) * audio + mix * wet
    if report is not None:
        report.ambience_mix = round(mix, 4)
        before = _band_rms(audio, sample_rate, 10000.0, 16000.0)
        after = _band_rms(out, sample_rate, 10000.0, 16000.0)
        report.cymbal_change_db = round(
            float(20 * np.log10((after + 1e-12) / (before + 1e-12))), 2
        )
        report.notes.append(
            f"{mix:.1%} of a {seconds:.1f}s room, filtered to "
            f"{WET_LOW_HZ:.0f}-{WET_HIGH_HZ / 1000:.0f} kHz so it cannot reach the "
            f"cymbals ({report.cymbal_change_db:+.2f} dB there)"
        )
    return out


def parallel_compress(
    samples: np.ndarray,
    sample_rate: int,
    mix: float,
    ratio: float = 8.0,
    threshold_pct: float = 35.0,
    attack_ms: float = 20.0,
    release_ms: float = 250.0,
    report: DepthReport | None = None,
) -> np.ndarray:
    """Blend a heavily compressed copy underneath, to lift what is quiet.

    Slow enough to let transients through - the squashed copy is underneath, so the
    attack the listener hears is still the dry one - and level-matched before blending so
    the control is a balance rather than a volume.
    """
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    mix = float(np.clip(mix, 0.0, MAX_PARALLEL_MIX))
    if mix <= 0.0:
        return audio

    detector = np.abs(audio).mean(axis=1)
    attack = np.exp(-1.0 / (sample_rate * attack_ms / 1000.0))
    release = np.exp(-1.0 / (sample_rate * release_ms / 1000.0))
    envelope = np.empty_like(detector)
    running = 0.0
    for index, value in enumerate(detector):
        coefficient = attack if value > running else release
        running = coefficient * running + (1 - coefficient) * value
        envelope[index] = running

    live = envelope[envelope > 1e-6]
    if live.size == 0:
        return audio
    threshold = float(np.percentile(live, threshold_pct))
    with np.errstate(divide="ignore"):
        over = np.maximum(
            20 * np.log10(np.maximum(envelope, 1e-9)) - 20 * np.log10(max(threshold, 1e-9)),
            0.0,
        )
    squashed = audio * (10 ** (-over * (1 - 1 / ratio) / 20.0))[:, None]

    squashed_rms = float(np.sqrt(np.mean(squashed**2)))
    dry_rms = float(np.sqrt(np.mean(audio**2)))
    if squashed_rms > 1e-12:
        squashed *= dry_rms / squashed_rms

    if report is not None:
        report.parallel_mix = round(mix, 3)
        report.notes.append(
            f"{mix:.0%} of a {ratio:.0f}:1 copy blended underneath, lifting the quiet "
            "detail without touching the attacks"
        )
    return (1.0 - mix) * audio + mix * squashed


def add_side_air(
    samples: np.ndarray,
    sample_rate: int,
    gain_db: float,
    hz: float = SIDE_AIR_HZ,
    report: DepthReport | None = None,
) -> np.ndarray:
    """Lift the top of the side channel only, leaving the middle where it is.

    Whatever is already wide is mostly ambience rather than parts, so this opens the room
    out without moving the things the groove depends on - which stay in the mid channel,
    untouched.
    """
    from scipy.signal import butter, sosfilt

    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1 or audio.shape[1] < 2 or not gain_db:
        return audio

    gain_db = float(np.clip(gain_db, 0.0, MAX_SIDE_AIR_DB))
    mid = (audio[:, 0] + audio[:, 1]) / 2.0
    side = (audio[:, 0] - audio[:, 1]) / 2.0

    sos = butter(2, min(hz / (sample_rate / 2.0), 0.99), btype="high", output="sos")
    side = side + sosfilt(sos, side) * (10 ** (gain_db / 20.0) - 1.0)

    if report is not None:
        report.side_air_db = round(gain_db, 2)
        report.notes.append(
            f"+{gain_db:.1f} dB above {hz / 1000:.0f} kHz on the sides only, "
            "so the middle stays anchored"
        )
    return np.stack([mid + side, mid - side], axis=1)
