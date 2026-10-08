"""What a record's rhythm and instrumentation actually measure as — Experiment 1.

Written for the stage-1 question in [PR0DUCER.md](../../../../../docs/proposals/PR0DUCER.md):
can a reference be *described* well enough that nobody needs a genre label? A label is a
guess at a marketing category; everything here is a count, a ratio or a dB figure taken
from one file, and every one of them can be disagreed with.

**Every figure carries a confidence, and a confidence of zero is a refusal.** That is not
decoration. `estimate_key` already returns ``confidence=0.0`` when the chroma is empty and
`detect_beats_per_bar` returns 4/4 at zero confidence when there is no accent to read, and
both of those exist because X0R-407's first version reported 0.99 on wrong answers. A swing
ratio taken from eleven hi-hat hits is the same failure wearing a different hat, so
:class:`Figure` makes "I could not measure this" a representable value rather than
something a caller has to infer from a suspiciously round number.

**One tolerance rule for everything.** A hit belongs to whichever sixteenth-note step of
the grid it is nearest, full stop. The histogram, the beat coverage counts and the timing
deviation all use that single assignment. An earlier sketch had a separate tolerance per
question — ±15% of a beat for coverage, nearest-step for the histogram — and the two
disagreed about the same hit, which made "kick on 61 of 64 beats" and the histogram
irreconcilable on the same clip.

**Nothing here names a genre, and nothing here should learn to.** See section 3 of the
proposal.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.domain.notes import StemKind
from app.domain.timing import TimingEstimate, choose_tempo

log = logging.getLogger(__name__)

#: Sixteenths. Everything in the brief — four-on-the-floor, offbeat hats, swung eighths —
#: resolves at this subdivision, and a finer grid would only make the nearest-step
#: assignment noisier without answering a question anyone asked.
STEPS_PER_BEAT = 4

#: Below this tempo score the grid is not worth placing anything against, so every figure
#: derived from it abstains rather than inheriting a bad downbeat.
#:
#: A judgement made here rather than inherited: `domain.timing` has no such constant,
#: because `choose_tempo` always returns its best candidate and leaves the caller to
#: decide whether to believe it. 0.35 is where an F-measure stops meaning "this grid
#: explains the onsets" and starts meaning "some onsets happen to land on it".
MIN_GRID_CONFIDENCE = 0.35

#: Below this, `beats_per_bar` is an assumption rather than a reading.
#:
#: `detect_beats_per_bar` reports zero when there is no accent to read, which X0R-407 added
#: precisely so that a guess would not look like a measurement - so anything above zero is
#: *some* evidence. This sits low because the figure is a ratio of mean onset strength on
#: candidate downbeats against the other beats, and a real backbeat does not have to be
#: dramatic to be real.
MIN_METRE_CONFIDENCE = 0.15

#: Minimum hits before a timing *distribution* means anything. Twenty-four is two bars of
#: steady eighths; below it the standard deviation is dominated by which hits the detector
#: happened to find.
MIN_HITS_FOR_TIMING = 24

#: Minimum off-beat events before a swing ratio is a ratio rather than an anecdote.
MIN_OFFBEATS_FOR_SWING = 12

#: Minimum hits before "x% of them are on the offbeat" is worth a percentage sign.
MIN_HITS_FOR_SHARE = 12

#: `drums.detect.find_hits` runs an STFT at hop 256. At 44.1 kHz that is 5.8 ms, so an
#: onset time is quantised to that grid and a set of perfectly placed hits still measures
#: a standard deviation of hop/sqrt(12) ≈ 1.7 ms. **This is a floor, not a measurement**:
#: a drum machine lands inside it, so "programmed" cannot be read as a number below it,
#: only as "at or under the resolution".
ONSET_HOP = 256


def _resolution_ms(sample_rate: int, hop: int = ONSET_HOP) -> float:
    """Standard deviation a set of *perfectly* placed hits still measures, from the
    detector's frame quantisation alone."""
    return 1000.0 * hop / sample_rate / math.sqrt(12.0)


#: How much spread `find_hits`' timestamps add on their own, measured rather than derived.
#:
#: Experiment 1 took the *same* kick events on the *same* grid and re-placed each one at
#: the steepest rise of the low-passed waveform, which is sample-accurate. One clip went
#: 7.67 → 6.83 ms; the other went 8.48 → 4.29 ms. So the detector contributes something
#: between 1 and 7 ms, it is not a constant, and — the part that matters — **it is large
#: enough to reorder two tracks**: by `find_hits` the first clip was the tighter of the
#: two, and sample-accurately it was the looser. A programmed/played verdict read off
#: figures this size is a coin toss, so anything under twice this says so.
#:
#: The frame quantisation above accounts for only 1.7 ms of it. The rest is `backtrack`
#: walking each onset back to a local minimum by a variable amount, plus whatever
#: separation and MP3 did to the attack.
DETECTOR_JITTER_MS = 7.0

#: Where a sidechain's gain reduction is deepest, relative to the kick.
DUCK_DIP_MS = (5.0, 90.0)
#: The bass has to already be sounding before the kick, or a "dip" is just a rest.
DUCK_PRE_MS = (-170.0, -30.0)
#: …and it has to come back, or the dip is the end of a note rather than a duck.
DUCK_RECOVERY_MS = (120.0, 280.0)
#: How far below its own loud moments the bass may sit and still count as playing.
BASS_ACTIVE_BELOW_PEAK_DB = 20.0
#: Fewer qualifying kicks than this and the duck figure abstains.
MIN_KICKS_FOR_DUCK = 8


@dataclass(frozen=True, slots=True)
class Figure:
    """One measured number, or an honest refusal to give one.

    ``confidence`` of 0.0 with ``value`` of None is the refusal. It is a separate field
    from the value rather than a sentinel in it, because 0.0 is a perfectly good swing
    deviation and -30 is a perfectly good relative level.
    """

    value: float | None
    confidence: float
    unit: str = ""
    #: What the number was computed from — "43 hats over 15.1 bars". Shown, not logged:
    #: the sample size is the reader's only way to disagree with the figure.
    basis: str = ""
    #: Why it is not trusted, when it is not.
    caveat: str = ""

    @property
    def measured(self) -> bool:
        return self.value is not None and self.confidence > 0.0

    @classmethod
    def unmeasured(cls, why: str, basis: str = "") -> Figure:
        return cls(value=None, confidence=0.0, basis=basis, caveat=why)

    def render(self, places: int = 2) -> str:
        if not self.measured:
            return f"not measured ({self.caveat})"
        return f"{self.value:.{places}f}{self.unit}"


@dataclass(frozen=True, slots=True)
class BeatGrid:
    """The sixteenth-note lattice every rhythmic figure is read against."""

    tempo_bpm: float
    beats_per_bar: int
    first_beat_s: float
    confidence: float
    duration_s: float
    #: How well `beats_per_bar` is supported. Zero means 4/4 was assumed because nothing
    #: in the audio said otherwise - a different claim from 4/4 measured, and the one that
    #: decides whether a histogram indexed by it means anything. X0R-1319 criterion 4.
    metre_confidence: float = 0.0

    @classmethod
    def from_timing(cls, timing: TimingEstimate, duration_s: float) -> BeatGrid:
        return cls(
            tempo_bpm=timing.tempo_bpm,
            beats_per_bar=timing.beats_per_bar,
            first_beat_s=timing.first_beat_s,
            confidence=timing.confidence,
            duration_s=duration_s,
            metre_confidence=getattr(timing, "metre_confidence", 0.0),
        )

    @property
    def usable(self) -> bool:
        return self.tempo_bpm > 0 and self.confidence >= MIN_GRID_CONFIDENCE

    @property
    def metre_resolved(self) -> bool:
        """Whether the bar length was read from the audio or assumed.

        Separate from `usable` on purpose: a tempo can be solid while the metre is a
        guess, and the two gate different things. A timing figure needs the beat; a
        histogram needs the *bar*, because that is what it is indexed by.
        """
        return self.metre_confidence >= MIN_METRE_CONFIDENCE

    @property
    def seconds_per_beat(self) -> float:
        return 60.0 / self.tempo_bpm if self.tempo_bpm > 0 else 0.5

    @property
    def steps_per_bar(self) -> int:
        return self.beats_per_bar * STEPS_PER_BEAT

    @property
    def step_s(self) -> float:
        return self.seconds_per_beat / STEPS_PER_BEAT

    @property
    def beats(self) -> int:
        """Whole beats the clip covers, counting from the first detected downbeat."""
        span = max(0.0, self.duration_s - self.first_beat_s)
        return int(span / self.seconds_per_beat) if self.seconds_per_beat > 0 else 0

    @property
    def bars(self) -> float:
        return self.beats / self.beats_per_bar if self.beats_per_bar else 0.0

    def step_of(self, time_s: float) -> tuple[int, float]:
        """(absolute step index, signed seconds the hit sits off that step)."""
        offset = time_s - self.first_beat_s
        index = int(round(offset / self.step_s))
        return index, offset - index * self.step_s

    def phase_of(self, time_s: float) -> float:
        """Where in its beat a hit falls, 0.0 on the beat, 0.5 exactly between two."""
        offset = (time_s - self.first_beat_s) % self.seconds_per_beat
        return offset / self.seconds_per_beat


def grid_from_drums(
    anchors: list[float], timing: TimingEstimate, duration_s: float
) -> BeatGrid:
    """Re-resolve the tempo octave against the drum hits, then fit the grid to them.

    `choose_tempo` is already the right tool and it is already correct; it was simply
    handed the wrong evidence. Run on the **whole mix's** onsets it saw a four-on-the-floor
    house record, found that a 64.6 BPM grid explained the onsets about as well as a
    129.2 BPM one — synths, vocal and hats fill the intervening beats either way — and
    applied its documented tie-break, which prefers the slower reading. Half time is the
    better answer for a tab, and it is a catastrophic answer for a rhythmic fingerprint:
    at 64.6 BPM the kick histogram of a record with a kick on literally every beat came
    back flat, because the kick period was 2.02 steps of the halved grid.

    Run on the **kicks and snares alone** the same function gets it right, and for the
    reason `score_tempo` was built around: the halved grid has no drum on half of its
    beats, so recall punishes it. 0.94 against 0.67 on the clip above.

    So the fix is not new maths, it is feeding the existing maths the drums. Which is
    only possible here, because `analysis.timing` runs before separation.
    """
    if not anchors:
        return BeatGrid.from_timing(timing, duration_s)

    chosen = choose_tempo(anchors, timing.tempo_bpm)
    grid = BeatGrid(
        tempo_bpm=chosen.bpm,
        beats_per_bar=timing.beats_per_bar,
        first_beat_s=chosen.offset_s,
        # The drum-anchored F-measure, not the mix-anchored one: this is the confidence
        # in the grid actually being used, and it is the stricter of the two.
        confidence=round(min(chosen.score, 1.0), 3),
        duration_s=duration_s,
    )
    return refine_grid(anchors, grid)


def refine_grid(times: list[float], grid: BeatGrid, rounds: int = 4) -> BeatGrid:
    """Re-fit tempo and downbeat to the drum hits by least squares. **Required.**

    This is not a refinement in the cosmetic sense, it is the difference between a
    fingerprint and noise, and Experiment 1 found that out the hard way.

    `choose_tempo` resolves the tempo *octave*, which is the problem it was written for,
    but it inherits librosa's precision — and it searches only the octave multiples of
    librosa's reading, so 129.2 BPM on a track that is actually 128.90 stays 129.2. That
    is a 0.23% error. It sounds like nothing. Over a 28-second clip it accumulates to
    about 136 ms of drift, which at 130 BPM is **more than a whole sixteenth**, so hits
    at the end of the clip are assigned to the wrong step. On a real four-on-the-floor
    record the kick histogram came back as ``[4,4,3,3,5,2,4,3,…]`` — flat, meaning no
    pattern at all — and after this fit it came back as ``[13,0,0,0, 12,0,0,0, …]``.
    Same audio, same detector, same hits. Only the grid changed.

    Fitting a straight line through (step index, hit time) recovers both the period and
    the phase at once. Iterated, because the step indices themselves depend on the grid:
    the first pass re-assigns the hits a bad grid had mislabelled, and the second fits to
    the corrected assignment. It converges in two or three.

    Feed it the **kicks and snares**, not every onset. Hats are too dense to assign
    unambiguously and they pull the fit toward whatever subdivision they happen to play.
    """
    if len(times) < 8 or not grid.tempo_bpm:
        return grid

    bpm, offset = grid.tempo_bpm, grid.first_beat_s
    ordered = np.array(sorted(times), dtype=float)
    for _ in range(rounds):
        step = 60.0 / bpm / STEPS_PER_BEAT
        index = np.round((ordered - offset) / step)
        # Hits more than nine tenths of the way to the next step are ambiguous, and
        # including them lets a bad grid keep justifying itself.
        keep = np.abs(ordered - (offset + index * step)) < step * 0.45
        if keep.sum() < 8:
            break
        slope, intercept = np.polyfit(index[keep], ordered[keep], 1)
        if slope <= 0:
            break
        bpm, offset = 60.0 / (slope * STEPS_PER_BEAT), float(intercept)

    # Least squares recovers the lattice but *not which of its rungs is a beat*: the fit
    # is over sixteenth indices, and the intercept lands on whichever sixteenth the first
    # hit happened to be assigned. Left alone that rotates the whole histogram, and a
    # four-on-the-floor kick comes back as [0,8,0,0, 0,8,0,0, …] — the right pattern on
    # the wrong beat, which is worse than a wrong pattern because it looks plausible.
    # Four rotations to try, and the drums themselves say which is right.
    step = 60.0 / bpm / STEPS_PER_BEAT
    rotation = max(
        range(STEPS_PER_BEAT),
        key=lambda r: sum(
            1
            for t in ordered
            if round((t - (offset + r * step)) / step) % STEPS_PER_BEAT == 0
        ),
    )
    # Wrapping by a whole beat is safe here and wrapping by a step would not be: a beat
    # is four steps, so it preserves the rotation just chosen.
    offset = (offset + rotation * step) % (60.0 / bpm)

    # The fit can only sharpen a grid, never validate its octave, so the confidence it
    # was given stays exactly as it was.
    return BeatGrid(
        tempo_bpm=round(bpm, 4),
        beats_per_bar=grid.beats_per_bar,
        first_beat_s=round(offset, 4),
        confidence=grid.confidence,
        duration_s=grid.duration_s,
    )


# ──────────────────────────── placing hits on the grid ────────────────────────────


def position_histogram(times: list[float], grid: BeatGrid) -> list[int]:
    """How many hits land on each sixteenth of the bar.

    The whole four-on-the-floor question is this list: a kick histogram reading
    ``[16,0,0,0, 16,0,0,0, 16,0,0,0, 16,0,0,0]`` *is* four on the floor, and no adjective
    was needed to say so.
    """
    counts = [0] * grid.steps_per_bar
    if not grid.steps_per_bar:
        return counts
    for time_s in times:
        index, _ = grid.step_of(time_s)
        counts[index % grid.steps_per_bar] += 1
    return counts


def beat_coverage(
    times: list[float], grid: BeatGrid, within_bar: int | None = None
) -> tuple[int, int]:
    """(beats carrying a hit, beats in the clip) — optionally only one beat of the bar.

    ``within_bar=0`` is the downbeat, ``2`` is the backbeat in 4/4. Counts *beats*, not
    hits, because two kicks flammed onto one downbeat is still one downbeat covered, and
    reporting "65 of 64" would be absurd.
    """
    total_beats = grid.beats
    if total_beats <= 0:
        return 0, 0

    wanted: set[int] = set()
    for beat in range(total_beats):
        if within_bar is None or beat % grid.beats_per_bar == within_bar:
            wanted.add(beat * STEPS_PER_BEAT)
    if not wanted:
        return 0, 0

    covered = set()
    for time_s in times:
        index, _ = grid.step_of(time_s)
        if index in wanted:
            covered.add(index)
    return len(covered), len(wanted)


def offbeat_share(times: list[float], grid: BeatGrid, step: int = 2) -> Figure:
    """What fraction of this drum's hits sit on the given sixteenth of each beat.

    ``step=2`` is the eighth-note offbeat — the "hats on the ands" question.
    """
    if not grid.usable:
        return Figure.unmeasured("the beat grid is below the confidence floor")
    if len(times) < MIN_HITS_FOR_SHARE:
        return Figure.unmeasured(f"only {len(times)} hits", basis=f"{len(times)} hits")

    on_step = sum(1 for t in times if grid.step_of(t)[0] % STEPS_PER_BEAT == step)
    share = on_step / len(times)
    return Figure(
        value=round(100.0 * share, 1),
        confidence=round(min(1.0, len(times) / 40.0) * grid.confidence, 3),
        unit="%",
        basis=f"{on_step} of {len(times)} hits",
    )


# ──────────────────────────────────── swing ────────────────────────────────────


def swing_ratio(times: list[float], grid: BeatGrid) -> Figure:
    """Where the off-beat eighth actually falls between two beats. 0.5 is straight.

    Measured as the median phase of every hit landing in the middle half of a beat.
    The window is **symmetric** around 0.5 on purpose: an asymmetric one (say 0.3–0.8,
    to leave room for a heavy shuffle) drags the median upward on perfectly straight
    material, which is the worst possible failure for a figure whose entire job is to say
    whether something is straight.

    The cost of that symmetry is a ceiling: a shuffle past about 0.72 starts to be
    indistinguishable from a sixteenth played at 0.75, and the ``caveat`` says so rather
    than the function pretending otherwise.

    Deliberately *not* done: weighting by hit strength. Tried, and it made the figure
    track which hits the detector found loudest rather than where they sat.
    """
    if not grid.usable:
        return Figure.unmeasured("the beat grid is below the confidence floor")

    phases = [p for p in (grid.phase_of(t) for t in times) if 0.25 <= p <= 0.75]
    if len(phases) < MIN_OFFBEATS_FOR_SWING:
        return Figure.unmeasured(
            f"only {len(phases)} off-beat events, under the {MIN_OFFBEATS_FOR_SWING} "
            "needed for a distribution",
            basis=f"{len(phases)} off-beat events",
        )

    ordered = sorted(phases)
    median = float(np.median(ordered))
    spread = float(np.percentile(ordered, 75) - np.percentile(ordered, 25))

    # A wide spread means these are not one population of off-beats — most often
    # sixteenths at 0.25 and 0.75 sitting either side of a genuine eighth. Reporting
    # their median as "the swing" would be averaging two different rhythms.
    tightness = max(0.0, 1.0 - spread / 0.25)
    caveat = ""
    if spread > 0.2:
        caveat = (
            f"the off-beat events are spread over {spread:.2f} of a beat, which is "
            "sixteenth content rather than one swung eighth"
        )
    elif median > 0.72:
        caveat = "at this ratio a heavy shuffle and a dotted-eighth sixteenth read alike"

    return Figure(
        value=round(median, 3),
        confidence=round(tightness * min(1.0, len(phases) / 32.0) * grid.confidence, 3),
        basis=f"median of {len(phases)} off-beat events, IQR {spread:.3f}",
        caveat=caveat,
    )


# ──────────────────────── programmed versus played ────────────────────────


@dataclass(frozen=True, slots=True)
class TimingSpread:
    """How far hits sit from the grid — raw, and with tempo drift taken out."""

    raw_ms: Figure
    detrended_ms: Figure
    resolution_floor_ms: float


def timing_spread(
    times: list[float], grid: BeatGrid, sample_rate: int = 44100
) -> TimingSpread:
    """Standard deviation of hit times around the nearest sixteenth, in milliseconds.

    Two numbers, because the raw one is not what the reader thinks it is. A grid whose
    tempo is 0.2 BPM out drifts steadily across a clip, and that drift lands in the
    standard deviation as though the drummer had done it. Fitting and removing a straight
    line through the deviations absorbs exactly that error, so the detrended figure is
    the one that answers "programmed or played"; the raw one is kept because the gap
    between them is how far the grid itself can be trusted.

    Both sit on top of a hard floor — see :data:`ONSET_HOP`. The detector cannot resolve a
    drum machine's few hundred microseconds, so the honest reading of a detrended figure
    at the floor is "at or below the measurement resolution", never "2 ms".
    """
    floor = _resolution_ms(sample_rate)
    if not grid.usable:
        why = "the beat grid is below the confidence floor"
        return TimingSpread(Figure.unmeasured(why), Figure.unmeasured(why), floor)
    if len(times) < MIN_HITS_FOR_TIMING:
        why = f"only {len(times)} hits, under the {MIN_HITS_FOR_TIMING} needed"
        basis = f"{len(times)} hits"
        return TimingSpread(
            Figure.unmeasured(why, basis), Figure.unmeasured(why, basis), floor
        )

    at = np.array([grid.step_of(t) for t in times], dtype=float)
    steps, deviations = at[:, 0], at[:, 1] * 1000.0
    raw_sd = float(np.std(deviations))

    # A deviation at half a step has wrapped onto the neighbouring sixteenth, and the
    # standard deviation of a wrapped quantity is meaningless. Hits crowding that
    # boundary are the warning sign.
    half_step_ms = grid.step_s * 1000.0 / 2.0
    wrapped = float(np.mean(np.abs(deviations) > 0.84 * half_step_ms))
    slope, intercept = np.polyfit(steps, deviations, 1)
    detrended_sd = float(np.std(deviations - (slope * steps + intercept)))

    drift_ms_per_bar = slope * grid.steps_per_bar
    basis = f"{len(times)} hits, grid drift {drift_ms_per_bar:+.1f} ms/bar"
    confidence = round(
        min(1.0, len(times) / 60.0) * grid.confidence * (1.0 - min(1.0, wrapped * 3)), 3
    )
    caveat = ""
    if detrended_sd <= DETECTOR_JITTER_MS * 2:
        caveat = (
            f"inside the detector's own ~{DETECTOR_JITTER_MS:.0f} ms contribution, so "
            "this cannot be read as programmed or played — only as 'not humanly loose'"
        )
    if detrended_sd <= floor * 1.5:
        caveat = (
            f"at the {floor:.1f} ms frame-quantisation floor — nothing can be measured "
            "below this"
        )
    if wrapped > 0.1:
        caveat = (
            f"{wrapped:.0%} of hits sit near the half-step boundary, so some are being "
            "assigned to the wrong sixteenth"
        )

    return TimingSpread(
        raw_ms=Figure(
            value=round(raw_sd, 2), confidence=confidence, unit=" ms", basis=basis
        ),
        detrended_ms=Figure(
            value=round(detrended_sd, 2),
            confidence=confidence,
            unit=" ms",
            basis=basis,
            caveat=caveat,
        ),
        resolution_floor_ms=round(floor, 2),
    )


# ─────────────────────────── bass ducked to the kick ───────────────────────────


@dataclass(frozen=True, slots=True)
class DuckMeasurement:
    """Whether the bass gets out of the kick's way, and whether it was ever in it."""

    #: How far the bass drops after a kick. On its own this means nothing — see
    #: :attr:`excess_db`.
    dip_db: Figure
    #: The same measurement at grid positions with no kick on them. The control.
    control_dip_db: Figure
    #: dip minus control. **This is the duck**; the other two are its working.
    excess_db: Figure
    #: Kicks where the bass was sounding either side, so a dip would have been visible.
    kicks_examined: int
    #: Kicks where the bass simply was not playing. An arrangement fact, not a duck.
    kicks_bass_silent: int
    kicks_total: int


def envelope_db(samples: np.ndarray, sample_rate: int, hop: int = 128) -> tuple[np.ndarray, np.ndarray]:
    """Short-frame RMS in dB, and the time of each frame.

    Hop 128 — about 2.9 ms at 44.1 kHz. A sidechain's release is tens of milliseconds, so
    the 5.8 ms used for onset detection would smear the very shape being looked for.
    """
    mono = samples.mean(axis=1) if samples.ndim > 1 else np.asarray(samples)
    mono = np.asarray(mono, dtype=np.float64)
    frames = max(1, len(mono) // hop)
    trimmed = mono[: frames * hop].reshape(frames, hop)
    rms = np.sqrt(np.mean(trimmed**2, axis=1))
    times = np.arange(frames) * hop / sample_rate
    return 20.0 * np.log10(np.maximum(rms, 1e-9)), times


def kick_duck(
    env_db: np.ndarray,
    env_times: np.ndarray,
    kick_times: list[float],
    grid: BeatGrid,
) -> DuckMeasurement:
    """How far the bass drops after a kick *over and above* how far it drops anywhere.

    Two traps, and the second one is the one that nearly produced a lie.

    **A bass that does not play on the kick looks exactly like a ducked one** if all you
    measure is "quiet after the kick". Distinguished by what happens either side: a
    ducked bass is sounding before the kick and sounding again a fifth of a second later,
    a bass arranged around the kick is silent through all three windows. Kicks failing
    that test are counted separately and reported as an arrangement fact.

    **A plucked bass note decaying also looks exactly like a ducked one.** Every note has
    an envelope; measure "how far below its own onset is this note 60 ms later" on any
    bass in the world and you get a number in the tens of dB. The first version of this
    function reported a 16.2 dB "duck" on a track with no sidechain on it, and a 45 dB one
    on a track that does have sidechain — both large, neither meaningful, because neither
    was compared against anything.

    The fix is a **control**: run the identical measurement at every sixteenth-note
    position that has *no* kick on it. What the bass does there is its note envelope.
    :attr:`DuckMeasurement.excess_db` is the difference, and it is the only figure of the
    three that is about the kick.
    """
    if env_db.size == 0 or not kick_times:
        why = "no bass envelope or no kicks"
        return DuckMeasurement(
            Figure.unmeasured(why), Figure.unmeasured(why), Figure.unmeasured(why),
            0, 0, len(kick_times),
        )

    active_floor = float(np.percentile(env_db, 95)) - BASS_ACTIVE_BELOW_PEAK_DB

    def window(centre: float, span_ms: tuple[float, float]) -> np.ndarray:
        lo, hi = centre + span_ms[0] / 1000.0, centre + span_ms[1] / 1000.0
        return env_db[(env_times >= lo) & (env_times <= hi)]

    def dips_at(centres: list[float]) -> tuple[list[float], int]:
        """(dip per usable position, positions where the bass was not playing)."""
        found: list[float] = []
        silent = 0
        for centre in centres:
            before, during, after = (
                window(centre, DUCK_PRE_MS),
                window(centre, DUCK_DIP_MS),
                window(centre, DUCK_RECOVERY_MS),
            )
            if before.size == 0 or during.size == 0 or after.size == 0:
                continue  # the clip ran out
            pre, post = float(np.median(before)), float(np.median(after))
            if pre < active_floor or post < active_floor:
                silent += 1
                continue
            # Baseline is the louder side, not the mean: a duck still recovering at
            # 120 ms would otherwise pull its own baseline down and under-report itself.
            found.append(max(pre, post) - float(np.min(during)))
        return found, silent

    dips, silent = dips_at(kick_times)

    kicks = np.array(kick_times, dtype=float)
    steps = int(grid.duration_s / grid.step_s) if grid.step_s > 0 else 0
    control_positions = [
        t
        for t in (grid.first_beat_s + i * grid.step_s for i in range(steps))
        if kicks.size == 0 or float(np.min(np.abs(kicks - t))) > grid.step_s * 0.5
    ]
    controls, _ = dips_at(control_positions)

    def summarise(values: list[float], label: str) -> tuple[Figure, float, float]:
        if len(values) < MIN_KICKS_FOR_DUCK:
            return (
                Figure.unmeasured(
                    f"the bass was sounding either side of only {len(values)} {label}",
                    basis=f"{len(values)} usable",
                ),
                0.0,
                0.0,
            )
        median = float(np.median(values))
        spread = float(np.percentile(values, 75) - np.percentile(values, 25))
        return (
            Figure(
                value=round(median, 2),
                confidence=round(min(1.0, len(values) / 24.0), 3),
                unit=" dB",
                basis=f"median over {len(values)} {label}, IQR {spread:.1f} dB",
            ),
            median,
            spread,
        )

    at_kick, kick_median, kick_spread = summarise(dips, "kicks")
    control, control_median, control_spread = summarise(controls, "kick-free positions")

    if not at_kick.measured or not control.measured:
        excess = Figure.unmeasured(
            "there is no control to compare against"
            if at_kick.measured
            else at_kick.caveat,
            basis=f"{len(dips)} kicks, {len(controls)} control positions",
        )
    else:
        # A sidechain is one compressor applied to every kick alike, so the dips should
        # agree with each other. Dips that disagree by more than a compressor would are
        # the bass part moving, and their median is not a duck depth.
        consistency = max(0.0, 1.0 - kick_spread / 8.0)
        excess = Figure(
            value=round(kick_median - control_median, 2),
            confidence=round(consistency * min(1.0, len(dips) / 24.0), 3),
            unit=" dB",
            basis=(
                f"{kick_median:.1f} dB at {len(dips)} kicks against "
                f"{control_median:.1f} dB at {len(controls)} kick-free positions"
            ),
            caveat=(
                f"the per-kick dips vary by {kick_spread:.0f} dB, more than one "
                "compressor would produce"
                if kick_spread > 8.0
                else ""
            ),
        )

    return DuckMeasurement(
        dip_db=at_kick,
        control_dip_db=control,
        excess_db=excess,
        kicks_examined=len(dips),
        kicks_bass_silent=silent,
        kicks_total=len(kick_times),
    )


# ──────────────────────────────── the whole thing ────────────────────────────────


@dataclass(slots=True)
class StemEntry:
    """One stem's place on the record."""

    stem: StemKind
    relative_lufs: float
    present: bool
    onsets_per_bar: Figure


@dataclass(slots=True)
class Fingerprint:
    """Everything measurable about a record's rhythm and instrumentation.

    No genre, no adjectives, no verdicts — counts, ratios and dB, each with the sample it
    came from. A caller that wants a sentence builds one from these; a caller that wants a
    label is asking the wrong module.
    """

    name: str
    duration_s: float
    grid: BeatGrid
    key_name: str = ""
    key_confidence: float = 0.0
    metre_source: str = ""

    kick_histogram: list[int] = field(default_factory=list)
    snare_histogram: list[int] = field(default_factory=list)
    hat_histogram: list[int] = field(default_factory=list)
    kick_on_beats: tuple[int, int] = (0, 0)
    kick_on_downbeats: tuple[int, int] = (0, 0)
    snare_on_backbeats: tuple[int, int] = (0, 0)
    hat_offbeat_share: Figure = field(
        default_factory=lambda: Figure.unmeasured("not computed")
    )
    swing: Figure = field(default_factory=lambda: Figure.unmeasured("not computed"))
    #: Keyed "kick" / "snare" / "hihat" / "all". Per drum because the hats dominate the
    #: hit count and are the noisiest thing the detector finds, so a single pooled figure
    #: is mostly a statement about hat detection — on one clip the pooled spread was
    #: 16.4 ms while the kick's was 7.7 ms, and only the second answers the question.
    timing: dict[str, TimingSpread] = field(default_factory=dict)
    duck: DuckMeasurement | None = None
    stems: list[StemEntry] = field(default_factory=list)
    hit_counts: dict[str, int] = field(default_factory=dict)


def measure(
    mix: Path,
    stems: dict[StemKind, Path],
    timing: TimingEstimate | None = None,
    name: str = "",
) -> Fingerprint:
    """Fingerprint one record from its mix and its separated stems.

    Timing is read from the **mix**, once, and applied to every stem — the same choice
    `analysis.timing` already documents, and for the same reason: a bass stem and a hat
    stem asked separately will not agree on a downbeat.
    """
    from app.services.analysis.timing import TimingAnalyser
    from app.services.drums.detect import count_by_kind, find_hits
    from app.services.mastering.instrument import profile_all
    from app.services.mixdown.encode import read_audio

    buffer = read_audio(mix)
    timing = timing or TimingAnalyser().analyse(mix)
    grid = BeatGrid.from_timing(timing, buffer.duration_s)
    key = timing.key

    # The drums have to be read before anything else, because the grid everything else is
    # measured against is re-derived from them. See `grid_from_drums` — this is not a
    # nicety, a mix-anchored grid produced a flat kick histogram on a four-on-the-floor
    # record.
    drums = stems.get(StemKind.DRUMS)
    hits: list = []
    drum_rate = buffer.sample_rate
    if drums and Path(drums).exists():
        drum_buffer = read_audio(Path(drums))
        drum_rate = drum_buffer.sample_rate
        hits = find_hits(drum_buffer.samples, drum_buffer.sample_rate)
        anchors = [h.time_s for h in hits if {"kick", "snare"} & set(h.kinds)]
        grid = grid_from_drums(anchors, timing, buffer.duration_s)

    fingerprint = Fingerprint(
        name=name or mix.stem,
        duration_s=round(buffer.duration_s, 2),
        grid=grid,
        key_name=key.name if key else "",
        key_confidence=key.confidence if key else 0.0,
        metre_source=timing.source,
    )

    profiles = profile_all(stems)
    for stem, path in stems.items():
        profile = profiles.get(stem)
        if profile is None:
            continue
        fingerprint.stems.append(
            StemEntry(
                stem=stem,
                relative_lufs=profile.relative_lufs,
                present=profile.present,
                onsets_per_bar=_onsets_per_bar(path, grid, profile.present),
            )
        )

    if hits:
        fingerprint.hit_counts = count_by_kind(hits)
        kicks = [h.time_s for h in hits if "kick" in h.kinds]
        snares = [h.time_s for h in hits if "snare" in h.kinds]
        hats = [h.time_s for h in hits if "hihat" in h.kinds]

        fingerprint.kick_histogram = position_histogram(kicks, grid)
        fingerprint.snare_histogram = position_histogram(snares, grid)
        fingerprint.hat_histogram = position_histogram(hats, grid)
        fingerprint.kick_on_beats = beat_coverage(kicks, grid)
        fingerprint.kick_on_downbeats = beat_coverage(kicks, grid, within_bar=0)
        # Beat index 1 of a 4/4 bar is the "2" a drummer counts, this being 0-indexed.
        fingerprint.snare_on_backbeats = beat_coverage(snares, grid, within_bar=1)
        fingerprint.hat_offbeat_share = offbeat_share(hats, grid)
        fingerprint.swing = swing_ratio(hats or [h.time_s for h in hits], grid)
        fingerprint.timing = {
            label: timing_spread(times, grid, drum_rate)
            for label, times in (
                ("kick", kicks),
                ("snare", snares),
                ("hihat", hats),
                ("all", [h.time_s for h in hits]),
            )
        }

        bass = stems.get(StemKind.BASS)
        if bass and Path(bass).exists():
            bass_buffer = read_audio(Path(bass))
            env, env_times = envelope_db(bass_buffer.samples, bass_buffer.sample_rate)
            fingerprint.duck = kick_duck(env, env_times, kicks, grid)

    return fingerprint


def _onsets_per_bar(path: Path, grid: BeatGrid, present: bool) -> Figure:
    """Events per bar in one stem.

    Abstains for an absent stem rather than returning its onset count: separation residue
    has onsets, they are just not an instrument's.
    """
    if not present:
        return Figure.unmeasured("the stem is below the presence threshold")
    if grid.bars <= 0:
        return Figure.unmeasured("no usable bar count")

    import librosa

    try:
        y, sr = librosa.load(str(path), sr=None, mono=True)
        onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time")
    except Exception:
        log.info("could not count onsets in %s", path, exc_info=True)
        return Figure.unmeasured("the stem could not be read")

    return Figure(
        value=round(len(onsets) / grid.bars, 2),
        confidence=round(grid.confidence if grid.usable else 0.0, 3),
        unit="/bar",
        basis=f"{len(onsets)} onsets over {grid.bars:.1f} bars",
        caveat=("the bar count comes from a grid below the confidence floor"
                if not grid.usable else ""),
    )
