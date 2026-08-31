"""Reference matching via the `matchering` library.

Matchering does the two things a reference master actually needs: it fits the target's
average frequency response to the reference's, then matches RMS/peak. We wrap it so
the rest of the app only ever sees a :class:`MasteringReport`.
"""

from __future__ import annotations

from pathlib import Path

from app.services.mastering.base import MasteringReport


class MatcheringEngine:
    name = "matchering"

    def __init__(self, bit_depth: int = 24, preview: bool = False) -> None:
        self.bit_depth = bit_depth
        self.preview = preview

    def available(self) -> bool:
        try:
            import matchering  # noqa: F401
        except ImportError:
            return False
        return True

    def match(self, target: Path, reference: Path, out_path: Path) -> MasteringReport:
        if not self.available():
            raise RuntimeError(
                "matchering is not installed - install requirements-ml.txt "
                "or set MASTERING_BACKEND=loudness"
            )
        import matchering as mg

        out_path.parent.mkdir(parents=True, exist_ok=True)
        report = MasteringReport(backend=self.name)
        mg.log(warning_handler=lambda message: report.warnings.append(str(message)))
        mg.process(
            target=str(target),
            reference=str(reference),
            results=[mg.pcm24(str(out_path))],
        )
        return report
