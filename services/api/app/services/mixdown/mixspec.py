"""The mix specification — what the Phase 2 editor sends back to the server.

Pure data plus a pure filter-graph builder, so the tricky part (turning a UI state
into a correct ffmpeg command) is unit-testable without ffmpeg installed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

FilterKind = Literal["lowshelf", "highshelf", "peaking", "highpass", "lowpass"]


@dataclass(frozen=True, slots=True)
class EqBand:
    kind: FilterKind
    frequency_hz: float
    gain_db: float = 0.0
    q: float = 0.707

    def to_ffmpeg(self) -> str:
        if self.kind == "highpass":
            return f"highpass=f={self.frequency_hz}"
        if self.kind == "lowpass":
            return f"lowpass=f={self.frequency_hz}"
        if self.kind == "lowshelf":
            return f"bass=g={self.gain_db}:f={self.frequency_hz}:w={self.q}"
        if self.kind == "highshelf":
            return f"treble=g={self.gain_db}:f={self.frequency_hz}:w={self.q}"
        return f"equalizer=f={self.frequency_hz}:t=q:w={self.q}:g={self.gain_db}"


@dataclass(frozen=True, slots=True)
class Compressor:
    threshold_db: float = -18.0
    ratio: float = 3.0
    attack_ms: float = 20.0
    release_ms: float = 250.0
    makeup_db: float = 0.0

    def to_ffmpeg(self) -> str:
        return (
            f"acompressor=threshold={self.threshold_db}dB:ratio={self.ratio}"
            f":attack={self.attack_ms}:release={self.release_ms}"
            f":makeup={max(self.makeup_db, 0.0)}"
        )


@dataclass(frozen=True, slots=True)
class Reverb:
    """Cheap algorithmic reverb via ffmpeg's aecho - a send-level, not a plate."""

    wet: float = 0.2
    delay_ms: float = 60.0
    decay: float = 0.4

    def to_ffmpeg(self) -> str:
        return f"aecho=0.8:{round(self.wet, 3)}:{round(self.delay_ms)}:{round(self.decay, 3)}"


@dataclass(slots=True)
class StemSettings:
    stem: str
    gain_db: float = 0.0
    pan: float = 0.0  # -1 hard left .. +1 hard right
    muted: bool = False
    solo: bool = False
    eq: list[EqBand] = field(default_factory=list)
    compressor: Compressor | None = None
    reverb: Reverb | None = None

    def filter_chain(self) -> list[str]:
        chain: list[str] = [band.to_ffmpeg() for band in self.eq]
        if self.compressor:
            chain.append(self.compressor.to_ffmpeg())
        if self.reverb:
            chain.append(self.reverb.to_ffmpeg())
        if self.gain_db:
            chain.append(f"volume={self.gain_db}dB")
        if self.pan:
            left = min(1.0, 1.0 - self.pan)
            right = min(1.0, 1.0 + self.pan)
            chain.append(f"pan=stereo|c0={left:.3f}*c0|c1={right:.3f}*c1")
        return chain or ["anull"]


@dataclass(slots=True)
class MixSpec:
    stems: list[StemSettings]
    master_gain_db: float = 0.0
    normalize_lufs: float | None = -14.0  # streaming-typical target; None to skip
    sample_rate: int = 44100
    bitrate_kbps: int = 320

    def active(self) -> list[StemSettings]:
        """Solo wins over mute, the way every DAW behaves."""
        soloed = [s for s in self.stems if s.solo]
        pool = soloed or self.stems
        return [s for s in pool if not s.muted or s.solo]


def build_filter_complex(spec: MixSpec, inputs: Sequence[str]) -> str:
    """Compose the per-stem chains and the summing bus into one filter_complex string.

    ``inputs`` are the stem names, in the same order they are passed to ffmpeg as -i.
    """
    active = spec.active()
    index_of = {name: i for i, name in enumerate(inputs)}
    parts: list[str] = []
    labels: list[str] = []

    for settings in active:
        if settings.stem not in index_of:
            raise KeyError(f"mix references unknown stem {settings.stem!r}")
        label = f"s{index_of[settings.stem]}"
        chain = ",".join(settings.filter_chain())
        parts.append(f"[{index_of[settings.stem]}:a]{chain}[{label}]")
        labels.append(f"[{label}]")

    if not labels:
        raise ValueError("mix has no audible stems")

    bus = "".join(labels)
    tail = [f"{bus}amix=inputs={len(labels)}:normalize=0[mix]"]
    last = "mix"
    if spec.master_gain_db:
        tail.append(f"[{last}]volume={spec.master_gain_db}dB[gain]")
        last = "gain"
    if spec.normalize_lufs is not None:
        tail.append(f"[{last}]loudnorm=I={spec.normalize_lufs}:TP=-1.0[out]")
        last = "out"
    else:
        tail.append(f"[{last}]anull[out]")

    return ";".join(parts + tail)
