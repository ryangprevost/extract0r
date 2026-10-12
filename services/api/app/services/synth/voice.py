"""Play a transcribed part on something that is not the instrument that played it.

X0R-1325. Ryan: *"allow for replacing that midi with another instrument to play it."*

### Why this is not the guitar non-goal

[REMIX0R/PR0DUCER.md §4](../../../../../docs/proposals/PR0DUCER.md) rules out guitar patches,
and the reason is specific: *synthesis cannot reach an amplified guitar*, so a guitar patch
would be the first thing in this codebase that is worse than the alternative. **Nothing here
imitates anything.** A guitar part's *notes* played on a supersaw is not a failed guitar, it
is a supersaw, and the comparison that non-goal loses is never attempted. That distinction
is the whole licence for this module and it should not be quietly widened later.

### A patch is parameters, not a folder of recordings

Exactly the argument `drums/kit.py` already makes and wins:

> "shipping a library of recorded hits would mean shipping someone's recordings — with the
> licensing that implies, and with no way for anyone to check where they came from."

So a voice here is a handful of numbers: which partials, how loud each one is, how the
envelope moves, how far the stack is detuned. It weighs nothing, needs no licence, and a
reviewer can read `SUPERSAW` and disagree with it. Uploaded samples are a separate card
(X0R-1326) precisely because they are a separate argument — a user's own audio, behind the
same attestation a reference track already needs.

### Second job: this is X0R-306's missing ground truth

X0R-405's own acceptance criterion — *a clean DI bass line transcribes with >= 90% note
accuracy* — has never been measured, because no track in `storage/` carries a ground-truth
note list. A synthesiser is a note list that can be *heard*: render a known part, transcribe
the render, and score the result against what was asked for. That is a best case and not a
real recording, and anything measured this way has to say so. But a pipeline that cannot
transcribe its own synthesiser will not survive a real mix, so the number is worth having
before fourteen points are spent on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.domain.notes import NoteEvent

#: Concert A, and the exponent that turns a MIDI number into a frequency. Stated rather
#: than inlined because the tuning work (X0R-1320) measured three records sitting at three
#: different A4s, and anything here that wants to follow a record's own tuning changes this
#: number rather than hunting for 440 in an expression.
A4_HZ = 440.0
A4_MIDI = 69

#: Notes sounding at once before the oldest is cut. A real synth steals voices; this one
#: does too, and says so rather than letting a dense transcription turn into mud. Six is
#: enough for a chord plus a moving line, and low enough that a transcription which has
#: hallucinated a cluster is audibly wrong instead of quietly loud.
MAX_POLYPHONY = 6

#: Fade applied at the very end of every note regardless of envelope, so a note that is cut
#: by voice-stealing or by the end of the clip does not click.
GUARD_S = 0.004


@dataclass(frozen=True, slots=True)
class PitchedVoice:
    """One synthesised instrument's parameters.

    Deliberately the same shape of thing as `drums/kit.Voice`: a short list of numbers,
    each of which does one audible thing, so the patch can be argued with rather than
    merely heard.
    """

    #: Amplitude of each harmonic, starting at the fundamental. The timbre lives here:
    #: `(1.0,)` is a sine, a long slowly-falling list is a saw, odd-only is a square.
    partials: tuple[float, ...]
    attack_s: float = 0.005
    decay_s: float = 0.12
    sustain: float = 0.7
    release_s: float = 0.08
    #: Copies of the whole stack, spread this many cents apart. What makes a supersaw wide;
    #: zero means one copy and a dead-centre pitch.
    stack: int = 1
    detune_cents: float = 0.0
    #: How much the upper partials fade as the note holds, per second. A plucked or struck
    #: instrument loses its top long before its fundamental, and without this every voice
    #: sounds like an organ.
    brightness_decay: float = 0.0
    #: Fraction of the note's own frequency added an octave down. Cheap weight for a bass
    #: voice without a second oscillator's worth of parameters.
    #:
    #: **Keep it well under the fundamental.** The first `subbass` here used 0.45 and that
    #: is not a bass patch, it is an octave-down patch: pYIN transcribed every note of it
    #: exactly twelve semitones flat - F1 0.000 against an octave-tolerant F1 of 1.000 -
    #: because the sub *was* the loudest thing in the note and the tracker was right to
    #: say so. A voice that changes the note it was asked to play is broken however good
    #: it sounds, and `test_synth.py` now asserts against it.
    sub_level: float = 0.0
    #: Soft saturation, 0 for none. `tanh` on the summed note: grit on an 808, glue on a
    #: supersaw. Odd harmonics only, so the fundamental stays the loudest thing in the note
    #: and the voice still plays the pitch it was asked for - see `test_synth`.
    drive: float = 0.0
    #: Semitones the note starts above its pitch and falls from over `pitch_drop_s`. The
    #: thing that makes an 808 sound like an 808 rather than a sine: the attack is sharp
    #: because the pitch is moving.
    pitch_drop: float = 0.0
    pitch_drop_s: float = 0.04


def _saw(count: int, rolloff: float = 1.0) -> tuple[float, ...]:
    """Partial amplitudes falling as 1/n — a sawtooth, which is where most synth leads start."""
    return tuple(1.0 / (n**rolloff) for n in range(1, count + 1))


#: Three voices, chosen for what synthesis is *good* at rather than for what gets asked for
#: most. None of them is pretending to be a recorded instrument, which is the point.
VOICES: dict[str, PitchedVoice] = {
    #: Wide, bright, obviously electronic. The sound a pop-punk guitar line turns into when
    #: somebody asks for a dance version of it.
    "supersaw": PitchedVoice(
        partials=_saw(14),
        attack_s=0.012,
        decay_s=0.25,
        sustain=0.75,
        release_s=0.12,
        stack=5,
        detune_cents=16.0,
        brightness_decay=1.4,
    ),
    #: Fundamental-heavy and almost clean, because a bass part's job is the note and
    #: everything above the second harmonic fights the kick.
    "subbass": PitchedVoice(
        partials=(1.0, 0.32, 0.1, 0.04),
        attack_s=0.006,
        decay_s=0.18,
        sustain=0.82,
        release_s=0.06,
        brightness_decay=2.2,
        sub_level=0.18,
    ),
    #: The sound EDM chord parts and riffs are mostly made of: bright on the attack and
    #: closing fast, so each note is a pluck rather than a hold. A guitar's power chords in
    #: eighths become this in a dance version more often than anything else.
    "pluck": PitchedVoice(
        partials=_saw(18),
        attack_s=0.002,
        decay_s=0.16,
        sustain=0.0,
        release_s=0.06,
        stack=3,
        detune_cents=8.0,
        brightness_decay=10.0,
        drive=0.15,
    ),
    #: Slow in, wide and held: what a chord becomes under a drop. Chords played on this from
    #: a strummed part keep their voicing, because every note of the chord is its own note.
    "pad": PitchedVoice(
        partials=_saw(12, rolloff=1.35),
        attack_s=0.35,
        decay_s=0.6,
        sustain=0.85,
        release_s=0.7,
        stack=4,
        detune_cents=13.0,
        brightness_decay=0.25,
    ),
    #: An 808: a near-sine with a falling start and some grit, so it is felt as much as
    #: heard and still cuts on a laptop speaker. The sub-octave stays off - an 808's weight
    #: *is* its fundamental, and `subbass` already showed what a loud sub-octave does to a
    #: pitch tracker.
    "808": PitchedVoice(
        partials=(1.0, 0.12, 0.05),
        attack_s=0.003,
        decay_s=0.9,
        sustain=0.55,
        release_s=0.12,
        drive=0.45,
        pitch_drop=7.0,
        pitch_drop_s=0.035,
    ),
    #: Struck rather than blown: fast in, bright for a moment, then dark and sustaining.
    #: `brightness_decay` is doing most of the work here.
    "epiano": PitchedVoice(
        partials=(1.0, 0.5, 0.28, 0.14, 0.09, 0.05, 0.03),
        attack_s=0.004,
        decay_s=0.5,
        sustain=0.35,
        release_s=0.35,
        brightness_decay=3.5,
    ),
    # --- Sprint 4, X0R-1343: the rest of a dance producer's first palette.
    #: Two detuned saws, low and wide - the moving, growling bass of drum and bass and
    #: bass house. The beating between the copies is the "movement"; no LFO needed.
    "reese": PitchedVoice(
        partials=_saw(16, rolloff=1.1),
        attack_s=0.01,
        decay_s=0.4,
        sustain=0.9,
        release_s=0.1,
        stack=2,
        detune_cents=22.0,
        brightness_decay=0.6,
        drive=0.25,
    ),
    #: Short, bright and hard-edged: a chord hit on the offbeat, the piano-house and
    #: rave sound. Closes fast like the pluck, but a squarer, hollower tone.
    "stab": PitchedVoice(
        partials=(1.0, 0.0, 0.42, 0.0, 0.3, 0.0, 0.2, 0.0, 0.14, 0.0, 0.1),
        attack_s=0.002,
        decay_s=0.11,
        sustain=0.0,
        release_s=0.04,
        stack=2,
        detune_cents=6.0,
        brightness_decay=6.0,
    ),
    #: Sparse upper partials and a long ring - a bell or mallet for a top line over the drop.
    "bell": PitchedVoice(
        partials=(1.0, 0.0, 0.0, 0.45, 0.0, 0.0, 0.0, 0.0, 0.2),
        attack_s=0.002,
        decay_s=1.2,
        sustain=0.0,
        release_s=0.5,
        brightness_decay=2.5,
    ),
    #: Odd harmonics, held: the hollow, bright square of chiptune and old-school rave leads.
    "square": PitchedVoice(
        partials=tuple(1.0 / n if n % 2 else 0.0 for n in range(1, 16)),
        attack_s=0.004,
        decay_s=0.2,
        sustain=0.7,
        release_s=0.06,
        drive=0.1,
    ),
}


def hz(pitch: int | float) -> float:
    """MIDI note number to frequency."""
    return A4_HZ * (2.0 ** ((float(pitch) - A4_MIDI) / 12.0))


def _envelope(voice: PitchedVoice, held_s: float, sample_rate: int) -> np.ndarray:
    """ADSR over the held length plus the release tail."""
    total = max(1, int((held_s + voice.release_s) * sample_rate))
    out = np.zeros(total)
    a = min(total, max(1, int(voice.attack_s * sample_rate)))
    d = max(1, int(voice.decay_s * sample_rate))
    r = max(1, int(voice.release_s * sample_rate))

    out[:a] = np.linspace(0.0, 1.0, a)
    end_of_hold = max(a, total - r)
    if end_of_hold > a:
        decay = np.linspace(0.0, (end_of_hold - a) / d, end_of_hold - a)
        out[a:end_of_hold] = voice.sustain + (1.0 - voice.sustain) * np.exp(-decay)
    out[end_of_hold:] = out[end_of_hold - 1] * np.linspace(1.0, 0.0, total - end_of_hold)

    guard = min(total, max(1, int(GUARD_S * sample_rate)))
    out[-guard:] *= np.linspace(1.0, 0.0, guard)
    return out


def render_note(
    voice: PitchedVoice, pitch: int | float, held_s: float, sample_rate: int
) -> np.ndarray:
    """One note, as audio.

    Additive: every partial is a sine, summed. Slower than a wavetable and far easier to
    read, which is the right trade for a patch that is supposed to be arguable - every
    number in `PitchedVoice` maps to one line here.
    """
    envelope = _envelope(voice, held_s, sample_rate)
    t = np.arange(envelope.size) / sample_rate
    fundamental = hz(pitch)
    out = np.zeros(envelope.size)

    # Partials above Nyquist are not quiet, they alias - they fold back down and land as
    # audible wrong pitches. A bass note at 41 Hz has fourteen partials under 600 Hz; the
    # same patch on a lead two octaves up does not, and this is why it still works.
    nyquist = sample_rate / 2.0
    spread = (
        np.linspace(-voice.detune_cents, voice.detune_cents, voice.stack)
        if voice.stack > 1
        else np.zeros(1)
    )
    # A falling start, as a multiplier on every partial. 1.0 throughout when there is no
    # drop, so the ordinary path is unchanged - the phase is still a plain 2*pi*f*t.
    glide = (
        2.0 ** (voice.pitch_drop * np.exp(-t / max(voice.pitch_drop_s, 1e-4)) / 12.0)
        if voice.pitch_drop
        else None
    )
    for cents in spread:
        f0 = fundamental * (2.0 ** (cents / 1200.0))
        for n, level in enumerate(voice.partials, start=1):
            freq = f0 * n
            if freq >= nyquist or level <= 0.0:
                continue
            # Upper partials fade as the note holds. n == 1 is untouched, so the
            # fundamental outlives the brightness, which is what a struck string does.
            fade = (
                np.exp(-voice.brightness_decay * (n - 1) * t / max(n, 1))
                if voice.brightness_decay > 0 and n > 1
                else 1.0
            )
            phase = (
                2.0 * np.pi * freq * t
                if glide is None
                else 2.0 * np.pi * np.cumsum(freq * glide) / sample_rate
            )
            out += level * fade * np.sin(phase)
    out /= max(voice.stack, 1)

    if voice.sub_level > 0 and fundamental / 2.0 < nyquist:
        out += voice.sub_level * np.sin(2.0 * np.pi * (fundamental / 2.0) * t)

    peak = float(np.max(np.abs(out))) or 1.0
    out = out / peak
    if voice.drive > 0:
        # Normalised back to full scale afterwards, so `drive` changes the colour and not
        # the level - otherwise more drive would read as "louder" and be chosen for that.
        out = np.tanh(out * (1.0 + 4.0 * voice.drive))
        out /= float(np.max(np.abs(out))) or 1.0
    return out * envelope


def render_notes(
    notes: list[NoteEvent],
    sample_rate: int,
    voice: PitchedVoice | str = "supersaw",
    duration_s: float | None = None,
    polyphony: int = MAX_POLYPHONY,
) -> np.ndarray:
    """A whole part, as audio.

    Notes land where they were transcribed. **Nothing here quantises, re-sequences or
    changes the tempo** - those are the epic's non-goals and this is the module best placed
    to break them by accident, so it is worth saying in the place somebody would come
    looking.
    """
    if isinstance(voice, str):
        voice = VOICES[voice]
    if not notes:
        return np.zeros(int((duration_s or 0.0) * sample_rate))

    end = duration_s if duration_s is not None else max(n.end_s for n in notes) + 1.0
    out = np.zeros(int(end * sample_rate) + sample_rate)

    # Voice stealing, oldest first. A transcription that hallucinates a twelve-note cluster
    # should come out thin and obviously wrong rather than loud and plausible.
    sounding: list[tuple[float, float]] = []
    for note in sorted(notes, key=lambda n: n.start_s):
        sounding = [(s, e) for s, e in sounding if e > note.start_s]
        if len(sounding) >= polyphony:
            continue
        sounding.append((note.start_s, note.end_s))

        audio = render_note(voice, note.pitch, max(note.end_s - note.start_s, 0.01), sample_rate)
        at = int(note.start_s * sample_rate)
        room = min(audio.size, out.size - at)
        if room > 0:
            out[at : at + room] += audio[:room] * (note.velocity / 127.0)

    peak = float(np.max(np.abs(out)))
    if peak > 1.0:
        out /= peak
    return out[: int(end * sample_rate)]
