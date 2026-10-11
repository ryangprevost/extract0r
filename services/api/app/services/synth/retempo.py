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


# --- the parts that cannot be re-played ------------------------------------------------
#
# Sprint 3 candidate E. A vocal is not a list of notes this application can sing back, so
# at a new tempo it has to be stretched. Chosen by measurement (candidate D) on a vocal with
# ground truth at exactly this use case's ratio, 170 -> 128:
#
#   |             | licence    | spectral fidelity | attacks | time  |
#   | librosa     | ISC        | 6.1 dB            | 0.20    | 1.67s |
#   | Signalsmith | MIT        | 3.8 dB            | 0.34    | 0.14s |
#   | Rubber Band | GPLv2/paid | 5.2 dB            | 0.81    | 0.41s |
#
# Signalsmith is the most faithful on sustained, tonal material - which is what a vocal
# mostly is - and the fastest. Rubber Band's real advantage is transients, and transients
# are exactly what this module never stretches: drums are re-struck. The architecture and
# the licence point the same way, which is a better reason than "it was free".
#
# A measurement note worth keeping: the first spectral metric floored silence at -120 dB and
# so measured noise floors rather than music. An inaudible 16-bit round trip moved it from
# 12 dB to 33, and it ranked Signalsmith *worst* - the opposite of the truth. Fixed by
# flooring each frame 60 dB below its own peak, and checked by that same round trip.


def stretcher_available() -> str:
    """Which stretcher this machine will use, said out loud so the result can be judged."""
    try:
        import python_stretch  # noqa: F401

        return "signalsmith"
    except ImportError:
        return "librosa"


def stretch(audio: np.ndarray, sample_rate: int, scale: float) -> np.ndarray:
    """Make a part `scale` times longer without changing its pitch.

    `audio` is (samples,) or (samples, channels); the result has the same layout.

    **Signalsmith's time factor is a speed factor**, the opposite way round from librosa's
    and Rubber Band's: `setTimeFactor(1.328)` made audio *shorter* when first tried. So it is
    given `1 / scale` here, and a test asserts the length, because getting this backwards
    turns a slowdown into a speed-up and is not something anyone would hear as a bug.
    """
    if abs(scale - 1.0) < 1e-6:
        return np.asarray(audio, dtype=np.float64)

    data = np.asarray(audio, dtype=np.float32)
    mono = data.ndim == 1
    channels_first = data[None, :] if mono else data.T.copy()

    if stretcher_available() == "signalsmith":
        import python_stretch as ps

        engine = ps.Signalsmith.Stretch()
        engine.preset(channels_first.shape[0], sample_rate)
        engine.setTimeFactor(1.0 / scale)
        out = np.asarray(engine.process(channels_first), dtype=np.float64)
    else:
        import librosa

        out = np.stack(
            [librosa.effects.time_stretch(ch, rate=1.0 / scale) for ch in channels_first]
        ).astype(np.float64)

    # Exactly the length the arithmetic says. A stretcher a few samples long or short
    # drifts against the re-played parts it is about to be summed with.
    want = int(round(channels_first.shape[1] * scale))
    out = out[:, :want] if out.shape[1] >= want else np.pad(
        out, ((0, 0), (0, want - out.shape[1]))
    )
    return out[0] if mono else out.T


# --- the whole song at the new tempo ---------------------------------------------------

#: How far a re-played part's length may be from what the tempo implies before it is treated
#: as having been rendered at a *different* tempo. Renders are named by stem and voice, not
#: by tempo, so a bass played at 90 and then a target of 128 would otherwise be picked up
#: and summed - a version at two tempos at once, which is the worst failure available here.
LENGTH_TOLERANCE = 0.02


@dataclass(frozen=True, slots=True)
class Part:
    """How one stem got into the version, said in the words the screen uses."""

    stem: str
    how: str  # "re-played" or "stretched" or "as recorded"
    detail: str


class StaleRender(ValueError):
    """A re-played part that was rendered at some other tempo."""

    def __init__(self, stem: str, got_s: float, want_s: float) -> None:
        super().__init__(
            f"The {stem} part was played at a different tempo ({got_s:.1f} s long, this version "
            f"needs {want_s:.1f} s). Press Play it on the {stem} again at this tempo."
        )
        self.stem = stem


def bounce(
    stems: dict[str, np.ndarray],
    sample_rate: int,
    scale: float,
    replays: dict[str, tuple[np.ndarray, str]],
) -> tuple[np.ndarray, list[Part]]:
    """Every part of the song at the new tempo, summed. Returns the audio and the account.

    `stems` are the separated parts as recorded, at the original tempo. `replays` maps a
    stem to its re-played render - already at the new tempo - and the voice that played it.
    A stem with a replay uses it; every other stem is stretched.

    **The account is half the point.** "Drums: re-played on the punchy kit. Vocals:
    stretched." is what lets somebody understand what they made and trust it, and it is the
    honest answer to the question this whole feature raises - how much of this is still my
    performance?
    """
    if not stems:
        return np.zeros((0, 2)), []

    longest = max(len(audio) for audio in stems.values())
    length = int(round(longest * scale))
    mix = np.zeros((length, 2))
    account: list[Part] = []
    engine = stretcher_available()

    for stem, audio in stems.items():
        audio = np.asarray(audio, dtype=np.float64)
        if audio.ndim == 1:
            audio = np.stack([audio, audio], axis=1)

        if stem in replays:
            render, voice = replays[stem]
            render = np.asarray(render, dtype=np.float64)
            if render.ndim == 1:
                render = np.stack([render, render], axis=1)
            want = len(audio) * scale
            if abs(len(render) - want) > want * LENGTH_TOLERANCE:
                raise StaleRender(stem, len(render) / sample_rate, want / sample_rate)
            part = render
            account.append(Part(stem, "re-played", f"on the {voice}"))
        elif abs(scale - 1.0) < 1e-6:
            part = audio
            account.append(Part(stem, "as recorded", "unchanged"))
        else:
            part = stretch(audio, sample_rate, scale)
            account.append(Part(stem, "stretched", f"with {engine}"))

        take = min(len(part), length)
        mix[:take] += part[:take]

    # Down to -1 dBFS if the sum went over. Not a limiter - this is a sketch of a version,
    # and the mastering page is where loudness is decided. It only stops the file clipping.
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    ceiling = 10 ** (-1.0 / 20)
    if peak > ceiling:
        mix *= ceiling / peak
    return mix, account


#: Stems whose character lives in their attacks. Stretching softens attacks - measured at
#: 0.34 of the truth for the stretcher in use - so when one of these is stretched rather than
#: re-played, the summary says so and says what to do about it.
PERCUSSIVE = ("drums",)


def summarise(move: Move | None, account: list[Part]) -> dict:
    """What a bounced version is made of, in words a person can act on.

    **Not `Move.describe()`.** That sentence - "re-played rather than stretched, so nothing
    is smeared" - is true of one re-played part and was being printed on whole bounces where
    five of six parts had been stretched, drums included. Somebody would hear soft drums and
    read that nothing smeared. For a feature whose job is to make people confident in what
    they made, a reassurance that is false is worse than none.

    So this counts. It names which parts were re-played and which stretched, and when a
    percussive part was stretched it says what that costs and how to avoid it - which turns
    the weakness into the next thing to try rather than a thing to be confused by.
    """
    replayed = [p.stem for p in account if p.how == "re-played"]
    stretched = [p.stem for p in account if p.how == "stretched"]

    if move is None or abs(move.scale - 1.0) < 1e-6:
        headline = "Same tempo — every part as you chose it."
    else:
        headline = (
            f"{move.source_bpm:.0f} to {move.target_bpm:.0f} BPM, "
            f"{move.percent}% {move.direction}."
        )

    lines = []
    if replayed:
        lines.append(
            f"Re-played at the new tempo, so as crisp as the original: {', '.join(replayed)}."
        )
    if stretched:
        lines.append(f"Stretched to fit: {', '.join(stretched)}.")

    tip = ""
    soft = [s for s in stretched if s in PERCUSSIVE]
    if soft:
        tip = (
            f"The {', '.join(soft)} were stretched, which softens every hit. Play them on a "
            f"kit above and bounce again - re-struck drums keep their punch at any tempo."
        )

    return {"headline": headline, "lines": lines, "tip": tip}
