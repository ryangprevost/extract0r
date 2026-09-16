"""Drum samples, and laying them over the ones already there.

**The samples are synthesised, not sampled.** Extract0r's whole position is that a
reference is analysed and never sampled, and shipping a library of recorded hits would
mean shipping someone's recordings — with the licensing that implies, and with no way for
anyone to check where they came from. These are built from oscillators and noise, so the
kit weighs nothing, needs no licence, and cannot contain anyone else's record.

**It layers rather than replaces.** Taking the original snare *out* of a drums stem means
separating drums from drums, which the separator does not do. What every practical drum
replacement does instead is trigger a sample and blend it against the original, and that is
what happens here: `blend` is how far to lean on the new sample. Calling it replacement
would be claiming a surgical removal that is not happening.

**Velocity comes from the original.** Each hit carries the peak it was detected at, and the
sample is scaled to match, so ghost notes stay ghost notes and the part keeps its dynamics
instead of turning into a drum machine.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.services.drums.detect import Hit

SR_ASSUMED = 44100

#: Louder than this and a layered sample stops reinforcing and starts being the part.
MAX_BLEND = 1.0

#: A trigger this far out of time is heard as a flam rather than as the same hit.
LATENCY_S = 0.0


@dataclass(slots=True)
class Voice:
    """One drum's synthesis parameters."""

    length_s: float
    #: Starting and ending pitch of the tuned part, in Hz. Equal means no sweep.
    pitch_from: float = 0.0
    pitch_to: float = 0.0
    pitch_decay: float = 20.0
    body_decay: float = 12.0
    noise_level: float = 0.0
    noise_decay: float = 20.0
    noise_highpass: float = 0.0
    body_level: float = 1.0


#: Three kits, chosen to be obviously different rather than subtly so - the point of
#: swapping a sample is to hear that you did.
#:
#: The kicks are tuned against a measurement rather than by ear. Averaging the kicks out
#: of a real drum stem puts -2.25 dB of their energy in 20-60 Hz and -4.18 in 60-120: the
#: sub band is the *strongest* part of a kick. The first versions here were 5 to 9.5 dB
#: short in that band and put their weight an octave up instead, which is what "the
#: bassiness was removed and it sounded flat" sounds like. All three now land within
#: 0.1 dB of a real kick down there, and differ where they should - in length, in how
#: fast the body dies, and in how much click is on the front.
KITS: dict[str, dict[str, Voice]] = {
    "tight": {
        "kick": Voice(0.32, 95.0, 38.0, 25.0, 7.0, noise_level=0.16, noise_decay=500.0),
        "snare": Voice(0.16, 200.0, 190.0, 40.0, 34.0, noise_level=0.8, noise_decay=30.0,
                       noise_highpass=1400.0, body_level=0.35),
        "hihat": Voice(0.05, 0.0, 0.0, 0.0, 0.0, noise_level=1.0, noise_decay=90.0,
                       noise_highpass=7000.0, body_level=0.0),
    },
    "roomy": {
        "kick": Voice(0.55, 105.0, 38.0, 18.0, 4.0, noise_level=0.09, noise_decay=500.0),
        "snare": Voice(0.38, 185.0, 175.0, 26.0, 12.0, noise_level=0.85, noise_decay=11.0,
                       noise_highpass=1100.0, body_level=0.4),
        "hihat": Voice(0.12, 0.0, 0.0, 0.0, 0.0, noise_level=1.0, noise_decay=38.0,
                       noise_highpass=6200.0, body_level=0.0),
    },
    "punchy": {
        "kick": Voice(0.24, 95.0, 50.0, 55.0, 10.0, noise_level=0.26, noise_decay=500.0),
        "snare": Voice(0.13, 225.0, 210.0, 50.0, 44.0, noise_level=0.7, noise_decay=42.0,
                       noise_highpass=1800.0, body_level=0.45),
        "hihat": Voice(0.035, 0.0, 0.0, 0.0, 0.0, noise_level=1.0, noise_decay=130.0,
                       noise_highpass=8000.0, body_level=0.0),
    },
}

DRUMS = ("kick", "snare", "hihat")


def render_voice(voice: Voice, sample_rate: int, seed: int = 0) -> np.ndarray:
    """One drum hit, built from a swept tone and filtered noise."""
    n = max(1, int(voice.length_s * sample_rate))
    t = np.arange(n) / sample_rate
    out = np.zeros(n)

    if voice.body_level > 0 and voice.pitch_from > 0:
        # A pitch falling as it decays is what makes a kick sound struck rather than
        # plucked; a snare barely sweeps at all.
        pitch = (voice.pitch_from - voice.pitch_to) * np.exp(
            -voice.pitch_decay * t
        ) + voice.pitch_to
        phase = 2 * np.pi * np.cumsum(pitch) / sample_rate
        out += voice.body_level * np.sin(phase) * np.exp(-voice.body_decay * t)

    if voice.noise_level > 0:
        rng = np.random.default_rng(seed)
        noise = rng.normal(0, 1, n) * np.exp(-voice.noise_decay * t)
        if voice.noise_highpass > 0:
            from scipy.signal import butter, sosfilt

            nyquist = sample_rate / 2
            sos = butter(
                4, min(voice.noise_highpass / nyquist, 0.99), btype="high", output="sos"
            )
            noise = sosfilt(sos, noise)
        out += voice.noise_level * noise

    # A couple of milliseconds of fade in and out, so a trigger never clicks.
    edge = max(2, int(0.002 * sample_rate))
    out[:edge] *= np.linspace(0.0, 1.0, edge)
    out[-edge:] *= np.linspace(1.0, 0.0, edge)

    peak = float(np.abs(out).max())
    return out / peak if peak > 0 else out


def layer(
    samples: np.ndarray,
    sample_rate: int,
    hits: list[Hit],
    kit: str = "tight",
    drums: tuple[str, ...] = ("kick", "snare"),
    blend: float = 0.5,
) -> np.ndarray:
    """Lay kit samples over the strokes already in a drums stem.

    `blend` is how loud the samples sit against the original, not a crossfade: the stem is
    left alone and the triggers are added to it. Hi-hats are left out by default because
    they are the densest and least forgiving part of a kit - a mistriggered hat is audible
    in a way a reinforced kick is not.
    """
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    blend = float(np.clip(blend, 0.0, MAX_BLEND))
    if blend <= 0 or not hits or not drums:
        return audio

    voices = KITS.get(kit) or KITS["tight"]
    rendered = {
        name: render_voice(voices[name], sample_rate, seed=index)
        for index, name in enumerate(DRUMS)
        if name in drums and name in voices
    }
    if not rendered:
        return audio

    triggers = np.zeros_like(audio)
    for hit in hits:
        start = int((hit.time_s + LATENCY_S) * sample_rate)
        if start < 0 or start >= audio.shape[0]:
            continue
        for name in hit.kinds:
            sample = rendered.get(name)
            if sample is None:
                continue
            end = min(start + sample.size, audio.shape[0])
            # Scaled by how hard the original was struck, so the part keeps its dynamics.
            shaped = sample[: end - start] * max(hit.strength, 0.02)
            triggers[start:end, 0] += shaped
            triggers[start:end, 1] += shaped

    # Match the triggers to the stem before blending, so `blend` means the same thing
    # whatever kit is chosen and whatever the stem's level happens to be.
    stem_rms = float(np.sqrt((audio**2).mean()))
    trigger_rms = float(np.sqrt((triggers**2).mean()))
    if trigger_rms > 1e-9 and stem_rms > 1e-9:
        triggers *= stem_rms / trigger_rms

    return audio + blend * triggers
