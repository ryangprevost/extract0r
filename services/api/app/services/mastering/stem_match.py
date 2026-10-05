"""Per-instrument matching: bass against bass, drums against drums.

Matching a whole mix against a whole mix can only ever move the *sum*. If the reference
has more low end than your track, a full-mix match has no way to know whether that means
"turn the bass up" or "the kick needs weight" — it just tilts everything, and the result
is a mix whose balance is unchanged but whose tone has been smeared. Worse, when a mix is
already bass-heavy relative to the reference, the correction cuts the low end across the
board and takes the bass guitar with it.

Separating the *reference* too makes the question answerable per instrument:

* **Level** is matched *relatively*. The absolute loudness of a reference's bass stem is
  meaningless — what matters is that it sits, say, 4 LU below its own mix. That offset is
  what gets applied, so a quiet demo does not get shouted at by a loud master.
* **Tone** is matched stem to stem, so the bass curve is derived from bass and cannot be
  polluted by the reference's cymbals.
* **Width** is matched too, because "professionally mixed" is largely a stereo statement:
  bass and kick in the middle, guitars and keys spread.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.domain.notes import StemKind
from app.services.mastering.dsp import (
    MatchSettings,
    apply_curve,
    apply_gain_db,
    average_spectrum,
    match_width,
    matching_curve,
    stereo_width,
)
from app.services.mastering.loudness_meter import integrated_loudness

# Re-exported, not unused: callers read the threshold through this module's namespace,
# and `presence` exists so that there is exactly one of it. See X0R-1127.
from app.services.mastering.presence import (
    ABSENT_BELOW_LU,  # noqa: F401
    why_not,
)
from app.services.mastering.presence import is_present as _present
from app.services.mixdown.encode import mix_buffers, read_audio

log = logging.getLogger(__name__)

# How far a single stem may be moved. Wider than the master-bus clamp, because a stem
# genuinely can be 6 dB out of place in a rough mix - but not unlimited, because a stem
# that Demucs barely found should not be dragged up to meet a reference.
MAX_STEM_GAIN_DB = 9.0

# Bass and kick belong in the middle. Widening them thins the low end and causes phase
# trouble on mono playback, so they are excluded from width matching regardless of what
# the reference measures.
NEVER_WIDEN = (StemKind.BASS,)

# A reference stem this far below its own mix is not an instrument, it is what separation
# leaves behind when the instrument is not there. A reference with no piano yields a piano
# stem at -60 LU or worse, and matching to it would ask for a -60 dB cut - silencing an
# instrument the user does have because the reference happens not to. Below this
# threshold the stem is treated as absent and left alone.


# How far stereo width may be moved. Narrower than the level clamp on purpose: collapsing
# a part to a quarter of its width is a drastic, obvious change, and separation artefacts
# make the measurement noisy enough that the extremes are rarely trustworthy.
WIDTH_LIMITS = (0.6, 2.0)


@dataclass(slots=True)
class StemProfile:
    """What one stem sounds like, in the terms matching needs."""

    stem: StemKind
    spectrum: np.ndarray
    loudness_lufs: float
    width: float
    #: Loudness relative to the mix this stem belongs to. The portable number.
    relative_lufs: float = 0.0
    sample_rate: int = 44100


@dataclass(slots=True)
class StemAdjustment:
    """What matching decided to do to one stem."""

    stem: StemKind
    gain_db: float = 0.0
    width_factor: float = 1.0
    eq_bands: list[tuple[float, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: False when the reference had no counterpart for this instrument.
    matched: bool = True
    #: True when the level came from the rest of the mix rather than from a counterpart.
    proportional: bool = False
    #: The user's own fader, kept separate so it is visible that it stacks on top.
    user_gain_db: float = 0.0


def has_counterpart(reference: StemProfile | None) -> bool:
    """Whether the reference actually contains this instrument.

    Separation returns a stem for everything the model knows, so "the reference has no
    piano" shows up as a piano stem tens of LU below its own mix rather than as a missing
    file. See `presence` for the threshold and for why it is written down once.

    Asks about the reference alone, which is what its callers want when they are deciding
    whether there is anything to copy. It is **not** enough to decide whether to match:
    that needs both sides, and `match_stem` checks both.
    """
    return reference is not None and _present(reference.relative_lufs)


def profile_stems(
    paths: dict[StemKind, Path], settings: MatchSettings | None = None
) -> dict[StemKind, StemProfile]:
    """Measure every stem, and each one's level relative to their sum.

    Reads each stem in full. Sampling a window from the middle was tried to make the
    comparison faster and abandoned on the numbers: relative level held for bass, drums
    and vocals but not for the parts that come and go. Against the full-track answer a
    60-second window put `other` 6.8 dB out and `guitar` 3 dB out, which is enough to
    invent a finding. Eleven seconds is not worth a wrong one.
    """
    settings = settings or MatchSettings()
    profiles: dict[StemKind, StemProfile] = {}
    buffers: list[np.ndarray] = []

    for stem, path in paths.items():
        if not path.exists():
            continue
        buffer = read_audio(path)
        loudness, _ = integrated_loudness(buffer.samples, buffer.sample_rate)
        if not np.isfinite(loudness):
            log.info("%s is silent; skipping it as a matching source", stem.value)
            continue
        profiles[stem] = StemProfile(
            stem=stem,
            spectrum=average_spectrum(buffer.samples, settings.n_fft, settings.hop),
            loudness_lufs=float(loudness),
            width=stereo_width(buffer.samples),
            sample_rate=buffer.sample_rate,
        )
        buffers.append(buffer.samples)

    if not buffers:
        return profiles

    # The mix these stems make, so each level can be expressed relative to it.
    mix = mix_buffers(buffers)
    rate = next(iter(profiles.values())).sample_rate
    mix_loudness, _ = integrated_loudness(mix, rate)
    if np.isfinite(mix_loudness):
        for profile in profiles.values():
            profile.relative_lufs = profile.loudness_lufs - float(mix_loudness)

    return profiles


def match_stem(
    samples: np.ndarray,
    sample_rate: int,
    source: StemProfile,
    reference: StemProfile,
    settings: MatchSettings | None = None,
    match_levels: bool = True,
    match_tone: bool = True,
    match_stereo: bool = True,
) -> tuple[np.ndarray, StemAdjustment]:
    """Move one stem towards its counterpart in the reference."""
    settings = settings or MatchSettings()
    adjustment = StemAdjustment(stem=source.stem)
    out = np.asarray(samples, dtype=np.float64)

    # Both sides, and it used to be one.
    #
    # A reference that does not contain this instrument cannot say anything useful about
    # it, and matching anyway would quietly delete a part the user played. That half was
    # here. The other half was not: a *source* that does not contain it has nothing for a
    # correction to land on, and the correction is a gain. Measured on a real pair - the
    # user's song has no guitar at -59.7 LU, the reference's guitar stem is residue at
    # -22.7 which clears the threshold - matching asked for +37 dB and applied the +9 the
    # clamp allowed, to an instrument nobody played. It was inaudible there only because
    # the stem was already 50 LU down; a quiet real guitar in the same position gets an
    # audible 9 dB of the wrong thing.
    #
    # `instrument.compare` and `critique` both already declined on either side. This was
    # the one path that did not, which is why the rule now lives in `presence` instead of
    # being written out three times.
    reason = why_not(
        source.relative_lufs,
        reference.relative_lufs if reference is not None else None,
        source.stem.value,
    )
    if reason:
        adjustment.matched = False
        adjustment.notes.append(reason)
        return out, adjustment

    if match_tone:
        curve = matching_curve(source.spectrum, reference.spectrum, sample_rate, settings)
        out = apply_curve(out, curve, settings.n_fft, settings.hop)
        adjustment.eq_bands = _describe(curve, sample_rate)

    if match_levels:
        # The relative offset is the portable part: how far this instrument sits from its
        # own mix. Copying absolute loudness between two different productions is
        # meaningless.
        wanted = reference.relative_lufs - source.relative_lufs
        applied = float(np.clip(wanted, -MAX_STEM_GAIN_DB, MAX_STEM_GAIN_DB))
        out = apply_gain_db(out, applied)
        adjustment.gain_db = round(applied, 2)
        if abs(wanted - applied) > 0.1:
            adjustment.notes.append(
                f"wanted {wanted:+.1f} dB, capped at {applied:+.1f} dB"
            )

    if match_stereo and source.stem not in NEVER_WIDEN:
        out, factor = match_width(
            out, reference.width, low=WIDTH_LIMITS[0], high=WIDTH_LIMITS[1]
        )
        adjustment.width_factor = round(factor, 3)
        if abs(factor - 1.0) < 0.02:
            adjustment.width_factor = 1.0
    elif source.stem in NEVER_WIDEN:
        adjustment.notes.append("kept centred - widening the low end thins it")

    return out, adjustment


REPORT_BANDS = (60, 120, 250, 500, 1000, 2000, 4000, 8000, 12000)


def _describe(curve: np.ndarray, sample_rate: int) -> list[tuple[float, float]]:
    freqs = np.fft.rfftfreq((curve.size - 1) * 2, d=1.0 / sample_rate)
    out: list[tuple[float, float]] = []
    for band in REPORT_BANDS:
        if band >= sample_rate / 2:
            continue
        index = min(int(np.searchsorted(freqs, band)), curve.size - 1)
        out.append((float(band), round(float(20.0 * np.log10(curve[index])), 2)))
    return out
