"""How much a part moves, and how to make it move less.

Two numbers describe this, they are not interchangeable, and picking the wrong one is how
three earlier attempts in this codebase went wrong:

**Dynamic range** is the spread between the loud stretches and the quiet ones, measured
the way EBU R128 measures loudness range: short windows, the silence gated out, and the
95th percentile minus the 10th. This is what compression reduces. A verse-chorus song has
a large range; a wall-of-sound master has a small one.

**Crest** is peak minus RMS *within* the loud material - how sharp the transients are. A
hard-hit snare has a high crest at any dynamic range at all.

The trap, recorded here because it has been fallen into repeatedly: a ratio of two
percentiles of the *level* measures how typical the typical moment is - density - not
peakiness. It reads high on a steady mix and low on a swinging one, which is backwards
from what anybody means by "dynamic". Percentiles of short-term level subtracted, not
divided, and peak against RMS for transients. Those two, and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Short-term window for the level histogram. R128 uses 3 s for loudness range, which is
#: right for a whole mix and far too slow for one instrument: a hi-hat pattern is entirely
#: inside a single 3 s window, so every window reads the same and the range comes out near
#: zero. 300 ms resolves a bar's worth of playing without resolving individual hits.
WINDOW_S = 0.3

#: Anything this far under the loudest window is the part not playing. Measuring it would
#: turn "the guitar is in the choruses only" into "the guitar has enormous dynamic range",
#: which is true of the arrangement and useless as a mix note.
GATE_BELOW_DB = 40.0

#: Percentiles subtracted to get the range. The same pair R128 uses.
LOW_PERCENTILE = 10.0
HIGH_PERCENTILE = 95.0

#: A compressor cannot pull the whole range out without becoming a gate on the quiet end.
#: At most this share of the measured range may be removed in one pass.
MAX_RANGE_SHARE = 0.7

#: Ceiling on a single stem's compression, in dB of range removed.
MAX_COMPRESSION_DB = 8.0

#: Soft knee width. A hard knee on a stem is audible as the compressor switching on.
KNEE_DB = 6.0


@dataclass(slots=True)
class CompressionReport:
    """What the compressor actually did, as opposed to what it was asked for."""

    #: Range before and after, in dB.
    range_before_db: float = 0.0
    range_after_db: float = 0.0
    #: Asked for, and achieved.
    wanted_db: float = 0.0
    achieved_db: float = 0.0
    ratio: float = 1.0
    threshold_db: float = 0.0
    #: Make-up applied to keep the control a balance rather than a volume.
    makeup_db: float = 0.0
    notes: list[str] | None = None


def _mono(samples: np.ndarray) -> np.ndarray:
    audio = np.asarray(samples, dtype=np.float64)
    return audio.mean(axis=1) if audio.ndim > 1 else audio


def short_term_db(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """RMS of each `WINDOW_S` window, in dB, with the silence gated out.

    Returns an empty array when there is not enough playing to say anything, which the
    callers check for rather than reporting a range measured from two windows.
    """
    mono = _mono(samples)
    window = max(int(sample_rate * WINDOW_S), 1)
    usable = len(mono) // window * window
    if usable < window * 4:
        return np.empty(0)

    frames = mono[:usable].reshape(-1, window)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(np.maximum(rms, 1e-12))

    if not np.isfinite(db).any():
        return np.empty(0)
    return db[db > db.max() - GATE_BELOW_DB]


def dynamic_range_db(samples: np.ndarray, sample_rate: int) -> float:
    """The spread between the loud stretches and the quiet ones.

    0.0 when the material is too short or too sparse to measure, which reads the same as
    "no range" and is deliberate: a caller that cannot tell the difference should not be
    making a compression suggestion either way.
    """
    db = short_term_db(samples, sample_rate)
    if db.size < 4:
        return 0.0
    return float(
        np.percentile(db, HIGH_PERCENTILE) - np.percentile(db, LOW_PERCENTILE)
    )


def loudest_window_s(
    samples: np.ndarray, sample_rate: int, seconds: float = 12.0
) -> float:
    """Where the busiest stretch of a stem starts, in seconds.

    For auditioning. A preview that begins at 0:00 usually begins in silence or in an
    intro, and on a four-minute song the user has to scrub to find the part the comparison
    is actually about. The loudest sustained window is a good enough proxy for "the
    chorus", and it costs one pass over the short-term levels that were being computed
    anyway.

    Deliberately not the loudest single moment, which is a cymbal crash and tells you
    nothing about how the part sits.
    """
    mono = _mono(samples)
    window = max(int(sample_rate * WINDOW_S), 1)
    usable = len(mono) // window * window
    if usable < window * 4:
        return 0.0

    frames = mono[:usable].reshape(-1, window)
    energy = np.mean(frames**2, axis=1)

    span = max(int(seconds / WINDOW_S), 1)
    if span >= len(energy):
        return 0.0

    # Rolling mean over `span` frames, via a cumulative sum.
    cumulative = np.concatenate([[0.0], np.cumsum(energy)])
    rolling = (cumulative[span:] - cumulative[:-span]) / span
    return float(np.argmax(rolling) * WINDOW_S)


def crest_db(samples: np.ndarray) -> float:
    """Peak minus RMS: how far the transients stick out of the body of the sound."""
    mono = _mono(samples)
    if mono.size == 0:
        return 0.0
    peak = float(np.abs(mono).max())
    rms = float(np.sqrt(np.mean(mono**2)))
    if peak <= 1e-12 or rms <= 1e-12:
        return 0.0
    return float(20.0 * np.log10(peak / rms))


def compress(
    samples: np.ndarray,
    sample_rate: int,
    range_db: float,
    attack_ms: float = 15.0,
    release_ms: float = 180.0,
    report: CompressionReport | None = None,
) -> np.ndarray:
    """Remove roughly `range_db` of dynamic range, and give the level back.

    The dial is the *outcome*, not a threshold and a ratio. "Take 3 dB of range out of the
    guitars" is a thing somebody can want; "4:1 at -18 dB" is a thing that means something
    different on every stem it is pointed at, which is why matching one stem's compressor
    settings to another's would be meaningless even if they could be measured.

    The threshold is put at the quiet end of the playing and the ratio solved so that the
    loud end comes down by the requested amount: the floor stays where it is, the peaks
    come toward it, the difference is the range removed. Then the whole thing is
    level-matched, because otherwise every comparison of this control is really a
    comparison of loudness.
    """
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    range_db = float(np.clip(range_db, 0.0, MAX_COMPRESSION_DB))
    if range_db <= 0.0:
        return audio

    before = dynamic_range_db(audio, sample_rate)
    if before < 1.0:
        # Nothing to take out. Compressing anyway would only add its own artefacts.
        if report is not None:
            report.range_before_db = round(before, 2)
            report.range_after_db = round(before, 2)
            report.wanted_db = round(range_db, 2)
            report.notes = ["already flat - nothing to compress"]
        return audio

    wanted = min(range_db, before * MAX_RANGE_SHARE)

    db = short_term_db(audio, sample_rate)
    low = float(np.percentile(db, LOW_PERCENTILE))
    high = float(np.percentile(db, HIGH_PERCENTILE))

    # Half a knee above the quiet end rather than on it. A soft knee is centred on its
    # threshold, so a threshold sitting exactly at the floor has the compressor already
    # working when the floor arrives - measured at 1.6 dB of reduction on the quiet
    # stretches, which is the compressor pulling the whole part down instead of pulling
    # its top down. Offset by half the knee, the knee opens at the floor and nothing
    # below it is touched.
    threshold = low + KNEE_DB / 2.0
    span = max(high - threshold, 1e-6)
    # (span) * (1 - 1/ratio) = wanted
    reduction_share = float(np.clip(wanted / span, 0.0, 0.9))
    ratio = 1.0 / max(1.0 - reduction_share, 1e-3)

    envelope = _envelope(audio, sample_rate, attack_ms, release_ms)
    with np.errstate(divide="ignore"):
        envelope_db = 20.0 * np.log10(np.maximum(envelope, 1e-12))
    over = envelope_db - threshold

    def squash(share: float) -> np.ndarray:
        """Gain reduction for a given share, with a soft knee either side of threshold."""
        knee = KNEE_DB
        gain_db = np.zeros_like(over)
        inside = (over > -knee / 2) & (over <= knee / 2)
        above = over > knee / 2
        gain_db[above] = -share * over[above]
        gain_db[inside] = -share * (over[inside] + knee / 2) ** 2 / (2 * knee)
        return audio * (10.0 ** (gain_db / 20.0))[:, None]

    # Then check, and correct once. Solving the ratio in closed form gets close and not
    # closer than that: the knee removes range the straight-line solution does not account
    # for, and the envelope's percentiles are not the windowed percentiles the range is
    # measured over. Open loop, asking for 3 dB delivered 3.68. One measured correction
    # brings it inside a tenth, and it costs a second pass over an envelope that has
    # already been computed rather than a second envelope.
    out = squash(reduction_share)
    achieved = before - dynamic_range_db(out, sample_rate)
    if achieved > 0.1 and abs(achieved - wanted) > 0.1:
        corrected = float(np.clip(reduction_share * wanted / achieved, 0.0, 0.9))
        out = squash(corrected)
        reduction_share = corrected
        ratio = 1.0 / max(1.0 - reduction_share, 1e-3)

    dry_rms = float(np.sqrt(np.mean(audio**2)))
    wet_rms = float(np.sqrt(np.mean(out**2)))
    makeup = 0.0
    if wet_rms > 1e-12:
        makeup = 20.0 * np.log10(dry_rms / wet_rms)
        out *= dry_rms / wet_rms

    if report is not None:
        after = dynamic_range_db(out, sample_rate)
        report.range_before_db = round(before, 2)
        report.range_after_db = round(after, 2)
        report.wanted_db = round(range_db, 2)
        report.achieved_db = round(before - after, 2)
        report.ratio = round(ratio, 2)
        report.threshold_db = round(threshold, 2)
        report.makeup_db = round(makeup, 2)
        report.notes = [
            f"{ratio:.1f}:1 above {threshold:.1f} dB, taking {before - after:.1f} dB of range "
            f"out of {before:.1f} and giving {makeup:+.1f} dB back"
        ]
    return out


def _envelope(
    audio: np.ndarray, sample_rate: int, attack_ms: float, release_ms: float
) -> np.ndarray:
    """A one-pole follower on the stereo sum: fast down, slow up.

    Vectorising this is the obvious optimisation and it cannot be done - each sample's
    coefficient depends on the previous sample's output. `scipy.signal.lfilter` would run
    it in C if the coefficient were fixed, but a fixed coefficient means attack and
    release are the same number, which is the one thing a compressor may not do.
    """
    detector = np.abs(audio).mean(axis=1)
    attack = float(np.exp(-1.0 / (sample_rate * max(attack_ms, 0.01) / 1000.0)))
    release = float(np.exp(-1.0 / (sample_rate * max(release_ms, 0.01) / 1000.0)))

    envelope = np.empty_like(detector)
    running = 0.0
    for index, value in enumerate(detector):
        coefficient = attack if value > running else release
        running = coefficient * running + (1.0 - coefficient) * value
        envelope[index] = running
    return envelope
