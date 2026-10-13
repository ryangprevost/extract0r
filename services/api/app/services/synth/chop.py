"""Chops: stutters, gates and stops cut into the version at phrase ends. Sprint 19.

Ryan, on the VaVaVa remix: *"make it a little more complextro sounding with chops and stabs
here and there to break up the beat and give it more drive."* Complextro breaks its beat with
edits on the whole track - the last beat of a phrase stuttering faster and faster, a bar
gated into sixteenths, a sudden stop - so the next phrase lands harder.

Each chop is applied to every layer the same way, and each is linear - a stutter re-reads
the audio, a gate multiplies it - so the layers still add up to the version exactly and the
mixer hears the same chops the file has.

- **stutter**: the window's first slice played again and again, faster through the window -
  eighths, then sixteenths, then thirty-seconds: the retrigger roll into a downbeat.
- **gate**: sixteenths on and off in a complextro rhythm, on the beat grid.
- **stop**: silence for the window - the whole track drops out, then slams back.
- **rise** (Sprint 20): a stutter in sixteenths whose every repeat is a semitone higher - the
  climbing retrigger Madeon cuts into a lead or a vocal before a phrase lands ("Icarus").
- **tape**: the part slows to a halt across the window, pitch falling with it - a tape stop.

A chop is on the whole track, or (Sprint 20) on chosen parts only: the lead stutters while
the beat carries on, which is how complextro and Madeon chop *instruments* rather than the
mix.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

KINDS = ("stutter", "gate", "stop", "rise", "tape")
#: The gate's rhythm over a beat's four sixteenths, repeated: on, off, on, on.
GATE = (1, 0, 1, 1)
#: Edges faded over this long, so a cut never clicks.
FADE_S = 0.003


@dataclass
class Chop:
    bar: int            # in the version, from 1
    beat: float         # where in the bar it starts, 0 to 3.75
    beats: float        # how long, in beats
    kind: str
    #: The parts (layers) it is cut into; empty is the whole track.
    parts: tuple[str, ...] = ()

    def describe(self) -> str:
        on = f" on the {', '.join(self.parts)}" if self.parts else ""
        return f"{self.kind} at bar {self.bar}{on}"

    def applies_to(self, layer: str | None) -> bool:
        """Whole-track chops are cut into the finished mix; a part's, into that part."""
        return (not self.parts) if layer is None else layer in self.parts


def _at(beats: np.ndarray, position: float) -> float | None:
    """The time of a beat position (0 = the version's first beat), between grid beats."""
    i = int(np.floor(position))
    if i < 0 or len(beats) < 2:
        return None
    if i + 1 >= len(beats):
        # Past the grid's last beat: carry on at its last beat's length.
        period = float(beats[-1] - beats[-2])
        return float(beats[-1] + (position - (len(beats) - 1)) * period)
    return float(beats[i] + (position - i) * (beats[i + 1] - beats[i]))


def _fade(n: int, rate: int) -> np.ndarray:
    edge = max(1, min(n // 2, int(FADE_S * rate)))
    env = np.ones(n)
    env[:edge] = np.linspace(0.0, 1.0, edge)
    env[-edge:] = np.minimum(env[-edge:], np.linspace(1.0, 0.0, edge))
    return env


def apply(audio: np.ndarray, sample_rate: int, beats: np.ndarray, chops: list[Chop],
          layer: str | None = None) -> np.ndarray:
    """`audio` with every chop for `layer` cut in - `None` is the finished mix, which takes
    the whole-track chops. Unchanged where there are none."""
    chops = [c for c in chops or [] if c.applies_to(layer)]
    out = np.array(audio, dtype=np.float64, copy=True)
    if not chops or beats is None or len(beats) < 2:
        return out
    stereo = out if out.ndim == 2 else out[:, None]
    source = stereo.copy()
    for c in chops:
        first = (c.bar - 1) * 4 + c.beat
        start, end = _at(beats, first), _at(beats, first + c.beats)
        if start is None or end is None:
            continue
        a, b = int(start * sample_rate), min(int(end * sample_rate), len(stereo))
        if b <= a:
            continue
        beat_len = (end - start) / c.beats
        if c.kind == "stop":
            # Silent between two short fades, so the drop-out does not click either side.
            stereo[a:b] = source[a:b] * (1.0 - _fade(b - a, sample_rate))[:, None]
            continue
        if c.kind == "tape":
            # Speed falls from 1 to 0 over the window: read position t - t^2 / 2T.
            n = b - a
            t = np.arange(n, dtype=np.float64)
            read = a + t - t * t / (2.0 * n)
            env = np.ones(n)
            edge = max(1, min(n, int(FADE_S * sample_rate)))
            env[-edge:] = np.linspace(1.0, 0.0, edge)     # out, so the halt does not click
            for ch in range(stereo.shape[1]):
                stereo[a:b, ch] = np.interp(read, np.arange(len(source)), source[:, ch]) * env
            continue
        if c.kind == "rise":
            n = max(2, int(beat_len / 4 * sample_rate))
            piece = source[a:a + n]
            at, step = a, 0
            while at < b:
                want = np.arange(n) * 2.0 ** (step / 12.0)
                want = want[want < len(piece) - 1]
                shifted = np.stack([np.interp(want, np.arange(len(piece)), piece[:, ch])
                                    for ch in range(stereo.shape[1])], axis=1)
                shifted *= _fade(len(shifted), sample_rate)[:, None]
                m = min(len(shifted), b - at)
                stereo[at:at + m] = shifted[:m]
                stereo[at + m: min(b, at + n)] = 0.0
                at += n
                step += 1
            continue
        if c.kind == "gate":
            sixteenth = beat_len / 4
            env = np.zeros(b - a)
            for k in range(int(np.ceil(c.beats * 4))):
                if not GATE[k % len(GATE)]:
                    continue
                s = int(k * sixteenth * sample_rate)
                e = min(b - a, int((k + 1) * sixteenth * sample_rate))
                if e > s:
                    env[s:e] = _fade(e - s, sample_rate)
            stereo[a:b] = source[a:b] * env[:, None]
            continue
        # stutter: half the window in eighths, a quarter in sixteenths, the rest in 32nds.
        plan = [(0.5, beat_len / 2), (0.25, beat_len / 4), (0.25, beat_len / 8)]
        at = a
        for share, slice_s in plan:
            span_end = min(b, at + int(share * (b - a)))
            n = max(1, int(slice_s * sample_rate))
            piece = source[a:a + n] * _fade(n, sample_rate)[:, None]
            while at < span_end:
                m = min(n, span_end - at)
                stereo[at:at + m] = piece[:m]
                at += m
        if at < b:
            stereo[at:b] = 0.0
    return stereo if out.ndim == 2 else stereo[:, 0]
