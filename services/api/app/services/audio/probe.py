"""Audio probing and canonical decoding.

Everything downstream — separation, transcription, mixdown — assumes one input format.
This module is where that guarantee is created.

Backends, in preference order:

1. ``soundfile`` (libsndfile). Bundled in the wheel, needs nothing installed on the
   system, and since libsndfile 1.1 it reads MP3 as well as WAV/FLAC/OGG/AIFF. This
   covers every format we accept except m4a/aac.
2. ``ffprobe``/``ffmpeg``, when they happen to be on PATH. Only reached for the formats
   libsndfile will not open.

That ordering is deliberate: it means a developer with no ffmpeg still gets a working
ingest path for the formats people actually upload.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# The canonical shape every stage downstream of ingest can rely on.
TARGET_SAMPLE_RATE = 44100
TARGET_CHANNELS = 2


class UnreadableAudioError(ValueError):
    """The file has an accepted extension but nothing here can decode it."""


@dataclass(frozen=True, slots=True)
class AudioInfo:
    duration_s: float
    sample_rate: int
    channels: int
    format: str
    backend: str

    @property
    def needs_normalising(self) -> bool:
        return self.sample_rate != TARGET_SAMPLE_RATE or self.channels != TARGET_CHANNELS


def _ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def _probe_soundfile(path: Path) -> AudioInfo | None:
    try:
        import soundfile as sf
    except ImportError:
        return None
    try:
        info = sf.info(str(path))
    except Exception as exc:  # libsndfile raises a bare RuntimeError for unknown formats
        log.debug("soundfile could not open %s: %s", path.name, exc)
        return None
    return AudioInfo(
        duration_s=float(info.duration),
        sample_rate=int(info.samplerate),
        channels=int(info.channels),
        format=str(info.format),
        backend="soundfile",
    )


def _probe_ffprobe(path: Path) -> AudioInfo | None:
    executable = _ffprobe_path()
    if executable is None:
        return None
    proc = subprocess.run(
        [
            executable, "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,channels,codec_name:format=duration",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        log.debug("ffprobe failed on %s: %s", path.name, proc.stderr.strip()[:200])
        return None
    try:
        data = json.loads(proc.stdout)
        stream = data["streams"][0]
        return AudioInfo(
            duration_s=float(data["format"]["duration"]),
            sample_rate=int(stream["sample_rate"]),
            channels=int(stream["channels"]),
            format=str(stream["codec_name"]).upper(),
            backend="ffprobe",
        )
    except (KeyError, IndexError, ValueError) as exc:
        log.debug("could not parse ffprobe output for %s: %s", path.name, exc)
        return None


def probe(path: Path) -> AudioInfo:
    """Read duration, sample rate, channels, and codec without decoding the whole file."""
    for backend in (_probe_soundfile, _probe_ffprobe):
        info = backend(path)
        if info is not None:
            return info
    raise UnreadableAudioError(
        f"Could not read {path.name}. libsndfile does not recognise it and ffprobe is "
        "not available — install ffmpeg to support m4a/aac."
    )


def _resample(samples, source_rate: int, target_rate: int):
    """Resample a (frames, channels) float array, best available quality.

    ``soxr`` is a small wheel with no system dependencies and is what librosa uses
    internally. The linear fallback exists so ingest still works without it, and says
    so in the logs rather than silently degrading.
    """
    import numpy as np

    if source_rate == target_rate:
        return samples

    try:
        import soxr

        return soxr.resample(samples, source_rate, target_rate, quality="HQ")
    except ImportError:
        log.warning(
            "soxr is not installed; falling back to linear interpolation for "
            "%d Hz -> %d Hz. Install soxr for production-quality resampling.",
            source_rate,
            target_rate,
        )

    frame_count = int(round(samples.shape[0] * target_rate / source_rate))
    source_index = np.linspace(0.0, samples.shape[0] - 1, frame_count)
    return np.stack(
        [np.interp(source_index, np.arange(samples.shape[0]), samples[:, channel])
         for channel in range(samples.shape[1])],
        axis=1,
    )


def _fit_channels(samples, target: int = TARGET_CHANNELS):
    """Mono becomes dual-mono; anything above stereo is downmixed by averaging."""
    import numpy as np

    channels = samples.shape[1]
    if channels == target:
        return samples
    if channels == 1:
        return np.repeat(samples, target, axis=1)
    if channels > target:
        return np.stack([samples[:, ::2].mean(axis=1), samples[:, 1::2].mean(axis=1)], axis=1)
    return np.repeat(samples[:, :1], target, axis=1)


def normalize(source: Path, out_path: Path) -> AudioInfo:
    """Decode ``source`` to canonical 44.1 kHz stereo 16-bit WAV at ``out_path``.

    Returns the info of the file that was written, not of the source.
    """
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise UnreadableAudioError(
            "soundfile and numpy are required to normalise audio at ingest"
        ) from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        samples, sample_rate = sf.read(str(source), dtype="float32", always_2d=True)
    except Exception as exc:
        # libsndfile cannot open it (m4a/aac); hand off to ffmpeg if it is there.
        if _transcode_with_ffmpeg(source, out_path):
            return probe(out_path)
        raise UnreadableAudioError(f"Could not decode {source.name}: {exc}") from exc

    samples = _fit_channels(np.asarray(samples))
    samples = _resample(samples, sample_rate, TARGET_SAMPLE_RATE)
    # Guard against inter-sample overshoot introduced by resampling.
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > 1.0:
        samples = samples / peak

    sf.write(str(out_path), samples, TARGET_SAMPLE_RATE, subtype="PCM_16")
    return probe(out_path)


def _transcode_with_ffmpeg(source: Path, out_path: Path) -> bool:
    executable = shutil.which("ffmpeg")
    if executable is None:
        return False
    proc = subprocess.run(
        [
            executable, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(source),
            "-ar", str(TARGET_SAMPLE_RATE),
            "-ac", str(TARGET_CHANNELS),
            "-c:a", "pcm_s16le",
            str(out_path),
        ],
        capture_output=True,
    )
    return proc.returncode == 0 and out_path.exists()
