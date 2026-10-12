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
    sounds: dict[str, np.ndarray] | None = None,
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
    if sounds is not None:
        # A kit from the library - possibly the user's own one-shots. X0R-1343.
        rendered = {name: hit for name, hit in sounds.items() if name in drums}
    else:
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
    """Which stretcher this machine will use, said out loud so the result can be judged.

    Empty when there is none. Both live in the ML extras, and an install without them used
    to find that out halfway through a bounce, as a `ModuleNotFoundError` in the job log -
    the route now asks first and says which parts to re-play instead.
    """
    try:
        import python_stretch  # noqa: F401

        return "signalsmith"
    except ImportError:
        pass
    try:
        import librosa  # noqa: F401

        return "librosa"
    except ImportError:
        return ""


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
#:
#: Tight, because every render is made by this code to an exact length. It was 2%, and a
#: render made before the kick-locked tempo (scaled by 168.5 rather than 170, 0.9% short)
#: slipped under that and would have been summed against parts that drift away from it.
LENGTH_TOLERANCE = 0.002


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
    beats: np.ndarray | None = None,
    bpm: float = 0.0,
    pump_db: float = 0.0,
    floor_kick: bool = False,
    drop_bar: int = 0,
    added_beat=None,
    beat_kit: str = "edm",
    swing: float | None = None,
    left_out: tuple[str, ...] = (),
    beat_sounds: dict[str, np.ndarray] | None = None,
    humanize: float = 0.0,
    pieces: list | None = None,
    layers_out: dict | None = None,
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
    # Sprint 5: an arrangement. Every part is cut at the same bar lines and laid end to end
    # (`arrange.assemble`), and everything added afterwards is laid on that new timeline.
    if pieces:
        from app.services.synth.arrange import arranged_beats

        if beats is not None:
            beats = arranged_beats(beats, pieces)
        length = int(round(sum(p.end_s - p.start_s for p in pieces) * sample_rate))
    mix = np.zeros((length, 2))
    account: list[Part] = []
    engine = stretcher_available()

    drops: list[int] = [drop_bar] if drop_bar else []
    if pieces and beats is not None:
        from app.services.synth.arrange import drop_bars

        drops = sorted({*drops, *drop_bars(pieces, beats)})
    builds: list[tuple[float, float]] = []
    if drops and beats is not None and bpm > 0:
        from app.services.synth.drop import _window

        builds = [_window(beats, bar) for bar in drops]
    beat_rests = list(builds)
    if pieces:
        from app.services.synth.arrange import muted_spans

        beat_rests += muted_spans(pieces, "beat")

    # The pump follows the kick. On every beat is right for a four-on-the-floor; under a
    # breakbeat or a trap pattern, whose kick is not on every beat, ducking on the beat
    # fights the beat. So with an added beat it ducks where that beat's kicks are.
    pump_at = beats
    if added_beat is not None and beats is not None and bpm > 0 and pump_db > 0:
        from app.services.synth.groove import events

        kicks = [t for t, kind, _ in events(added_beat, beats, beat_rests, swing,
                                             humanize=humanize) if kind == "kick"]
        if kicks:
            pump_at = np.asarray(kicks)
    # And it rests through a build, with the kick, so the drop is where the pump arrives.
    if builds and pump_at is not None:
        from app.services.synth.groove import resting

        pump_at = np.asarray([t for t in np.asarray(pump_at) if not resting(t, builds)])

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

        if pieces:
            from app.services.synth.arrange import assemble

            part = assemble(part, sample_rate, pieces, stem)

        # The pump goes on everything except the drums: ducking the kick to itself is
        # silence on every beat, which is the opposite of the effect.
        if pump_db > 0 and beats is not None and bpm > 0 and stem != "drums":
            part = pump(part, sample_rate, pump_at, bpm, pump_db)
        if drops and beats is not None and stem != "drums":
            from app.services.synth.drop import sweep

            for bar in drops:
                part = sweep(part, sample_rate, beats, bar)

        take = min(len(part), length)
        mix[:take] += part[:take]
        if layers_out is not None:
            # Sprint 7: each part kept on its own, for the mixer.
            layer = np.zeros((length, 2))
            layer[:take] = part[:take]
            layers_out[stem] = layer

    if pump_db > 0 and beats is not None and bpm > 0:
        pumped = [p.stem for p in account if p.stem != "drums"]
        if pumped:
            # Named for what it follows, because that is what is heard.
            follows = "kick" if added_beat is not None and pump_at is not beats else "beat"
            account.append(Part(f"pump on the {follows}", "pumped", ", ".join(pumped)))

    if added_beat is not None and beats is not None and bpm > 0:
        # Any groove - built in, or read off a reference - added alongside the band. Sprint 4.
        from app.services.synth.groove import render as play_groove

        played = play_groove(added_beat, beats, sample_rate, length, kit=beat_kit,
                             rest=beat_rests, swing=swing, sounds=beat_sounds,
                             humanize=humanize)
        mix += played
        if layers_out is not None:
            layers_out["beat"] = played
        account.append(Part("beat", "added", _beat_detail(added_beat, swing, humanize)))
    elif floor_kick and beats is not None and bpm > 0:
        # The added kick sits out the build, so the drop is where it arrives.
        played = four_on_the_floor(beats, bpm, sample_rate, length, rest=beat_rests)
        mix += played
        if layers_out is not None:
            layers_out["beat"] = played
        account.append(Part("four on the floor", "added",
                            "a kick on every beat and hats between — not from your recording"))
    for stem in left_out:
        account.append(Part(stem, "left out", "muted in this version - still in your stems"))
    if drops and beats is not None and bpm > 0:
        from app.services.synth.drop import build_and_drop, describe

        for bar in drops:
            built = build_and_drop(beats, bpm, sample_rate, length, bar)
            mix += built
            if layers_out is not None:
                layers_out["build"] = layers_out.get("build", 0) + built
            build, impact = describe(bar)
            account.append(Part("build", "added", build))
            account.append(Part("drop", "added", impact))
    if pieces:
        account.append(Part("arrangement", "arranged", _arrangement_detail(pieces, beats)))

    # Down to -1 dBFS if the sum went over. Not a limiter - this is a sketch of a version,
    # and the mastering page is where loudness is decided. It only stops the file clipping.
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    ceiling = 10 ** (-1.0 / 20)
    if peak > ceiling:
        mix *= ceiling / peak
    return mix, account


def _arrangement_detail(pieces: list, beats) -> str:
    """"6 blocks, 28 bars, 2 drops" - what the arrangement made, counted."""
    bars = len(beats) // 4 if beats is not None else 0       # whole bars only
    drops = sum(1 for p in pieces if p.drop)
    text = f"{len(pieces)} block{'s' if len(pieces) != 1 else ''}, {bars} bars"
    if drops:
        text += f", {drops} drop{'s' if drops != 1 else ''}"
    return text


def _beat_detail(groove, swing: float | None, humanize: float = 0.0) -> str:
    """How the account names an added beat: whose it is, and that it is not the band's."""
    whose = ("the beat from your reference" if groove.source == "your reference"
             else groove.name if groove.source == "you"
             else f"a {groove.name} beat")
    feel = ""
    if swing is not None and swing > 0.02:
        feel = f", swung at {int(round(50 + 50 * swing / 3))}%"
    elif groove.source == "your reference" and groove.swing_percent >= 54:
        feel = f", with its swing ({groove.swing_percent}%)"
    if humanize > 0.02:
        feel += ", played with a human feel" if humanize >= 0.6 else ", with a little human feel"
    return f"{whose}{feel} — not from your recording"


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
    added = [p for p in account if p.how == "added"]
    pumped = [p for p in account if p.how == "pumped"]
    left_out = [p.stem for p in account if p.how == "left out"]
    arranged = [p for p in account if p.how == "arranged"]

    if move is None or abs(move.scale - 1.0) < 1e-6:
        headline = "Same tempo — every part as you chose it."
    else:
        headline = (
            f"{move.source_bpm:.0f} to {move.target_bpm:.0f} BPM, "
            f"{move.percent}% {move.direction}."
        )

    lines = []
    if replayed:
        # At the song's own tempo there is no new tempo to speak of (Sprint 15).
        moved = move is not None and abs(move.scale - 1.0) > 1e-6
        lines.append(
            f"Re-played at the new tempo, so as crisp as the original: {', '.join(replayed)}."
            if moved else f"Re-played on the sounds you chose: {', '.join(replayed)}."
        )
    edited = [p.stem for p in account
              if p.how == "re-played" and p.detail.endswith("as you edited it")]
    if edited:
        # Sprint 6: an edit is the user's, and is never passed off as the band's playing.
        lines.append(f"Edited by you, so these play your notes rather than the band's: "
                     f"{', '.join(edited)}.")
    sampled = [p.stem for p in account
               if p.how == "re-played" and "sampled from your reference" in p.detail]
    if sampled:
        # Sprint 15: a sound taken from someone else's recording is named as such.
        lines.append(f"Played on a sound sampled from your reference - clear the sample "
                     f"before you release this: {', '.join(sampled)}.")
    if stretched:
        lines.append(f"Stretched to fit: {', '.join(stretched)}.")
    for part in pumped:
        if part.stem.endswith("kick"):
            lines.append(f"Pumping with the added beat's kick, like a dance record: "
                         f"{part.detail}.")
        else:
            lines.append(f"Pumping on every beat, like a dance record: {part.detail}.")
    for part in added:
        lines.append(f"Added: {part.detail}.")
    for part in arranged:
        lines.append(f"Rearranged: {part.detail}, cut on the bar lines so the beat carries "
                     f"straight through.")
    if left_out:
        lines.append(f"Left out, by your choice: {', '.join(left_out)}. They are still in "
                     f"your stems and come back the moment you tick them.")

    tip = ""
    soft = [s for s in stretched if s in PERCUSSIVE]
    if soft:
        tip = (
            f"The {', '.join(soft)} were stretched, which softens every hit. Play them on a "
            f"kit above and bounce again - re-struck drums keep their punch at any tempo."
        )

    return {"headline": headline, "lines": lines, "tip": tip}


# --- what makes a tempo change sound like a dance record --------------------------------
#
# A pop punk song at 128 BPM is not yet an EDM track. Ryan, hearing the first version: the
# MIDI "is a great start but I want to see it subbing in samples for synths and other
# instruments to create an actual remix". Two things are missing that no amount of re-voicing
# supplies, and they are the two a listener identifies the genre by inside a bar:
#
# * **The pump.** Every non-drum part ducks on every beat and swells back - a sidechain
#   compressor keyed to the kick. `mastering/sidechain.py` already has the shape (X0R-1308);
#   here it is used deeper, as an effect rather than a correction, with its release tied to
#   the tempo so it has recovered by the next beat.
# * **Four on the floor.** A kick on every beat, offbeat hats between. A pop punk drummer's
#   pattern re-struck on a dance kit is still a pop punk pattern.
#
# The second one is **added, not moved**, and that distinction is the line this project kept
# when Ryan reopened tempo. Re-sequencing - moving the drummer's hits to where a dance record
# puts them - is still out. Laying a new part *alongside* the drummer leaves every hit he
# played exactly where he played it, which is what a remixer adding a kick does. The account
# says "added" and says it is not from the recording, so nobody mistakes it for their band.

#: How deep the pump goes. Mastering ducks a bass by 3 dB at most so it is felt and not heard;
#: a dance pump is *meant* to be heard. 8 dB is where it reads as the effect rather than as
#: a bass that got quieter, without the parts vanishing between beats.
PUMP_DB = 8.0

#: How much of the beat the swell back up takes. The rest of the beat sits at full level.
PUMP_RELEASE_BEATS = 0.75


def beat_grid(first_beat_s: float, bpm: float, duration_s: float) -> np.ndarray:
    """Every beat at the new tempo, starting from where the song's first beat now falls.

    A first beat a hair *before* zero - a kick found at -0.5 ms - wraps to almost a whole
    beat later under a plain modulo, and the song's opening beat gets no added kick. So a
    start within 20 ms of a full period is treated as the beat at zero.
    """
    if bpm <= 0 or duration_s <= 0:
        return np.array([])
    period = 60.0 / bpm
    start = first_beat_s % period
    if start > period - 0.02:
        start -= period
    beats = np.arange(start, duration_s, period)
    return np.clip(beats[beats >= -0.02], 0.0, None)


def pump_envelope(beats: np.ndarray, length: int, sample_rate: int, bpm: float,
                  depth_db: float = PUMP_DB) -> np.ndarray:
    """A gain curve that drops on every beat, *stays down*, then swells back.

    **Not `sidechain.gain_envelope`, which this first reused.** That curve recovers with a
    time constant of a quarter of its release, so it is nearly back up before the ear
    catches the dip - exactly right for the mastering correction it was written for, where
    the duck is meant to be felt rather than heard. Measured as a pump, an "8 dB" duck read
    **-1.9 dB** 60 ms after the beat. A dance pump is the opposite brief: the dip *is* the
    sound. So the recovery here is a smoothstep - flat at the bottom, rising through the
    middle of the beat, flat at the top - which is the breathing shape.
    """
    gain = np.ones(length)
    if length == 0 or depth_db <= 0 or bpm <= 0:
        return gain
    floor = 10.0 ** (-depth_db / 20.0)
    attack = max(1, int(0.005 * sample_rate))
    release = max(2, int(PUMP_RELEASE_BEATS * 60.0 / bpm * sample_rate))
    x = np.linspace(0.0, 1.0, release)
    rise = floor + (1.0 - floor) * (3 * x**2 - 2 * x**3)
    shape = np.concatenate([np.linspace(1.0, floor, attack, endpoint=False), rise])

    for beat in np.atleast_1d(beats):
        at = int(round(beat * sample_rate))
        if at >= length:
            continue
        head = max(0, at)
        piece = shape[max(0, -at): max(0, -at) + (length - head)]
        window = gain[head: head + piece.size]
        np.minimum(window, piece, out=window)
    return gain


def pump(audio: np.ndarray, sample_rate: int, beats: np.ndarray, bpm: float,
         depth_db: float = PUMP_DB) -> np.ndarray:
    """Duck a part on every beat and let it swell back. The sound of a dance record."""
    audio = np.asarray(audio, dtype=np.float64)
    gain = pump_envelope(beats, len(audio), sample_rate, bpm, depth_db)
    return audio * (gain[:, None] if audio.ndim > 1 else gain)


def four_on_the_floor(beats: np.ndarray, bpm: float, sample_rate: int, length: int,
                      kit: str = "edm", rest=None) -> np.ndarray:
    """A kick on every beat and a hat on every offbeat - the house groove - as stereo audio.

    No clap. The drummer's own backbeat, re-struck on the dance kit, already lands on 2 and
    4 as a clap; adding another would double it and bury the one thing left of the band's
    groove.
    """
    out = np.zeros((length, 2))
    voices = KITS.get(kit) or KITS["edm"]
    kick = render_voice(voices["kick"], sample_rate, seed=11)
    hat = render_voice(voices["hihat"], sample_rate, seed=12)
    half = 30.0 / bpm

    def lay(sample: np.ndarray, time_s: float, gain: float) -> None:
        at = int(round(time_s * sample_rate))
        if at < 0 or at >= length:
            return
        end = min(length, at + sample.size)
        out[at:end, 0] += sample[: end - at] * gain
        out[at:end, 1] += sample[: end - at] * gain

    for beat in beats:
        # `rest` is a build: from its start up to (not including) the drop, nothing.
        from app.services.synth.groove import resting

        if resting(beat, rest):
            continue
        lay(kick, beat, 0.95)
        lay(hat, beat + half, 0.38)
    return out


# --- where the beats really are ----------------------------------------------------------
#
# The four-on-the-floor and the pump have to agree with the re-played drummer on both rate
# and phase, or the added kick flams against his and the pump ducks the wrong half of the
# beat. Found by measuring the first "Make it EDM" version rather than by listening:
#
# * **Phase.** The beat grid started from `TimingEstimate.first_beat_s`, which put it 166 ms
#   into a 469 ms beat on the pop punk demo - over a third of a beat late.
# * **Rate.** The whole-mix estimate read 168.5 BPM for a song built at exactly 170. Re-played
#   parts follow the real performance scaled by 168.5/128, so they land at 129.1 - while a
#   grid laid at exactly 60/128 runs at 128, and the two slide apart across the song. That is
#   also why the analyser kept reading the "128" versions as 129.2, which had been put down
#   to its resolution. It was not resolution.
#
# The existing drum tools did not rescue it on this material: the hit classifier labelled 14
# of about 40 kicks and snares and missed beat one, the drum-anchored grid then fell to the
# half-time 85 BPM, and a tempo map started from the first stroke started on an offbeat
# hi-hat - which would have put an added kick on every "and".
#
# So this searches instead of estimating. **Beats are where the kicks are**: sweep tempo
# near the estimate and phase across one beat, and take the comb that lands on the most
# low-frequency onset energy. Deterministic, scipy only, and it measures the estimate's own
# error rather than inheriting it.

#: How far either side of the estimate to search. Wide enough for a whole-mix estimate's
#: usual error - the pop punk demo was 0.9% out - and narrow enough to stay in the
#: estimate's octave, which is a separate question with its own one-tap fix.
TEMPO_SEARCH = 0.04


def _kick_onsets(
    drums: np.ndarray, sample_rate: int, target_rate: int = 1000
) -> tuple[np.ndarray, float]:
    """Low-band onset strength - rises in energy under 200 Hz, which is a kick - and the
    rate it is actually sampled at.

    200 Hz, chosen by sweeping. At 150 a kick whose pitch starts above the band - the dance
    kit's dives from 170 Hz - was found 19 ms late, which is where an added kick flams. At
    200 it is 6.9 ms and a recorded kick stays at 0.2; wider bands help the dance kick a
    little more and let in more of the bass.

    **The rate is returned rather than assumed, and that is a fix.** The envelope is
    decimated by a whole number of samples, and `44100 // 1000` is 44, which is 1002.27 Hz,
    not 1000. The first version converted indices to seconds at 1000 Hz, stretching every
    time by 0.227% - so a song built at exactly 170 BPM measured 169.61, and two independent
    methods agreed on that wrong number because they shared the same clock. Agreement
    between methods that share an input is not corroboration.
    """
    from scipy.signal import butter, sosfiltfilt

    mono = drums.mean(axis=1) if drums.ndim > 1 else drums
    low = sosfiltfilt(butter(4, 200.0 / (sample_rate / 2), output="sos"), mono)
    step = max(1, sample_rate // target_rate)
    width = max(1, int(0.008 * sample_rate))
    energy = np.convolve(np.abs(low), np.ones(width) / width, "same")[::step]
    return np.maximum(np.diff(energy, prepend=energy[0]), 0.0), sample_rate / step


def find_beats(drums: np.ndarray, sample_rate: int, estimate_bpm: float) -> tuple[float, float]:
    """The tempo and the first beat, as the kick drum says they are. (bpm, first_beat_s).

    Falls back to the estimate and zero when there is nothing to lock to - a drumless song
    should get the grid it was going to get, not an error.
    """
    if estimate_bpm <= 0:
        return estimate_bpm, 0.0
    onset, rate = _kick_onsets(drums, sample_rate)
    if onset.size < rate or not onset.any():
        return estimate_bpm, 0.0

    n = onset.size
    best = (0.0, estimate_bpm, 0.0)
    for bpm in np.arange(estimate_bpm * (1 - TEMPO_SEARCH), estimate_bpm * (1 + TEMPO_SEARCH),
                         0.05):
        period = 60.0 / bpm * rate
        phases = np.arange(0.0, period, 2.0)
        ticks = np.arange(0.0, n - 1, period)
        positions = (phases[:, None] + ticks[None, :]).astype(int)
        positions = np.clip(positions, 0, n - 1)
        scores = onset[positions].sum(axis=1) / ticks.size
        k = int(np.argmax(scores))
        if scores[k] > best[0]:
            best = (float(scores[k]), float(bpm), float(phases[k] / rate))

    # The search gets the phase exactly and the rate to within a step's worth of a flat
    # score surface - 169.58 for a song built at 170 on the pop punk demo, which is 0.25%
    # and still drifts about 30 ms by the end of a song. So the search seeds a least-squares
    # fit on the kick peaks themselves, each assigned to its nearest sixteenth: time against
    # grid index is a straight line, and its slope is the tempo.
    _, bpm, first = best
    period = 60.0 / bpm
    peaks = _peaks(onset, rate)
    if peaks.size >= 4:
        step = period / 4.0
        index = np.round((peaks - first) / step)
        near = np.abs(peaks - (first + index * step)) < step / 2
        if near.sum() >= 4:
            slope, intercept = np.polyfit(index[near], peaks[near], 1)
            fitted = 60.0 / (slope * 4.0)
            if abs(fitted / bpm - 1.0) < TEMPO_SEARCH:
                bpm = fitted
                first = intercept % (slope * 4.0)

        # Back from where each kick's onset *peaks* to where it *began*. The peak is the
        # steepest rise in low-band energy, which comes after the hit starts - by 3 ms for a
        # kick whose pitch starts under 150 Hz and by about 20 ms for one that sweeps down
        # into the band from above, as the dance kit's does. 20 ms is where an added kick
        # starts to flam against the one it is meant to sit on. The median, so one odd kick
        # cannot move the grid.
        lead = np.median([_rise(onset, int(round(t * rate))) for t in peaks]) / rate
        first = (first - lead) % (60.0 / bpm)
    return round(float(bpm), 2), float(first)


def _rise(onset: np.ndarray, peak: int) -> int:
    """How many samples before `peak` its rise began: back to 10% of the peak height."""
    floor = 0.1 * onset[peak]
    j = peak
    while j > 0 and onset[j - 1] > floor and onset[j - 1] <= onset[j]:
        j -= 1
    return peak - j


def _peaks(onset: np.ndarray, rate: float) -> np.ndarray:
    """Times of clear kick onsets: one per kick, as near as the envelope allows.

    Tuned against kicks at known tempi from 120 to 180 BPM. The first settings - 30% of the
    peak, 60 ms apart - found 3.7 peaks per kick, because a kick's pitch sweep moves through
    the low band and the onset envelope bumps more than once on the way, and those extra
    points pulled the tempo fit 0.5 BPM out. At 60% and 90 ms it is 1.17 per kick and 0.054
    BPM worst case. 90 ms can drop one of a punk double kick; the fit only needs enough
    points, not all of them.
    """
    threshold = 0.6 * float(onset.max())
    gap = int(0.09 * rate)
    out: list[int] = []
    for i in range(1, onset.size - 1):
        if onset[i] >= threshold and onset[i] >= onset[i - 1] and onset[i] > onset[i + 1]:
            if not out or i - out[-1] >= gap:
                out.append(i)
            elif onset[i] > onset[out[-1]]:
                out[-1] = i
    return np.asarray(out, dtype=float) / rate


# --- where each hit really starts ---------------------------------------------------------
#
# X0R-412, which had been open since the transcription epic, turned out to sit underneath the
# four-on-the-floor. `find_hits` detects a kick a median **10.5 ms late** - measured against
# kicks at known times, range 8 to 13 ms - even with librosa's backtracking on, because its
# onset envelope is framed at 256 samples and backtracking only walks back to a frame. That
# was harmless while a hit time only labelled a stroke. Once re-emission *places a sample* at
# it, the whole re-struck drum part lands 10 ms late, 14 ms after scaling to 128 - against an
# added kick on the true beat, which is a flam.

#: Search this far before a detected hit for where it really starts, and this far after.
#: The look-ahead was 10 ms, on the assumption that detection is always late. It usually is,
#: and on the pop punk demo one kick was detected 11 ms *early* - so the real kick sat just
#: outside the window, the search grabbed the tail of something earlier, and moved the hit
#: the full 30 ms the wrong way.
ONSET_LOOKBACK_S = 0.030
ONSET_LOOKAHEAD_S = 0.025


def refine_hit_times(samples: np.ndarray, sample_rate: int, hits: list[Hit]) -> list[Hit]:
    """Each hit moved back to where its sound actually begins, to about a millisecond.

    Around every detected time, find the loudest point of the drum and walk back to where it
    first rose above a tenth of that. A stroke is a sharp rise out of near-silence, so the
    start of the rise is where the drummer hit it - and it is the only time that should place
    a sample.
    """
    mono = samples.mean(axis=1) if samples.ndim > 1 else np.asarray(samples, dtype=np.float64)
    width = max(1, int(0.001 * sample_rate))
    envelope = np.convolve(np.abs(mono), np.ones(width) / width, "same")
    back = int(ONSET_LOOKBACK_S * sample_rate)
    ahead = int(ONSET_LOOKAHEAD_S * sample_rate)

    out = []
    for hit in hits:
        centre = int(round(hit.time_s * sample_rate))
        lo, hi = max(0, centre - back), min(envelope.size, centre + ahead)
        if hi - lo < 4:
            out.append(hit)
            continue
        window = envelope[lo:hi]
        peak = int(np.argmax(window))
        floor = 0.1 * window[peak]
        start = peak
        while start > 0 and window[start - 1] > floor:
            start -= 1
        # A walk that ran all the way to the edge of the window never found the quiet before
        # a stroke - something was already sounding - so it found nothing, and the detector's
        # own time is the better guess. This is what turned one kick into a 54 ms flam.
        if start == 0 and lo > 0:
            out.append(hit)
            continue
        out.append(Hit(time_s=(lo + start) / sample_rate, kinds=list(hit.kinds),
                       strength=hit.strength, rises=dict(hit.rises)))
    return out
