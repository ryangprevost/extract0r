"""Loudness-only mastering fallback.

No tonal matching, just EBU R128 measurement of both files and a gain move so the
target lands on the reference's integrated loudness, with a true-peak ceiling so the
result never clips. Uses ffmpeg's `loudnorm` filter, which is everywhere.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from app.services.mastering.base import LoudnessStats, MasteringReport

TRUE_PEAK_CEILING_DBTP = -1.0


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def measure(path: Path) -> LoudnessStats:
    """Run loudnorm in analysis mode and read the JSON block it prints to stderr."""
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
            "-af", "loudnorm=print_format=json", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    match = re.search(r"\{[^{}]*input_i[^{}]*\}", proc.stderr, re.DOTALL)
    if not match:
        raise RuntimeError(f"could not measure loudness of {path.name}")
    data = json.loads(match.group(0))
    return LoudnessStats(
        integrated_lufs=float(data["input_i"]),
        true_peak_dbtp=float(data["input_tp"]),
        loudness_range_lu=float(data["input_lra"]),
    )


class LoudnessMatchEngine:
    name = "loudness"

    def available(self) -> bool:
        return _ffmpeg_available()

    def match(self, target: Path, reference: Path, out_path: Path) -> MasteringReport:
        if not self.available():
            raise RuntimeError("ffmpeg is not on PATH; loudness matching is unavailable")

        report = MasteringReport(backend=self.name)
        report.source = measure(target)
        report.reference = measure(reference)
        report.warnings.append(
            "Loudness-only match: frequency balance is untouched. "
            "Install matchering for tonal matching."
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-i", str(target),
                "-af",
                f"loudnorm=I={report.reference.integrated_lufs}:"
                f"TP={TRUE_PEAK_CEILING_DBTP}:"
                f"LRA={report.reference.loudness_range_lu}",
                str(out_path),
            ],
            capture_output=True,
            check=True,
        )
        report.gain_applied_db = (
            report.reference.integrated_lufs - report.source.integrated_lufs
        )
        report.result = measure(out_path)
        return report
