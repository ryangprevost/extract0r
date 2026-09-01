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

from app.domain.notes import StemKind
from app.services.mastering.base import MasteringReport
from app.services.mastering.dsp import MatchSettings, set_width
from app.services.mastering.spectral import SpectralMatchEngine
from app.services.mastering.stem_match import (
    StemAdjustment,
    match_stem,
    profile_stems,
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
    muted: bool = False
    solo: bool = False


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
    export_wav: bool = False


@dataclass(slots=True)
class MasterResult:
    mp3_path: Path
    wav_path: Path | None = None
    report: MasteringReport | None = None
    included: list[StemKind] = field(default_factory=list)
    duration_s: float = 0.0
    stem_adjustments: list[StemAdjustment] = field(default_factory=list)


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
    for index, setting in enumerate(chosen):
        buffer: AudioBuffer = read_audio(request.stems[setting.stem])
        sample_rate = buffer.sample_rate
        samples = buffer.samples

        # The user's own moves come first: matching should refine an intent, not erase it.
        if setting.width != 1.0:
            samples = set_width(samples, setting.width)
        if setting.pan:
            samples = apply_pan(samples, setting.pan)

        source = source_profiles.get(setting.stem)
        target = reference_profiles.get(setting.stem)
        if source is not None and target is not None:
            samples, adjustment = match_stem(
                samples,
                sample_rate,
                source,
                target,
                MatchSettings(strength=request.match_strength),
                match_levels=request.match_stem_levels,
                match_tone=request.match_stem_tone,
                match_stereo=request.match_stem_width,
            )
            adjustments.append(adjustment)
        elif per_stem:
            adjustments.append(
                StemAdjustment(
                    stem=setting.stem,
                    notes=["no matching stem in the reference; left as it was"],
                )
            )

        buffers.append(samples)
        gains.append(setting.gain_db)
        report(
            0.15 + span * (index + 1) / len(chosen),
            f"{'matched' if target is not None else 'loaded'} {setting.stem.value}",
        )

    # --- sum, then match the sum -------------------------------------------
    report(0.15 + span, "mixing stems")
    mixed = mix_buffers(buffers, gains)

    work_dir.mkdir(parents=True, exist_ok=True)
    mix_wav = work_dir / "mix.wav"
    write_wav(mix_wav, mixed, sample_rate)

    master_report = None
    mastered_wav = mix_wav
    if request.reference is not None:
        report(0.5, "matching the reference")
        engine = SpectralMatchEngine(MatchSettings(strength=request.match_strength))
        mastered_wav = work_dir / "mastered.wav"
        master_report = engine.match(mix_wav, request.reference, mastered_wav)
        report(0.8, f"matched, {master_report.gain_applied_db:+.1f} dB")

    # --- encode -------------------------------------------------------------
    report(0.85, "encoding mp3")
    final = read_audio(mastered_wav)
    mp3_path = work_dir / "master.mp3"
    write_mp3(mp3_path, final.samples, final.sample_rate, request.bitrate_kbps)

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
    )
