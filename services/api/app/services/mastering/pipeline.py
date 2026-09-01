"""The mastering workflow: stems in, one mastered MP3 out.

The order matters and is not arbitrary. Stems are mixed **first** and matched **second**,
because tonal balance is a property of a whole mix. Matching each stem against a full-mix
reference separately would push every stem towards the reference's overall spectrum,
which is a curve that includes all the other instruments — the bass would be told to
grow a top end it should not have.

Per-stem gain, pan, mute and solo still apply before the sum, so the user shapes the mix
and the reference then decides how that mix should sit.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.notes import StemKind
from app.services.mastering.base import MasteringReport
from app.services.mastering.dsp import MatchSettings
from app.services.mastering.spectral import SpectralMatchEngine
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
    muted: bool = False
    solo: bool = False


@dataclass(slots=True)
class MasterRequest:
    """Everything one mastering run needs."""

    stems: dict[StemKind, Path]
    settings: list[StemSetting]
    reference: Path | None = None
    bitrate_kbps: int = 320
    match_strength: float = 1.0
    export_wav: bool = False


@dataclass(slots=True)
class MasterResult:
    mp3_path: Path
    wav_path: Path | None = None
    report: MasteringReport | None = None
    included: list[StemKind] = field(default_factory=list)
    duration_s: float = 0.0


def audible(settings: list[StemSetting]) -> list[StemSetting]:
    """Solo wins over mute, the way every DAW behaves."""
    soloed = [s for s in settings if s.solo]
    pool = soloed or settings
    return [s for s in pool if not s.muted or s.solo]


def run(
    request: MasterRequest, work_dir: Path, on_progress: Progress | None = None
) -> MasterResult:
    def report(fraction: float, message: str) -> None:
        if on_progress:
            on_progress(fraction, message)

    chosen = audible(request.settings)
    if not chosen:
        raise ValueError("every stem is muted, so there is nothing to master")

    missing = [s.stem.value for s in chosen if s.stem not in request.stems]
    if missing:
        raise KeyError(f"no audio for stem(s): {', '.join(missing)}")

    # --- load and shape each stem ------------------------------------------
    report(0.05, f"loading {len(chosen)} stem(s)")
    buffers, gains, sample_rate = [], [], 44100
    for index, setting in enumerate(chosen):
        buffer: AudioBuffer = read_audio(request.stems[setting.stem])
        sample_rate = buffer.sample_rate
        samples = apply_pan(buffer.samples, setting.pan) if setting.pan else buffer.samples
        buffers.append(samples)
        gains.append(setting.gain_db)
        report(0.05 + 0.25 * (index + 1) / len(chosen), f"loaded {setting.stem.value}")

    # --- sum, then match the sum -------------------------------------------
    report(0.35, "mixing stems")
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
    )
