"""A tempo that is allowed to change during the song.

X0R-1319, criteria 1 and 2. Everything that reads a grid in this application reads one
number for the whole clip, and a live drummer does not play one number.

### What it achieves, measured

Kick and snare onsets from real separated drum stems, against their nearest sixteenth.
"Before" is the single global tempo this project shipped with; "after" is this map. The
programmed control recorded 5.7 ms, which is the order of magnitude criterion 2 asks for:

| | tempo | before | after | drift found |
|---|---:|---:|---:|---:|
| a live source | 166.71 | 23.2 ms | **6.4 ms** | 6.98 BPM |
| another source | 129.20 | 34.8 ms | **5.2 ms** | 2.91 BPM |
| its reference | 129.20 | 23.2 ms | 15.9 ms | 8.30 BPM |
| the other reference | 129.20 | 29.0 ms | 27.1 ms | 18.52 BPM |

**Two of the four reach it; the other two are the honest limit of this approach.** A
sixteenth at 129 BPM is 116 ms, so half a step is 58 ms and a *random* set of times would
sit a median of 29 ms from the grid. The bottom row starts at 29.0 ms - its global tempo was
no better than chance, and the row above it is close behind. This map follows drift around a
roughly correct tempo; **it cannot rescue a tempo that is wrong**, and the rows where it
barely moves are the rows where the grid was never locked in the first place. Those are
criteria 3 and 5 - reporting no confidence, and abstaining downstream - not this one.

### Whether a grid is worth computing against at all

That table is also where criterion 5 came from. A time with no relationship to the grid sits
a median of a quarter-step away, so at 129 BPM **chance is 29 ms** - and the bottom two rows
start at 29.0 and 23.2. Their tempo explained nothing, and every figure computed against them
was noise with units. `TempoMap.lock` is that comparison, one meaning exact and zero meaning
no better than chance:

| | before | after | chance | lock | locked |
|---|---:|---:|---:|---:|---|
| a live source | 23.2 ms | 6.4 ms | 22.2 ms | **0.71** | yes |
| its reference | 29.0 ms | 27.1 ms | 27.8 ms | **0.03** | **no** |

`lock` **does not resolve the octave** and must not be read as if it does: every hit on a
100 BPM grid is also on a 200 BPM grid, so a doubled reading scores at least as well as the
truth. That is criterion 3, this card proved no onset-only measure can settle it, and there
is a test asserting the limitation rather than hiding it.

A note on reproducing any of this: two of the four tracks measured above were **deleted by
the retention sweep between two runs minutes apart** - 24 hours by design, working correctly.
The figures survive because they are written here. A committed synthetic pair, programmed and
drifting, is what would make them re-runnable, and that is criterion 6's remaining gap.

### Two notes for whoever measures this next

**Onset density.** The first run of that table found 1721 onsets in a 28-second clip, 61 a
second, which no drummer plays. Default onset detection with no `delta` or `wait` finds
texture, and a residual computed against it improved beautifully and meant nothing. The
anchors above are spaced at least 46 ms apart.

**Onset *resolution*, which is subtler and nearly got through.** Onset times come back exactly
frame-aligned, so the analysis frame is a hard floor under any figure in this module. Measured
against known hit times: 19.19 ms at hop 512, 9.46 at 256, 5.43 at 128, 3.78 at 64. The table
above was first measured at hop 512, where the frame is 11.6 ms at 44.1 kHz - and it reported
"after" figures of 6.4 and 5.2 ms, *below the detector's own resolution*, which should have
been impossible. Re-measured at hop 128 the figures are **6.2 and 27.5 ms**, so they were
sound and the suspicion was unfounded; but a synthetic fixture built at hop 512 and 22 kHz had
a 23.22 ms frame and reported a residual of *exactly* 23.22 for both a steady and a drifting
record. A frame larger than the microtiming cannot measure it, and nothing warned about that.

### The control came out the opposite way round

The card assumed a programmed record is on its grid and has nothing to recover. It is not. On
a synthesised 129.2 BPM pattern the shipped global grid leaves **17.4 ms**, and this map takes
it to **7.1** - because `librosa.feature.tempo` returned 129.10, and a tenth of a BPM
accumulates phase across sixteen bars. The grid is wrong on the easiest possible input, which
is a better argument for this module than either live record was.

### What this does, and what it refuses to do

It walks the clip beat by beat, and at each beat the drum hits near it say "you are a little
early" or "a little late". A fraction of that is fed back into where the next beat lands and
into how fast the grid is running - a phase-locked loop, the same shape a tape machine used
to chase timecode with. Two limits matter more than the fit itself:

* **`MAX_TEMPO_DRIFT` caps how far the local tempo may stray from the global one**, not how
  far a beat may move. The first version capped displacement from the steady grid, and that
  is the wrong guard: drift *accumulates*, so a record that speeds up for thirty seconds
  ends up arbitrarily far from where a steady tempo would have put it while never once
  playing an unreasonable tempo. Measured, that cap pinned the map at 119-120 BPM across a
  100-to-150 BPM ramp and recovered only a fifth of the error. Capping the tempo instead
  lets the grid follow real drift however far it travels, and still refuses to believe a
  drummer changed speed by half.
* **The gains are well under one**, so each beat is nudged toward its evidence rather than
  snapped onto it. Without that, a map drives the residual to zero by landing a beat on
  every hit - which is not a tempo map, it is a list of onsets with the word "beat" written
  on it, and every timing figure downstream would read zero by construction.

So the residual it leaves is **meant** to be non-zero. Microtiming of 5-50 ms is the thing a
groove card exists to report; a map that ate it would make this application worse at exactly
its own job while appearing to improve. There is a test that a swung record comes out still
swung.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: How far the local tempo may stray from the global estimate, as a fraction. This is the
#: guard that keeps the result a tempo map rather than a transcription of the onsets, and it
#: replaced a cap on how far a *beat* could move - see the module docstring for why that was
#: the wrong quantity to limit. Eight per cent is about 10 BPM at 129, which is more drift
#: than any take that still counts as one tempo.
MAX_TEMPO_DRIFT = 0.08

#: How much of each beat's measured error is fed back into where the next beat lands, and
#: into how fast the grid is running. Both well under one, which is what makes this track
#: the tempo instead of chasing individual hits: a lone shoved snare moves the grid by a
#: third of its own lateness for one beat and is then outvoted by its neighbours.
PHASE_GAIN = 0.30
TEMPO_GAIN = 0.10

#: A grid whose hits sit this fraction of the random-chance distance away, or further, is
#: not locked. See `TempoMap.lock` for where the chance figure comes from and why this is a
#: measure of the grid rather than of the playing. 0.35 is set from measurement: real stems
#: score 0.72-0.82 once mapped, and the two whose global tempo was no better than chance
#: score 0.00 - there is nothing near the threshold to argue about.
LOCK_FLOOR = 0.35

#: Below this many anchors there is nothing to fit and the global grid stands. Four hits is
#: not a tempo, and fitting one anyway is how a quiet intro gets a grid built out of noise.
MIN_ANCHORS = 12


@dataclass(frozen=True, slots=True)
class TempoMap:
    """Beat times for one clip, and what fitting them achieved.

    `beats` is the whole of the map: every downstream user wants "where is the grid at time
    t", and a list of beat times answers that without anybody having to integrate a tempo
    curve. The BPM figures are for display.
    """

    beats: np.ndarray
    #: The tempo the loop tracked at each beat, for anything that wants to show the shape of
    #: the drift. **Not** `60 / diff(beats)`: the gap between two beats also contains that
    #: beat's phase correction, so spacing can read outside the clamp even though the tempo
    #: never left it. Measured, the difference was 25 BPM of apparent drift against a clamp
    #: that only permits 21 - a figure that contradicted the guarantee in the docstring.
    bpm: np.ndarray
    #: Median distance of an anchor from its nearest sixteenth, before and after, in ms.
    #: Reported rather than asserted - criterion 2 asks for the improvement to be visible.
    residual_before_ms: float
    residual_after_ms: float
    #: False when the map is the steady grid unchanged, because there was too little to fit
    #: or because fitting made the figure worse.
    fitted: bool
    #: Subdivision the residuals were measured against, needed to say what distance chance
    #: would have produced.
    division: int = 4

    @property
    def chance_residual_ms(self) -> float:
        """How far from the grid a *random* set of times would sit.

        A time with no relationship to the grid lands uniformly within a step, so its
        distance to the nearest grid point is uniform on half a step and its median is a
        **quarter of a step**. At 129 BPM a sixteenth is 116 ms, so chance is 29 ms.
        """
        if self.beats.size < 2:
            return 0.0
        step = float(np.mean(np.diff(self.beats))) / self.division
        return step * 1000.0 / 4.0

    @property
    def lock(self) -> float:
        """How much of the playing this grid actually explains, 0 to 1.

        Criterion 5: *a clip the grid cannot lock is said so plainly*. One measured against
        chance, so 1.0 is hits exactly on the grid and 0.0 is a grid no better than picking
        times at random. This is what made the need visible in the first place - two of the
        four real stems measured for criterion 2 started at **exactly** the chance figure,
        meaning the tempo they were handed explained nothing, and every timing figure
        computed against them was noise with units.

        **Only ever compare this between two maps at the same tempo hypothesis.** A denser
        lattice fits everything better, so a faster grid scores higher whether or not it is
        right - every hit on a 100 BPM grid is also on a 200 BPM grid, and the doubled reading
        scores a *higher* lock than the truth. Normalising by chance removes the units but not
        this. Measured on one real reference: the same drums scored **0.02 at 129.2 BPM and
        0.84 at 193.8**, which are two estimators disagreeing by exactly 3:2 and not evidence
        for either. Reading that as "193.8 is right" is the one way to misuse this number.

        So it answers *is this grid worth computing against*, and never *which grid is right*.
        The second is criterion 3, which this card proved no onset-only measure can settle, and
        there are tests asserting both halves of the limitation rather than hiding them.
        """
        chance = self.chance_residual_ms
        if chance <= 0:
            return 0.0
        return float(np.clip(1.0 - self.residual_after_ms / chance, 0.0, 1.0))

    @property
    def locked(self) -> bool:
        """Whether anything downstream should compute a timing figure against this grid."""
        return self.lock >= LOCK_FLOOR

    @property
    def improvement_ms(self) -> float:
        return round(self.residual_before_ms - self.residual_after_ms, 2)

    @property
    def mean_bpm(self) -> float:
        return float(np.mean(self.bpm)) if self.bpm.size else 0.0

    @property
    def drift_bpm(self) -> float:
        """How much the tempo moves across the clip, slowest local reading to fastest."""
        return float(np.max(self.bpm) - np.min(self.bpm)) if self.bpm.size else 0.0

    def step_at(self, time_s: float, division: int = 4) -> float:
        """The length of one subdivision at this point in the clip."""
        if self.beats.size < 2:
            return 0.5 / division
        index = int(np.clip(np.searchsorted(self.beats, time_s) - 1, 0, self.beats.size - 2))
        return float(self.beats[index + 1] - self.beats[index]) / division

    def nearest(self, time_s: float, division: int = 4) -> float:
        """The subdivision closest to `time_s`, on this map rather than on a steady grid."""
        if self.beats.size < 2:
            return time_s
        grid = subdivisions(self.beats, division)
        return float(grid[int(np.argmin(np.abs(grid - time_s)))])


def subdivisions(beats: np.ndarray, division: int = 4) -> np.ndarray:
    """Every sixteenth (or other division) implied by a sequence of beat times."""
    beats = np.asarray(beats, dtype=float)
    if beats.size < 2:
        return beats
    inner = beats[:-1, None] + np.diff(beats)[:, None] * (np.arange(division) / division)
    return np.append(inner.ravel(), beats[-1])


def residual_ms(anchors, grid) -> float:
    """Median distance from each anchor to its nearest grid point, in milliseconds."""
    anchors, grid = np.asarray(anchors, dtype=float), np.asarray(grid, dtype=float)
    if anchors.size == 0 or grid.size < 2:
        return 0.0
    index = np.clip(np.searchsorted(grid, anchors), 1, grid.size - 1)
    left, right = grid[index - 1], grid[index]
    nearest = np.where(anchors - left <= right - anchors, left, right)
    return float(np.median(np.abs(anchors - nearest)) * 1000.0)


def _track(
    anchors: np.ndarray,
    period0: float,
    first_beat_s: float,
    duration_s: float,
    division: int,
) -> tuple[np.ndarray, np.ndarray]:
    """One forward pass of the loop: walk the clip, nudging the grid toward the hits.

    Each anchor is evidence about its nearest **subdivision**, not its nearest beat. An
    earlier version measured the offset to the nearest beat and accepted anything within
    half a beat, which makes an ordinary snare on 2-and read as a beat half a beat late and
    drags the whole grid after it.
    """
    low_period = period0 * (1.0 - MAX_TEMPO_DRIFT)
    high_period = period0 * (1.0 + MAX_TEMPO_DRIFT)
    ceiling = int(duration_s / low_period) + 4

    period, pos = period0, first_beat_s
    beats: list[float] = []
    periods: list[float] = []
    while pos < duration_s and len(beats) < ceiling:
        beats.append(pos)
        periods.append(period)
        step = period / division
        near = anchors[
            int(np.searchsorted(anchors, pos - step / 2)) : int(
                np.searchsorted(anchors, pos + period - step / 2)
            )
        ]
        offset = 0.0
        if near.size:
            ticks = np.round((near - pos) / step)
            offset = float(np.mean(near - (pos + ticks * step)))
        # Feed a fraction of the error back into the phase and into the rate. The clamp is
        # what stops a long stretch of one-sided evidence - a swung groove, say - from
        # walking the tempo somewhere nobody played.
        pos += PHASE_GAIN * offset
        period = float(np.clip(period + TEMPO_GAIN * offset, low_period, high_period))
        pos += period
    return np.asarray(beats, dtype=float), np.asarray(periods, dtype=float)


def fit(
    anchors,
    tempo_bpm: float,
    first_beat_s: float,
    duration_s: float,
    division: int = 4,
) -> TempoMap:
    """Bend a steady grid to follow the drummer, within limits.

    `anchors` are drum hit times - kick and snare, by preference, because they are what a
    bar is counted on. The steady grid from `tempo_bpm` and `first_beat_s` is the starting
    point and the thing the result is measured against.
    """
    anchors = np.sort(np.asarray(list(anchors), dtype=float))
    if tempo_bpm <= 0 or duration_s <= 0:
        return TempoMap(np.array([]), np.array([]), 0.0, 0.0, False, division)

    period = 60.0 / tempo_bpm
    count = max(2, int((duration_s - first_beat_s) / period) + 1)
    steady = first_beat_s + np.arange(count) * period
    before = round(residual_ms(anchors, subdivisions(steady, division)), 2)

    def unfitted() -> TempoMap:
        flat = np.full(max(count - 1, 1), tempo_bpm)
        return TempoMap(steady, flat, before, before, False, division)

    if anchors.size < MIN_ANCHORS:
        return unfitted()

    beats, periods = _track(anchors, period, first_beat_s, duration_s, division)
    # A second pass from the tempo the first one settled on. The loop needs a few beats to
    # lock, and those beats are at the start of the song where nobody wants a worse grid;
    # starting from the converged rate costs one more cheap pass and removes most of it.
    if beats.size >= 3:
        again, again_periods = _track(
            anchors, float(np.mean(periods)), first_beat_s, duration_s, division
        )
        if again.size >= 3 and residual_ms(anchors, subdivisions(again, division)) < residual_ms(
            anchors, subdivisions(beats, division)
        ):
            beats, periods = again, again_periods

    if beats.size < 3:
        return unfitted()

    after = round(residual_ms(anchors, subdivisions(beats, division)), 2)
    # A fit that made the figure worse is not applied. The clamps and the gains can each
    # hold a beat away from its own evidence, so this is checked rather than trusted.
    if after > before:
        return unfitted()

    return TempoMap(beats, 60.0 / periods, before, after, True, division)
