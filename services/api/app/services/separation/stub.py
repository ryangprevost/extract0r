"""A separator that needs no ML stack, so the whole pipeline runs on a laptop.

It copies the source once per stem. Useless musically, invaluable for developing the
API, the job queue, and the front end without a 2 GB model download.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.domain.notes import StemKind
from app.services.separation.base import SeparatedStem, SeparationResult

DEFAULT_STEMS = (StemKind.DRUMS, StemKind.BASS, StemKind.VOCALS, StemKind.OTHER)


class StubSeparator:
    name = "stub"

    def __init__(self, stems: tuple[StemKind, ...] = DEFAULT_STEMS) -> None:
        self.stems = stems

    def available(self) -> bool:
        return True

    def separate(self, source: Path, out_dir: Path) -> SeparationResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        produced = []
        for kind in self.stems:
            target = out_dir / f"{kind.value}{source.suffix or '.wav'}"
            shutil.copyfile(source, target)
            produced.append(
                SeparatedStem(kind=kind, path=target, sample_rate=44100, duration_s=0.0)
            )
        return SeparationResult(tuple(produced), backend=self.name, model="passthrough")
