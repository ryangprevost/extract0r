"""X0R-306: score a bass transcription against a hand-written tab.

Ground truth here is a tab the bass player wrote for their own song, which sidesteps the
licensing problem entirely — you cannot buy a MUSDB18 track whose bassist will tell you
what they played.

The metrics are deliberately blunt, because the failures worth catching are blunt:

* **in-vocabulary rate** — the fraction of detected notes whose pitch the song actually
  contains. A bass line built from five notes should not produce thirty.
* **octave correctness** — are notes in the register a bass occupies, or an octave up?
  This is the classic pitch-tracker failure and it is invisible in a pitch-class score.
* **pitch-class agreement** — how the detected distribution compares with the expected one.

    python tools/evaluate_bass.py <bass-stem.wav>
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.notes import StemKind  # noqa: E402
from app.domain.tab.fretboard import solve_with_report  # noqa: E402
from app.domain.timing import PITCH_CLASSES  # noqa: E402

# From the reference tab: standard-tuning bass, E1=28 A1=33 D2=38 G2=43.
#   E-7 = 35 (B1)   A-5 = 38 (D2)   E-5 = 33 (A1)   E-3 = 31 (G1)   E-2 = 30 (F#1)
EXPECTED_PITCHES = {30, 31, 33, 35, 38}
EXPECTED_CLASSES = {p % 12 for p in EXPECTED_PITCHES}
# The song was tracked in drop D, so D1 (26) is a real note, not an octave error.
DROP_D_LOW = 26
EXPECTED_PITCHES_WITH_DROP_D = EXPECTED_PITCHES | {DROP_D_LOW}
PLAUSIBLE_RANGE = (26, 50)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stem", type=Path)
    parser.add_argument("--limit", type=float, default=0.0, help="only the first N seconds")
    args = parser.parse_args()

    from app.services.transcription.pyin import PyinTranscriber

    transcriber = PyinTranscriber()
    result = transcriber.transcribe(args.stem, StemKind.BASS)
    notes = [n for n in result.notes if not args.limit or n.start_s < args.limit]

    if not notes:
        print("no notes detected at all")
        return 1

    total = len(notes)
    in_vocab = sum(1 for n in notes if n.pitch in EXPECTED_PITCHES_WITH_DROP_D)
    in_class = sum(1 for n in notes if n.pitch % 12 in EXPECTED_CLASSES)
    in_range = sum(1 for n in notes if PLAUSIBLE_RANGE[0] <= n.pitch <= PLAUSIBLE_RANGE[1])

    print(f"stem            {args.stem.name}")
    print(f"notes detected  {total}")
    print(f"duration        {max(n.end_s for n in notes):.1f}s")
    print(f"median length   {sorted(n.duration_s for n in notes)[total // 2]:.3f}s")
    print()
    print(f"in the song's pitches      {in_vocab / total:>6.1%}  ({in_vocab}/{total})")
    print(f"right pitch class         {in_class / total:>6.1%}  (ignores octave errors)")
    span = f"{PLAUSIBLE_RANGE[0]}-{PLAUSIBLE_RANGE[1]}"
    print(f"in a bass register        {in_range / total:>6.1%}  ({span})")
    print()

    print("detected pitch distribution (top 12):")
    counts = Counter(n.pitch for n in notes)
    for pitch, count in counts.most_common(12):
        name = f"{PITCH_CLASSES[pitch % 12]}{pitch // 12 - 1}"
        mark = "  <- in the song" if pitch in EXPECTED_PITCHES_WITH_DROP_D else ""
        bar = "#" * max(1, int(40 * count / counts.most_common(1)[0][1]))
        print(f"  {pitch:>3} {name:<4} {count:>5}  {bar}{mark}")

    print()
    print("expected, from the reference tab:")
    for pitch in sorted(EXPECTED_PITCHES):
        name = f"{PITCH_CLASSES[pitch % 12]}{pitch // 12 - 1}"
        got = counts.get(pitch, 0)
        print(f"  {pitch:>3} {name:<4} detected {got:>5} times")

    octaves = Counter(n.pitch // 12 - 1 for n in notes)
    print(f"\noctave spread: {dict(sorted(octaves.items()))}  (expect almost all 1 and 2)")

    from app.domain.tab.fretboard import DROP_D_BASS

    report = solve_with_report(notes, DROP_D_BASS)
    print(
        f"\nfretboard: {len(report.shapes)} shapes, "
        f"{len(report.dropped)} dropped as unplayable"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
