"""Mixing each part of a version: level, pan, mute and solo, tone, reverb and delay. Sprint 7.

Ryan: *"go ahead with mixing each part next."* A version is built from layers - each stem as
played or stretched, the added beat, the builds and drops - and until now they were summed
at one level each. This is the mixer between the layers and the file.

### Heard live, rendered the same

The page mixes the layers live in the browser with Web Audio, so a fader is heard as it
moves. The file is rendered here. For what is heard to be what is bounced, this module does
the browser's own arithmetic rather than something that merely sounds similar:

* **Pan** is Web Audio's `StereoPannerNode` algorithm for stereo input, line for line.
* **Low and high cut** are the RBJ cookbook biquads at Q = 1/sqrt(2) - what `BiquadFilterNode`
  implements - so a 200 Hz low cut here is the 200 Hz low cut that was heard.
* **Delay** is a feedback delay synced to the tempo, the same loop the page builds from a
  `DelayNode` and a feedback `GainNode`.
* **Reverb** is a convolution with an impulse response generated here, seeded, and served
  to the page for its `ConvolverNode` - the same impulse on both sides.

Sends are post-fader and post-pan, as on a desk: turning a part down turns its reverb down.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: The layers a version can have, in the order a mixer shows them, with their names.
LAYERS = {
    "drums": "Drums",
    "bass": "Bass",
    "guitar": "Guitar",
    "piano": "Keys",
    "vocals": "Vocals",
    "other": "The rest",
    "beat": "Added beat",
    "build": "Builds and drops",
}

#: The delay: a dotted eighth, the dance-music delay, fed back this much.
DELAY_BEATS = 0.75
DELAY_FEEDBACK = 0.35
#: How loud each effect returns at a send of 1.
REVERB_RETURN = 0.5
DELAY_RETURN = 0.5
#: The reverb: a hall-ish tail, this long, decaying 60 dB over it.
REVERB_S = 2.2
REVERB_SEED = 1370
#: Never boost a layer further than this, so a slip of the fader cannot wreck a file.
MAX_GAIN_DB = 12.0
#: The bottom of the fader is off, not merely quiet - the page shows it as "off" and plays
#: silence, so the file must too.
OFF_DB = -60.0


@dataclass
class Channel:
    """One layer's settings. The defaults change nothing."""

    gain_db: float = 0.0
    pan: float = 0.0
    mute: bool = False
    solo: bool = False
    #: Low cut (high-pass) and high cut (low-pass) frequencies in Hz; 0 is off.
    low_cut_hz: float = 0.0
    high_cut_hz: float = 0.0
    #: How much goes to the reverb and the delay, 0..1.
    reverb: float = 0.0
    delay: float = 0.0
    #: Sprint 9: settings that move over the song - {setting: [[beat, value], ...]}, beats
    #: counted from the version's first beat. A moving setting replaces the fixed one.
    automation: dict = field(default_factory=dict)

    def is_flat(self) -> bool:
        return self == Channel()


# --- automation: settings that move ---------------------------------------------------------
#
# Sprint 9. A lane is a list of points, [beat, value]; between two points the setting moves
# in a straight line, and before the first and after the last it holds - exactly what a
# Web Audio AudioParam does with setValueAtTime and a ramp to each point. Level ramps in
# linear gain, as a GainNode's does. Cut frequencies ramp *exponentially* - evenly in pitch,
# which is how a filter sweep is heard - with exponentialRampToValueAtTime on the page.

#: What can move, and the range it moves in.
AUTOMATABLE = {
    "gain_db": (-60.0, 12.0),
    "pan": (-1.0, 1.0),
    "low_cut_hz": (20.0, 2000.0),
    "high_cut_hz": (200.0, 20000.0),
    "reverb": (0.0, 1.0),
    "delay": (0.0, 1.0),
}
EXPONENTIAL = frozenset({"low_cut_hz", "high_cut_hz"})
#: A moving filter's coefficients are recomputed this often, in samples.
FILTER_BLOCK = 16
#: Most points one lane may have.
MAX_POINTS = 256


def curve(points, n: int, sample_rate: int, bpm: float, first_beat_s: float,
          setting: str) -> np.ndarray:
    """A lane as one value per sample - the value the page's AudioParam has at each frame."""
    low, high = AUTOMATABLE[setting]
    points = sorted((float(b), float(np.clip(v, low, high))) for b, v in points)
    period = 60.0 / bpm if bpm > 0 else 0.5
    times = np.array([first_beat_s + b * period for b, _ in points])
    values = np.array([v for _, v in points])
    if setting == "gain_db":
        values = np.where(values <= OFF_DB, 0.0, 10 ** (np.minimum(values, MAX_GAIN_DB) / 20))
    t = np.arange(n) / sample_rate
    if setting in EXPONENTIAL:
        return np.exp(np.interp(t, times, np.log(values)))
    return np.interp(t, times, values)


def pan_moving(stereo: np.ndarray, position: np.ndarray) -> np.ndarray:
    """`pan`, with the position changing every sample - the StereoPanner law per frame."""
    position = np.clip(position, -1.0, 1.0)
    left, right = stereo[:, 0], stereo[:, 1]
    x = np.where(position <= 0, position + 1.0, position)
    gain_l, gain_r = np.cos(x * np.pi / 2), np.sin(x * np.pi / 2)
    out_l = np.where(position <= 0, left + right * gain_l, left * gain_l)
    out_r = np.where(position <= 0, right * gain_r, right + left * gain_r)
    return np.stack([out_l, out_r], axis=1)


def sweep(stereo: np.ndarray, sample_rate: int, kind: str, cutoff: np.ndarray) -> np.ndarray:
    """A biquad whose cutoff moves: coefficients every FILTER_BLOCK samples, the filter's
    past carried across each change as direct-form-I state (inputs and outputs), which is
    how a BiquadFilterNode holds it."""
    from scipy.signal import lfilter, lfiltic

    out = np.empty_like(stereo)
    channels = stereo.shape[1]
    past_x = np.zeros((2, channels))       # x[n-1], x[n-2]
    past_y = np.zeros((2, channels))       # y[n-1], y[n-2]
    for at in range(0, len(stereo), FILTER_BLOCK):
        end = min(len(stereo), at + FILTER_BLOCK)
        b, a = _biquad(kind, float(cutoff[at]), sample_rate)
        for c in range(channels):
            zi = lfiltic(b, a, past_y[:, c], past_x[:, c])
            out[at:end, c], _ = lfilter(b, a, stereo[at:end, c], zi=zi)
        x = stereo[max(0, end - 2): end][::-1]
        y = out[max(0, end - 2): end][::-1]
        past_x[: len(x)] = x
        past_y[: len(y)] = y
    return out


# --- the pieces, each the browser's arithmetic ----------------------------------------------


def pan(stereo: np.ndarray, position: float) -> np.ndarray:
    """Web Audio's StereoPannerNode for a stereo input (Web Audio API spec, "StereoPanner")."""
    position = float(np.clip(position, -1.0, 1.0))
    left, right = stereo[:, 0], stereo[:, 1]
    x = position + 1.0 if position <= 0 else position
    gain_l, gain_r = np.cos(x * np.pi / 2), np.sin(x * np.pi / 2)
    if position <= 0:
        out_l, out_r = left + right * gain_l, right * gain_r
    else:
        out_l, out_r = left * gain_l, right + left * gain_r
    return np.stack([out_l, out_r], axis=1)


def _biquad(kind: str, hz: float, sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    """RBJ cookbook coefficients at Q = 1/sqrt(2), as BiquadFilterNode computes them."""
    w0 = 2 * np.pi * min(hz, sample_rate / 2 * 0.99) / sample_rate
    alpha = np.sin(w0) / (2 * (1 / np.sqrt(2)))
    cos = np.cos(w0)
    if kind == "lowpass":
        b = np.array([(1 - cos) / 2, 1 - cos, (1 - cos) / 2])
    else:
        b = np.array([(1 + cos) / 2, -(1 + cos), (1 + cos) / 2])
    a = np.array([1 + alpha, -2 * cos, 1 - alpha])
    return b / a[0], a / a[0]


def tone(stereo: np.ndarray, sample_rate: int, low_cut: float, high_cut: float) -> np.ndarray:
    from scipy.signal import lfilter

    out = stereo
    if low_cut and low_cut > 0:
        b, a = _biquad("highpass", low_cut, sample_rate)
        out = lfilter(b, a, out, axis=0)
    if high_cut and high_cut > 0:
        b, a = _biquad("lowpass", high_cut, sample_rate)
        out = lfilter(b, a, out, axis=0)
    return out


def delay(stereo: np.ndarray, sample_rate: int, bpm: float,
          feedback: float = DELAY_FEEDBACK) -> np.ndarray:
    """y[n] = x[n - d] + feedback * y[n - d], with d a dotted eighth at `bpm` - the loop a
    DelayNode with a feedback gain makes. Returns the wet signal, tails included."""
    d = max(1, int(round(DELAY_BEATS * 60.0 / bpm * sample_rate)))
    repeats = int(np.ceil(np.log(1e-3) / np.log(feedback))) if feedback > 0 else 1
    out = np.zeros((stereo.shape[0] + d * repeats, stereo.shape[1]))
    level = 1.0
    for k in range(1, repeats + 1):
        out[k * d: k * d + stereo.shape[0]] += stereo * level
        level *= feedback
    return out


def impulse(sample_rate: int) -> np.ndarray:
    """The reverb's impulse response: decaying stereo noise, darker as it fades, seeded so
    the page and the server use the same one."""
    n = int(REVERB_S * sample_rate)
    t = np.arange(n) / sample_rate
    rng = np.random.default_rng(REVERB_SEED)
    noise = rng.standard_normal((n, 2))
    from scipy.signal import butter, sosfilt

    dark = sosfilt(butter(1, 3000.0 / (sample_rate / 2), output="sos"), noise, axis=0)
    fade = np.clip(t / (REVERB_S * 0.6), 0, 1)[:, None]
    body = noise * (1 - fade) + dark * fade
    envelope = np.exp(-6.9 * t / REVERB_S)[:, None]
    ir = body * envelope
    ir[: int(0.01 * sample_rate)] *= np.linspace(0, 1, int(0.01 * sample_rate))[:, None]
    return ir / np.sqrt(np.sum(ir**2) / 2)


def reverb(stereo: np.ndarray, ir: np.ndarray) -> np.ndarray:
    from scipy.signal import fftconvolve

    return np.stack([fftconvolve(stereo[:, c], ir[:, c]) for c in range(2)], axis=1)


# --- the whole mix ---------------------------------------------------------------------------


def mix(layers: dict[str, np.ndarray], channels: dict[str, Channel], sample_rate: int,
        bpm: float, first_beat_s: float = 0.0) -> np.ndarray:
    """Every layer through its channel, summed, the sends through the effects.

    With every channel flat this is the plain sum the version was before - the mixer adds
    nothing until it is touched. The file is as long as the longest layer: an effect's tail
    past the end is cut, as a version has always ended where its music ends.
    """
    if not layers:
        return np.zeros((0, 2))
    length = max(len(a) for a in layers.values())
    soloing = any(c.solo for c in channels.values())
    out = np.zeros((length, 2))
    reverb_bus = np.zeros((length, 2))
    delay_bus = np.zeros((length, 2))
    for name, audio in layers.items():
        channel = channels.get(name, Channel())
        if channel.mute or (soloing and not channel.solo):
            continue
        audio = np.asarray(audio, dtype=np.float64)
        stereo = audio if audio.ndim > 1 else np.stack([audio, audio], axis=1)
        moving = {k: v for k, v in (channel.automation or {}).items()
                  if k in AUTOMATABLE and v}

        def lane(setting: str, size: int, moving=moving) -> np.ndarray:
            return curve(moving[setting], size, sample_rate, bpm, first_beat_s, setting)

        # Tone: a moving cut is a sweep; a fixed one is the plain biquad, or nothing.
        if "low_cut_hz" in moving:
            stereo = sweep(stereo, sample_rate, "highpass", lane("low_cut_hz", len(stereo)))
        else:
            stereo = tone(stereo, sample_rate, channel.low_cut_hz, 0.0)
        if "high_cut_hz" in moving:
            stereo = sweep(stereo, sample_rate, "lowpass", lane("high_cut_hz", len(stereo)))
        else:
            stereo = tone(stereo, sample_rate, 0.0, channel.high_cut_hz)
        if "gain_db" in moving:
            stereo = stereo * lane("gain_db", len(stereo))[:, None]
        elif channel.gain_db <= OFF_DB:
            continue
        else:
            stereo = stereo * 10 ** (min(channel.gain_db, MAX_GAIN_DB) / 20)
        if "pan" in moving:
            stereo = pan_moving(stereo, lane("pan", len(stereo)))
        elif channel.pan:
            stereo = pan(stereo, channel.pan)
        take = min(len(stereo), length)
        out[:take] += stereo[:take]
        for setting, bus in (("reverb", reverb_bus), ("delay", delay_bus)):
            if setting in moving:
                bus[:take] += stereo[:take] * lane(setting, take)[:, None]
            elif getattr(channel, setting) > 0:
                bus[:take] += stereo[:take] * getattr(channel, setting)
    if np.any(reverb_bus):
        out += reverb(reverb_bus, impulse(sample_rate))[:length] * REVERB_RETURN
    if np.any(delay_bus) and bpm > 0:
        out += delay(delay_bus, sample_rate, bpm)[:length] * DELAY_RETURN
    return out


def describe(channels: dict[str, Channel]) -> list[str]:
    """What the mix did, in sentences, for the version's account. Flat channels say nothing."""
    lines = []
    soloed = [LAYERS.get(n, n).lower() for n, c in channels.items() if c.solo]
    if soloed:
        lines.append(f"Soloed: {', '.join(soloed)} - everything else is silent in this file.")
    words = {"gain_db": "level", "pan": "pan", "low_cut_hz": "low cut",
             "high_cut_hz": "high cut", "reverb": "reverb", "delay": "delay"}
    for name, c in channels.items():
        if c.is_flat() or c.solo:
            continue
        label = LAYERS.get(name, name)
        if c.mute:
            lines.append(f"{label}: muted.")
            continue
        moving = [words[k] for k, v in (c.automation or {}).items() if k in words and v]
        if moving:
            lines.append(f"{label}: {', '.join(moving)} moving over the song.")
        bits = []
        if abs(c.gain_db) >= 0.1:
            bits.append(f"{c.gain_db:+.1f} dB")
        if abs(c.pan) >= 0.02:
            bits.append(f"panned {abs(c.pan) * 100:.0f}% {'left' if c.pan < 0 else 'right'}")
        if c.low_cut_hz:
            bits.append(f"low cut at {c.low_cut_hz:.0f} Hz")
        if c.high_cut_hz:
            bits.append(f"high cut at {c.high_cut_hz:.0f} Hz")
        if c.reverb:
            bits.append(f"reverb {c.reverb * 100:.0f}%")
        if c.delay:
            bits.append(f"delay {c.delay * 100:.0f}%")
        if bits:
            lines.append(f"{label}: {', '.join(bits)}.")
    return lines
