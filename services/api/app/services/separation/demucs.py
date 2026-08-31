"""Demucs v4 backend — the real separator.

``htdemucs`` gives drums/bass/vocals/other; ``htdemucs_6s`` adds guitar and piano,
which is what makes per-instrument tab worth doing. Imports are deferred so the API
still boots on a machine without torch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.domain.notes import StemKind
from app.services.separation.base import SeparatedStem, SeparationResult

MODEL_STEMS = {
    "htdemucs": (StemKind.DRUMS, StemKind.BASS, StemKind.VOCALS, StemKind.OTHER),
    "htdemucs_ft": (StemKind.DRUMS, StemKind.BASS, StemKind.VOCALS, StemKind.OTHER),
    "htdemucs_6s": (
        StemKind.DRUMS,
        StemKind.BASS,
        StemKind.VOCALS,
        StemKind.OTHER,
        StemKind.GUITAR,
        StemKind.PIANO,
    ),
}


class DemucsSeparator:
    name = "demucs"

    def __init__(self, model: str = "htdemucs_6s", device: str = "cpu", jobs: int = 1) -> None:
        self.model = model
        self.device = device
        self.jobs = jobs

    def available(self) -> bool:
        try:
            import demucs  # noqa: F401
            import torch  # noqa: F401
        except ImportError:
            return False
        return True

    def separate(self, source: Path, out_dir: Path) -> SeparationResult:
        if not self.available():
            raise RuntimeError(
                "demucs/torch are not installed - install requirements-ml.txt "
                "or set SEPARATION_BACKEND=stub"
            )
        out_dir.mkdir(parents=True, exist_ok=True)
        # The CLI is the supported surface and keeps model loading out of the web process.
        subprocess.run(
            [
                "python", "-m", "demucs.separate",
                "-n", self.model,
                "-d", self.device,
                "-j", str(self.jobs),
                "-o", str(out_dir),
                str(source),
            ],
            check=True,
        )

        produced = []
        model_dir = out_dir / self.model / source.stem
        for kind in MODEL_STEMS.get(self.model, MODEL_STEMS["htdemucs"]):
            path = model_dir / f"{kind.value}.wav"
            if path.exists():
                produced.append(
                    SeparatedStem(kind=kind, path=path, sample_rate=44100, duration_s=0.0)
                )
        return SeparationResult(tuple(produced), backend=self.name, model=self.model)
