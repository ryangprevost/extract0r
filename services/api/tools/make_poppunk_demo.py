"""A 170 BPM pop punk demo, so the pop-punk-to-EDM use case can be shown on something that
actually moves. Everything here is synthesised by this project's own code - no recordings,
nothing anybody else owns - which is also why it is safe to demonstrate with.

    python tools/make_poppunk_demo.py ../../demo/poppunk-170bpm-original.wav

Upload the result on the first screen, separate it, then open pr0ducer and pick
"house / EDM · 128". Demo tracks in `storage/` are deleted after 24 hours by the retention
sweep, so this script is the durable copy rather than the audio.

Power chords in eighths, a driving root-note bass, a vocal-ish lead line, and a fast
backbeat. Four bars of verse, four of chorus, I-V-vi-IV in E.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

#: services/api, wherever this checkout lives.
API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))

import soundfile as sf  # noqa: E402

from app.domain.notes import NoteEvent  # noqa: E402
from app.services.drums.kit import KITS, render_voice  # noqa: E402
from app.services.synth.voice import PitchedVoice, render_notes  # noqa: E402

SR = 44100
BPM = 170.0
BEAT = 60.0 / BPM
EIGHTH = BEAT / 2
BARS = 8

#: I - V - vi - IV in E, the progression pop punk is made of. Roots as MIDI, bass register.
PROGRESSION = [40, 47, 49, 45]

#: A brighter, grittier guitar than the built-in voices: lots of upper partials, a short
#: pick attack, and enough stack to sound like two rhythm guitars hard-panned and summed.
GUITAR = PitchedVoice(
    partials=tuple(1.0 / n**0.7 for n in range(1, 22)),
    attack_s=0.004,
    decay_s=0.08,
    sustain=0.8,
    release_s=0.03,
    stack=3,
    detune_cents=9.0,
    brightness_decay=0.6,
)


def guitar_part() -> list[NoteEvent]:
    """Downstroked power chords in straight eighths: root, fifth, octave."""
    out = []
    for bar in range(BARS):
        root = PROGRESSION[bar % 4] + 12
        for e in range(8):
            start = (bar * 8 + e) * EIGHTH
            for interval in (0, 7, 12):
                out.append(NoteEvent(start, start + EIGHTH * 0.82, root + interval, velocity=104))
    return out


def bass_part() -> list[NoteEvent]:
    """Root notes on every eighth, the way pop punk bass locks to the kick and guitar."""
    out = []
    for bar in range(BARS):
        root = PROGRESSION[bar % 4]
        for e in range(8):
            start = (bar * 8 + e) * EIGHTH
            out.append(NoteEvent(start, start + EIGHTH * 0.88, root, velocity=110))
    return out


def lead_part() -> list[NoteEvent]:
    """A vocal-ish line, quieter in the verse and up an octave-ish in the chorus."""
    verse = [(0, 2), (2, 1), (4, 1), (4, 2), (2, 2)]
    chorus = [(7, 2), (9, 1), (11, 1), (12, 2), (11, 2)]
    out = []
    for bar in range(BARS):
        shape = verse if bar < 4 else chorus
        at = bar * 8 * EIGHTH
        base = 64 + (PROGRESSION[bar % 4] - 40) % 12
        for interval, length in shape:
            dur = length * EIGHTH
            out.append(NoteEvent(at, at + dur * 0.9, min(base + interval, 84), velocity=96))
            at += dur
    return out


def drum_part(duration: float) -> np.ndarray:
    out = np.zeros(int(duration * SR) + SR)
    kit = KITS["punchy"]
    rendered = {name: render_voice(kit[name], SR, seed=i) for i, name in enumerate(kit)}

    def hit(name: str, t: float, gain: float) -> None:
        sample = rendered[name]
        at = int(t * SR)
        out[at : at + sample.size] += sample[: max(0, min(sample.size, out.size - at))] * gain

    for bar in range(BARS):
        for beat in range(4):
            t = (bar * 4 + beat) * BEAT
            # The pop punk beat: kick on 1 and the "and" of 2, snare on 2 and 4.
            if beat in (0, 2):
                hit("kick", t, 1.0)
            if beat == 1:
                hit("kick", t + EIGHTH, 0.85)
            if beat in (1, 3):
                hit("snare", t, 0.95)
            hit("hihat", t, 0.45)
            hit("hihat", t + EIGHTH, 0.35)
    return out[: int(duration * SR)]


def main() -> None:
    duration = BARS * 4 * BEAT + 0.4
    guitar = render_notes(guitar_part(), SR, GUITAR, duration_s=duration)
    bass = render_notes(bass_part(), SR, "subbass", duration_s=duration)
    lead = render_notes(lead_part(), SR, "epiano", duration_s=duration)
    drums = drum_part(duration)

    n = min(len(guitar), len(bass), len(lead), len(drums))
    mix = guitar[:n] * 0.45 + bass[:n] * 0.7 + lead[:n] * 0.4 + drums[:n] * 0.75
    mix /= max(float(np.max(np.abs(mix))), 1e-9) / 0.89
    dest = Path(sys.argv[1])
    sf.write(str(dest), np.stack([mix, mix], axis=1), SR)
    print(f"wrote {dest.name}: {n / SR:.1f} s at {BPM:.0f} BPM, {BARS} bars")


if __name__ == "__main__":
    main()
