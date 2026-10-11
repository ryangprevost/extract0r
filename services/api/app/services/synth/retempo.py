"""Put a part at a different tempo without stretching it.

Sprint 3, candidates B and C. Ryan: *"I just want to see it taking pop punk songs to edm
songs as a use case for now."*

### Why this is not time-stretching, and why that matters more than it sounds

A tempo change normally means a phase vocoder, and a phase vocoder means smeared transients.
librosa's own documentation is blunt about its:

> does not try to handle transients and is likely to produce many audible artifacts

Drums are nothing *but* transients, so a pop punk record stretched to 128 BPM arrives with
its snare turned to mush. That is the whole difficulty of the use case, and it is the reason
Rubber Band exists and is GPL-or-pay.

**This application does not have to stretch the parts it has transcribed.** `drums/kit.py`
synthesises a kit at whatever hit positions it is given. `synth/voice.py` plays a part at
whatever note times it is given. So for drums and for any re-voiced part, a tempo change is
arithmetic on a list of times and then a fresh render - **nothing is stretched, so nothing
smears.** The output is as clean at 128 BPM as it was at 170.

### What that costs, said plainly rather than buried

Re-emitting is not free of consequence, it is free of *artefacts*:

* **The drums become the kit, not your drums.** A re-emitted drum part is synthesis at your
  drummer's timing, not your drummer's sound. For pop punk to EDM that is usually the point;
  it is still a substitution and the screen has to say so.
* **Anything not transcribed does not move.** Vocals and parts kept as recorded stay at the
  original tempo, so a half-converted mix is incoherent. Sprint 3 candidates D and E are
  about that, and until they exist this is honest about which parts moved.
* **Timing is scaled, not quantised.** A drummer who rushed the chorus still rushes it,
  proportionally. That is deliberate: this project measures timing rather than correcting
  it, and re-emission must not become quantisation by accident.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.domain.notes import NoteEvent
from app.services.drums.detect import Hit
from app.services.drums.kit import DRUMS, KITS, VOICE_FOR_STEM, render_voice, replaceable

#: How far the tempo may be moved. Beyond this the result stops being the same performance:
#: a part at half speed has different note *lengths* relative to the beat, and this module
#: scales positions rather than re-interpreting the playing. Pop punk to EDM - 170 to 128 -
#: is 0.75, comfortably inside.
MIN_RATIO = 0.5
MAX_RATIO = 2.0


@dataclass(frozen=True, slots=True)
class Move:
    """A tempo change, and what it did - the figures the screen needs to explain itself."""

    source_bpm: float
    target_bpm: float
    #: What every time is multiplied by. Greater than one means the song gets longer.
    scale: float
    duration_before_s: float
    duration_after_s: float

    @property
    def percent(self) -> int:
        """How much slower or faster, as a whole number, for saying out loud."""
        return int(round(abs(1.0 - 1.0 / self.scale) * 100))

    @property
    def direction(self) -> str:
        return "slower" if self.scale > 1.0 else "faster"

    def describe(self) -> str:
        if abs(self.scale - 1.0) < 0.001:
            return "Same tempo — nothing moved."
        return (
            f"{self.source_bpm:.0f} to {self.target_bpm:.0f} BPM, "
            f"{self.percent}% {self.direction}. "
            f"Re-played at the new tempo rather than stretched, so nothing is smeared."
        )


def plan(source_bpm: float, target_bpm: float, duration_s: float) -> Move | None:
    """Work out the move, or None when it is not one this should attempt.

    None rather than a clamp: silently doing something smaller than what was asked for is
    how a user ends up at 140 BPM believing they are at 100.
    """
    if source_bpm <= 0 or target_bpm <= 0:
        return None
    scale = source_bpm / target_bpm
    if not MIN_RATIO <= scale <= MAX_RATIO:
        return None
    return Move(
        source_bpm=source_bpm,
        target_bpm=target_bpm,
        scale=scale,
        duration_before_s=duration_s,
        duration_after_s=duration_s * scale,
    )


def move_notes(notes: list[NoteEvent], scale: float) -> list[NoteEvent]:
    """The same performance, at a different tempo.

    Positions *and* lengths scale together, because a note held for a beat is still held
    for a beat at the new tempo - scaling only the starts would turn a legato line staccato
    as the song slowed down.

    Microtiming survives proportionally. A snare 20 ms behind the beat at 170 BPM is 27 ms
    behind it at 128, which is the same lateness measured in beats and is the thing that
    makes a performance sound like a performance. Quantising here would be a different
    product, and one this project has twice decided against.
    """
    return [
        NoteEvent(
            start_s=note.start_s * scale,
            end_s=note.end_s * scale,
            pitch=note.pitch,
            velocity=note.velocity,
            confidence=note.confidence,
        )
        for note in notes
    ]


def move_hits(hits: list[Hit], scale: float) -> list[Hit]:
    """Drum strokes at the new tempo. Only the time changes - a kick is still a kick."""
    return [
        Hit(time_s=hit.time_s * scale, kinds=list(hit.kinds), strength=hit.strength,
            rises=dict(hit.rises))
        for hit in hits
    ]


def rebuild_drums(
    hits: list[Hit],
    sample_rate: int,
    duration_s: float,
    kit: str = "tight",
    drums: tuple[str, ...] = ("kick", "snare", "hihat"),
) -> np.ndarray:
    """A drum part, synthesised at these positions, with nothing underneath it.

    This is where the no-stretching claim is actually cashed. `kit.layer` adds triggers *to*
    an existing stem, because reinforcing a drum that is still there is what it is for. Here
    the original stem is not present at all - it is at the old tempo and cannot come - so
    the kit is the whole part.

    Hi-hats are included by default, unlike in `layer`. There, a mistriggered hat sits on top
    of a real one and is audible as a flam; here there is no real one underneath, and a drum
    part with no hats at 128 BPM is not a drum part.
    """
    out = np.zeros((int(duration_s * sample_rate) + sample_rate, 2))
    voices = KITS.get(kit) or KITS["tight"]
    rendered = {
        name: render_voice(voices[name], sample_rate, seed=index)
        for index, name in enumerate(DRUMS)
        if name in drums and name in voices
    }
    if not rendered:
        return out[: int(duration_s * sample_rate)]

    for hit in hits:
        start = int(hit.time_s * sample_rate)
        if start < 0 or start >= out.shape[0]:
            continue
        for name in replaceable(hit):
            sample = rendered.get(VOICE_FOR_STEM.get(name, name))
            if sample is None:
                continue
            end = min(start + sample.size, out.shape[0])
            # Scaled by how hard the original was struck, so the part keeps its dynamics
            # rather than arriving as a machine playing everything at one velocity.
            shaped = sample[: end - start] * max(hit.strength, 0.02)
            out[start:end, 0] += shaped
            out[start:end, 1] += shaped

    peak = float(np.max(np.abs(out)))
    if peak > 1.0:
        out /= peak
    return out[: int(duration_s * sample_rate)]
