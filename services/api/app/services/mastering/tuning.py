"""How close to the grid a vocal sits, and what grid it is.

A person comparing their vocal with a record's is often chasing a sound that came out of
an editor rather than out of a throat. Measured on three records at 2-cent resolution,
after removing each record's own tuning reference: a modern major-label rock vocal sits
**4.0 cents** from its own tuning, an indie rock vocal **14.0**, and a rapped vocal
**26.0**. Four against fourteen is a 3.5× separation that no amount of detector noise
explains, and the reading is the obvious one - the first was pitch-corrected and the
second was not. Whether a record was tuned is a *production* decision, which is this
product's subject, rather than a performance one.

**This reads the f0 contour, not notes.** No segmentation, no note offsets, no onset
detector and no grid, so none of X0R-1319's tempo problems and none of X0R-412's
backtracking touch it. That is what makes it the most reachable of the Melodyne-shaped
comparisons rather than the most ambitious.

## Three things this measurement is not

**It is not "how well this person sings".** Vibrato and portamento inflate the figure
without anybody being out of tune, and the probe's own finding is that vibrato cannot be
measured well enough here to compensate for it. The wording everywhere is *how close to
the grid this vocal sits*, and the caveat ships on the finding rather than in a help
panel.

**It is an upper bound, not a measurement of the singer.** Separation artefacts and pitch
tracking both add spread; neither removes it. So *theirs is tighter than yours* is
supported, and *yours is 14 cents out* is not - the first is a comparison of two numbers
biased the same way, and the second treats a biased number as absolute.

**It has no ground truth.** Nobody has confirmed that any record here was tuned; it is an
inference from a figure. X0R-306 would put a confidence on the pitch track underneath it.
It would not validate the inference, and nothing here should pretend otherwise.

## Removing the record's own tuning is part of the measurement

Not a refinement. The three records above are tuned to three different A4s - 439.8,
444.9 and 442.4 Hz - and the middle one is 19 cents sharp of concert pitch. Without this
step a record tuned sharp reads as a singer who is sharp, which is a different claim
about a different person.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

#: Pitch range searched, in Hz. Wide enough for a bass voice to a soprano and no wider:
#: pYIN's cost grows with the range, and octave errors outside a singer's register are
#: the commonest way a contour measurement goes wrong.
FMIN_HZ = 65.0
FMAX_HZ = 1000.0

#: Two estimators, and the reason is a bug this card nearly shipped.
#:
#: The obvious implementation runs pYIN at `resolution=0.02` - 2 cents, which is what the
#: probe's figures were quoted at - and reads both voicing and pitch off it. Measured on
#: two real vocal stems, that **destroys the voicing decision**: at pYIN's default
#: resolution they come back 39% and 38% voiced, and at 0.02 they come back **3.2% and
#: 0.2%**. Finer bins spread the observation probability thinner, the HMM's unvoiced
#: state wins, and the result is a stem that looks empty. The first run of this module
#: reported 77 and 6 voiced frames on loud vocals sitting 5 dB under their own mix, and
#: would have abstained on every record for the wrong reason.
#:
#: So voicing comes from pYIN at its **default** resolution, where it is robust, and the
#: pitch from `librosa.yin`, which uses parabolic interpolation and returns a continuous
#: f0 rather than a binned one - 919 distinct values against pYIN's 165 on the same
#: frames. It is also four times faster: about 5 s per stem for both, against 30 for the
#: single fine-resolution pass that did not work.
#:
#: Cross-checked against the probe: its rapped vocal measured 26.0 cents at 2-cent pYIN,
#: and this route gives 24.4 on the same recording. Two different estimators within
#: 1.6 cents is the closest thing to a ground truth available here.
#: Below this share of frames carrying a confident pitch, there is not enough voice here
#: to say anything. A stem that is mostly separation residue lands here.
MIN_VOICED_FRACTION = 0.10

#: Fewest voiced frames worth reporting a median over. The probe worked with 2,900-4,300
#: per 28 seconds, so this is a floor against a near-empty stem rather than a real
#: sample-size rule.
MIN_VOICED_FRAMES = 400

#: How concentrated the pitch has to be around *some* grid before this is a sung vocal.
#:
#: The resultant length of the circular mean over cents-modulo-a-semitone: 1 when every
#: frame sits on the same point of the semitone, 0 when they are spread uniformly, which
#: is what speech looks like. Measured:
#:
#:     a rapped vocal                      R = 0.027
#:     an electro vocal, also not sung     R = 0.130
#:     a synthesised line, 15 cents loose  R = 0.672
#:     a synthesised line, dead on pitch   R = 0.911
#:
#: **0.25, and the number moved once already.** It was 0.35 until a synthesised singer at
#: 22 cents of scatter measured R = 0.26 and was told it was a rap - which is the card's
#: own named harm pointed the other way. For a wrapped normal, R is `exp(-sigma^2 / 2)`
#: in angular terms, so 0.35 corresponds to about 23 cents of scatter and 0.25 to about
#: 26: the first refuses a loose singer, the second clears one.
#:
#: **There is a grey zone and it is not resolved.** The two measured raps sit at 0.03 and
#: 0.13, so 0.25 clears both by a comfortable margin - but the probe's rapped vocal had a
#: 26-cent median, which is exactly where this threshold lands. A vocal scattering
#: between roughly 20 and 30 cents could be a loose singer or a melodic rap, and nothing
#: available here separates them. X0R-306's eval set is what would; until then the gate
#: errs toward answering, because withholding a finding is a smaller wrong than telling
#: somebody their singing is not singing.
#:
#: The gate is deliberately **not** the centredness figure itself. Gating a measurement
#: on the measurement would relabel every high reading as "not sung" and guarantee the
#: metric never disagreed with itself, which is not a gate, it is a tautology.
#:
#: R earns its place twice over, because it is also the confidence in the tuning
#: reference. On the rapped vocal above, where R is 0.027, the estimated A4 came back as
#: 449.3 Hz - 36 cents sharp, and meaningless, because a circular mean over a nearly
#: uniform distribution points nowhere. The number that says "this is not sung" is the
#: same number that says "and so this record's tuning cannot be read either".
MIN_CONCENTRATION = 0.25

#: Below this difference in median cents, two vocals are as close to their own grids as
#: each other and there is nothing to report.
#:
#: Every other dimension in `instrument` has one of these - `SAME_LEVEL_DB`,
#: `SAME_BAND_DB`, `SAME_CREST_DB` - and this one went in without it, which showed up as
#: a track compared against *itself* producing a row that said the reference's vocal sat
#: further from the grid than its own, by zero cents. Three is chosen against what the
#: measurement can actually resolve: the probe's discriminating case was 4.0 against
#: 14.0 cents, and pitch tracking through separation has at least a couple of cents of
#: error of its own.
SAME_CENTS = 3.0


@dataclass(slots=True)
class Tuning:
    """What one stem's pitch contour says about the record it came from."""

    #: The record's own A4, in Hz, and how far that is from concert pitch.
    a4_hz: float
    a4_cents: float
    #: Median and 90th percentile of |cents from that record's own grid|.
    median_cents: float
    p90_cents: float
    voiced_frames: int
    voiced_fraction: float
    #: Resultant length of the circular mean, 0 to 1. The sung/not-sung gate, and the
    #: confidence in `a4_hz` - they are the same quantity.
    concentration: float
    #: False when this is not a sung vocal, or when there is too little voice to tell.
    sung: bool
    #: Why not, when `sung` is False. Empty otherwise.
    declined: str = ""


def contour(samples: np.ndarray, sample_rate: int):
    """Frame-level pitch in Hz and a voicing flag, from two estimators.

    See the note on `MIN_VOICED_FRACTION` above for why this is two calls rather than
    one: pYIN decides *whether* there is a pitch, which it does well at its default
    resolution and badly at a fine one, and `yin` says *what* the pitch is, continuously.
    """
    import librosa

    audio = np.asarray(samples, dtype=np.float64)
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    _, voiced, _ = librosa.pyin(y=mono, fmin=FMIN_HZ, fmax=FMAX_HZ, sr=sample_rate)
    f0 = librosa.yin(y=mono, fmin=FMIN_HZ, fmax=FMAX_HZ, sr=sample_rate)
    length = min(len(f0), len(voiced))
    return f0[:length], voiced[:length]


def _cents_from_a440(f0: np.ndarray) -> np.ndarray:
    return 1200.0 * np.log2(f0 / 440.0)


def concentration(cents: np.ndarray) -> float:
    """How tightly the pitches cluster on *some* grid, from 0 to 1.

    The resultant length of the same circular mean `tuning_reference` takes the angle of.
    A sung line returns to the same points of the scale and piles up near one phase; a
    spoken or rapped line glides through every phase equally and cancels to nothing.
    """
    if not len(cents):
        return 0.0
    offsets = ((cents + 50.0) % 100.0) - 50.0
    return float(np.abs(np.mean(np.exp(2j * np.pi * offsets / 100.0))))


def tuning_reference(cents: np.ndarray) -> float:
    """The record's own tuning, as cents from A440, in the range (-50, +50].

    A *circular* mean, because the quantity is cents-from-the-nearest-semitone and that
    wraps at 50: a record 49 cents sharp and one 49 cents flat are one cent apart, not
    ninety-eight, and an ordinary mean of the two would report 0 - exactly concert pitch,
    from two records that are as far from it as it is possible to get.
    """
    offsets = ((cents + 50.0) % 100.0) - 50.0
    angle = np.angle(np.mean(np.exp(2j * np.pi * offsets / 100.0)))
    return float(angle * 100.0 / (2.0 * np.pi))


def measure(samples: np.ndarray, sample_rate: int) -> Tuning | None:
    """Everything this module knows about one stem, or None when it cannot read it."""
    f0, voiced = contour(samples, sample_rate)
    if f0 is None or not len(f0):
        return None

    usable = voiced & np.isfinite(f0) & (f0 > 0)
    frames, total = int(np.sum(usable)), int(len(f0))
    fraction = frames / total if total else 0.0

    def declining(why: str, spread: float = 0.0) -> Tuning:
        return Tuning(
            a4_hz=0.0, a4_cents=0.0, median_cents=0.0, p90_cents=0.0,
            voiced_frames=frames, voiced_fraction=round(fraction, 3),
            concentration=round(spread, 3), sung=False, declined=why,
        )

    if frames < MIN_VOICED_FRAMES or fraction < MIN_VOICED_FRACTION:
        return declining(
            f"only {frames} frames of this stem carry a pitch, which is not enough to "
            "say anything about tuning"
        )

    cents = _cents_from_a440(f0[usable])
    spread = concentration(cents)
    if spread < MIN_CONCENTRATION:
        # A rap is not out of tune, and neither is a spoken word. Without this the app
        # calls a rapper flat, which is the one way this card could insult somebody.
        return declining(
            f"this part does not hold pitches on a scale (concentration {spread:.2f}, "
            f"against {MIN_CONCENTRATION:.2f} for a sung line), so it is spoken, rapped "
            "or not a voice at all - and none of those can be in or out of tune",
            spread,
        )

    offset = tuning_reference(cents)
    # Distance from *this record's* grid, wrapped into the half-semitone either side.
    deviation = ((cents - offset + 50.0) % 100.0) - 50.0

    return Tuning(
        a4_hz=round(float(440.0 * 2.0 ** (offset / 1200.0)), 1),
        a4_cents=round(offset, 1),
        median_cents=round(float(np.median(np.abs(deviation))), 1),
        p90_cents=round(float(np.percentile(np.abs(deviation), 90)), 1),
        voiced_frames=frames,
        voiced_fraction=round(fraction, 3),
        concentration=round(spread, 3),
        sung=True,
    )
