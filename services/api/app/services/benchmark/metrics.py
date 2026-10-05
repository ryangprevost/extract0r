"""How good is it, in numbers somebody else could reproduce.

Sprint 1 finished with every backend running and nobody able to say whether any of it was
accurate. The end-to-end run returned a bass line an octave high and a tempo of 60 against
a true 120 - and a controlled check showed pYIN reads those notes correctly from the
*unseparated* signal, so the fault was in feeding Demucs synthetic sine waves it was never
trained on. That is the lesson this module is built around: **synthetic audio exercises
the wiring and measures nothing.** Every number here is only as good as the recording it
was computed from, and `eval_set` is where that is kept honest.

Synthetic audio is exactly right for one job, though, and it is the job the tests do:
proving the ruler. A signal whose SDR is known by construction says whether
`separation_scores` reports it, and that question has nothing to do with Demucs.

**Nothing here is a metric of my own invention.** SDR, SIR and SAR come from `mir_eval`'s
BSS Eval, and the note scores from its transcription module - both are the implementations
the literature is written against, so a number from here can be put next to a number from
a paper. What this module contributes is the four decisions around them, each of which can
silently turn a benchmark into a vanity metric.

**On `mir_eval.separation`, which is deprecated.** It is removed in mir_eval 0.9, and
upstream recommends sigsep-museval - the SiSEC evaluator, whose BSS Eval v4 numbers would
be directly comparable with the published MUSDB18 leaderboard. That comparability is the
*only* thing it buys, and it cashes solely on MUSDB18's own test set. Nothing this project
scores is MUSDB18: the eval sets it is built for are a DI bass, a DI guitar, four isolated
drum mics and a sung vocal, and for none of those does a published number exist to compare
with. What those need is a convention held *fixed* between runs, which a pin gives for
free, rather than a convention that is standard.

So museval is deferred rather than rejected, and the decision is written where somebody
will be standing when they try to undo it - the pin comments in both requirements files,
which also name the two conditions that would make it right. X0R-308 is the card. The
whole BSS call is `_bss` below, so the migration stays one function rather than an
archaeology project.

**1. The permutation is fixed.** `bss_eval_sources` will by default try every assignment
of estimates to references and keep the best. That is right for blind separation, where
the sources come out unlabelled, and wrong here: a model that put the bass in the `other`
file would score as if it had not. We know which stem is which, so we say so.

**2. It is scored in windows, and the median is reported.** BSS Eval solves a least-
squares projection whose cost grows with the square of the signal length; on a three-minute
stereo track it is minutes of work and gigabytes of memory. Thirty-second windows are what
SiSEC uses, and the median across them is more robust than the mean to the one window
where a stem happens to be silent.

**3. Silent references are dropped by name, not quietly.** A reference stem of digital
silence makes SDR undefined - the projection has nothing to project onto. Dropping it is
correct and hiding the drop is not: a benchmark that silently scored four stems while
claiming six would read as a good result.

**4. Cents accuracy is measured on onset-matched notes, not on pitch-matched ones.** This
is the subtle one. The obvious implementation asks `precision_recall_f1_overlap` for its
matches and measures the pitch distance across them - but that function only calls two
notes a match when they are already within `pitch_tolerance`, so the answer is bounded by
the tolerance and means nothing. Matching on *onset* and then measuring pitch is the
question actually worth asking: for the notes it found at the right time, how far off was
it?
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)

#: Thirty seconds at 44.1 kHz, and fifteen seconds of hop. SiSEC's window, for the reason
#: in point 2 above. Not in samples-per-second terms because `mir_eval` wants samples.
WINDOW_SAMPLES = 30 * 44100
HOP_SAMPLES = 15 * 44100

#: Below this a reference stem is digital silence rather than a quiet part, and BSS Eval
#: has nothing to project onto. Peak rather than RMS: a stem holding one short note is not
#: silent, and an RMS test over three minutes would call it so.
SILENT_PEAK = 1e-6

#: How far apart two onsets may be and still be the same note. `mir_eval`'s default, which
#: is also MIREX's, so the numbers stay comparable with published ones.
ONSET_TOLERANCE_S = 0.05

#: How far apart two pitches may be and still be the same note, in cents. Half a semitone,
#: `mir_eval`'s default.
PITCH_TOLERANCE_CENTS = 50.0

#: The octave every pitch is folded into for the octave-tolerant score. Arbitrary - only
#: the fact that both sides are folded the same way matters.
FOLD_OCTAVE = 5


@dataclass(slots=True)
class SeparationScore:
    """BSS Eval for one stem, in the three numbers that mean different things.

    `sdr` is the overall distortion, which is the headline. `sir` is how much of the
    *other* sources leaked in, and is the number this project needs most: it is the bleed
    figure that per-drum comparison has been caveating without a measurement behind it.
    `sar` is how much of what is wrong is the model's own artefacts rather than leakage.

    A stem that scores a good SDR and a poor SIR is bleeding; one with a good SIR and a
    poor SAR is inventing. They want different fixes, which is why one number will not do.
    """

    stem: str
    sdr_db: float
    sir_db: float
    sar_db: float
    #: How many thirty-second windows the medians were taken across.
    windows: int = 0


@dataclass(slots=True)
class TranscriptionScore:
    """How well the notes came back, and - separately - how well the pitches did.

    `f1` and `f1_octave_tolerant` differ by exactly one failure, and it is the classic
    one: a pitch tracker that is right about the note and wrong about the register. A big
    gap between them says the transcriber hears the music and cannot place it; no gap says
    the errors are somewhere else entirely.
    """

    stem: str
    precision: float
    recall: float
    f1: float
    #: The same score with every pitch folded into one octave first.
    f1_octave_tolerant: float
    notes_reference: int
    notes_estimated: int
    #: Mean absolute and 95th-percentile pitch error over onset-matched notes, in cents.
    #: `None` when nothing matched - which is itself worth seeing, and is not zero.
    cents_mae: float | None = None
    cents_p95: float | None = None
    matched_notes: int = 0


@dataclass(slots=True)
class Speed:
    """Wall clock, as the multiple of real time anybody actually plans around."""

    label: str
    audio_seconds: float
    wall_seconds: float
    #: Audio length over wall clock. Above 1 is faster than real time.
    realtime_multiple: float
    notes: list[str] = field(default_factory=list)


# --- separation ---------------------------------------------------------------------


def _mono(samples: np.ndarray) -> np.ndarray:
    audio = np.asarray(samples, dtype=np.float64)
    return audio.mean(axis=1) if audio.ndim > 1 else audio


def separation_scores(
    references: dict[str, np.ndarray],
    estimates: dict[str, np.ndarray],
    window_samples: int = WINDOW_SAMPLES,
    hop_samples: int = HOP_SAMPLES,
) -> tuple[list[SeparationScore], list[str]]:
    """SDR, SIR and SAR per stem, plus a line per stem that could not be scored.

    Mono, because BSS Eval's source formulation is per-channel and running it twice to
    average two numbers that differ by a fraction of a decibel is not worth four times the
    runtime. Said here rather than assumed, because a stereo-aware variant
    (`bss_eval_images`, which museval uses) gives slightly different figures and anybody
    comparing with a published number needs to know which was run.

    Returns the scores and the skipped stems, never raising on a bad stem: one silent
    reference should cost its own row, not the whole benchmark.
    """
    skipped: list[str] = []
    usable: list[str] = []
    for stem in references:
        if stem not in estimates:
            skipped.append(f"{stem}: the separator produced no such stem")
            continue
        if float(np.abs(_mono(references[stem])).max(initial=0.0)) < SILENT_PEAK:
            skipped.append(f"{stem}: the reference is silent, so SDR is undefined")
            continue
        if float(np.abs(_mono(estimates[stem])).max(initial=0.0)) < SILENT_PEAK:
            skipped.append(f"{stem}: the estimate is silent, so SDR is undefined")
            continue
        usable.append(stem)

    if len(usable) < 2:
        # SIR is "how much of the *other* sources is in this one". With one source there
        # are no others, and mir_eval returns infinity - a number that would read as a
        # perfect result rather than as a missing comparison.
        skipped.append(
            f"scored {len(usable)} stem(s); BSS Eval needs at least two, because SIR is "
            "about the other sources"
        )
        return [], skipped

    length = min(
        min(len(_mono(references[s])) for s in usable),
        min(len(_mono(estimates[s])) for s in usable),
    )
    reference = np.stack([_mono(references[s])[:length] for s in usable])
    estimate = np.stack([_mono(estimates[s])[:length] for s in usable])

    # Silenced narrowly, and only here. `mir_eval.separation` warns on every call that
    # it is deprecated; the decision about that is recorded in this module's docstring
    # and enforced by a pin in requirements-ml.txt, so repeating it once per stem per
    # track is noise an operator cannot act on. The pin is what stops it being forgotten.
    with warnings.catch_warnings():
        # Matched on the message, not on the module: mir_eval warns with a `stacklevel`
        # that attributes it to this file, so a module filter would never fire.
        warnings.filterwarnings(
            "ignore", category=FutureWarning, message=r"mir_eval\.separation.*"
        )
        scores, unscored = _bss(reference, estimate, usable, window_samples, hop_samples)
    return scores, skipped + unscored


def _bss(reference, estimate, usable, window_samples, hop_samples):
    import mir_eval

    length = reference.shape[1]
    if length <= window_samples:
        # Short enough to score in one go, which also avoids a framewise call that would
        # return a single window and the same answer more slowly.
        sdr, sir, sar, _ = mir_eval.separation.bss_eval_sources(
            reference, estimate, compute_permutation=False
        )
        windows = 1
        sdr, sir, sar = (np.atleast_1d(v) for v in (sdr, sir, sar))
    else:
        sdr, sir, sar, _ = mir_eval.separation.bss_eval_sources_framewise(
            reference,
            estimate,
            window=window_samples,
            hop=hop_samples,
            compute_permutation=False,
        )
        windows = int(np.asarray(sdr).shape[-1])
        # A window where a source is silent comes back NaN. The median across the rest is
        # the figure; a mean would be pulled around by the one quiet bar. The warning is
        # expected rather than exceptional - a part that does not play in every bar is a
        # normal arrangement, not a problem.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="All-NaN slice", category=RuntimeWarning)
            sdr, sir, sar = (np.nanmedian(np.asarray(v), axis=-1) for v in (sdr, sir, sar))

    scores, unscored = [], []
    for index, stem in enumerate(usable):
        values = (float(sdr[index]), float(sir[index]), float(sar[index]))
        if not all(np.isfinite(v) for v in values):
            # A stem silent in every window. Printing "nan" in a results table is worse
            # than printing nothing, because a reader has to work out which of several
            # things went wrong before they can ignore it.
            unscored.append(
                f"{stem}: silent in every window scored, so there is no median to report"
            )
            continue
        scores.append(
            SeparationScore(
                stem=stem,
                sdr_db=round(values[0], 2),
                sir_db=round(values[1], 2),
                sar_db=round(values[2], 2),
                windows=windows,
            )
        )
    return scores, unscored


def reconstruction_db(mixture: np.ndarray, estimates: dict[str, np.ndarray]) -> float:
    """How far the stems sum away from the track they came out of, in dB.

    The one quality figure that needs **no ground truth at all**, which is what makes it
    worth having: it can be computed on every track anybody ever runs, including the song
    a user uploaded five minutes ago. Separation is not lossless, and this is the size of
    what was lost - energy the model dropped or invented, relative to the mixture.

    It is also the number `pipeline.preserve_source` exists because of. The mix is built
    by applying the stems' *changes* to the original rather than by summing the stems,
    precisely so that this residual stays out of anything the user did not ask to change.

    **It is not a substitute for SDR, and the difference is not subtle.** A separator that
    put the entire bass in the vocals file would reconstruct the mixture perfectly and
    score well here while being useless. This bounds how much was lost; it says nothing
    about whether what survived went in the right file. Reported alongside SDR where
    there is ground truth, and alone where there is not - clearly labelled as the weaker
    question.

    Returned as residual-to-mixture, so **more negative is better**: -25 dB means what
    the stems failed to account for sits 25 dB under the track.
    """
    mix = _mono(mixture)
    if not estimates:
        return 0.0
    length = min([len(mix)] + [len(_mono(e)) for e in estimates.values()])
    total = np.zeros(length)
    for estimate in estimates.values():
        total += _mono(estimate)[:length]

    residual = mix[:length] - total
    mix_rms = float(np.sqrt(np.mean(mix[:length] ** 2)))
    if mix_rms < SILENT_PEAK:
        return 0.0
    return round(
        20.0 * np.log10(max(float(np.sqrt(np.mean(residual**2))), 1e-20) / mix_rms), 2
    )


# --- transcription ---------------------------------------------------------------------


def _intervals_and_pitches(notes) -> tuple[np.ndarray, np.ndarray]:
    """`NoteEvent`s as the two arrays `mir_eval` wants: seconds, and Hz.

    Hz rather than MIDI because that is what its pitch tolerance is expressed against -
    fifty cents is a ratio, not a number of semitones.
    """
    if not notes:
        return np.zeros((0, 2)), np.zeros(0)
    intervals = np.array([[n.start_s, max(n.end_s, n.start_s + 1e-4)] for n in notes])
    pitches = np.array([440.0 * 2.0 ** ((n.pitch - 69) / 12.0) for n in notes])
    return intervals, pitches


def _folded(notes):
    """The same notes with every pitch moved into one octave.

    This is what "octave tolerance" means in practice, and it is deliberately crude: two
    notes an octave apart become the same note, so a transcriber that got the register
    wrong scores as if it had not. Crude is the point - the gap between the folded score
    and the plain one *is* the octave-error rate.

    One honest caveat: folding can collapse two different notes sounding together into
    one pitch, which makes a chord slightly easier to match. Real on polyphonic material,
    negligible on the monophonic stems this metric is most useful for.
    """
    from dataclasses import replace

    return [replace(n, pitch=FOLD_OCTAVE * 12 + (n.pitch % 12)) for n in notes]


def transcription_score(
    stem: str,
    reference_notes,
    estimated_notes,
    onset_tolerance_s: float = ONSET_TOLERANCE_S,
    pitch_tolerance_cents: float = PITCH_TOLERANCE_CENTS,
) -> TranscriptionScore:
    """Note-level precision, recall and F1, with and without the octave, plus cents.

    Offsets are not scored. `offset_ratio=None` turns that off in `mir_eval`, and it is
    the right call here: none of this project's transcribers claims to know when a note
    stopped - pYIN's offsets come from a voicing decision and basic-pitch's from a
    threshold - so scoring them would measure a thing nobody is trying to get right and
    drag every F1 down by a constant nobody could act on.
    """
    import mir_eval

    ref_intervals, ref_pitches = _intervals_and_pitches(reference_notes)
    est_intervals, est_pitches = _intervals_and_pitches(estimated_notes)

    def score(ref_i, ref_p, est_i, est_p) -> tuple[float, float, float]:
        if not len(ref_i) or not len(est_i):
            return 0.0, 0.0, 0.0
        precision, recall, f1, _ = mir_eval.transcription.precision_recall_f1_overlap(
            ref_i,
            ref_p,
            est_i,
            est_p,
            onset_tolerance=onset_tolerance_s,
            pitch_tolerance=pitch_tolerance_cents,
            offset_ratio=None,
        )
        return float(precision), float(recall), float(f1)

    precision, recall, f1 = score(ref_intervals, ref_pitches, est_intervals, est_pitches)

    folded_ref_i, folded_ref_p = _intervals_and_pitches(_folded(reference_notes))
    folded_est_i, folded_est_p = _intervals_and_pitches(_folded(estimated_notes))
    _, _, f1_octave = score(folded_ref_i, folded_ref_p, folded_est_i, folded_est_p)

    cents_mae, cents_p95, matched = _cents(
        ref_intervals, ref_pitches, est_intervals, est_pitches, onset_tolerance_s
    )

    return TranscriptionScore(
        stem=stem,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        f1_octave_tolerant=round(f1_octave, 4),
        notes_reference=len(reference_notes),
        notes_estimated=len(estimated_notes),
        cents_mae=cents_mae,
        cents_p95=cents_p95,
        matched_notes=matched,
    )


def _cents(
    ref_intervals, ref_pitches, est_intervals, est_pitches, onset_tolerance_s: float
) -> tuple[float | None, float | None, int]:
    """Pitch error in cents over notes matched by **onset alone**.

    Point 4 of the module docstring, and the reason this is not three lines inside
    `transcription_score`: matching on pitch and then measuring pitch is circular, and the
    circularity is invisible in the output - it just produces a reassuringly small number
    bounded by whatever tolerance was passed in.
    """
    import mir_eval

    if not len(ref_intervals) or not len(est_intervals):
        return None, None, 0

    matches = mir_eval.transcription.match_note_onsets(
        ref_intervals, est_intervals, onset_tolerance=onset_tolerance_s
    )
    if not matches:
        return None, None, 0

    errors = np.array(
        [
            1200.0 * np.log2(est_pitches[estimated] / ref_pitches[reference])
            for reference, estimated in matches
        ]
    )
    return (
        round(float(np.mean(np.abs(errors))), 1),
        round(float(np.percentile(np.abs(errors), 95)), 1),
        len(matches),
    )


# --- speed -------------------------------------------------------------------------


def speed(label: str, audio_seconds: float, wall_seconds: float, notes=None) -> Speed:
    """A realtime multiple, which is the only form of this number anybody plans around.

    "Ninety seconds" means nothing without the length of the song. "0.6x real time" means
    a four-minute track takes about seven minutes, which is a decision somebody can make.
    """
    audio_seconds = max(float(audio_seconds), 0.0)
    wall_seconds = max(float(wall_seconds), 1e-9)
    return Speed(
        label=label,
        audio_seconds=round(audio_seconds, 2),
        wall_seconds=round(wall_seconds, 2),
        realtime_multiple=round(audio_seconds / wall_seconds, 3),
        notes=list(notes or []),
    )
