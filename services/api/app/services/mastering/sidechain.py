"""The bass getting out of the kick's way, measured on both sides and then applied.

X0R-1308, the last unblocked card in EPIC-13. The measurement already existed -
`fingerprint.kick_duck` reads how far the bass drops after a kick *over and above* how far
it drops anywhere, against a control at kick-free grid positions, because without that
control every bass in the world "ducks" by tens of decibels and the number is a note
envelope. What did not exist was comparing two sides of it, or doing anything about it.

### The control only goes one way, and that is not a limitation to be fixed

A duck can be added. **It cannot be taken away.** If your bass ducks 6 dB on every kick and
the reference's ducks 1 dB, there is no process here that restores the bass that was
compressed out of your recording - the samples are gone, and anything that appeared to put
them back would be inventing them. So:

* **Yours ducks less than theirs** - suggest a duck, a fraction of the measured gap, like
  every other suggestion in this application.
* **Yours ducks more than theirs** - say so, and offer nothing. A finding with no dial.

This is the same shape as `X0R-1307`: an observation the application can make and honestly
cannot act on. The difference is that half of this one *is* actionable, and reporting both
halves through one comparison is what makes the asymmetry visible instead of mysterious.

### Abstention is the common path, by design

The card says so, and the experiments are why: the figure abstained on one of two tracks in
Experiment 1 and on six of seven files in Experiment 2, because the per-kick dips varied by
8 to 18 dB - more than one compressor would produce, which is the signature of a bass part
moving rather than a sidechain working. X0R-414 gave the detector cleaner kick times, which
was never why it abstained.

So the ordinary outcome of this module is a sentence explaining which side could not be
measured and what would have to be true for it to be. `compare` returns that sentence as a
finding rather than returning nothing, because a silent abstention is indistinguishable
from a feature that is broken.
"""

from __future__ import annotations

import numpy as np

from app.domain.notes import StemKind
from app.services.analysis.fingerprint import DuckMeasurement
from app.services.mastering.budget import Limits
from app.services.mastering.instrument import NUDGE_SHARE, InstrumentMove

#: How fast the gain gets out of the way. A sidechain compressor's attack is a few
#: milliseconds - `fingerprint.DUCK_DIP_MS` looks for the deepest point between 5 and 90 ms
#: after the kick, so anything slower than this would not produce the shape the measurement
#: is looking for, and the round-trip test would catch it.
ATTACK_MS = 6.0

#: And how long it takes to come back. `DUCK_RECOVERY_MS` requires the bass to be back by
#: 120-280 ms, so a release materially longer than this measures as a bass that never
#: recovered - which is an arrangement, not a duck.
RELEASE_MS = 150.0

#: Below this there is nothing to claim. Lower than it looks it should be, and the reason
#: is `SEPARATION_FLATTENS_IT` below: at 0.5 this abstained on a reference whose bass had
#: been ducked seven decibels, which is not a borderline case. 0.3 is still clear of the
#: 0.1 dB of offset separation adds between two sides measured the same way.
MIN_USEFUL_DB = 0.3

#: **A duck measured through stem separation reads about a fifth of what is really there.**
#:
#: Measured 2026-10-06 end to end, two mixes identical except that the reference's bass was
#: ducked 7 dB to its own kick before mixing:
#:
#: | measured on | no duck | 7 dB duck | gap |
#: |---|---:|---:|---:|
#: | the original bass, exact kick times | +0.17 | +3.87 | **3.70** |
#: | the separated bass, exact kick times | +0.56 | +1.34 | **0.78** |
#: | the separated bass, detected kick times | +0.48 | +1.39 | 0.91 |
#:
#: The loss is between rows one and two, so it is **separation and not kick detection** -
#: demucs reconstructs a bass without preserving its gain envelope, and four fifths of the
#: dip is filled back in. Detecting the kicks off the separated kick sub-stem costs
#: nothing by comparison, which is the opposite of what was assumed.
#:
#: Three consequences, all of them live:
#:
#: 1. **This is why the figure abstains so often.** Experiment 2 saw it abstain on six of
#:    seven files, and this is a better explanation than any of the ones offered then.
#: 2. **The suggestion is a floor, not an estimate.** Both sides pass through the same
#:    separation so the *comparison* is fair - the direction and the sign are right - but
#:    the magnitude is compressed about fivefold, and the gain the render applies lands on
#:    an already-separated bass at full strength. So a user who takes the suggestion gets
#:    materially less ducking than the measured gap implies. Under-delivering is the safe
#:    direction for a tool whose whole rule is "a share of the gap, never the whole thing",
#:    and the finding says so rather than claiming a closure it does not make.
#: 3. **Correcting for it would need real material.** One synthetic pair is one data
#:    point, and a fivefold constant fitted to it would be exactly the fiction that
#:    `gain_for_excess` exists to avoid. Filed as X0R-1311.
SEPARATION_FLATTENS_IT = True

#: The most this may add at the default budget, scaled by `Limits` like every other
#: ceiling. Three decibels of pumping is plainly audible; six is an effect.
MAX_SIDECHAIN_DB = 3.0

#: Under this many usable kicks the shape is not a pattern, whatever the arithmetic says.
#: Mirrors `fingerprint.MIN_KICKS_FOR_DUCK`, which gates the measurement this reads.
MIN_KICKS = 8

#: The trial depth used to calibrate. Large enough to read cleanly over the measurement's
#: own noise, small enough to stay in the range where the relationship is near-linear.
TRIAL_DB = 6.0

#: A slope outside this is not a measurement of this bass, it is the measurement failing.
#: Measured range across five synthetic basses was 0.53 to 0.75 (see `gain_for_excess`).
SLOPE_LIMITS = (0.25, 1.5)

#: The hardest this will ever pull the bass down, whatever the arithmetic asks for. Past
#: about this much, a listener stops hearing a mix that breathes and starts hearing an
#: effect - and on a bass where the solve lands here, the honest reading is that the
#: measurement is struggling rather than that eleven decibels are wanted.
MAX_APPLIED_DB = 8.0


def gain_envelope(
    kick_times: list[float] | np.ndarray,
    n_samples: int,
    sample_rate: int,
    depth_db: float,
    attack_ms: float = ATTACK_MS,
    release_ms: float = RELEASE_MS,
) -> np.ndarray:
    """A linear gain curve that dips `depth_db` at each kick and recovers.

    Shaped rather than drawn: the attack is a linear ramp down and the release an
    exponential recovery, which is what a compressor's release does and - more to the
    point here - what the measurement on the other side is looking for.

    Overlapping kicks take the **deepest** gain at each sample rather than the sum. Two
    kicks 100 ms apart on a fast track would otherwise duck twice as far as either, which
    no compressor does: a compressor already holding 3 dB of reduction does not add
    another 3 for the next hit.
    """
    gain = np.ones(max(0, int(n_samples)), dtype=np.float64)
    if gain.size == 0 or depth_db <= 0.0:
        return gain

    floor = 10.0 ** (-abs(depth_db) / 20.0)
    attack = max(1, int(sample_rate * attack_ms / 1000.0))
    release = max(1, int(sample_rate * release_ms / 1000.0))

    # One kick's shape, built once: down over the attack, then back up over the release.
    down = np.linspace(1.0, floor, attack, endpoint=False)
    # Exponential recovery to within a thousandth of unity by the end of the release,
    # so the curve is continuous where it meets the next sample of untouched audio.
    curve = 1.0 - (1.0 - floor) * np.exp(-np.arange(release) / (release / 4.0))
    shape = np.concatenate([down, curve])

    for time_s in np.atleast_1d(np.asarray(kick_times, dtype=float)):
        start = int(round(time_s * sample_rate))
        if start >= gain.size:
            continue
        head = max(0, start)
        piece = shape[max(0, -start) : max(0, -start) + (gain.size - head)]
        if piece.size == 0:
            continue
        window = gain[head : head + piece.size]
        np.minimum(window, piece, out=window)

    return gain


def apply(
    samples: np.ndarray,
    sample_rate: int,
    kick_times: list[float] | np.ndarray,
    depth_db: float,
    attack_ms: float = ATTACK_MS,
    release_ms: float = RELEASE_MS,
) -> np.ndarray:
    """Duck `samples` to `kick_times`. A depth of 0 returns the audio untouched.

    The null case is exact rather than nearly exact - the same property the per-drum moves
    were built to have - so a control at rest cannot be heard to do anything.
    """
    if depth_db <= 0.0 or samples.size == 0:
        return samples
    gain = gain_envelope(kick_times, len(samples), sample_rate, depth_db, attack_ms, release_ms)
    if samples.ndim > 1:
        return samples * gain[:, None]
    return samples * gain


# --- what the detector reads is not what the gain did -------------------------------------


def measured_excess(
    samples: np.ndarray,
    sample_rate: int,
    kick_times: list[float] | np.ndarray,
    grid,
) -> float | None:
    """Run the detector on one bass and return its excess dip, or None if it abstains."""
    from app.services.analysis.fingerprint import envelope_db, kick_duck

    env, times = envelope_db(samples, sample_rate)
    reading = kick_duck(env, times, list(np.atleast_1d(np.asarray(kick_times, float))), grid)
    return float(reading.excess_db.value) if reading.excess_db.measured else None


def gain_for_excess(
    samples: np.ndarray,
    sample_rate: int,
    kick_times: list[float] | np.ndarray,
    grid,
    wanted_excess_db: float,
    trial_db: float = TRIAL_DB,
) -> float | None:
    """How much gain reduction produces `wanted_excess_db` **on this bass**.

    **The detector does not read back the gain that was applied, and it was never built
    to.** It reports the deepest point in a window against a control measured elsewhere,
    and how far a given gain reduction moves that figure depends on the bass underneath
    it. Measured on five synthetic basses, applying 3, 6 and 9 dB:

    | bass | reading at 3 / 6 / 9 dB | slope |
    |---|---|---:|
    | held 55 Hz | 1.8 / 3.8 / 6.3 | 0.75 |
    | held 82 Hz | 1.6 / 3.4 / 5.7 | 0.69 |
    | held 41 Hz | 1.4 / 3.0 / 4.8 | 0.57 |
    | plucked 55 Hz | -7.9 / -6.9 / -4.7 | 0.53 |
    | walking | -8.1 / -6.1 / -3.6 | 0.74 |

    Two things in that table. The slope varies by nearly half across bass parts, so **a
    single calibration constant would be fiction** - which is why this measures the slope
    on the actual bass instead of carrying one. And the plucked rows start at about -8 dB
    with no duck on them at all: their notes restart on the beat, so the kick positions
    catch an attack while the control positions catch a decay. That offset is why only the
    *slope* is used here and never the absolute reading.

    Returns None when the bass cannot be read well enough to calibrate against, which is
    the same honest refusal the rest of this module is built around.
    """
    if wanted_excess_db <= 0.0:
        return 0.0

    rest = measured_excess(samples, sample_rate, kick_times, grid)
    if rest is None:
        return None
    trial = measured_excess(
        apply(samples, sample_rate, kick_times, trial_db), sample_rate, kick_times, grid
    )
    if trial is None:
        return None

    slope = (trial - rest) / trial_db
    if not SLOPE_LIMITS[0] <= slope <= SLOPE_LIMITS[1]:
        return None

    first = min(wanted_excess_db / slope, MAX_APPLIED_DB)

    # One refinement, because the relationship is convex: a slope fitted at 6 dB
    # extrapolated to 10.7 dB overshot the target by 78% on a plucked bass. Re-fitting
    # between the trial point and the first solve is a Newton step, and it costs one more
    # pass over an envelope that is already cheap next to the separation behind it.
    landed = measured_excess(
        apply(samples, sample_rate, kick_times, first), sample_rate, kick_times, grid
    )
    if landed is not None and abs(first - trial_db) > 0.5:
        local = (landed - trial) / (first - trial_db)
        if SLOPE_LIMITS[0] <= local <= SLOPE_LIMITS[1]:
            corrected = first + (wanted_excess_db - (landed - rest)) / local
            first = min(max(corrected, 0.0), MAX_APPLIED_DB)

    return round(first, 2)


# --- the comparison ---------------------------------------------------------------------


def _usable(measurement: DuckMeasurement | None) -> bool:
    return (
        measurement is not None
        and measurement.excess_db.measured
        and measurement.kicks_examined >= MIN_KICKS
    )


def _why_not(measurement: DuckMeasurement | None, whose: str) -> str:
    """The sentence that makes an abstention useful rather than merely honest."""
    if measurement is None:
        return f"{whose} was not measured - it needs the drums split and a bass to read."
    if measurement.kicks_total == 0:
        return f"no kicks were found in {whose}."
    if measurement.kicks_examined < MIN_KICKS:
        silent = measurement.kicks_bass_silent
        of = f"{measurement.kicks_total} kicks"
        if silent:
            return (
                f"in {whose} the bass was not playing through {silent} of {of}, leaving "
                f"{measurement.kicks_examined} where a dip would have been visible - "
                f"fewer than the {MIN_KICKS} this needs. A bass arranged around the kick "
                "looks exactly like a ducked one, which is why those do not count."
            )
        return (
            f"{whose} had {measurement.kicks_examined} usable kicks of {of}, fewer than "
            f"the {MIN_KICKS} this needs."
        )
    caveat = measurement.excess_db.caveat or "the measurement did not settle"
    return f"in {whose}, {caveat}."


def compare(
    mine: DuckMeasurement | None,
    theirs: DuckMeasurement | None,
    limits: Limits | None = None,
) -> list[InstrumentMove]:
    """Your bass's relationship to your kick, against the reference's.

    Returns a single finding, always - a suggestion when there is one to make, and
    otherwise the reason there is not. See the module docstring for why abstention is the
    expected outcome rather than a failure.
    """
    limits = limits or Limits()
    ceiling = getattr(limits, "max_sidechain_db", MAX_SIDECHAIN_DB)

    if not _usable(mine) or not _usable(theirs):
        unusable = (
            _why_not(mine, "your mix")
            if not _usable(mine)
            else _why_not(theirs, "the reference")
        )
        return [
            InstrumentMove(
                stem=StemKind.BASS.value,
                dimension="sidechain",
                headline="Whether the bass ducks to the kick could not be compared",
                detail=(
                    "A sidechain duck is one compressor applied to every kick alike, so "
                    "the only way to tell one from a bass part that happens to rest on "
                    "the beat is consistency across many kicks - and "
                    + unusable
                    + " This abstains more often than it reports, on purpose: the "
                    "alternative is a number that is mostly note envelope."
                ),
                severity="match",
                confident=False,
                control="",
            )
        ]

    assert mine is not None and theirs is not None  # narrowed by _usable
    ours = float(mine.excess_db.value)
    reference = float(theirs.excess_db.value)
    gap = reference - ours

    if abs(gap) < MIN_USEFUL_DB:
        return [
            InstrumentMove(
                stem=StemKind.BASS.value,
                dimension="sidechain",
                headline="Your bass gets out of the kick's way about as much as theirs",
                detail=(
                    f"Yours ducks {ours:.1f} dB on each kick over and above how far it "
                    f"drops anywhere else; theirs ducks {reference:.1f} dB. "
                    f"{abs(gap):.1f} dB apart, which is not a difference worth a control."
                ),
                severity="match",
                yours=ours,
                reference=reference,
                measured=gap,
                control="",
            )
        ]

    if gap < 0:
        # Yours ducks harder. There is no process here that puts back bass that was
        # compressed out of the recording, and one that appeared to would be inventing it.
        return [
            InstrumentMove(
                stem=StemKind.BASS.value,
                dimension="sidechain",
                headline="Your bass ducks harder to the kick than theirs does",
                detail=(
                    f"Yours drops {ours:.1f} dB on each kick against the reference's "
                    f"{reference:.1f} dB - {abs(gap):.1f} dB more pumping. **There is no "
                    "control for this one.** A duck can be added; it cannot be taken "
                    "away, because the bass that was compressed out of your recording is "
                    "not in the file any more and anything that appeared to restore it "
                    "would be inventing it. If this is not what you want, it has to come "
                    "off the original mix."
                ),
                severity="notable",
                yours=ours,
                reference=reference,
                measured=gap,
                control="",
                confident=True,
            )
        ]

    suggested = min(gap * NUDGE_SHARE, ceiling)
    if suggested < MIN_USEFUL_DB:
        return [
            InstrumentMove(
                stem=StemKind.BASS.value,
                dimension="sidechain",
                headline="Your bass could get further out of the kick's way, barely",
                detail=(
                    f"Theirs ducks {reference:.1f} dB to yours at {ours:.1f}. A share of "
                    f"that gap is {gap * NUDGE_SHARE:.1f} dB, which is under the "
                    f"{MIN_USEFUL_DB:.1f} dB worth applying."
                ),
                severity="match",
                yours=ours,
                reference=reference,
                measured=gap,
                control="",
            )
        ]

    severity = "strong" if gap >= 4.0 else "notable" if gap >= 2.0 else "slight"
    return [
        InstrumentMove(
            stem=StemKind.BASS.value,
            dimension="sidechain",
            headline="Their bass gets out of the kick's way more than yours does",
            detail=(
                f"Theirs drops {reference:.1f} dB on each kick over and above how far it "
                f"drops anywhere else; yours drops {ours:.1f} dB. Both measured against a "
                "control at kick-free positions, without which every bass in the world "
                f"appears to duck. This offers {suggested:.1f} dB of it, applied at your "
                "own kick times. **Read these as a floor rather than a measurement of the "
                "record.** Both figures come off separated stems, and separation fills "
                "most of a duck back in - a bass ducked 7 dB before mixing measured 1.3 dB "
                "after being separated out again. The direction is right and the size is "
                "understated, so if it sounds like it wants more, it probably does."
            ),
            severity=severity,
            yours=ours,
            reference=reference,
            measured=gap,
            suggested=round(suggested, 2),
            control="sidechain_db",
            # The measurement carries its own confidence, and the two sides multiply:
            # a weak reading on either side is a weak suggestion.
            confident=bool(
                mine.excess_db.confidence * theirs.excess_db.confidence >= 0.25
            ),
        )
    ]
