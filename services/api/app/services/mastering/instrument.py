"""One instrument, measured the way a mix note describes it - and the same instrument in
a reference, so the two can be put side by side.

`stem_match` already moves a stem toward its counterpart on level, tone and width, but it
does it as one opaque operation: three checkboxes, all or nothing, and a matching curve
with hundreds of bins that nobody can look at and agree or disagree with. This module
answers a different question - *what is different about your snare and that record's, in
words, with a number and a dial per difference* - so each one can be taken or left on its
own.

Six dimensions, and the honest status of each:

* **Level** - where the instrument sits against its own mix. Relative, always: the
  absolute loudness of a reference's bass stem is a fact about how loud that record was
  mastered, not about how its bass was balanced.
* **Tone** - five bands, each measured against the stem's own total, so this is shape and
  not level. Applied by solving for the filter gains that produce the asked-for band
  change rather than assuming a bell centred at 250 Hz moves the 120-500 Hz band by its
  own gain. It does not; it moves it by about two thirds.
* **Dynamics** - dynamic range, per `dynamics`. What compression changes.
* **Punch** - crest within the loud material. What compression changes *differently*:
  two stems can share a dynamic range and have completely different transients.
* **Panning** - stereo balance. Offered quietly, because a reference stem sitting off
  centre is usually a deliberate arrangement choice rather than a mistake to copy.
* **Width** - how far the instrument spreads. Never applied to bass.

**Saturation is not in the list, and cannot be.** Distortion adds harmonics at multiples
of what is already there, so separating "this guitar was driven" from "this guitar was
playing a brighter chord voicing" needs the undistorted signal for comparison, which by
definition does not exist. What is measurable is brightness, which is in the tone bands
already. Per-stem drive stays a control the ear sets, not a number this file invents.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.domain.notes import StemKind
from app.services.mastering.dsp import (
    DEFAULT_HOP,
    DEFAULT_N_FFT,
    apply_curve,
    apply_gain_db,
    average_spectrum,
    set_width,
    stereo_width,
)
from app.services.mastering.dynamics import (
    MAX_COMPRESSION_DB,
    compress,
    crest_db,
    dynamic_range_db,
    loudest_window_s,
)
from app.services.mastering.loudness_meter import integrated_loudness
from app.services.mastering.polish import bell_ramp, shelf_ramp
from app.services.mixdown.encode import apply_pan, mix_buffers, read_audio

log = logging.getLogger(__name__)

#: The five bands every tone comparison is expressed in. Wide on purpose: a comparison
#: between two different songs cannot support narrow bands, because the difference between
#: a third-octave slice of your chorus and a third-octave slice of theirs is mostly the
#: difference between the two chords being played.
BANDS: tuple[tuple[str, float, float], ...] = (
    ("low", 20.0, 120.0),
    ("low_mid", 120.0, 500.0),
    ("high_mid", 500.0, 3000.0),
    ("presence", 3000.0, 8000.0),
    ("air", 8000.0, 16000.0),
)

BAND_WORDS: dict[str, str] = {
    "low": "weight",
    "low_mid": "body",
    "high_mid": "midrange",
    "presence": "presence",
    "air": "air",
}

#: The filter that moves each band. A shelf at the ends, where there is nothing beyond to
#: protect, and a bell in the middle, where there is.
BASIS: tuple[tuple[str, str, float], ...] = (
    ("low", "low_shelf", 120.0),
    ("low_mid", "bell", 250.0),
    ("high_mid", "bell", 1200.0),
    ("presence", "bell", 5000.0),
    ("air", "high_shelf", 9000.0),
)

#: How far a nudge goes: the share of the measured gap a suggestion actually asks for.
#:
#: This is the most important number in the file and it used to be 1.0 - close the gap
#: completely, make the stem measure like the reference's. On a real song that produced a
#: master the user could not recognise as his own song, and he was right. Two records are
#: not two takes of the same arrangement. A reference whose guitars sit 9 dB hotter than
#: yours may simply be a wall-of-guitars record where yours is not, and "fixing" that is
#: not mixing advice, it is replacing the arrangement with somebody else's.
#:
#: Half the gap moves a mix audibly toward a reference while leaving it recognisably the
#: same record - which is the whole brief: a nudge in the direction of the thing you
#: admire, not a carbon copy of it.
NUDGE_SHARE = 0.5

#: How far one band may be moved on one stem, after the nudge share is applied. Three dB
#: is already a large EQ move on a single instrument; the previous six let a single band
#: rewrite what the instrument sounded like.
MAX_BAND_DB = 2.5

#: How much shape change one stem may be asked to take in total, summed across the five
#: bands. Without a budget, a stem whose balance differs wholesale from the reference's
#: asks for the per-band maximum in every band at once - a real drum stem asked for +3 dB
#: in four bands simultaneously, which is not an EQ move, it is a different drum sound.
#: Over budget, every band is scaled down together so the *shape* of the request survives
#: and only its size changes.
TONE_BUDGET_DB = 5.0

#: Ridge term for the tone solve, and the fix for a specific complaint: masters that came
#: back "swirly", "hollow" and "muddy".
#:
#: The exact solve does hit its band targets, and the price is wild disagreement between
#: neighbouring filters - asking for +3 dB of presence produced +3.55 on the presence bell
#: and -2.02 on the air shelf, a 5.6 dB swing between two overlapping filters, which is a
#: crude comb and sounds like one. Penalising large gains trades exactness for smoothness:
#: at 0.35 the worst adjacent swing falls from 5.6-8.1 dB to 2.9-4.4 dB while still
#: delivering about 70% of the requested shape. The remaining 30% is not a bug to fix -
#: the whole point is a gentle nudge, and a smooth curve that moves a little is worth more
#: than an exact one that phases.
TONE_REGULARISATION = 0.35

#: Below this the difference is not worth a row on the screen.
SAME_BAND_DB = 1.0
SAME_LEVEL_DB = 1.0
SAME_RANGE_DB = 1.5
SAME_CREST_DB = 2.0
SAME_PAN = 0.08
SAME_WIDTH_RATIO = 0.15

#: Below this a stem is mono in every sense that matters, and the ratio between two such
#: measurements is noise. A real drum stem measured 0.06 against a reference's 0.08 - a
#: ratio of 1.39, which the comparison offered as "widen these by 39%" on the strength of
#: two hundredths of absolute width. Both were mono kick-and-snare stems and neither had
#: any width to compare.
MIN_MEANINGFUL_WIDTH = 0.15

#: A band holding less than this share of a stem does not contain the instrument; it
#: contains what leaked in from the others. Measured on a real song: a vocal stem held
#: 0.04% of its energy below 120 Hz and a guitar stem 0.07%, which is correct - neither
#: instrument lives there. The reference's vocal held 0.35%, so the comparison asked to
#: lift the band by 9.5 dB, and taking it would have raised nothing but kick bleed and
#: rumble. Cuts are left alone: removing what is not there costs nothing.
QUIET_BAND_DB = -30.0

#: How far a stem's fader may be moved. Was 9 dB, matching `stem_match`, and that is far
#: too much: 9 dB up on the guitars against 4 dB down on the bass is a 13 dB swing between
#: two instruments, which is not a correction, it is a different mix.
MAX_LEVEL_DB = 3.0

#: Past this, a level difference between the same instrument on two records is much more
#: likely to be a difference of arrangement - or of which bucket separation chose to put
#: something in - than a mixing mistake. Measured on a real pair: the user's guitar stem
#: sat 9.3 dB below the reference's, because the reference is a doubled-guitar record and
#: the user's lead part had been filed under `other`. Still reported, because it is true
#: and worth knowing, but flagged rather than offered as a confident fix.
LIKELY_ARRANGEMENT_DB = 6.0

#: How far `apply_shape` will move a level it is handed. Deliberately much wider than
#: MAX_LEVEL_DB, which is a limit on what this module will *suggest*. What the tool
#: proposes on its own and what a user is allowed to ask for by dragging a fader are two
#: different questions, and collapsing them would mean a suggestion limit silently
#: becoming a ceiling on the mixer.
MAX_APPLIED_GAIN_DB = 12.0

#: The same distinction for tone: how far a user may push a band by hand, against
#: MAX_BAND_DB which is how far this module will suggest pushing it.
MAX_APPLIED_BAND_DB = 6.0

#: Stereo limits. Narrowed from (0.6, 2.0) for the same reason as everything else here -
#: collapsing a part to 60% of its width is a drastic move to make on a measurement taken
#: from a different song.
WIDTH_LIMITS = (0.8, 1.35)

#: Bass and kick belong in the middle whatever the reference measures.
NEVER_MOVE_SIDEWAYS = (StemKind.BASS,)

#: A stem this far below its own mix is what separation leaves behind when the instrument
#: is not there, not the instrument. Matching to it would delete a part the user played.
ABSENT_BELOW_LU = -30.0


@dataclass(slots=True)
class InstrumentProfile:
    """Everything measured about one stem."""

    stem: StemKind
    #: Level against the mix this stem belongs to. The portable number.
    relative_lufs: float = 0.0
    loudness_lufs: float = 0.0
    #: Each band's energy against this stem's own total, in dB. Shape, not level.
    bands: dict[str, float] = field(default_factory=dict)
    dynamic_range_db: float = 0.0
    crest_db: float = 0.0
    #: -1 hard left, 0 centred, +1 hard right.
    pan: float = 0.0
    width: float = 1.0
    sample_rate: int = 44100
    #: Where the busiest stretch of this stem starts, for auditioning it. A preview that
    #: opens at 0:00 usually opens in an intro or in silence.
    preview_start_s: float = 0.0
    #: The averaged spectrum, kept so tone moves can be solved against real content.
    spectrum: np.ndarray | None = None
    #: False when this is separation residue rather than an instrument.
    present: bool = True


@dataclass(slots=True)
class InstrumentMove:
    """One difference between your instrument and the reference's, and the dial for it."""

    stem: str
    #: level | tone | dynamics | punch | pan | width
    dimension: str
    #: Which band, for tone moves. Empty otherwise.
    band: str = ""
    headline: str = ""
    detail: str = ""
    #: match | slight | notable | strong
    severity: str = "slight"
    yours: float = 0.0
    reference: float = 0.0
    #: The whole measured gap, before the nudge share and the clamp. Sent so the page can
    #: offer "go further" without paying for the comparison again, and so the difference
    #: between what was measured and what is being suggested stays visible.
    measured: float = 0.0
    #: What the control should be set to: part of the way toward the reference. See
    #: `_nudge` for why this is deliberately not the whole gap.
    suggested: float = 0.0
    #: The field on the stem's settings this writes to.
    control: str = ""
    #: True when the measurement is reliable enough to act on without listening first.
    confident: bool = True


# --- measuring -----------------------------------------------------------------------


def band_levels(
    spectrum: np.ndarray, sample_rate: int, n_fft: int = DEFAULT_N_FFT
) -> dict[str, float]:
    """Each band's share of this stem's energy, in dB.

    Normalised by the total so the result describes tone and not volume. Two takes of the
    same guitar at different fader positions measure identically here, which is the whole
    point - level has its own dimension.

    A tempting and wrong "fix", recorded so it is not attempted again. Because these are
    shares they must sum to one, from which it seems to follow that a gap vector asking to
    raise four bands at once is describing an impossible spectrum, and that the gaps should
    be made level-neutral by subtracting their mean. Checked against a real drum stem, that
    reasoning is backwards. The stem held 96.4% of its energy below 120 Hz, so raising the
    other four bands barely moves the total: applying the raw gaps renormalised the result
    by 0.03 dB and every band landed within 0.03 dB of what was asked. Subtracting the mean
    would instead have demanded a 9.8 dB cut of the low end, against a reference that has
    1.6 dB less of it. The raw gap is the right number; only the cap needs explaining.
    """
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    power = np.asarray(spectrum, dtype=np.float64) ** 2
    total = float(power.sum())
    if total <= 1e-20:
        return {name: -120.0 for name, _, _ in BANDS}

    out: dict[str, float] = {}
    for name, low, high in BANDS:
        mask = (freqs >= low) & (freqs < min(high, sample_rate / 2.0))
        share = float(power[mask].sum()) / total
        out[name] = round(float(10.0 * np.log10(max(share, 1e-12))), 2)
    return out


def balance(samples: np.ndarray) -> float:
    """Stereo balance from -1 to +1, from the two channels' energies."""
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim < 2 or audio.shape[1] < 2:
        return 0.0
    left = float(np.sqrt(np.mean(audio[:, 0] ** 2)))
    right = float(np.sqrt(np.mean(audio[:, 1] ** 2)))
    if left + right <= 1e-12:
        return 0.0
    return float(np.clip((right - left) / (right + left), -1.0, 1.0))


def profile(
    samples: np.ndarray,
    sample_rate: int,
    stem: StemKind,
    n_fft: int = DEFAULT_N_FFT,
    hop: int = DEFAULT_HOP,
) -> InstrumentProfile:
    """Measure one stem across every dimension at once."""
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)

    loudness, _ = integrated_loudness(audio, sample_rate)
    spectrum = average_spectrum(audio, n_fft, hop)
    return InstrumentProfile(
        stem=stem,
        loudness_lufs=float(loudness) if np.isfinite(loudness) else -120.0,
        bands=band_levels(spectrum, sample_rate, n_fft),
        dynamic_range_db=round(dynamic_range_db(audio, sample_rate), 2),
        crest_db=round(crest_db(audio), 2),
        pan=round(balance(audio), 3),
        width=round(stereo_width(audio), 3),
        sample_rate=sample_rate,
        preview_start_s=round(loudest_window_s(audio, sample_rate), 1),
        spectrum=spectrum,
    )


def profile_all(
    paths: dict[StemKind, Path], n_fft: int = DEFAULT_N_FFT, hop: int = DEFAULT_HOP
) -> dict[StemKind, InstrumentProfile]:
    """Measure every stem, and each one's level against their sum.

    Reads every stem in full. Sampling a window was tried in `stem_match` and abandoned on
    the numbers: it put the parts that come and go several dB out, which is enough to
    invent a finding.
    """
    profiles: dict[StemKind, InstrumentProfile] = {}
    buffers: list[np.ndarray] = []

    for stem, path in paths.items():
        if not Path(path).exists():
            continue
        try:
            buffer = read_audio(Path(path))
        except Exception:
            log.info("could not read the %s stem for profiling", stem.value, exc_info=True)
            continue
        one = profile(buffer.samples, buffer.sample_rate, stem, n_fft, hop)
        if one.loudness_lufs <= -119.0:
            continue  # silent
        profiles[stem] = one
        buffers.append(buffer.samples)

    if not buffers:
        return profiles

    mix = mix_buffers(buffers)
    rate = next(iter(profiles.values())).sample_rate
    mix_loudness, _ = integrated_loudness(mix, rate)
    if np.isfinite(mix_loudness):
        for one in profiles.values():
            one.relative_lufs = round(one.loudness_lufs - float(mix_loudness), 2)
            one.present = one.relative_lufs >= ABSENT_BELOW_LU
    return profiles


# --- tone: asking for a band change and getting it -------------------------------------


def _ramps(sample_rate: int, n_fft: int) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for name, kind, hz in BASIS:
        if kind == "bell":
            out[name] = bell_ramp(n_fft, sample_rate, hz, octaves=0.9)
        elif kind == "low_shelf":
            out[name] = shelf_ramp(n_fft, sample_rate, hz, octaves=1.0, kind="low")
        else:
            out[name] = shelf_ramp(n_fft, sample_rate, hz, octaves=1.0, kind="high")
    return out


def _band_masks(sample_rate: int, n_fft: int) -> dict[str, np.ndarray]:
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    return {
        name: (freqs >= low) & (freqs < min(high, sample_rate / 2.0))
        for name, low, high in BANDS
    }


def tone_matrix(
    sample_rate: int, spectrum: np.ndarray | None = None, n_fft: int = DEFAULT_N_FFT
) -> np.ndarray:
    """Band asked for, filter gains needed: the five by five that `tone_curve` inverts.

    Exposed because the browser needs it. The monitoring chain in the page runs the same
    five filters through Web Audio so a slider can be heard before anything is rendered,
    and if it set those filters to the raw band request it would be running a different EQ
    from the one the export applies - the preview would lie by about a third of every
    move. Sending the matrix lets the page do the identical solve on 25 floats.
    """
    ramps = _ramps(sample_rate, n_fft)
    masks = _band_masks(sample_rate, n_fft)
    names = [name for name, _, _ in BANDS]
    bins = len(next(iter(masks.values())))

    if spectrum is not None and len(spectrum) == bins:
        weight = np.asarray(spectrum, dtype=np.float64) ** 2
    else:
        weight = np.ones(bins, dtype=np.float64)

    matrix = np.zeros((len(names), len(names)), dtype=np.float64)
    for row, band in enumerate(names):
        share = weight[masks[band]]
        total = float(share.sum())
        for column, control in enumerate(names):
            if total <= 1e-20:
                matrix[row, column] = 1.0 if row == column else 0.0
            else:
                matrix[row, column] = float(
                    (ramps[control][masks[band]] * share).sum() / total
                )
    return matrix


def tone_solver(
    sample_rate: int, spectrum: np.ndarray | None = None, n_fft: int = DEFAULT_N_FFT
) -> np.ndarray:
    """The matrix that turns a band request into filter gains: `gains = solver @ wanted`.

    A ridge solve rather than an exact one - `(MᵀM + λI)⁻¹Mᵀ` rather than `M⁻¹`. See
    `TONE_REGULARISATION` for the measurements behind that choice; the short version is
    that the exact inverse is free to set neighbouring filters several dB against each
    other to hit a band target, and overlapping filters in opposition comb.

    Sent to the browser precomputed, so the monitor multiplies rather than solving. The
    page used to run its own Gaussian elimination on the raw matrix, which was correct
    right up until the server stopped solving it the same way.
    """
    matrix = tone_matrix(sample_rate, spectrum, n_fft)
    size = matrix.shape[0]
    damped = matrix.T @ matrix + TONE_REGULARISATION * np.eye(size)
    try:
        return np.linalg.solve(damped, matrix.T)
    except np.linalg.LinAlgError:  # pragma: no cover - damped, this cannot be singular
        return np.eye(size)


def tone_filter_gains(
    wanted: dict[str, float],
    sample_rate: int,
    spectrum: np.ndarray | None = None,
    n_fft: int = DEFAULT_N_FFT,
) -> dict[str, float]:
    """The gain each of the five filters needs, for the band change asked for."""
    names = [name for name, _, _ in BANDS]
    target = np.array([float(wanted.get(name, 0.0)) for name in names])
    if not np.any(target):
        return dict.fromkeys(names, 0.0)

    gains = tone_solver(sample_rate, spectrum, n_fft) @ target
    # Still clamped, as a backstop. With the ridge term in place this rarely binds.
    gains = np.clip(gains, -MAX_BAND_DB * 2.0, MAX_BAND_DB * 2.0)
    return {name: float(gain) for name, gain in zip(names, gains, strict=True)}


def within_budget(wanted: dict[str, float]) -> dict[str, float]:
    """Scale a whole stem's tone request down until it fits the budget.

    Proportionally, so the shape of the request is kept and only its size changes. A stem
    asking for +3 dB in four bands at once is not describing an EQ move, it is describing
    a different instrument, and the honest response is to move in that direction by less
    rather than to refuse.
    """
    total = sum(abs(value) for value in wanted.values())
    if total <= TONE_BUDGET_DB or total <= 0:
        return dict(wanted)
    scale = TONE_BUDGET_DB / total
    return {band: round(value * scale, 2) for band, value in wanted.items()}


def tone_curve(
    wanted: dict[str, float],
    sample_rate: int,
    spectrum: np.ndarray | None = None,
    n_fft: int = DEFAULT_N_FFT,
) -> np.ndarray:
    """A per-bin magnitude curve that moves each band by the dB asked for.

    The naive version - one bell per band, set to the gap - does not work, and the size of
    the error is not small. A bell at 250 Hz with 0.9 octaves of width covers rather less
    than the 120-500 Hz band it is responsible for, so asking for +3 dB of body delivers
    about +2. Worse, the filters overlap: the presence bell reaches into the air band, so
    five independent gains produce five wrong answers that each depend on the other four.

    So the gains are solved for. Build the matrix of how much one dB of each filter moves
    each band - weighted by the stem's own spectrum, because what a filter does to a band
    depends on where in that band the energy actually is - and invert it. Five by five;
    the cost is nothing and the control then reads true.

    One thing that looks like a bug in the measurements and is not. `band_levels` reports
    each band's *share* of the stem, so lifting one band lowers the other four by
    arithmetic alone. Asking for +3 dB of presence measures as +2.65 dB on presence and
    -0.34 dB on each of the others - a relative movement of 2.99 dB, which is the number
    that was asked for. The shares have to sum to one; a control that moved presence +3
    dB of share without moving anything else would be describing an impossible spectrum.
    Every test of this asserts the gap between the moved band and the rest, never the
    moved band on its own.
    """
    ramps = _ramps(sample_rate, n_fft)
    bins = len(next(iter(ramps.values())))
    if not any(wanted.values()):
        return np.ones(bins, dtype=np.float64)

    gains = tone_filter_gains(wanted, sample_rate, spectrum, n_fft)
    total_db = np.zeros(bins, dtype=np.float64)
    for name, gain in gains.items():
        total_db += gain * ramps[name]
    return 10.0 ** (total_db / 20.0)


def shape_tone(
    samples: np.ndarray,
    sample_rate: int,
    wanted: dict[str, float],
    spectrum: np.ndarray | None = None,
) -> np.ndarray:
    """Apply a band-by-band tone change to one stem."""
    if not any(wanted.values()):
        return np.asarray(samples, dtype=np.float64)
    curve = tone_curve(wanted, sample_rate, spectrum)
    return apply_curve(samples, curve, DEFAULT_N_FFT, DEFAULT_HOP)


# --- comparing --------------------------------------------------------------------------


def _nudge(gap: float, limit: float) -> float:
    """Part of the way toward the reference, never all of it.

    Every suggestion this module makes goes through here, which is the single place the
    difference between "move toward that record" and "measure like that record" lives.
    The second is what it used to do, and on a real song it produced a master its own
    author could not recognise.
    """
    return round(float(np.clip(gap * NUDGE_SHARE, -limit, limit)), 2)


def _severity(gap: float, slight: float, notable: float) -> str:
    size = abs(gap)
    if size < slight:
        return "match"
    if size < notable:
        return "slight"
    return "notable" if size < notable * 2 else "strong"


def compare(
    stem: StemKind,
    mine: InstrumentProfile,
    theirs: InstrumentProfile,
    words: tuple[str, bool] | None = None,
) -> list[InstrumentMove]:
    """Every difference between one instrument and its counterpart, with its dial.

    Returns nothing when either side does not really contain the instrument. A reference
    with no piano yields a piano stem 40 dB under its own mix, and matching to it would
    ask for a 40 dB cut - silencing a part the user played because the record they like
    happens not to have one.
    """
    if not mine.present or not theirs.present:
        return []

    name, plural = words or (stem.value, False)
    sits = "sit" if plural else "sits"
    verb = "are" if plural else "is"
    moves: list[InstrumentMove] = []

    # --- level ---------------------------------------------------------------
    gap = theirs.relative_lufs - mine.relative_lufs
    if abs(gap) >= SAME_LEVEL_DB:
        applied = _nudge(gap, MAX_LEVEL_DB)
        back = gap > 0
        # A very large level difference is far more likely to be a different arrangement,
        # or a different guess by the separator about which bucket a part belongs in, than
        # a mixing mistake worth copying.
        arrangement = abs(gap) >= LIKELY_ARRANGEMENT_DB
        aside = (
            f" A gap this size is usually a difference of arrangement rather than of "
            f"mixing - a record built on stacked {name} will measure like this against "
            f"one that is not, and separation may also have filed part of yours "
            f"elsewhere. Worth hearing both before you take it."
            if arrangement
            else ""
        )
        moves.append(
            InstrumentMove(
                stem=stem.value,
                dimension="level",
                headline=f"The reference's {name} {sits} {abs(gap):.1f} dB "
                f"{'further forward' if back else 'further back'}",
                detail=f"Yours {sits} {mine.relative_lufs:.1f} LU under its own mix; the "
                f"reference's {sits} {theirs.relative_lufs:.1f} LU under that one. "
                f"Measured against each mix's own level, so this is balance and not "
                f"which file is louder.{aside}",
                severity=_severity(gap, SAME_LEVEL_DB, 3.0),
                yours=mine.relative_lufs,
                reference=theirs.relative_lufs,
                measured=round(gap, 2),
                suggested=applied,
                control="gain_db",
                confident=not arrangement,
            )
        )

    # --- tone ---------------------------------------------------------------
    #
    # Nudged first, then budgeted as a set. The budget has to see the whole stem at once:
    # five bands each individually reasonable can still add up to a request to rebuild the
    # instrument, and scaling them one at a time would change the shape of the request
    # rather than its size.
    gaps = {
        band: theirs.bands.get(band, -120.0) - mine.bands.get(band, -120.0)
        for band, _, _ in BANDS
    }
    wanted = {
        band: _nudge(gap, MAX_BAND_DB)
        for band, gap in gaps.items()
        if abs(gap) >= SAME_BAND_DB
    }
    budgeted = within_budget(wanted)

    for band, _, _ in BANDS:
        if band not in budgeted:
            continue
        mine_db = mine.bands.get(band, -120.0)
        theirs_db = theirs.bands.get(band, -120.0)
        band_gap = gaps[band]
        applied = budgeted[band]
        if abs(applied) < 0.1:
            continue  # scaled down to nothing; not worth a row
        more = band_gap > 0
        word = BAND_WORDS[band]
        low, high = next((lo, hi) for n, lo, hi in BANDS if n == band)
        # Always say what was measured against what is being offered, because they are
        # deliberately different numbers now - the suggestion is half the gap, capped.
        # Without this the control looks like it is guessing rather than holding back.
        capped = (
            f" The gap measures {band_gap:+.1f} dB; this offers {applied:+.1f}, which is "
            f"a move in that direction rather than a copy of it."
            if abs(applied - band_gap) > 0.05
            else ""
        )
        if sum(abs(v) for v in wanted.values()) > TONE_BUDGET_DB:
            capped += (
                f" Held back further because this {name} differs from the reference's "
                f"across most of the spectrum, and re-EQing every band at once stops "
                f"being a nudge."
            )
        # Lifting a band your stem has almost nothing in does not lift the instrument -
        # it lifts whatever separation leaked into it. Flagged rather than withheld: the
        # measurement is real and the user may want it anyway, but not unheard.
        empty = more and mine_db < QUIET_BAND_DB
        if empty:
            capped += (
                f" Note that this band holds only {10 ** (mine_db / 10):.2%} of your "
                f"{name} - there is very little of the instrument down here, so lifting "
                f"it mostly lifts what leaked in from the other stems."
            )
        moves.append(
            InstrumentMove(
                stem=stem.value,
                dimension="tone",
                band=band,
                headline=f"The reference's {name} {'has' if not plural else 'have'} "
                f"{'more' if more else 'less'} {word}",
                detail=f"Between {_hz(low)} and {_hz(high)}, yours holds "
                f"{mine_db:.1f} dB of its own energy against the reference's "
                f"{theirs_db:.1f} dB. Each measured against its own stem, so this is "
                f"shape rather than level.{capped}",
                severity=_severity(band_gap, SAME_BAND_DB, 2.5),
                yours=mine_db,
                reference=theirs_db,
                measured=round(band_gap, 2),
                suggested=applied,
                control=f"tone_{band}_db",
                confident=not empty,
            )
        )

    # --- dynamics -----------------------------------------------------------
    if mine.dynamic_range_db > 0 and theirs.dynamic_range_db > 0:
        range_gap = mine.dynamic_range_db - theirs.dynamic_range_db
        if range_gap >= SAME_RANGE_DB:
            applied = _nudge(range_gap, MAX_COMPRESSION_DB)
            moves.append(
                InstrumentMove(
                    stem=stem.value,
                    dimension="dynamics",
                    headline=f"Your {name} {verb} less even than the reference's",
                    detail=f"Yours swings {mine.dynamic_range_db:.1f} dB between its "
                    f"quiet and loud stretches; the reference's swings "
                    f"{theirs.dynamic_range_db:.1f} dB. Compression closes that by "
                    f"holding the loud parts down and giving the level back.",
                    severity=_severity(range_gap, SAME_RANGE_DB, 4.0),
                    yours=mine.dynamic_range_db,
                    reference=theirs.dynamic_range_db,
                    measured=round(range_gap, 2),
                    suggested=applied,
                    control="compress_db",
                )
            )
        elif range_gap <= -SAME_RANGE_DB:
            moves.append(
                InstrumentMove(
                    stem=stem.value,
                    dimension="dynamics",
                    headline=f"Your {name} {verb} already more even than the "
                    f"reference's",
                    detail=f"Yours swings {mine.dynamic_range_db:.1f} dB against the "
                    f"reference's {theirs.dynamic_range_db:.1f}. There is nothing to "
                    f"compress here, and this tool cannot put range back.",
                    severity="slight",
                    yours=mine.dynamic_range_db,
                    reference=theirs.dynamic_range_db,
                    suggested=0.0,
                    control="",
                )
            )

    # --- punch ---------------------------------------------------------------
    crest_gap = theirs.crest_db - mine.crest_db
    if abs(crest_gap) >= SAME_CREST_DB:
        sharper = crest_gap > 0
        hits = "hit" if plural else "hits"
        moves.append(
            InstrumentMove(
                stem=stem.value,
                dimension="punch",
                headline=f"The reference's {name} {hits} "
                f"{'harder' if sharper else 'softer'}",
                detail=f"Peaks stand {theirs.crest_db:.1f} dB above the body of the "
                f"reference's {name} against {mine.crest_db:.1f} dB on yours. This is "
                f"about transients rather than balance: no dial here sharpens an attack "
                f"that was not recorded, so read it as a note about the playing and the "
                f"source, not a setting to change.",
                severity="slight",
                yours=mine.crest_db,
                reference=theirs.crest_db,
                suggested=0.0,
                control="",
                confident=False,
            )
        )

    # --- pan ---------------------------------------------------------------
    pan_gap = theirs.pan - mine.pan
    if abs(pan_gap) >= SAME_PAN and stem not in NEVER_MOVE_SIDEWAYS:
        moves.append(
            InstrumentMove(
                stem=stem.value,
                dimension="pan",
                headline=f"The reference's {name} {sits} further "
                f"{'right' if pan_gap > 0 else 'left'}",
                detail=f"Theirs balances at {_side(theirs.pan)} against yours at "
                f"{_side(mine.pan)}. Worth a listen before taking it: a part sitting off "
                f"centre on a record is usually a decision about that arrangement rather "
                f"than something yours is getting wrong.",
                severity="slight",
                yours=mine.pan,
                reference=theirs.pan,
                suggested=round(float(np.clip(mine.pan + pan_gap, -1.0, 1.0)), 3),
                control="pan",
                confident=False,
            )
        )

    # --- width ---------------------------------------------------------------
    both_have_width = (
        mine.width >= MIN_MEANINGFUL_WIDTH and theirs.width >= MIN_MEANINGFUL_WIDTH
    )
    if stem not in NEVER_MOVE_SIDEWAYS and both_have_width:
        ratio = theirs.width / mine.width
        if abs(ratio - 1.0) >= SAME_WIDTH_RATIO:
            factor = float(
                np.clip(1.0 + (ratio - 1.0) * NUDGE_SHARE, *WIDTH_LIMITS)
            )
            wider = ratio > 1.0
            moves.append(
                InstrumentMove(
                    stem=stem.value,
                    dimension="width",
                    headline=f"The reference's {name} {verb} "
                    f"{'wider' if wider else 'narrower'}",
                    detail=f"Yours measures {mine.width:.2f} across against the "
                    f"reference's {theirs.width:.2f}.",
                    severity=_severity(20.0 * np.log10(max(ratio, 1e-6)), 1.0, 3.0),
                    yours=mine.width,
                    reference=theirs.width,
                    measured=round(ratio, 3),
                    suggested=round(factor, 3),
                    control="width",
                )
            )
    elif stem in NEVER_MOVE_SIDEWAYS:
        pass  # the low end stays centred whatever the reference does

    return moves


def _hz(value: float) -> str:
    return f"{value / 1000:.0f} kHz" if value >= 1000 else f"{value:.0f} Hz"


def _side(pan: float) -> str:
    if abs(pan) < 0.03:
        return "centre"
    return f"{abs(pan) * 100:.0f}% {'right' if pan > 0 else 'left'}"


# --- applying ---------------------------------------------------------------------------


@dataclass(slots=True)
class StemShape:
    """Everything that can be done to one stem before it reaches the mix bus."""

    gain_db: float = 0.0
    pan: float = 0.0
    width: float = 1.0
    tone_low_db: float = 0.0
    tone_low_mid_db: float = 0.0
    tone_high_mid_db: float = 0.0
    tone_presence_db: float = 0.0
    tone_air_db: float = 0.0
    compress_db: float = 0.0
    saturation_db: float = 0.0

    def tone(self) -> dict[str, float]:
        return {
            "low": self.tone_low_db,
            "low_mid": self.tone_low_mid_db,
            "high_mid": self.tone_high_mid_db,
            "presence": self.tone_presence_db,
            "air": self.tone_air_db,
        }

    def is_identity(self) -> bool:
        return (
            not self.gain_db
            and not self.pan
            and self.width == 1.0
            and not any(self.tone().values())
            and not self.compress_db
            and not self.saturation_db
        )


def apply_shape(
    samples: np.ndarray,
    sample_rate: int,
    shape: StemShape,
    spectrum: np.ndarray | None = None,
) -> np.ndarray:
    """Run one stem through its shape, in the order a channel strip would.

    Tone before dynamics, because a compressor reacts to what it is fed and an EQ move of
    several dB changes what it reacts to. Drive after dynamics, because saturating a
    signal whose peaks are already held down is what makes it sound driven rather than
    clipped. Level and position last, where a fader and a pan pot are.
    """
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    if shape.is_identity():
        return audio

    if any(shape.tone().values()):
        audio = shape_tone(audio, sample_rate, shape.tone(), spectrum)

    if shape.compress_db:
        audio = compress(audio, sample_rate, shape.compress_db)

    if shape.saturation_db:
        from app.services.mastering.saturation import add_saturation

        audio = add_saturation(audio, sample_rate, shape.saturation_db)

    if shape.width != 1.0:
        audio = set_width(audio, float(np.clip(shape.width, *WIDTH_LIMITS)))

    if shape.pan:
        audio = apply_pan(audio, shape.pan)

    if shape.gain_db:
        audio = apply_gain_db(
            audio, float(np.clip(shape.gain_db, -MAX_APPLIED_GAIN_DB, MAX_APPLIED_GAIN_DB))
        )

    return audio
