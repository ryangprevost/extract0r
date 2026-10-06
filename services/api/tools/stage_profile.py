"""X0R-1403: where the comparison's twenty seconds actually goes.

The backlog assumed the pitch contour, because that is what was added last. Assumed is
not measured, and the progress bar (X0R-1404) cannot be weighted by an assumption.

Synthetic stems rather than a real separation: the stages being timed read audio and do
arithmetic on it, and neither cares whether the waveform came out of a model. Six stems,
three and a half minutes, 44.1k stereo - the shape of a real job.

Run it from `services/api` as `python tools/stage_profile.py <dir> [seconds]`, in the
venv that has librosa - the cost being measured is almost all pitch tracking, so the
venv without it measures a different program.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from app.domain.notes import StemKind  # noqa: E402

RATE = 44100
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 210.0

# Kept per length, so a second run at the same length reuses the files and times the
# work rather than the disk.
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".") / f"profile_stems_{int(SECONDS)}"
OUT.mkdir(parents=True, exist_ok=True)
STEMS = [StemKind.VOCALS, StemKind.DRUMS, StemKind.BASS, StemKind.GUITAR,
         StemKind.PIANO, StemKind.OTHER]

rng = np.random.default_rng(7)
t = np.arange(int(RATE * SECONDS)) / RATE


def sung(hz: float) -> np.ndarray:
    """A voice-ish signal: a held pitch with vibrato and partials, gated into phrases.

    The tracker needs something it can actually follow, or the timing measured is the
    timing of the abstention path rather than of the work.
    """
    wobble = 0.22 * np.sin(2 * np.pi * 5.2 * t)
    f = hz * 2 ** ((wobble + 1.5 * np.sin(2 * np.pi * 0.08 * t)) / 12)
    phase = 2 * np.pi * np.cumsum(f) / RATE
    tone = sum(0.6 ** k * np.sin((k + 1) * phase) for k in range(4))
    phrase = (np.sin(2 * np.pi * 0.12 * t) > -0.2).astype(float)
    return 0.2 * tone * phrase


def hits(per_second: float, decay: float) -> np.ndarray:
    out = np.zeros_like(t)
    step = int(RATE / per_second)
    env = np.exp(-np.arange(int(RATE * decay)) / (RATE * decay / 5))
    for start in range(0, len(out) - len(env), step):
        out[start:start + len(env)] += env * rng.uniform(0.6, 1.0)
    return 0.3 * out * rng.standard_normal(len(out))


paths = {}
for kind in STEMS:
    path = OUT / f"{kind.value}.wav"
    if not path.exists():
        if kind is StemKind.VOCALS:
            mono = sung(220.0)
        elif kind is StemKind.DRUMS:
            mono = hits(4.0, 0.25)
        elif kind is StemKind.BASS:
            mono = sung(82.0) * 0.8
        else:
            mono = 0.15 * np.sin(2 * np.pi * 440 * t) * (np.sin(2 * np.pi * 0.3 * t) > 0)
        stereo = np.stack([mono, mono * 0.92], axis=-1).astype(np.float32)
        sf.write(path, stereo, RATE)
    paths[kind] = str(path)

print(f"stems in {OUT}, {SECONDS:.0f}s each\n")

from app.services.mastering.character import observations  # noqa: E402
from app.services.mastering.critique import STEM_WORDS  # noqa: E402
from app.services.mastering.instrument import compare, profile_all  # noqa: E402
from app.services.mixdown.encode import read_audio  # noqa: E402

timings = {}


def timed(label, fn):
    start = time.perf_counter()
    value = fn()
    timings[label] = time.perf_counter() - start
    print(f"  {label:38s} {timings[label]:7.2f} s")
    return value


print("the three stages the job reports:")
mine = timed("measuring your instruments", lambda: profile_all(paths))
theirs = timed("measuring the reference's", lambda: profile_all(paths))


def comparisons():
    out = []
    for kind in STEMS:
        a, b = mine.get(kind), theirs.get(kind)
        if a is None or b is None:
            continue
        out.append(compare(kind, a, b, STEM_WORDS.get(kind, (kind.value, False))))
    return out


timed("comparing them: the dials", comparisons)

# The character pass, which is inside "comparing them" and is the newest thing on the path.
buffers = {}


def read_both():
    for kind in STEMS:
        buffers[kind] = read_audio(Path(paths[kind]))
    return buffers


timed("comparing them: re-reading the audio", read_both)


def character():
    out = {}
    for kind in STEMS:
        words = STEM_WORDS.get(kind, (kind.value, False))
        buffer = buffers[kind]
        start = time.perf_counter()
        out[kind] = observations(
            kind, words[0], words[1], buffer.samples, buffer.samples, buffer.sample_rate
        )
        timings[f"    character: {kind.value}"] = time.perf_counter() - start
    return out


found = timed("comparing them: character", character)
for kind in STEMS:
    print(f"      {kind.value:12s} {timings[f'    character: {kind.value}']:7.2f} s"
          f"  ({len(found[kind])} findings)")

total = sum(v for k, v in timings.items() if not k.startswith("    "))
print(f"\n  {'total':38s} {total:7.2f} s")
print("\nshare of the whole job:")
for label in ("measuring your instruments", "measuring the reference's",
              "comparing them: the dials", "comparing them: re-reading the audio",
              "comparing them: character"):
    print(f"  {label:38s} {timings[label] / total:6.1%}")
