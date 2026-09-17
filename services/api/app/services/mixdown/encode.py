"""Reading and writing audio without ffmpeg.

Phase 2 was written against ffmpeg for both filtering and encoding, which meant mastering
and export could not run at all on a machine where Phase 1 worked perfectly — and this
one has no ffmpeg. `soundfile` reads and writes WAV/FLAC/OGG, and `lameenc` writes MP3;
both were already installed as transitive dependencies of the ML stack.

ffmpeg is still supported for formats libsndfile cannot open, but it is no longer on the
critical path for anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 44100
VALID_BITRATES = (128, 192, 256, 320)


class EncodingError(RuntimeError):
    """Audio could not be written in the requested format."""


@dataclass(frozen=True, slots=True)
class AudioBuffer:
    """Decoded audio, always float64 and always 2-D as (frames, channels)."""

    samples: np.ndarray
    sample_rate: int

    @property
    def duration_s(self) -> float:
        return self.samples.shape[0] / self.sample_rate if self.sample_rate else 0.0

    @property
    def channels(self) -> int:
        return self.samples.shape[1]


def read_audio(path: Path) -> AudioBuffer:
    """Read any accepted format to float64 at its own sample rate.

    A reference can be an m4a, which libsndfile will not open, so this falls through to
    the same PyAV decoder that ingest uses. Without that the file probes cleanly on
    upload and then fails later, when it is read to master against - the confusing
    version of the bug.

    Note this does not resample: callers that need a canonical rate go through
    `probe.normalize` instead.
    """
    import soundfile as sf

    try:
        samples, sample_rate = sf.read(str(path), dtype="float64", always_2d=True)
    except Exception:
        from app.services.audio.probe import decode_with_av

        decoded = decode_with_av(path)
        if decoded is None:
            raise
        samples, sample_rate = decoded
        samples = samples.astype("float64")

    return AudioBuffer(samples=samples, sample_rate=int(sample_rate))


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> Path:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), _as_stereo(samples), sample_rate, subtype="PCM_24")
    return path


def id3v2_tag(fields: dict[str, str]) -> bytes:
    """A minimal ID3v2.3 tag, built by hand.

    Hand-built because the alternative is another dependency for perhaps sixty lines, and
    because the tag matters: an export needs to say which reference it was matched
    against. A filename holds one name comfortably, and a master is the product of two.
    Six months later "which reference was this?" is otherwise unanswerable.

    Text is UTF-16LE with a byte-order mark, which is what v2.3 specifies for anything
    beyond Latin-1 - song titles collect accents and typographic apostrophes.

    Known frames: TIT2 title, TPE1 artist, TALB album, TENC encoder, COMM comment.
    """
    def frame(name: str, payload: bytes) -> bytes:
        # v2.3 sizes are plain big-endian, unlike the synchsafe header size below.
        return name.encode("ascii") + len(payload).to_bytes(4, "big") + b"\x00\x00" + payload

    def text(value: str) -> bytes:
        return b"\x01" + b"\xff\xfe" + value.encode("utf-16-le")

    body = b""
    for name, value in fields.items():
        if not value:
            continue
        if name == "COMM":
            # encoding, language, short description (empty, terminated), then the text.
            payload = b"\x01eng" + b"\xff\xfe" + b"\x00\x00" + b"\xff\xfe" + value.encode(
                "utf-16-le"
            )
            body += frame("COMM", payload)
        else:
            body += frame(name, text(value))

    if not body:
        return b""

    # The header size is synchsafe: seven bits per byte, so a size byte can never look
    # like an MPEG frame sync and confuse a decoder scanning for one.
    size = len(body)
    synchsafe = bytes(((size >> shift) & 0x7F) for shift in (21, 14, 7, 0))
    return b"ID3" + b"\x03\x00" + b"\x00" + synchsafe + body


def write_mp3(
    path: Path,
    samples: np.ndarray,
    sample_rate: int,
    bitrate_kbps: int = 320,
    tags: dict[str, str] | None = None,
) -> Path:
    """Encode to MP3 with LAME directly, no external process."""
    try:
        import lameenc
    except ImportError as exc:  # pragma: no cover - lameenc ships with the ML extras
        raise EncodingError(
            "lameenc is not installed, so MP3 export is unavailable. "
            "Install requirements-ml.txt."
        ) from exc

    if bitrate_kbps not in VALID_BITRATES:
        raise EncodingError(f"bitrate must be one of {VALID_BITRATES}, got {bitrate_kbps}")

    audio = _as_stereo(samples)
    # LAME wants interleaved 16-bit PCM. Clip first: wrapping an over-range sample round
    # to the opposite polarity is the loudest possible click.
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").reshape(-1)

    encoder = lameenc.Encoder()
    encoder.set_bit_rate(bitrate_kbps)
    encoder.set_in_sample_rate(sample_rate)
    encoder.set_channels(audio.shape[1])
    encoder.set_quality(2)  # 0 = best and slowest, 9 = worst; 2 is the usual choice

    data = encoder.encode(pcm.tobytes())
    data += encoder.flush()

    path.parent.mkdir(parents=True, exist_ok=True)
    # The tag goes in front of the audio, which is where a decoder expects to find it.
    path.write_bytes(id3v2_tag(tags or {}) + bytes(data))
    return path


def _as_stereo(samples: np.ndarray) -> np.ndarray:
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:
        audio = np.stack([audio[:, ::2].mean(axis=1), audio[:, 1::2].mean(axis=1)], axis=1)
    return audio


def mix_buffers(
    buffers: list[np.ndarray], gains_db: list[float] | None = None
) -> np.ndarray:
    """Sum stems to one stereo buffer, padding to the longest.

    Deliberately does **not** normalise the sum. Separation is additive, so stems summed
    at unity reconstruct the original mix; scaling here would quietly change the balance
    the user set.
    """
    if not buffers:
        raise ValueError("nothing to mix")

    prepared = [_as_stereo(b) for b in buffers]
    length = max(b.shape[0] for b in prepared)
    gains = gains_db or [0.0] * len(prepared)
    if len(gains) != len(prepared):
        raise ValueError("one gain per buffer is required")

    out = np.zeros((length, 2), dtype=np.float64)
    for buffer, gain in zip(prepared, gains, strict=True):
        scaled = buffer * (10.0 ** (gain / 20.0))
        out[: scaled.shape[0]] += scaled
    return out


def apply_pan(samples: np.ndarray, pan: float) -> np.ndarray:
    """Constant-power pan, -1 hard left to +1 hard right.

    Constant power rather than linear: a linear pan audibly dips in level as it crosses
    the centre.
    """
    audio = _as_stereo(samples)
    position = float(np.clip(pan, -1.0, 1.0))
    angle = (position + 1.0) * np.pi / 4.0
    return np.stack(
        [audio[:, 0] * np.cos(angle) * np.sqrt(2), audio[:, 1] * np.sin(angle) * np.sqrt(2)],
        axis=1,
    )
