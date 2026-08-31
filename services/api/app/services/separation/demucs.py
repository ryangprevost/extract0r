"""Demucs v4 backend — the real separator.

``htdemucs`` gives drums/bass/vocals/other; ``htdemucs_6s`` adds guitar and piano,
which is what makes per-instrument tab worth doing.

Run through the CLI rather than importing the model: it keeps multi-gigabyte weights out
of the web process, and it gives us a progress stream to parse. Imports are deferred so
the API still boots on a machine without torch.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from collections import deque
from collections.abc import Callable
from pathlib import Path

from app.domain.notes import StemKind
from app.services.separation.base import SeparationResult, describe_stem

log = logging.getLogger(__name__)

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

# Demucs draws a tqdm bar on stderr:
#   " 42%|####2     | 100.8/241.2 [00:15<00:21,  6.44seconds/s]"
# The fraction is more precise than the integer percentage, so prefer it.
_FRACTION = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*\[")
_PERCENT = re.compile(r"(\d{1,3})%\|")

# How many stderr lines to keep so a failure can be reported with context.
_STDERR_TAIL = 20


def parse_progress(line: str) -> float | None:
    """Pull a 0..1 fraction out of one line of Demucs output, or None if there is none.

    Pure and separately tested — the parsing is the part that breaks when Demucs changes
    its output, and it should not take a model download to find that out.
    """
    match = _FRACTION.search(line)
    if match:
        done, total = float(match.group(1)), float(match.group(2))
        if total > 0:
            return max(0.0, min(1.0, done / total))
    match = _PERCENT.search(line)
    if match:
        return max(0.0, min(1.0, int(match.group(1)) / 100.0))
    return None


class DemucsSeparator:
    name = "demucs"

    def __init__(
        self,
        model: str = "htdemucs_6s",
        device: str = "cpu",
        jobs: int = 1,
        shifts: int = 0,
    ) -> None:
        self.model = model
        self.device = device
        self.jobs = jobs
        # Shifts multiply runtime for a small quality gain; default off.
        self.shifts = shifts

    def available(self) -> bool:
        try:
            import demucs  # noqa: F401
            import torch  # noqa: F401
        except ImportError:
            return False
        return True

    def separate(
        self,
        source: Path,
        out_dir: Path,
        on_progress: Callable[[float], None] | None = None,
    ) -> SeparationResult:
        if not self.available():
            raise RuntimeError(
                "demucs/torch are not installed - install requirements-ml.txt "
                "or set SEPARATION_BACKEND=stub"
            )
        out_dir.mkdir(parents=True, exist_ok=True)

        command = [
            sys.executable, "-m", "demucs.separate",
            "-n", self.model,
            "-d", self.device,
            "-j", str(self.jobs),
            "--shifts", str(self.shifts),
            "-o", str(out_dir),
            str(source),
        ]
        log.info("running %s", " ".join(command))
        output_tail = self._run(command, on_progress)

        produced = []
        model_dir = out_dir / self.model / source.stem
        for kind in MODEL_STEMS.get(self.model, MODEL_STEMS["htdemucs"]):
            path = model_dir / f"{kind.value}.wav"
            if path.exists():
                produced.append(describe_stem(kind, path))
        if not produced:
            # Demucs exits 0 for some failures - a missing input file, for one - so a
            # clean return code is not proof of success. Its stdout is the only place
            # the actual reason appears, so it must reach the user.
            detail = "\n".join(output_tail)
            raise RuntimeError(
                f"demucs failed: it exited cleanly but wrote no stems to "
                f"{model_dir}.\n{detail}"
            )
        return SeparationResult(tuple(produced), backend=self.name, model=self.model)

    def _run(
        self, command: list[str], on_progress: Callable[[float], None] | None
    ) -> list[str]:
        """Stream Demucs' output, forwarding progress and returning a tail for errors."""
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            errors="replace",
        )
        tail: deque[str] = deque(maxlen=_STDERR_TAIL)
        highest = 0.0

        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.rstrip()
            if line:
                tail.append(line)
            fraction = parse_progress(line)
            # Demucs restarts its bar per model in a bag-of-models; never go backwards.
            if fraction is not None and on_progress and fraction > highest:
                highest = fraction
                on_progress(fraction)

        if process.wait() != 0:
            detail = "\n".join(tail)
            raise RuntimeError(f"demucs failed (exit {process.returncode}):\n{detail}")
        return list(tail)
