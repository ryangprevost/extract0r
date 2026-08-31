"""Source-separation contract.

Every backend returns the same thing — one audio file per :class:`StemKind` — so the
pipeline never has to care whether Demucs, Spleeter, or the stub produced them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.domain.notes import StemKind


@dataclass(frozen=True, slots=True)
class SeparatedStem:
    kind: StemKind
    path: Path
    sample_rate: int
    duration_s: float


@dataclass(frozen=True, slots=True)
class SeparationResult:
    stems: tuple[SeparatedStem, ...]
    backend: str
    model: str

    def by_kind(self, kind: StemKind) -> SeparatedStem | None:
        return next((s for s in self.stems if s.kind is kind), None)


@runtime_checkable
class Separator(Protocol):
    name: str

    def available(self) -> bool:
        """True when this backend's heavy dependencies are actually installed."""

    def separate(
        self,
        source: Path,
        out_dir: Path,
        on_progress: Callable[[float], None] | None = None,
    ) -> SeparationResult:
        """Split ``source`` into stems under ``out_dir``.

        ``on_progress`` receives a monotonically increasing 0..1 fraction when the
        backend can report one; backends that cannot simply never call it.
        """


def describe_stem(kind: StemKind, path: Path) -> SeparatedStem:
    """Build a :class:`SeparatedStem`, filling in real duration when it is cheap to read.

    Probing is header-only, so this costs nothing next to the separation itself, and it
    means the UI can show stem lengths without a second round trip.
    """
    from app.services.audio.probe import UnreadableAudioError, probe

    try:
        info = probe(path)
    except UnreadableAudioError:
        return SeparatedStem(kind=kind, path=path, sample_rate=44100, duration_s=0.0)
    return SeparatedStem(
        kind=kind,
        path=path,
        sample_rate=info.sample_rate,
        duration_s=info.duration_s,
    )
