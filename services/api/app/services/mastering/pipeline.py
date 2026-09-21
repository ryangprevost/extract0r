"""The mastering workflow: stems in, one mastered MP3 out.

Two ways to use a reference, and they compose:

**Bus matching** (always available) mixes the stems and moves the *sum* towards the
reference. Cheap, and it only needs the reference itself. Its limit is that it can only
tilt the whole mix: if your track is bass-heavy relative to the reference it cuts the low
end across the board, taking the bass guitar with it — which is exactly the "minimal
bass" complaint this module grew out of.

**Per-stem matching** (needs the reference separated too) compares bass against bass and
drums against drums, so each instrument gets its own level, tone and width. That is the
one that can say "your bass is 5 dB quiet" rather than "there is too much low end".

Per-stem runs first and bus matching second, on the result — instrument balance, then
the sound of the whole. Per-stem gain, pan, mute and solo from the user apply before
either, because the user's intent should not be overwritten by a machine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.domain.notes import StemKind
from app.services.mastering.base import MasteringReport
from app.services.mastering.dsp import (
    MatchSettings,
    apply_gain_db,
    normalise_peak,
    set_width,
)
from app.services.mastering.polish import (
    Polish,
    add_air,
    add_bass,
    add_warmth,
    widen_above,
)
from app.services.mastering.exciter import (
    DEFAULT_FROM_HZ as DEFAULT_SPARKLE_FROM_HZ,
    add_sparkle,
)
from app.services.mastering.instrument import StemShape, apply_shape
from app.services.mastering.reverb import apply_reverb
from app.services.mastering.spectral import SpectralMatchEngine
from app.services.mastering.stem_match import (
    StemAdjustment,
    has_counterpart,
    match_stem,
    profile_stems,
)
from app.services.mastering.vocals import (
    VocalPresence,
    VocalReport,
    duck_under_vocal,
    should_duck,
    vocal_envelope,
    vocal_lift_db,
)
from app.services.mixdown.encode import (
    AudioBuffer,
    apply_pan,
    mix_buffers,
    read_audio,
    write_mp3,
    write_wav,
)

log = logging.getLogger(__name__)

Progress = Callable[[float, str], None]


@dataclass(slots=True)
class StemSetting:
    """What the user did to one stem before it reaches the mix bus."""

    stem: StemKind
    gain_db: float = 0.0
    pan: float = 0.0
    #: 1.0 leaves the stereo image alone; >1 widens, <1 narrows towards mono.
    width: float = 1.0
    #: Seconds of tail, and how much of it to blend in. 0 mix leaves it dry.
    reverb_s: float = 1.2
    reverb_mix: float = 0.0
    #: Harmonics generated from this stem's own upper mids and added above
    #: `sparkle_from_hz`. Per stem rather than on the master because that is the whole
    #: point: driving the mix makes harmonics from the bass and the vocal too, so the
    #: hats gain nothing on anything. Driving the drums alone lifts the cymbals against
    #: everything else - measured, +4 dB on the drums moved hats and cymbals 2.4 dB in
    #: the finished mix while the kick band did not move at all.
    sparkle_db: float = 0.0
    sparkle_from_hz: float = DEFAULT_SPARKLE_FROM_HZ
    #: Tone, band by band, in the five bands `instrument` compares in. These are what the
    #: per-instrument comparison writes into when a suggestion is taken: one row of the
    #: comparison, one field here, so a user can accept the air on the drums and decline
    #: everything else. Solved for rather than applied literally - see `instrument`.
    tone_low_db: float = 0.0
    tone_low_mid_db: float = 0.0
    tone_high_mid_db: float = 0.0
    tone_presence_db: float = 0.0
    tone_air_db: float = 0.0
    #: dB of dynamic range to take out of this stem, level-matched afterwards.
    compress_db: float = 0.0
    #: Harmonic drive on this stem alone. Not suggested by the comparison and cannot be:
    #: added harmonics are indistinguishable from played ones without the dry signal.
    saturation_db: float = 0.0
    muted: bool = False
    solo: bool = False

    def shape(self) -> "StemShape":
        """The channel-strip half of these settings, in the form `instrument` applies."""
        return StemShape(
            tone_low_db=self.tone_low_db,
            tone_low_mid_db=self.tone_low_mid_db,
            tone_high_mid_db=self.tone_high_mid_db,
            tone_presence_db=self.tone_presence_db,
            tone_air_db=self.tone_air_db,
            compress_db=self.compress_db,
            saturation_db=self.saturation_db,
        )


@dataclass(slots=True)
class MasterRequest:
    """Everything one mastering run needs."""

    stems: dict[StemKind, Path]
    settings: list[StemSetting]
    reference: Path | None = None
    #: Separated stems of the reference, keyed the same way as `stems`. When present,
    #: each source stem is matched to its counterpart before the bus is matched.
    reference_stems: dict[StemKind, Path] = field(default_factory=dict)
    bitrate_kbps: int = 320
    match_strength: float = 1.0
    match_stem_levels: bool = True
    match_stem_tone: bool = True
    match_stem_width: bool = True
    #: Where the lead vocal should sit. Applied as a floor after matching, so a reference
    #: cannot leave the vocal buried.
    vocal_presence: VocalPresence | None = VocalPresence.NATURAL
    #: How far competing stems duck inside the vocal band while the vocal is singing.
    vocal_duck_db: float = 3.0
    #: The track the stems were separated from. When present, the mix is built by
    #: applying the stems' *changes* to this rather than by summing the stems - see
    #: `_apply_as_correction`.
    source: Path | None = None
    #: Whether to do that. Off means summing the stems, artefacts and all.
    preserve_source: bool = True
    #: ID3 fields for the exported MP3, so the file itself records what it came from and
    #: what it was matched against.
    tags: dict[str, str] = field(default_factory=dict)
    #: Name of a kit to lay over the drums, or None to leave them as recorded.
    drum_kit: str | None = None
    #: Which drums to trigger, and how far to lean on the samples against the originals.
    drum_targets: tuple[str, ...] = ("kick", "snare")
    drum_blend: float = 0.5
    #: Air, width and headroom - the finishing moves a reference match cannot make.
    polish: Polish = field(default_factory=Polish)
    export_wav: bool = False


@dataclass(slots=True)
class MasterResult:
    mp3_path: Path
    wav_path: Path | None = None
    report: MasteringReport | None = None
    included: list[StemKind] = field(default_factory=list)
    duration_s: float = 0.0
    stem_adjustments: list[StemAdjustment] = field(default_factory=list)
    vocals: VocalReport | None = None


def audible(settings: list[StemSetting]) -> list[StemSetting]:
    """Solo wins over mute, the way every DAW behaves."""
    soloed = [s for s in settings if s.solo]
    pool = soloed or settings
    return [s for s in pool if not s.muted or s.solo]


def run(
    request: MasterRequest, work_dir: Path, on_progress: Progress | None = None
) -> MasterResult:
    highest = 0.0

    def report(fraction: float, message: str) -> None:
        # Stage boundaries do not land on exactly the same float from both sides, and a
        # bar that steps back even by 1e-17 is visible. The job store enforces this too;
        # doing it here as well keeps the pipeline honest on its own terms.
        nonlocal highest
        highest = max(highest, min(1.0, fraction))
        if on_progress:
            on_progress(highest, message)

    chosen = audible(request.settings)
    if not chosen:
        raise ValueError("every stem is muted, so there is nothing to master")

    missing = [s.stem.value for s in chosen if s.stem not in request.stems]
    if missing:
        raise KeyError(f"no audio for stem(s): {', '.join(missing)}")

    # --- profile both sides, if per-instrument matching was asked for -------
    adjustments: list[StemAdjustment] = []
    source_profiles: dict[StemKind, object] = {}
    reference_profiles: dict[StemKind, object] = {}
    per_stem = bool(request.reference_stems)

    if per_stem:
        report(0.05, "measuring your stems")
        source_profiles = profile_stems(
            {s.stem: request.stems[s.stem] for s in chosen}
        )
        report(0.12, "measuring the reference stems")
        reference_profiles = profile_stems(request.reference_stems)

    # --- load and shape each stem ------------------------------------------
    report(0.15, f"loading {len(chosen)} stem(s)")
    buffers, gains, sample_rate = [], [], 44100
    span = 0.35 if per_stem else 0.20

    # The stems exactly as separated, summed. Subtracting this from the original leaves
    # only what separation got wrong, which is how the artefacts are kept out of the mix.
    #
    # Every separated stem goes in, not only the audible ones. A muted stem is still part
    # of what the original contains, so leaving it out means never subtracting it and the
    # mute does nothing at all - which is exactly what happened before a test caught it.
    untouched: np.ndarray | None = None

    for index, setting in enumerate(chosen):
        buffer: AudioBuffer = read_audio(request.stems[setting.stem])
        sample_rate = buffer.sample_rate
        samples = buffer.samples

        if request.preserve_source:
            raw = np.asarray(samples, dtype=np.float64)
            if untouched is None:
                untouched = raw.copy()
            else:
                length = min(len(untouched), len(raw))
                untouched[:length] += raw[:length]

        # The user's own moves come first: matching should refine an intent, not erase
        # it. Their fader is kept out of `samples` and applied at the mix bus, so it
        # stacks on top of whatever matching decides rather than being folded into the
        # measurement matching is derived from.
        if setting.stem is StemKind.DRUMS and request.drum_kit:
            # Before anything else: the samples should be panned, widened and reverbed
            # along with the drums they are reinforcing, not bolted on afterwards.
            from app.services.drums.detect import find_hits
            from app.services.drums.kit import layer

            report(0.15, "finding the drums")
            samples = layer(
                samples,
                sample_rate,
                find_hits(samples, sample_rate),
                kit=request.drum_kit,
                drums=tuple(request.drum_targets),
                blend=request.drum_blend,
            )

        shape = setting.shape()
        if not shape.is_identity():
            # The per-instrument moves, taken from the comparison with the reference's
            # counterpart stem. First in the strip, because everything after this - the
            # exciter, the tail, the width - should be reacting to the instrument as it is
            # meant to sound rather than to the version that needed correcting.
            samples = apply_shape(samples, sample_rate, shape)

        if setting.sparkle_db > 0:
            # Before the tail, so the reverb is fed the excited signal and the two agree
            # about what the instrument sounds like.
            samples = add_sparkle(
                samples, sample_rate, setting.sparkle_db, setting.sparkle_from_hz
            )

        if setting.reverb_mix > 0:
            # Before width and pan: the tail is part of the sound, so it should be placed
            # and spread with it rather than sitting outside the stem's position.
            samples = apply_reverb(
                samples, sample_rate, setting.reverb_s, setting.reverb_mix
            )
        if setting.width != 1.0:
            samples = set_width(samples, setting.width)
        if setting.pan:
            samples = apply_pan(samples, setting.pan)

        buffers.append(samples)
        gains.append(setting.gain_db)
        report(0.15 + span * 0.4 * (index + 1) / len(chosen), f"loaded {setting.stem.value}")

    if request.preserve_source:
        silent = [k for k in request.stems if k not in {s.stem for s in chosen}]
        for kind in silent:
            muted_buffer = read_audio(request.stems[kind])
            raw = np.asarray(muted_buffer.samples, dtype=np.float64)
            if untouched is None:
                untouched = raw.copy()
            else:
                length = min(len(untouched), len(raw))
                untouched[:length] += raw[:length]

    # --- match the instruments the reference actually contains ---------------
    #
    # Two passes, because the second depends on the first. A stem the reference has no
    # counterpart for cannot be matched - but leaving it untouched is wrong too: every
    # other instrument has just moved, so a piano left where it was ends up louder or
    # quieter *relative to the arrangement* purely by accident. It follows the others
    # instead, which keeps its place in the mix.
    matched_gains: list[float] = []
    unmatched: list[int] = []

    if per_stem:
        for index, setting in enumerate(chosen):
            source = source_profiles.get(setting.stem)
            target = reference_profiles.get(setting.stem)

            if source is None:
                adjustments.append(
                    StemAdjustment(
                        stem=setting.stem,
                        matched=False,
                        user_gain_db=setting.gain_db,
                        notes=["this stem is silent, so there was nothing to match"],
                    )
                )
                continue

            if not has_counterpart(target):
                unmatched.append(index)
                continue

            buffers[index], adjustment = match_stem(
                buffers[index],
                sample_rate,
                source,
                target,
                MatchSettings(strength=request.match_strength),
                match_levels=request.match_stem_levels,
                match_tone=request.match_stem_tone,
                match_stereo=request.match_stem_width,
            )
            adjustment.user_gain_db = setting.gain_db
            adjustments.append(adjustment)
            if request.match_stem_levels:
                matched_gains.append(adjustment.gain_db)
            report(
                0.15 + span * (0.4 + 0.6 * (len(adjustments)) / len(chosen)),
                f"matched {setting.stem.value}",
            )

        # --- carry the unmatched stems along with everything else ------------
        proportional_db = (
            sum(matched_gains) / len(matched_gains) if matched_gains else 0.0
        )
        for index in unmatched:
            setting = chosen[index]
            buffers[index] = apply_gain_db(buffers[index], proportional_db)
            adjustments.append(
                StemAdjustment(
                    stem=setting.stem,
                    gain_db=round(proportional_db, 2),
                    matched=False,
                    proportional=True,
                    user_gain_db=setting.gain_db,
                    notes=[
                        "the reference has no "
                        f"{setting.stem.value}, so it follows the rest of the mix "
                        f"({proportional_db:+.1f} dB)"
                    ],
                )
            )

    # --- place the vocal ----------------------------------------------------
    # Done after matching and before the sum, because it is a statement about the
    # arrangement rather than about the reference: a vocal that a listener has to strain
    # for is wrong even when every number matched.
    vocal_report = None
    if request.vocal_presence is not None:
        vocal_report = _place_vocal(
            chosen, buffers, gains, sample_rate, request, report,
            match_curve=_predicted_match_curve(
                buffers, gains, chosen, sample_rate, request
            ),
        )

    # --- sum, then match the sum -------------------------------------------
    report(0.15 + span, "mixing stems")
    mixed = mix_buffers(buffers, gains)
    if request.preserve_source and request.source is not None and untouched is not None:
        mixed = _apply_as_correction(request.source, untouched, mixed, report)

    work_dir.mkdir(parents=True, exist_ok=True)
    mix_wav = work_dir / "mix.wav"
    write_wav(mix_wav, mixed, sample_rate)

    # The reference should be matched against your balance, not against your faders. A
    # second mixdown with the user's own moves removed gives matching something neutral
    # to read the tone from; see SpectralMatchEngine.match.
    analysis_wav = None
    if any(setting.gain_db for setting in chosen):
        neutral = [g - setting.gain_db for g, setting in zip(gains, chosen, strict=True)]
        analysis_wav = work_dir / "analysis.wav"
        work_dir.mkdir(parents=True, exist_ok=True)
        write_wav(analysis_wav, mix_buffers(buffers, neutral), sample_rate)

    master_report = None
    mastered_wav = mix_wav
    if request.reference is not None:
        report(0.5, "matching the reference")
        engine = SpectralMatchEngine(MatchSettings(strength=request.match_strength))
        mastered_wav = work_dir / "mastered.wav"
        master_report = engine.match(
            mix_wav,
            request.reference,
            mastered_wav,
            analysis=analysis_wav,
            polish=request.polish,
        )
        report(0.8, f"matched, {master_report.gain_applied_db:+.1f} dB")

    elif request.polish.wanted():
        # No reference means no match stage to hang the finishing moves off, but the
        # dials still have to work: without this branch air and width would silently do
        # nothing whenever matching is off.
        report(0.5, "finishing")
        shaped = mixed
        if request.polish.bass_db:
            shaped = add_bass(
                shaped, sample_rate, request.polish.bass_db, request.polish.bass_hz
            )
        if request.polish.warmth_db:
            shaped = add_warmth(
                shaped, sample_rate, request.polish.warmth_db, request.polish.warmth_hz
            )
        if request.polish.air_db:
            shaped = add_air(
                shaped, sample_rate, request.polish.air_db, request.polish.air_hz
            )
        if request.polish.width != 1.0:
            shaped = widen_above(
                shaped, sample_rate, request.polish.width, request.polish.width_floor_hz
            )
        mastered_wav = work_dir / "mastered.wav"
        write_wav(mastered_wav, normalise_peak(shaped), sample_rate)

    # --- encode -------------------------------------------------------------
    report(0.85, "encoding mp3")
    final = read_audio(mastered_wav)
    mp3_path = work_dir / "master.mp3"
    write_mp3(
        mp3_path, final.samples, final.sample_rate, request.bitrate_kbps, request.tags
    )

    wav_path = None
    if request.export_wav:
        wav_path = work_dir / "master.wav"
        write_wav(wav_path, final.samples, final.sample_rate)

    report(1.0, "done")
    return MasterResult(
        mp3_path=mp3_path,
        wav_path=wav_path,
        report=master_report,
        included=[s.stem for s in chosen],
        duration_s=final.duration_s,
        stem_adjustments=adjustments,
        vocals=vocal_report,
    )


def _apply_as_correction(
    source: Path,
    untouched: np.ndarray,
    mixed: np.ndarray,
    report: Progress,
) -> np.ndarray:
    """Apply what the stems *changed* to the original, instead of using the stems.

    Separation is not lossless. Summing this track's six stems back up reproduces it only
    to within -25.6 dB, and that error is worst in the presence range - which is what a
    sizzle or a rattle is: what the separator could not put back, sitting up where nothing
    masks it.

    Summing the processed stems inherits all of that. Adding the *difference* instead does
    not::

        out = original + (processed stems - untouched stems)

    With nothing changed the two sums cancel exactly and the output is the original file,
    sample for sample, with no separation error in it at all. Once something is changed,
    the artefacts come back only in proportion to the change: a stem lifted 3 dB
    contributes 0.41 of itself rather than all of it, so its share of the error arrives
    about 8 dB quieter. Muting a stem is the one case with no saving, and rightly - it is
    a full-magnitude subtraction - but everything not muted keeps the original's fidelity
    instead of its own reconstruction's.

    The one case it does not help is soloing. Keeping one stem out of six means
    subtracting the other five from the original, which leaves that stem *plus* the whole
    track's reconstruction error - worse than simply taking the stem. Muting one or two is
    fine and better than the alternative; hearing one alone is what the toggle is for.

    Trimmed to the shortest of the three, because a stem can come back a sample or two
    longer than what went in.
    """
    try:
        original = read_audio(source).samples
    except Exception:
        log.info("could not read %s; mixing the stems directly", source.name)
        return mixed

    original = np.asarray(original, dtype=np.float64)
    if original.ndim == 1:
        original = np.stack([original, original], axis=1)

    length = min(len(original), len(untouched), len(mixed))
    if length == 0 or original.shape[1] != mixed.shape[1]:
        return mixed

    report(0.15, "applying changes to the original rather than to the stems")
    return original[:length] + (mixed[:length] - untouched[:length])


def _predicted_match_curve(
    buffers: list,
    gains: list[float],
    chosen: list[StemSetting],
    sample_rate: int,
    request: MasterRequest,
):
    """The tone move the reference match is about to make, computed in advance.

    Placement has to run before the match, because it changes the stem gains the match
    will read. But that leaves it measuring a balance the match then rewrites, and the
    rewrite is not neutral: a reference with more weight at both ends than yours scoops
    the middle, which is where a lead vocal lives. Measured on one real track the match
    asked for -3.5 dB at the vocal's body while adding +2 dB of bass and air - a 4.2 dB
    tilt away from the vocal, applied after placement had already decided the vocal was
    sitting fine.

    So placement is given the curve and measures through it. Returns None when there is
    no reference, in which case there is no tilt to allow for.

    The curve is computed from the balance as it stands now, before placement moves the
    vocal. Placement's own lift would shift it slightly - this is knowingly one
    iteration of a fixed point rather than a solve, because the second iteration moves
    the answer by a fraction of a decibel and costs another pair of spectra.
    """
    if request.reference is None:
        return None
    try:
        from app.services.mastering.dsp import (
            MatchSettings,
            average_spectrum,
            matching_curve,
        )

        # The user's own faders come out, exactly as they do for the real match: the
        # question is what the reference does to this arrangement, not to their moves.
        neutral = [g - setting.gain_db for g, setting in zip(gains, chosen, strict=True)]
        provisional = mix_buffers(buffers, neutral)
        reference = read_audio(request.reference).samples
        settings = MatchSettings(strength=request.match_strength)
        return matching_curve(
            average_spectrum(provisional, settings.n_fft, settings.hop),
            average_spectrum(reference, settings.n_fft, settings.hop),
            sample_rate,
            settings,
        )
    except Exception:
        log.debug("could not predict the match curve; placing the vocal on the raw mix",
                  exc_info=True)
        return None


def _place_vocal(
    chosen: list[StemSetting],
    buffers: list,
    gains: list[float],
    sample_rate: int,
    request: MasterRequest,
    report: Progress,
    match_curve=None,
) -> VocalReport | None:
    """Lift the vocal to its target placement and duck what masks it."""
    from app.services.mastering.loudness_meter import integrated_loudness
    from app.services.mastering.vocals import PRESENCE_TARGETS

    index = next(
        (i for i, s in enumerate(chosen) if s.stem is StemKind.VOCALS), None
    )
    if index is None:
        return None

    out = VocalReport(target_lu=PRESENCE_TARGETS[request.vocal_presence])

    # Measure the vocal where it naturally sits, with the user's own fader taken out of
    # both sides. Placement sets a floor and the fader rides on top of it. Folding the
    # fader into the measurement instead makes placement hand back exactly what the fader
    # added, so "+3 dB on the vocal" lands as +0 dB in the finished master.
    user_db = gains[index]
    unfadered = list(gains)
    unfadered[index] = 0.0
    provisional = mix_buffers(buffers, unfadered)
    vocal = buffers[index]

    # Measure through the match, not around it. Both signals get the same curve, so this
    # changes the reading only in so far as their spectra differ - which is the whole
    # point: a mid-heavy vocal loses more to a scooped match than the broad mix does,
    # and that gap is what placement is supposed to be closing.
    if match_curve is not None:
        from app.services.mastering.dsp import MatchSettings, apply_curve

        settings = MatchSettings(strength=request.match_strength)
        try:
            provisional = apply_curve(provisional, match_curve, settings.n_fft, settings.hop)
            vocal = apply_curve(vocal, match_curve, settings.n_fft, settings.hop)
        except Exception:
            log.debug("could not measure through the match curve", exc_info=True)

    # Hand the vocal back what the match takes out of its range, on its own stem. This
    # runs before the measurement below so placement reads the vocal it will actually
    # get, and before the sum so the compensation is really in the mix.
    if match_curve is not None:
        from app.services.mastering.vocals import match_compensation_curve

        compensation = match_compensation_curve(match_curve, sample_rate)
        if compensation is not None:
            from app.services.mastering.dsp import MatchSettings, apply_curve

            shaped = MatchSettings(strength=request.match_strength)
            try:
                buffers[index] = apply_curve(
                    buffers[index], compensation, shaped.n_fft, shaped.hop
                )
                vocal = apply_curve(vocal, compensation, shaped.n_fft, shaped.hop)
                peak_db = float(20 * np.log10(max(float(compensation.max()), 1e-9)))
                out.notes.append(
                    f"gave the vocal back up to {peak_db:.1f} dB the match cut from "
                    "its range"
                )
                report(0.15, f"restoring {peak_db:.1f} dB of vocal range")
            except Exception:
                log.debug("could not compensate the vocal band", exc_info=True)

    mix_lufs, _ = integrated_loudness(provisional, sample_rate)
    vocal_lufs, _ = integrated_loudness(vocal, sample_rate)
    if not (np.isfinite(mix_lufs) and np.isfinite(vocal_lufs)):
        out.notes.append("could not measure the vocal; left as it was")
        return out

    out.measured_lu = round(float(vocal_lufs - mix_lufs), 2)
    lift, note = vocal_lift_db(out.measured_lu, request.vocal_presence)
    out.lift_db = round(lift, 2)
    if note:
        out.notes.append(note)

    if lift > 0:
        gains[index] += lift
        report(0.15, f"vocal lifted {lift:+.1f} dB to sit at {out.target_lu:.1f} LU")

    out.user_gain_db = round(float(user_db), 2)
    if user_db:
        out.notes.append(f"your fader adds {user_db:+.1f} dB on top of this")

    # --- duck what competes ------------------------------------------------
    if request.vocal_duck_db > 0:
        envelope = vocal_envelope(buffers[index], sample_rate)
        for position, setting in enumerate(chosen):
            if not should_duck(setting.stem):
                continue
            buffers[position] = duck_under_vocal(
                buffers[position], envelope, sample_rate, request.vocal_duck_db
            )
            out.ducked_stems.append(setting.stem.value)
        out.duck_depth_db = request.vocal_duck_db
        if out.ducked_stems:
            report(0.15, f"ducking {', '.join(out.ducked_stems)} under the vocal")

    return out
