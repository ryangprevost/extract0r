"""Reference mastering contract (Phase 2).

The user hands us a commercial track they want to sound like; a backend measures the
difference and applies it. Everything a backend reports goes into
:class:`MasteringReport` so the UI can show *what changed*, not just "done".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LoudnessStats:
    """EBU R128 measurements, the numbers streaming platforms normalise against."""

    integrated_lufs: float
    true_peak_dbtp: float
    loudness_range_lu: float


@dataclass(slots=True)
class MasteringReport:
    backend: str
    source: LoudnessStats | None = None
    reference: LoudnessStats | None = None
    result: LoudnessStats | None = None
    gain_applied_db: float = 0.0
    eq_curve_db: list[tuple[float, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: What the finishing stage did on top of the match. Typed loosely to keep this
    #: module free of a dependency on the engine that fills it in.
    polish: object | None = None
    #: How hard the limiter had to work to hold the ceiling.
    limiter: object | None = None


@runtime_checkable
class MasteringEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def match(
        self, target: Path, reference: Path, out_path: Path
    ) -> MasteringReport:
        """Process ``target`` to sit near ``reference`` tonally and in loudness."""
