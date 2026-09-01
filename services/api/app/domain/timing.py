"""Tempo, metre, and key reasoning — the pure half.

Everything here takes plain numbers and returns plain numbers, so the decisions that
actually matter (which tempo octave is right, where the downbeat sits, what key it is in)
are unit-testable without librosa, without audio, and without a model download.

The feature extraction that feeds these lives in
:mod:`app.services.analysis.timing`. This split exists because sprint 1 showed the hard
part is not *measuring* tempo, it is *choosing between* the octaves a measurement gives
you — and that choice is pure arithmetic over onset times.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

# Krumhansl-Schmuckler key profiles: the average perceived stability of each scale degree.
# Correlating a chroma vector against all 24 rotations of these is the standard way to
# guess a key, and it needs no training data.
MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)

PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Keys with flats in their signature read better with flat spellings.
FLAT_KEYS = {"F", "A#", "D#", "G#", "C#", "F#"}
FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")

# Tempos outside this are almost always an octave error rather than a real reading.
MIN_SENSIBLE_BPM = 55.0
MAX_SENSIBLE_BPM = 200.0

# You cannot infer a tempo from one or two events. Below this, say nothing rather than
# returning a confident-looking number derived from noise.
MIN_ONSETS_FOR_TEMPO = 4


class Mode(StrEnum):
    MAJOR = "major"
    MINOR = "minor"


@dataclass(frozen=True, slots=True)
class KeyEstimate:
    tonic: str
    mode: Mode
    confidence: float

    @property
    def name(self) -> str:
        return f"{self.tonic} {self.mode.value}"

    @property
    def prefers_flats(self) -> bool:
        """Whether to spell accidentals as flats when rendering note names."""
        minor_flat_keys = {"D", "G", "C", "F"}
        return self.tonic in FLAT_KEYS or (
            self.mode is Mode.MINOR and self.tonic in minor_flat_keys
        )


@dataclass(frozen=True, slots=True)
class TempoCandidate:
    bpm: float
    score: float
    offset_s: float


@dataclass(slots=True)
class TimingEstimate:
    """Everything downstream needs to lay notes on a grid."""

    tempo_bpm: float
    beats_per_bar: int = 4
    beat_unit: int = 4          # the 4 in 3/4; 8 for 6/8
    first_beat_s: float = 0.0
    confidence: float = 0.0
    key: KeyEstimate | None = None
    candidates: list[TempoCandidate] = field(default_factory=list)
    source: str = "detected"

    @property
    def time_signature(self) -> tuple[int, int]:
        return (self.beats_per_bar, self.beat_unit)

    @property
    def seconds_per_beat(self) -> float:
        return 60.0 / self.tempo_bpm if self.tempo_bpm > 0 else 0.5


def score_tempo(onsets: list[float], bpm: float, offset_s: float = 0.0) -> float:
    """How well a beat grid at ``bpm`` explains these onset times, in 0..1.

    The score is deliberately symmetric — an F-measure between two quantities:

    * **precision**: of the onsets, how many land on a beat
    * **recall**: of the beats, how many have an onset on them

    That symmetry is the whole point. Scoring only precision would rank double-time
    perfectly, because every onset that lands on a beat at N BPM also lands on one at
    2N. Recall punishes the doubled grid for the empty beats it invents, which is exactly
    the octave error librosa hands us.
    """
    if len(onsets) < MIN_ONSETS_FOR_TEMPO or bpm <= 0:
        return 0.0

    period = 60.0 / bpm
    tolerance = period * 0.15  # within 15% of a beat counts as "on" it

    span = max(onsets) - offset_s
    beat_count = int(span / period) + 1
    if beat_count < 2:
        return 0.0

    hit_onsets = 0
    for onset in onsets:
        phase = (onset - offset_s) % period
        distance = min(phase, period - phase)
        if distance <= tolerance:
            hit_onsets += 1

    occupied_beats = set()
    for onset in onsets:
        index = round((onset - offset_s) / period)
        if 0 <= index < beat_count:
            phase = (onset - offset_s) % period
            if min(phase, period - phase) <= tolerance:
                occupied_beats.add(index)

    precision = hit_onsets / len(onsets)
    recall = len(occupied_beats) / beat_count
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def best_offset(onsets: list[float], bpm: float, steps: int = 48) -> float:
    """Find the grid phase that best fits the onsets — i.e. where beat one sits.

    Two passes. The coarse search finds the right *region*, but it cannot do better than
    the beat tolerance: every offset that puts the onsets "on the beat" scores identically,
    so the search would return whichever it happened to try first. The refinement then
    takes the circular mean of the on-beat onsets' phases, which lands on the true
    downbeat rather than merely inside the tolerance window.
    """

    if len(onsets) < MIN_ONSETS_FOR_TEMPO or bpm <= 0:
        return 0.0

    period = 60.0 / bpm
    coarse, best_score = 0.0, -1.0
    for step in range(steps):
        offset = period * step / steps
        score = score_tempo(onsets, bpm, offset)
        if score > best_score:
            coarse, best_score = offset, score

    tolerance = period * 0.15
    on_beat = []
    for onset in onsets:
        phase = (onset - coarse) % period
        if min(phase, period - phase) <= tolerance:
            on_beat.append(phase if phase <= period / 2 else phase - period)
    if not on_beat:
        return coarse

    # Circular mean, so phases either side of the beat average correctly rather than
    # cancelling to the middle of the bar.
    angles = [2 * math.pi * p / period for p in on_beat]
    mean_angle = math.atan2(
        sum(math.sin(a) for a in angles) / len(angles),
        sum(math.cos(a) for a in angles) / len(angles),
    )
    return (coarse + mean_angle * period / (2 * math.pi)) % period


def octave_variants(bpm: float) -> list[float]:
    """The tempos a beat tracker confuses with this one, within a sensible range."""
    out = []
    for factor in (0.25, 1 / 3, 0.5, 2 / 3, 1.0, 1.5, 2.0, 3.0, 4.0):
        value = bpm * factor
        if MIN_SENSIBLE_BPM <= value <= MAX_SENSIBLE_BPM:
            out.append(round(value, 3))
    return sorted(set(out))


def choose_tempo(onsets: list[float], reported_bpm: float) -> TempoCandidate:
    """Pick the most defensible tempo octave for a beat tracker's raw reading.

    Sprint 1 found a 100 BPM click and a 200 BPM click both reported ~99.4. Rather than
    trusting that number, score every octave of it against the onsets and take the best.
    """
    candidates = []
    for bpm in octave_variants(reported_bpm) or [reported_bpm]:
        offset = best_offset(onsets, bpm)
        candidates.append(TempoCandidate(bpm=bpm, score=score_tempo(onsets, bpm, offset),
                                         offset_s=offset))

    if not candidates:
        return TempoCandidate(bpm=reported_bpm, score=0.0, offset_s=0.0)

    # Ties go to the slower tempo: a half-time reading is easier for a player to follow
    # than a double-time one, and it produces fewer, longer bars.
    candidates.sort(key=lambda c: (-round(c.score, 3), c.bpm))
    return candidates[0]


def detect_beats_per_bar(
    onsets: list[float],
    bpm: float,
    offset_s: float,
    strengths: list[float] | None = None,
    options: tuple[int, ...] = (4, 3),
) -> tuple[int, float]:
    """Guess the metre from where the *accents* fall, not merely where onsets exist.

    Presence alone cannot distinguish 3/4 from 4/4 in music that plays something on every
    beat — every candidate bar length fits equally, and an earlier version of this
    returned 0.99 confidence on flatly wrong answers because of it. What actually marks a
    bar is that beat one is *louder*, so this compares mean onset strength on candidate
    downbeats against the other beats.

    Without strengths it can only fall back to presence, and reports no confidence to say
    so. Returns (beats_per_bar, confidence); low confidence means "assume 4/4".
    """
    if len(onsets) < MIN_ONSETS_FOR_TEMPO or bpm <= 0:
        return 4, 0.0

    period = 60.0 / bpm
    tolerance = period * 0.15
    weights = strengths if strengths and len(strengths) == len(onsets) else None
    if weights is None:
        # No accent information: any bar length fits equally well, and saying otherwise
        # would be inventing evidence.
        return 4, 0.0

    scores: dict[int, float] = {}
    for candidate in options:
        downbeat_strength: list[float] = []
        offbeat_strength: list[float] = []
        for onset, strength in zip(onsets, weights, strict=True):
            beat_index = round((onset - offset_s) / period)
            phase = (onset - offset_s) % period
            if min(phase, period - phase) > tolerance:
                continue  # not on the grid at all
            if beat_index % candidate == 0:
                downbeat_strength.append(strength)
            else:
                offbeat_strength.append(strength)

        if not downbeat_strength or not offbeat_strength:
            scores[candidate] = 0.0
            continue

        down = sum(downbeat_strength) / len(downbeat_strength)
        off = sum(offbeat_strength) / len(offbeat_strength)
        # How much louder beat one is than the rest, as a fraction. Zero means no accent.
        scores[candidate] = (down - off) / down if down > 0 else 0.0

    best = max(scores, key=lambda k: (scores[k], -k))
    if scores[best] <= 0.05:
        # No candidate shows a real accent - 4/4 is the safe default, and we say we are
        # guessing rather than pretending to have detected something.
        return 4, 0.0

    ordered = sorted(scores.values(), reverse=True)
    margin = ordered[0] - ordered[1] if len(ordered) > 1 else ordered[0]
    return best, round(max(0.0, min(1.0, margin * 2)), 3)


def estimate_key(chroma: list[float]) -> KeyEstimate:
    """Krumhansl-Schmuckler: correlate a 12-bin chroma against all 24 key profiles."""
    if len(chroma) != 12:
        raise ValueError(f"chroma must have 12 bins, got {len(chroma)}")

    total = sum(chroma)
    if total <= 0:
        return KeyEstimate(tonic="C", mode=Mode.MAJOR, confidence=0.0)
    normalised = [v / total for v in chroma]

    scored: list[tuple[float, str, Mode]] = []
    for mode, profile in ((Mode.MAJOR, MAJOR_PROFILE), (Mode.MINOR, MINOR_PROFILE)):
        for rotation in range(12):
            rotated = [profile[(i - rotation) % 12] for i in range(12)]
            scored.append((_correlate(normalised, rotated), PITCH_CLASSES[rotation], mode))

    scored.sort(reverse=True)
    best, runner_up = scored[0], scored[1]
    # Margin over the next-best key is a far more honest confidence than the raw
    # correlation, which is high for almost any tonal music.
    confidence = round(max(0.0, min(1.0, (best[0] - runner_up[0]) * 5)), 3)
    return KeyEstimate(tonic=best[1], mode=best[2], confidence=confidence)


def _correlate(a: list[float], b: list[float]) -> float:
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    numerator = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True))
    denom_a = sum((x - mean_a) ** 2 for x in a) ** 0.5
    denom_b = sum((y - mean_b) ** 2 for y in b) ** 0.5
    if denom_a == 0 or denom_b == 0:
        return 0.0
    return numerator / (denom_a * denom_b)


def spell_pitch(midi: int, key: KeyEstimate | None = None) -> str:
    """Name a MIDI pitch, choosing sharps or flats to suit the key."""
    names = FLAT_NAMES if (key and key.prefers_flats) else PITCH_CLASSES
    return f"{names[midi % 12]}{midi // 12 - 1}"
