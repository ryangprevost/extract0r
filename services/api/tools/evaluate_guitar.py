"""X0R-306, guitar half: what does the polyphonic transcriber actually produce?

There is no hand-written guitar tab to score against, so this measures the things that
are checkable without one:

* how many notes come back, and how long they are — a rock guitar part is not 4000
  notes, and it is not 12 either
* whether they sit in a guitar's register, or an octave out
* whether their pitch classes agree with the key the bass establishes; a guitar playing
  a different set of notes from the bass is a transcription failure, not an arrangement

    python tools/evaluate_guitar.py <guitar-stem.wav> [--thresholds]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.notes import StemKind  # noqa: E402
from app.domain.tab.fretboard import DROP_D_GUITAR, solve_with_report  # noqa: E402
from app.domain.timing import PITCH_CLASSES  # noqa: E402

# The bass plays F#1 G1 A1 B1 D2 (+ drop-D D1), so the song sits in G major / E minor.
KEY_CLASSES = {2, 4, 6, 7, 9, 11}          # D E F# G A B
ROOT_CLASSES = {2, 6, 7, 9, 11}            # the roots the bass actually lands on
# A guitar in drop D spans D2 (38) to roughly the 22nd fret of the top string (86).
GUITAR_RANGE = (38, 86)


def describe(notes, label: str) -> None:
    if not notes:
        print(f"{label:<22} no notes")
        return

    total = len(notes)
    in_key = sum(1 for n in notes if n.pitch % 12 in KEY_CLASSES)
    on_root = sum(1 for n in notes if n.pitch % 12 in ROOT_CLASSES)
    in_range = sum(1 for n in notes if GUITAR_RANGE[0] <= n.pitch <= GUITAR_RANGE[1])
    lengths = sorted(n.duration_s for n in notes)

    print(
        f"{label:<22} {total:>5} notes | in key {in_key / total:>5.1%} | "
        f"on a root {on_root / total:>5.1%} | in range {in_range / total:>5.1%} | "
        f"median {lengths[total // 2]:.3f}s"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stem", type=Path)
    parser.add_argument("--thresholds", action="store_true",
                        help="sweep onset/frame thresholds instead of one run")
    args = parser.parse_args()

    from app.services.transcription.basic_pitch import BasicPitchTranscriber

    if args.thresholds:
        print("sweeping basic-pitch thresholds\n")
        for onset in (0.3, 0.5, 0.7):
            for frame in (0.3, 0.5):
                for conf in (0.0, 0.3):
                    t = BasicPitchTranscriber(
                        onset_threshold=onset, frame_threshold=frame, min_confidence=conf
                    )
                    result = t.transcribe(args.stem, StemKind.GUITAR)
                    describe(result.notes, f"onset={onset} frame={frame} conf={conf}")
        return 0

    result = BasicPitchTranscriber().transcribe(args.stem, StemKind.GUITAR)
    notes = result.notes
    describe(notes, "defaults")
    if not notes:
        return 1

    print("\npitch-class distribution:")
    classes = Counter(n.pitch % 12 for n in notes)
    top = classes.most_common(1)[0][1]
    for cls in range(12):
        count = classes.get(cls, 0)
        if not count:
            continue
        mark = "  <- root in this song" if cls in ROOT_CLASSES else (
            "  <- in key" if cls in KEY_CLASSES else "  <- OUT OF KEY")
        print(f"  {PITCH_CLASSES[cls]:<3} {count:>5}  {'#' * max(1, int(30 * count / top))}{mark}")

    octaves = Counter(n.pitch // 12 - 1 for n in notes)
    print(f"\noctave spread: {dict(sorted(octaves.items()))}  (a guitar lives in 2-5)")

    report = solve_with_report(notes, DROP_D_GUITAR)
    print(f"\nfretboard: {len(report.shapes)} shapes, {len(report.dropped)} unplayable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
