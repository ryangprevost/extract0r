"""Render a :class:`MixSpec` plus stem files down to a single MP3 via ffmpeg."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.services.mixdown.mixspec import MixSpec, build_filter_complex


@dataclass(frozen=True, slots=True)
class RenderResult:
    path: Path
    command: list[str]


class MixdownRenderer:
    name = "ffmpeg"

    def available(self) -> bool:
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            return False
        return True

    def build_command(
        self, spec: MixSpec, stem_paths: dict[str, Path], out_path: Path
    ) -> list[str]:
        """Pure: produce the exact ffmpeg argv. Kept separate so tests can assert on it."""
        names = list(stem_paths)
        command = ["ffmpeg", "-y", "-hide_banner"]
        for name in names:
            command += ["-i", str(stem_paths[name])]
        command += [
            "-filter_complex", build_filter_complex(spec, names),
            "-map", "[out]",
            "-ar", str(spec.sample_rate),
            "-c:a", "libmp3lame",
            "-b:a", f"{spec.bitrate_kbps}k",
            str(out_path),
        ]
        return command

    def render(
        self, spec: MixSpec, stem_paths: dict[str, Path], out_path: Path
    ) -> RenderResult:
        if not self.available():
            raise RuntimeError("ffmpeg is not on PATH; cannot render a mixdown")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        command = self.build_command(spec, stem_paths, out_path)
        subprocess.run(command, capture_output=True, check=True)
        return RenderResult(path=out_path, command=command)
