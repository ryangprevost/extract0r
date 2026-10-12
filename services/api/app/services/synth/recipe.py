"""What a reference remix is made of, as a recipe for this song. Sprint 4.

Ryan: *"applying elements of the reference remix track to the source and allowing it to
extract the essential elements."* A producer asked what makes a dance track sound the way it
does would name five things, and this reads exactly those five from the reference's stems:

1. **The tempo** - read off its kick, the same way this application reads the source's.
2. **The beat** - its drum pattern, accents and feel (`groove.py`).
3. **The pump** - how far everything ducks on each beat, measured rather than assumed.
4. **The kick** - long and subby, or short and clicky, matched to the nearest kit here.
5. **The bass** - a pure sub, or something with grit on top, matched to the nearest voice.

### Analysed, never sampled

Nothing of the reference's audio reaches the remix. Each element is reduced to a handful of
numbers - a tempo, a sixteen-step pattern, a depth in dB, a pair of spectral shares - and the
remix is built from this application's own synthesis to match them. That is the same line
the mastering suite draws (a reference is measured, not copied) and the reason this is a
remix *in the style of* a track rather than a remix *of* it.

### Every choice is shown and can be changed

The recipe lands on the page as ordinary choices - the tempo box, each row's voice, the beat,
the pump - each with the sentence that explains it. Nobody should have to trust a black box
to feel like they made something.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.services.drums.kit import KITS, render_voice
from app.services.synth.groove import Groove

#: Bins per beat for folding a part's level over the beat to find a pump.
PHASE_BINS = 32
#: A fold shallower than this is a part's own rhythm, not a pump.
MIN_PUMP_DB = 1.5
#: Deepest pump this will copy. Deeper than this the parts vanish between beats.
MAX_PUMP_DB = 12.0

#: The voices that make sense on a bass line, for matching a reference's bass.
BASS_VOICES = ("808", "subbass", "supersaw", "pluck")


# --- the pump ----------------------------------------------------------------------------


def measure_pump(audio: np.ndarray, sample_rate: int, beats: np.ndarray) -> float:
    """How far a part ducks on each beat, in dB. Zero when it does not pump.

    Fold the part's level over the beat - every beat laid on top of every other - and look
    at the shape. A pump is low just after the beat and recovered by the second half; a bass
    that simply plays on the beat is the opposite shape, loudest at the start, and must not
    read as a pump because it has a big level swing.
    """
    mono = audio.mean(axis=1) if audio.ndim > 1 else np.asarray(audio, dtype=np.float64)
    beats = np.asarray(beats, dtype=np.float64)
    if beats.size < 3 or mono.size == 0:
        return 0.0
    hop = max(1, int(0.005 * sample_rate))
    frames = mono[: mono.size // hop * hop].reshape(-1, hop)
    level = np.sqrt(np.mean(frames**2, axis=1)) + 1e-9
    times = (np.arange(level.size) + 0.5) * hop / sample_rate

    folded = np.zeros(PHASE_BINS)
    counts = np.zeros(PHASE_BINS)
    for start, end in zip(beats[:-1], beats[1:], strict=True):
        inside = (times >= start) & (times < end)
        if not inside.any():
            continue
        phase = ((times[inside] - start) / (end - start) * PHASE_BINS).astype(int)
        np.add.at(folded, np.clip(phase, 0, PHASE_BINS - 1), level[inside])
        np.add.at(counts, np.clip(phase, 0, PHASE_BINS - 1), 1)
    if not counts.all():
        return 0.0
    shape = 20 * np.log10(folded / counts)

    early = shape[: PHASE_BINS // 4]          # the first quarter of the beat
    late = shape[PHASE_BINS // 2: int(PHASE_BINS * 0.95)]
    depth = float(np.mean(late) - np.min(early))
    # Loudest at the start of the beat is a part playing on the beat, not a pump. And a part
    # that is all but silent for half the beat is playing a rhythm - the offbeat house bass,
    # which on the test reference read 12 dB and up against a real pump of 6 - so a fold
    # deeper than any pump worth copying is not read as one.
    if np.argmax(shape) < PHASE_BINS // 8 or depth < MIN_PUMP_DB or depth > MAX_PUMP_DB:
        return 0.0
    return float(depth)


# --- the kick and the bass ---------------------------------------------------------------


def _shares(audio: np.ndarray, sample_rate: int, low_hz: float, high_hz: float
            ) -> tuple[float, float]:
    """Energy share below `low_hz` and above `high_hz`, in dB of the whole."""
    spectrum = np.abs(np.fft.rfft(audio)) ** 2
    freqs = np.fft.rfftfreq(audio.size, 1.0 / sample_rate)
    total = spectrum.sum() + 1e-12
    low = spectrum[(freqs >= 20) & (freqs < low_hz)].sum() + 1e-12
    high = spectrum[freqs >= high_hz].sum() + 1e-12
    return float(10 * np.log10(low / total)), float(10 * np.log10(high / total))


def _decay_ms(audio: np.ndarray, sample_rate: int) -> float:
    """How long until it has fallen 20 dB below its peak, in ms."""
    envelope = np.abs(audio)
    width = max(1, int(0.005 * sample_rate))
    envelope = np.convolve(envelope, np.ones(width) / width, "same")
    peak = int(np.argmax(envelope))
    below = np.nonzero(envelope[peak:] < envelope[peak] * 0.1)[0]
    end = below[0] if below.size else envelope.size - peak
    return 1000.0 * end / sample_rate


def kick_features(audio: np.ndarray, sample_rate: int) -> tuple[float, float, float]:
    """(sub share dB, click share dB, decay ms) of one kick.

    Each read where nothing else can reach it, because in a real beat a hat lands a
    sixteenth after the kick: the sub share below 2 kHz, the click in the first 15 ms, and
    the decay on the band below 200 Hz.
    """
    from scipy.signal import butter, sosfilt

    nyquist = sample_rate / 2
    body = sosfilt(butter(4, 2000.0 / nyquist, output="sos"), audio)
    sub, _ = _shares(body, sample_rate, 60.0, 2000.0)
    _, click = _shares(audio[: max(16, int(0.015 * sample_rate))], sample_rate, 60.0, 2000.0)
    low = sosfilt(butter(4, 200.0 / nyquist, output="sos"), audio)
    return sub, click, _decay_ms(low, sample_rate)


def reference_kick(drums: np.ndarray, sample_rate: int, kick_times: list[float]
                   ) -> tuple[float, float, float] | None:
    """The median kick of a drums stem, as features. Up to 32 strokes, 400 ms each - cut
    short at the next *kick*, which is the only stroke that reaches the band the decay is
    read on."""
    mono = drums.mean(axis=1) if drums.ndim > 1 else np.asarray(drums, dtype=np.float64)
    found = []
    times = sorted(kick_times)
    for i, t in enumerate(times[:32]):
        at = int(t * sample_rate)
        stop = int(min(t + 0.4, times[i + 1] if i + 1 < len(times) else t + 0.4) * sample_rate)
        piece = mono[at:stop]
        if piece.size > int(0.05 * sample_rate):
            found.append(kick_features(piece, sample_rate))
    if not found:
        return None
    return tuple(float(np.median([f[i] for f in found])) for i in range(3))


def nearest_kit(features: tuple[float, float, float], sample_rate: int) -> tuple[str, str]:
    """The kit whose kick is closest, and a sentence saying why."""
    sub, click, decay = features
    best, best_distance = "edm", float("inf")
    for name, voices in KITS.items():
        s, c, d = kick_features(render_voice(voices["kick"], sample_rate, seed=0), sample_rate)
        # dB differences, and decay in steps of 50 ms - roughly where a kick audibly changes.
        distance = abs(s - sub) + 0.5 * abs(c - click) + abs(d - decay) / 50.0
        if distance < best_distance:
            best, best_distance = name, distance
    weight = "deep and subby" if sub > -3 else ("punchy" if sub > -8 else "tight and light")
    length = "long" if decay > 250 else ("medium" if decay > 120 else "short")
    return best, (f"Their kick is {weight} and {length} ({decay:.0f} ms to fade) - the "
                  f"{best} kit is the closest match here.")


def bass_features(audio: np.ndarray, sample_rate: int) -> tuple[float, float]:
    """(sub share below 80 Hz, grit share above 400 Hz), both dB of the whole."""
    return _shares(audio, sample_rate, 80.0, 400.0)


def nearest_bass(features: tuple[float, float], sample_rate: int) -> tuple[str, str]:
    """The bass voice closest to a reference bass, and why. Each voice is measured on the
    same two-bar line in E1-E2, the register a dance bass lives in."""
    from app.domain.notes import NoteEvent
    from app.services.synth.voice import render_notes

    line = [NoteEvent(i * 0.25, i * 0.25 + 0.22, 28 + (12 if i % 4 == 3 else 0), 100)
            for i in range(16)]
    sub, grit = features
    best, best_distance = "808", float("inf")
    for name in BASS_VOICES:
        s, g = bass_features(render_notes(line, sample_rate, name, duration_s=4.2),
                             sample_rate)
        distance = abs(s - sub) + abs(g - grit)
        if distance < best_distance:
            best, best_distance = name, distance
    character = ("almost all sub" if grit < -20 else
                 "sub with some edge" if grit < -10 else "bright and gritty")
    return best, f"Their bass is {character} - the {best} voice is the closest match here."


# --- the whole recipe --------------------------------------------------------------------


@dataclass
class Recipe:
    tempo_bpm: float
    groove: Groove
    pump_db: float
    kit: str
    bass_voice: str
    #: One sentence per element, in the order the page shows them.
    lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tempo_bpm": round(self.tempo_bpm, 1),
            "groove": {
                "name": self.groove.name,
                "grid": self.groove.grid(),
                "swing_percent": self.groove.swing_percent,
                "bars": self.groove.bars,
            },
            "pump_db": round(self.pump_db, 1),
            "kit": self.kit,
            "bass_voice": self.bass_voice,
            "lines": self.lines,
        }


def tempo_line(theirs: float, ours: float, target: float) -> str:
    if abs(target - theirs) < 0.5:
        return f"Their tempo: {theirs:.0f} BPM. Yours is {ours:.0f}, so the remix moves to theirs."
    return (f"Their tempo is {theirs:.0f} BPM, further from your {ours:.0f} than a "
            f"performance can be moved - so the remix uses {target:.0f}, the same groove at "
            f"{'half' if target < theirs else 'double'} speed.")


def pump_line(depth_db: float) -> str:
    if depth_db <= 0:
        return "No pump - their parts hold steady through the beat, so the remix's will too."
    strength = "hard" if depth_db > 7 else ("clearly" if depth_db > 4 else "gently")
    return (f"Pumps {strength}: everything ducks about {depth_db:.0f} dB on each beat and "
            f"swells back. The remix copies the depth.")


# --- a reference's tempo -----------------------------------------------------------------

#: Where dance music lives. A reference read outside this is almost certainly the right
#: groove at the wrong multiple.
DANCE_RANGE = (95.0, 180.0)
#: Candidates scoring within this share of the best count as a tie, settled by closeness to
#: `DANCE_HOME`.
TIE = 0.05
DANCE_HOME = 125.0


def kick_comb(drums: np.ndarray, sample_rate: int, bpm: float, first: float) -> float:
    """Mean kick-band onset strength on every beat of a grid: how well a tempo lands on the
    kicks. A four-on-the-floor scores the same at its tempo and at half of it, which is why
    the range and the tie-break exist."""
    from app.services.synth.retempo import _kick_onsets

    onset, rate = _kick_onsets(drums, sample_rate)
    if onset.size == 0 or bpm <= 0:
        return 0.0
    ticks = np.arange(first, onset.size / rate, 60.0 / bpm)
    # Best within 20 ms of each tick, so the score is not at the mercy of a sample.
    reach = max(1, int(0.02 * rate))
    peaks = [onset[max(0, int(t * rate) - reach): int(t * rate) + reach + 1].max()
             for t in ticks if int(t * rate) < onset.size]
    return float(np.mean(peaks)) if peaks else 0.0


def dance_tempo(drums: np.ndarray, sample_rate: int, estimate: float) -> tuple[float, float]:
    """A reference's tempo and first beat, with the whole-mix estimator's multiples checked.

    Found on the first reference this read: a house track built at 124 came back as 186 -
    3:2, the error X0R-1319 proved onsets alone cannot always rule out - and every element
    read after it (beat, swing, pump) was then read against the wrong grid. So each of the
    estimate's usual mistakes is tried, the kick decides, and inside the dance range a tie
    goes to the tempo nearest 125.
    """
    from app.services.synth.retempo import find_beats

    candidates = [estimate * m for m in (1.0, 2 / 3, 3 / 2, 1 / 2, 2.0, 3 / 4, 4 / 3)]
    inside = [c for c in candidates if DANCE_RANGE[0] <= c <= DANCE_RANGE[1]] or [estimate]
    scored = []
    for candidate in inside:
        bpm, first = find_beats(drums, sample_rate, candidate)
        scored.append((kick_comb(drums, sample_rate, bpm, first), bpm, first))
    top = max(score for score, _, _ in scored)
    ties = [(abs(bpm - DANCE_HOME), bpm, first) for score, bpm, first in scored
            if score >= top * (1 - TIE)]
    _, bpm, first = min(ties)
    return bpm, first
