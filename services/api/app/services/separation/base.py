"""Source-separation contract.

Every backend returns the same thing — one audio file per :class:`StemKind` — so the
pipeline never has to care whether Demucs, Spleeter, or the stub produced them.
"""

from __future__ import annotations

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

    def separate(self, source: Path, out_dir: Path) -> SeparationResult: ...
