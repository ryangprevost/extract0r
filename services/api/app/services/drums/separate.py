"""Splitting a drums stem into the drums inside it.

`detect` answers "which drum is this stroke?" by comparing how far two frequency bands
rose, on a stem where every drum is summed together. It is a good answer to an impossible
question, and the impossibility shows: a club kick's click lands in the snare's rattle
band, so on one twenty-eight second clip six of twenty-seven kicks sat within 6 dB of the
line that separates them. A threshold across a quantity that straddles it does not produce
a few wrong labels, it produces flicker - and flicker is what an ear notices. Ryan reported
it twice, the second time as a snare that "comes in and out at various kick hits".

No threshold fixes that, because the information needed is not in the summed stem. This
module gets it from somewhere else: a second separation pass over the drums alone, which
returns the kick, the snare, the cymbals and the toms as *audio*. After that there is
nothing to classify. An onset in the kick file is a kick, because it came out of the kick
file.

**The model.** DrumSep, by Iñaki Goyeneche - a Hybrid Demucs fine-tune, MIT licensed. The
same architecture as the separator this project already runs, which is why this module is
sixty lines and not six hundred: it is the same CLI, the same torch, and the same progress
stream, with `--repo` pointed at a different set of weights.

**Why it is opt-in.** It is a second pass over one stem. Measured on a thirty second clip:
sixteen seconds on CPU, so roughly half the length of the audio again on top of the main
separation. Worth it when you are replacing drums, wasted when you are not.

**What it is not.** The stems are not perfectly clean - a loud kick leaves a trace in the
snare file and a cymbal rings through everything, which is true of every separator and of
the six-way split this project already relies on. What changes is the kind of mistake:
bleed makes a trigger slightly early or slightly quiet, where a misclassification put an
entire snare on top of a kick.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from app.services.drums.detect import Hit

log = logging.getLogger(__name__)

#: The model's signature, which is also the folder demucs writes into. Not a name anyone
#: chose - it is the hash demucs assigns a set of weights, and the CLI wants it verbatim.
MODEL = "49469ca8"

#: What the model calls its outputs, and what this project calls them. The model was
#: trained and published in Spanish; translating at the boundary means the rest of the
#: codebase never has to know that, and `kit.DRUMS` already uses these English names.
STEM_NAMES = {
    "bombo": "kick",
    "redoblante": "snare",
    "platillos": "cymbals",
    "toms": "toms",
}

#: Onset detection on an isolated drum does not need the `backtrack` that `find_hits`
#: uses, and should not have it: see X0R-412. Here the time is used to place a sample, so
#: the transient's true start is what matters.
_HOP = 512

#: How far below a drum's own loudest stroke a stroke may be and still be that drum.
#:
#: Separation is not surgery. A kick leaves a trace in the snare file, and an onset
#: detector run over that trace finds strokes that are really the kick arriving late.
#: Without a gate this clip produced 103 snares in 28 seconds, where a backbeat at 125 BPM
#: allows about 29.
#:
#: The number is a judgement and the measurement says so. Strokes surviving each gate,
#: against each stem's own loudest:
#:
#:      gate     kick   snare   cymbals
#:      -6 dB      60       4        21
#:     -14 dB      60      10        55
#:     -24 dB      60      24        56
#:     -30 dB      60      31        59
#:     -40 dB      60      45        76
#:
#: The kick does not care - sixty strokes at every setting, because a programmed
#: four-on-the-floor has sixty near-identical hits and nothing else. The cymbals have a
#: knee at about -14. The snare has **no knee at all**: it is a smooth slope from backbeat
#: down into bleed, so any cut is a choice rather than a discovery. -24 dB lands at 24
#: against the ~29 the tempo allows, which errs toward missing a ghost note rather than
#: reinforcing a kick that leaked.
#:
#: It errs that way deliberately. `kit.layer` already scales each trigger by the stroke's
#: strength, so a quiet stroke that slips through is quiet - the gate only has to stop the
#: smear of near-silent triggers that scaling alone would still accumulate.
QUIET_STROKE_DB = -24.0


def model_path(models_dir: Path) -> Path:
    return Path(models_dir) / "drumsep" / f"{MODEL}.th"


def available(models_dir: Path) -> bool:
    """True when the weights are on disk and demucs can be imported.

    Both halves matter and they fail differently: a missing model is something the user
    can fix by downloading it, and a missing demucs means this build has no ML extras at
    all. `why_unavailable` says which.
    """
    if not model_path(models_dir).exists():
        return False
    # Reusing the main separator's probe rather than `import demucs` here, and the
    # difference is not academic. This project's app venv has a torch missing `torchgen`:
    # `import demucs` succeeds, and the failure only appears when demucs itself imports
    # torch, several seconds into a subprocess. Worse, a failed `import torch` leaves its
    # native DLLs loaded and they fault at interpreter exit - which is the segfault that
    # once stopped the whole test suite from printing a result. The probe asks a separate
    # process, which is the only answer that matches what `separate` will actually do.
    from app.services.separation.demucs import demucs_is_importable

    return demucs_is_importable()


def why_unavailable(models_dir: Path) -> str:
    """A sentence a user can act on, or empty when it is available."""
    path = model_path(models_dir)
    if not path.exists():
        return (
            f"Per-drum separation needs the DrumSep model at {path}. It is a 167 MB "
            "download from huggingface.co/vincewin/drumsep (MIT, by Iñaki Goyeneche)."
        )
    from app.services.separation.demucs import demucs_is_importable

    if not demucs_is_importable():
        return (
            "Per-drum separation needs a working demucs and torch in this interpreter. "
            "Install requirements-ml.txt, or run from the ML venv."
        )
    return ""


def separate(
    drums: Path,
    out_dir: Path,
    models_dir: Path,
    device: str = "cpu",
    on_progress: Callable[[float], None] | None = None,
) -> dict[str, Path]:
    """Split one drums stem into kick, snare, cymbals and toms.

    Returns the stems that were actually written, keyed by the English name. A model that
    produced fewer than it promised yields a shorter dict rather than an exception: the
    caller can still replace the drums it did get, and a missing toms file on a track with
    no toms is not an error worth refusing the whole operation over.
    """
    drums = Path(drums)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable, "-m", "demucs",
        "--repo", str(Path(models_dir) / "drumsep"),
        "-n", MODEL,
        "-d", device,
        "-o", str(out_dir),
        str(drums),
    ]
    log.info("separating drums with %s", MODEL)
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join((result.stderr or "").strip().splitlines()[-10:])
        raise RuntimeError(f"drumsep failed ({result.returncode}):\n{tail}")

    # demucs writes <out>/<model>/<input stem name>/<source>.wav
    written = out_dir / MODEL / drums.stem
    stems: dict[str, Path] = {}
    for spanish, english in STEM_NAMES.items():
        path = written / f"{spanish}.wav"
        if path.exists():
            stems[english] = path
        else:
            log.info("drumsep produced no %s for %s", spanish, drums.name)
    if on_progress:
        on_progress(1.0)
    return stems


def hits_from_stems(stems: dict[str, Path]) -> list[Hit]:
    """Every stroke in every separated drum, each labelled with the one drum it is.

    This is the whole payoff and it is deliberately dull. There is no classifier here and
    no threshold to tune: an onset in the kick file is a kick. `Hit.kinds` therefore holds
    exactly one name, so nothing downstream can ever lay two samples on one stroke.

    Strength is the peak of the stroke in its own stem rather than in the mix, which is
    the number that makes a reinforced part keep its dynamics - a ghost note stays a ghost
    note.
    """
    import numpy as np

    from app.services.mixdown.encode import read_audio

    hits: list[Hit] = []
    for name, path in stems.items():
        try:
            buffer = read_audio(Path(path))
        except Exception:
            log.info("could not read the %s stem", name, exc_info=True)
            continue

        times = _onsets(buffer.samples, buffer.sample_rate)
        mono = buffer.samples.mean(axis=1) if buffer.samples.ndim > 1 else buffer.samples

        found = []
        for time_s in times:
            start = int(time_s * buffer.sample_rate)
            window = mono[start : start + int(0.03 * buffer.sample_rate)]
            found.append((float(time_s), float(np.abs(window).max()) if window.size else 0.0))

        # Gated against this drum's own loudest stroke, not against the mix: a quiet
        # instrument played properly is not bleed, and comparing across stems would
        # silence the whole snare on a record the kick dominates.
        loudest = max((s for _, s in found), default=0.0)
        floor = loudest * 10.0 ** (QUIET_STROKE_DB / 20.0)
        for time_s, strength in found:
            if strength <= floor:
                continue
            hits.append(
                Hit(time_s=time_s, kinds=[name], strength=strength, rises={})
            )

    hits.sort(key=lambda h: h.time_s)
    return hits


def _onsets(samples, sample_rate: int) -> list[float]:
    """Onset times in one isolated drum stem.

    `backtrack=False`, against `find_hits`' True. Backtracking walks an onset back to a
    local minimum of the envelope, which is right when you are looking for the start of a
    transient to trigger from and wrong when you want to know *when* the drum was struck -
    it moves each time by a variable amount, which is X0R-412. Here the time places a
    sample against the original, so it has to be the time.
    """
    import librosa
    import numpy as np

    audio = np.asarray(samples, dtype=np.float64)
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    if not np.any(np.abs(mono) > 1e-6):
        return []

    envelope = librosa.onset.onset_strength(y=mono, sr=sample_rate, hop_length=_HOP)
    frames = librosa.onset.onset_detect(
        onset_envelope=envelope, sr=sample_rate, hop_length=_HOP, backtrack=False
    )
    return [float(t) for t in librosa.frames_to_time(frames, sr=sample_rate, hop_length=_HOP)]
