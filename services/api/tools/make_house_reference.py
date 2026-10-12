"""A 124 BPM house track with known ingredients, to test "remix like your reference" against.

    python tools/make_house_reference.py ../../demo/house-124bpm-reference.wav

Like the pop punk demo, everything is synthesised by this project's own code, so there is
nothing in it anybody else owns. Unlike a real reference, every essential element is known -
which is what makes it a test rather than a demonstration:

* tempo 124 BPM
* the "house" beat on the roomy kit, hats swung at 0.3 (55%)
* a pumped bass on the 808, 6 dB deep
* a pad, pumped the same way

Upload it as the reference for the pop punk demo, split it, and press *Remix like your
reference*: the recipe should read back 124, the house pattern, a swing near 55%, and a
pump near 6 dB.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))

import soundfile as sf  # noqa: E402

from app.domain.notes import NoteEvent  # noqa: E402
from app.services.synth.groove import BUILT_IN, Groove, Step  # noqa: E402
from app.services.synth.groove import render as play  # noqa: E402
from app.services.synth.retempo import beat_grid, pump  # noqa: E402
from app.services.synth.voice import render_notes  # noqa: E402

SR = 44100
BPM = 124.0
BEAT = 60.0 / BPM
BARS = 16
SWING = 0.3
PUMP_DB = 6.0
#: vi - IV - I - V in A minor-ish, one chord a bar.
ROOTS = [33, 29, 36, 31]


def beat() -> Groove:
    """House, with closed hats on every sixteenth under the open ones so swing is audible."""
    house = Groove.from_dict(BUILT_IN["house"].to_dict())
    house.steps["hihat"] = [
        Step(rate=1.0, velocity=0.9 if i % 4 == 2 else 0.45) for i in range(16)
    ]
    return house


def main() -> None:
    duration = BARS * 4 * BEAT
    length = int((duration + 0.5) * SR)
    beats = beat_grid(0.0, BPM, duration)
    drums = play(beat(), beats, SR, length, kit="roomy", swing=SWING)

    bass_notes = [NoteEvent((bar * 4 + b) * BEAT + BEAT / 2, (bar * 4 + b) * BEAT + BEAT * 0.95,
                            ROOTS[bar % 4], 110)
                  for bar in range(BARS) for b in range(4)]
    bass = render_notes(bass_notes, SR, "808", duration_s=duration + 0.5)[:length]
    pad_notes = [NoteEvent(bar * 4 * BEAT, (bar + 1) * 4 * BEAT, ROOTS[bar % 4] + 24 + i, 80)
                 for bar in range(BARS) for i in (0, 3, 7)]
    pad = render_notes(pad_notes, SR, "pad", duration_s=duration + 0.5)[:length]

    bass = pump(bass, SR, beats, BPM, PUMP_DB)
    pad = pump(pad, SR, beats, BPM, PUMP_DB)
    mono = drums.mean(axis=1) * 0.8 + bass * 0.6 + pad * 0.35
    mono /= max(float(np.max(np.abs(mono))), 1e-9) / 0.89
    dest = Path(sys.argv[1])
    sf.write(str(dest), np.stack([mono, mono], axis=1), SR)
    print(f"wrote {dest.name}: {duration:.1f} s at {BPM:.0f} BPM, {BARS} bars, swing {SWING}, "
          f"pump {PUMP_DB} dB")


if __name__ == "__main__":
    main()
