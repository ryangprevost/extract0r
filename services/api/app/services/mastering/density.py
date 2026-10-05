"""How often each part plays, so that "their mix sounds less busy" becomes a number.

Measured on bass across three records: **186 ms** between notes on one, 302 on another,
441 on a third. "Their bass plays twice as often as yours" is an observation about
arrangement density that this application has never been able to make, and it costs one
onset detector run per stem.

**The interval, not the note, and that is the whole trick.** A median inter-onset
interval needs **no grid**, so none of X0R-1319's tempo trouble applies to it - and it is
robust to the error that wrecks absolute placement. `find_hits` backtracks each onset to
a local minimum of the envelope, which on a pitched stem moves it by 15-31 ms, and that
shift **cancels in the difference between consecutive onsets**. A quantity nobody has to
apologise for is rare in this epic.

**It is an observation with no dial, and the card says so** rather than implying one is
coming. There is no control in this application that makes a bass play more often, and
inventing one would be composing somebody's part for them - the same line X0R-1311 is on
the wrong side of.

## What is refused here, not deferred

**Note length, legato and staccato.** Measured legato ratios came back at exactly 1.000
on one record, which is a ceiling artefact of abutting notes rather than a measurement;
0.946 with an IQR of 0.158 on a second; and 0.757 with an **IQR of 0.592** on a third,
where the spread is wider than the entire difference between legato and staccato. Note
offsets are the least reliable quantity in transcription, which is why the field reports
F-measure and F-measure-no-offset as separate numbers.

**Note counts.** They depend on segmentation thresholds nobody has benchmarked. The
median interval does not, which is the only reason it is here and they are not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

#: Onsets closer together than this are one event seen twice, not two events. Below a
#: drummer's fastest credible double-stroke and well below anything a pitched instrument
#: does, so it removes detector chatter without removing music.
MIN_INTERVAL_S = 0.040

#: Fewest onsets worth a median. Two onsets give one interval, which is not a
#: distribution; ten give nine, which on a 28-second clip is a part that actually plays.
MIN_ONSETS = 10

#: How far apart two medians must be before the difference is worth a sentence.
#:
#: A ratio rather than a number of milliseconds, because density is multiplicative: 180
#: against 200 ms is nothing and 200 against 400 is a different arrangement. 1.3 is
#: roughly a third again as busy, which is audible as busier rather than as a detector
#: disagreeing with itself.
MEANINGFUL_RATIO = 1.3


@dataclass(slots=True)
class Density:
    """How often one part plays."""

    #: Median gap between consecutive onsets, in seconds.
    median_interval_s: float
    onsets: int
    seconds: float
    #: Onsets per second, which is the same fact the other way up and is what a reader
    #: compares without doing arithmetic.
    per_second: float

    @property
    def readable(self) -> str:
        return f"{self.median_interval_s * 1000:.0f} ms"


def measure(samples: np.ndarray, sample_rate: int) -> Density | None:
    """The median interval between onsets in one stem, or None when it barely plays.

    `backtrack=False`, matching `drums.separate._onsets` and for a related reason: the
    backtracked time is right for triggering a sample and wrong for measuring when
    something happened. Here it would mostly cancel anyway, but a quantity that does not
    need the cancellation is better than one that does.
    """
    import librosa

    audio = np.asarray(samples, dtype=np.float64)
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    seconds = len(mono) / sample_rate if sample_rate else 0.0
    if not np.any(np.abs(mono) > 1e-6):
        return None

    times = librosa.onset.onset_detect(
        y=mono, sr=sample_rate, backtrack=False, units="time"
    )
    times = np.asarray(times, dtype=np.float64)
    if len(times) < 2:
        return None

    intervals = np.diff(times)
    intervals = intervals[intervals >= MIN_INTERVAL_S]
    if len(intervals) + 1 < MIN_ONSETS:
        return None

    median = float(np.median(intervals))
    return Density(
        median_interval_s=round(median, 4),
        onsets=len(intervals) + 1,
        seconds=round(seconds, 1),
        per_second=round((len(intervals) + 1) / seconds, 2) if seconds else 0.0,
    )


def compare(mine: Density | None, theirs: Density | None, name: str, plural: bool) -> str:
    """One sentence about the two, or empty when there is nothing worth saying.

    Returns prose rather than a move because there is no dial: the caller wraps it in a
    finding with an empty `control`, the same shape `punch` already uses.
    """
    if mine is None or theirs is None:
        return ""
    ratio = mine.median_interval_s / max(theirs.median_interval_s, 1e-6)
    if 1 / MEANINGFUL_RATIO < ratio < MEANINGFUL_RATIO:
        return ""

    busier = ratio > 1.0  # yours waits longer between notes, so theirs is busier
    times = max(ratio, 1 / ratio)
    verb = "play" if plural else "plays"
    return (
        f"The reference's {name} {verb} about {times:.1f}x "
        f"{'more often' if busier else 'less often'} than yours - "
        f"{theirs.readable} between notes against your {mine.readable}, "
        f"over {theirs.onsets} and {mine.onsets} onsets. This is about how busy the two "
        f"arrangements are rather than about mixing, so there is no control for it: "
        f"nothing here can make a part play more often, and inventing one would be "
        f"writing the part for you."
    )
