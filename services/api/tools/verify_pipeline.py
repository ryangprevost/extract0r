"""End-to-end pipeline verification against the real backends.

Synthesises a short multi-instrument mix, runs it through the whole pipeline exactly as
the API would, and prints what came out. Not a test — it needs the ML extras, downloads
model weights, and takes minutes. It exists so "does the pipeline work" can be answered
without a browser.

**This proves plumbing, not accuracy.** The input is synthesised sine waves, which is far
outside anything Demucs was trained on, so the stems it returns are poor and the
transcription of them is worse. On the first 6-stem run the bass came back an octave high
— and a controlled check confirmed pYIN reads the same notes correctly from the
unseparated signal, so the error was in the separation of synthetic audio, not the
transcriber. Judge quality with X0R-306's real eval set; judge *wiring* with this.

    cd services/api
    C:\\Users\\<you>\\.x0r-venv\\Scripts\\python.exe tools/verify_pipeline.py

Pass --model htdemucs for the faster 4-stem run.
"""

from __future__ import annotations

import argparse
import math
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.domain.notes import StemKind  # noqa: E402
from app.services import pipeline  # noqa: E402
from app.services.storage import TrackStorage  # noqa: E402

SAMPLE_RATE = 44100
# E2 A2 D3 G3 - an open-string bass walk, so the expected output is unambiguous.
BASS_MIDI = (40, 45, 50, 55)
# E minor and G major triads, the same voicings the solver picked in docs/samples.
CHORDS = ((52, 55, 59), (55, 59, 62))


def midi_to_hz(pitch: int) -> float:
    return 440.0 * 2 ** ((pitch - 69) / 12)


def synthesise(seconds: float = 12.0):
    """A crude three-part arrangement: bass, chords, and a backbeat."""
    import numpy as np

    total = int(seconds * SAMPLE_RATE)
    t = np.arange(total) / SAMPLE_RATE
    mix = np.zeros(total, dtype="float64")

    # --- bass: one note per bar, square-ish so it has harmonics to track
    bar = total // len(BASS_MIDI)
    for index, pitch in enumerate(BASS_MIDI):
        start, end = index * bar, (index + 1) * bar
        local = t[start:end] - t[start]
        freq = midi_to_hz(pitch)
        wave = (
            0.55 * np.sin(2 * math.pi * freq * local)
            + 0.20 * np.sin(4 * math.pi * freq * local)
        )
        mix[start:end] += wave * np.minimum(1.0, np.exp(-local * 0.6))

    # --- chords: sustained triads, alternating each half
    half = total // 2
    for index, chord in enumerate(CHORDS):
        start, end = index * half, (index + 1) * half
        local = t[start:end] - t[start]
        for pitch in chord:
            mix[start:end] += 0.16 * np.sin(2 * math.pi * midi_to_hz(pitch) * local)

    # --- drums: kick on 1 and 3, snare on 2 and 4, at 120 BPM
    rng = np.random.default_rng(0)
    for beat in range(int(seconds * 2)):
        start = int(beat * 0.5 * SAMPLE_RATE)
        length = min(int(0.06 * SAMPLE_RATE), total - start)
        if length <= 0:
            break
        decay = np.exp(-np.arange(length) / (0.010 * SAMPLE_RATE))
        if beat % 2 == 0:
            hit = np.sin(2 * math.pi * 60 * np.arange(length) / SAMPLE_RATE)
        else:
            hit = rng.standard_normal(length)
        mix[start : start + length] += 0.5 * decay * hit

    peak = np.max(np.abs(mix)) or 1.0
    return (0.85 * mix / peak).astype("float32")


def main() -> int:
    import numpy as np
    import soundfile as sf

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="htdemucs_6s")
    parser.add_argument("--keep", action="store_true", help="keep the working directory")
    args = parser.parse_args()

    work = Path(__file__).resolve().parents[3] / "storage" / "_verify"
    shutil.rmtree(work, ignore_errors=True)

    settings = Settings(
        storage_dir=work,
        separation_backend="demucs",
        demucs_model=args.model,
        transcription_backend="auto",
        drum_backend="onset",
        retention_sweep_minutes=0,
    )
    storage = TrackStorage(settings.storage_dir)

    source = work / "input.wav"
    source.parent.mkdir(parents=True, exist_ok=True)
    audio = synthesise()
    sf.write(str(source), np.stack([audio, audio], axis=1), SAMPLE_RATE)

    stored = storage.save_upload("verify.wav", source.read_bytes())
    print(f"track {stored.track_id}  ({stored.size_bytes / 1e6:.1f} MB)")

    started = time.monotonic()
    last = [0.0]

    def report(fraction: float) -> None:
        if fraction - last[0] >= 0.1:
            last[0] = fraction
            print(f"  separating... {fraction:>4.0%}")

    separation = pipeline.separate(stored.track_id, storage, settings, on_progress=report)
    elapsed = time.monotonic() - started
    print(
        f"\nseparated with {separation.backend}:{separation.model} "
        f"in {elapsed:.0f}s ({elapsed / 12.0:.1f}x realtime for 12s of audio)"
    )
    for stem in separation.stems:
        print(f"  {stem.kind.value:8} {stem.duration_s:5.1f}s  {stem.path.name}")

    wanted = [s.kind for s in separation.stems if s.kind in
              (StemKind.BASS, StemKind.GUITAR, StemKind.DRUMS, StemKind.OTHER)]
    print(f"\ntranscribing {', '.join(s.value for s in wanted)} ...")

    started = time.monotonic()
    bundle = pipeline.transcribe(
        stored.track_id, wanted, storage, settings, separation
    )
    print(f"transcribed in {time.monotonic() - started:.0f}s\n")

    for artifact in bundle.artifacts:
        print("=" * 72)
        print(f"{artifact.stem.value}  ({artifact.note_count} notes, {artifact.notation.value})")
        print("=" * 72)
        print(artifact.tab_text)

    print(f".x0r written to {bundle.x0r_path}")
    expected = {p % 12 for p in BASS_MIDI}
    bass = next((a for a in bundle.artifacts if a.stem is StemKind.BASS), None)
    if bass:
        print(f"\nexpected bass pitch classes: {sorted(expected)} (E A D G)")

    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
