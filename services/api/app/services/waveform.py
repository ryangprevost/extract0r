"""Amplitude envelopes for drawing waveforms in the browser.

Shipping the WAV to the client and decoding it there is hundreds of megabytes for a
five-minute song, so the envelope is computed here and sent as a few hundred numbers.

Two decisions carry the whole module.

**RMS per bucket, not peak.** Peak is dominated by isolated samples, so a stem that is
essentially silent but carries a few separation artefacts draws as a row of spikes.

**Decibels, not linear amplitude.** Loudness is logarithmic. A linear envelope makes quiet
passages invisible and near-silence look busy; dB is what a DAW draws. The floor is what
makes a rest look like a rest.

The dB values are kept alongside the drawing envelope because comparing two renders of the
same song - before and after mastering - is a question about decibels, not about pixels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

# Enough buckets for a detailed waveform at typical widths without shipping a huge array.
DEFAULT_PEAK_BUCKETS = 1200
MAX_PEAK_BUCKETS = 4000

#: Anything quieter than this reads as silence.
SILENCE_FLOOR_DB = -55.0

#: Stands in for log10(0) so an all-zero bucket has a number rather than -inf.
QUIET_DB = -90.0


@dataclass(frozen=True, slots=True)
class Envelope:
    """One file, reduced to something drawable and something comparable."""

    buckets: int
    duration_s: float
    sample_rate: int
    #: 0..1 per bucket, dB-scaled against SILENCE_FLOOR_DB - the drawing height.
    peaks: list[float]
    #: The same buckets as RMS dBFS, for comparing two files against each other.
    db: list[float]
    peak_dbfs: float | None
    silent: bool

    def as_payload(self) -> dict:
        return {
            "buckets": self.buckets,
            "duration_s": self.duration_s,
            "sample_rate": self.sample_rate,
            "peaks": self.peaks,
            "db": self.db,
            "peak_dbfs": self.peak_dbfs,
            "silent": self.silent,
            "floor_dbfs": SILENCE_FLOOR_DB,
        }


def measure(path: Path, buckets: int = DEFAULT_PEAK_BUCKETS) -> Envelope:
    """Reduce an audio file to `buckets` RMS values, read in blocks rather than at once."""
    import numpy as np
    import soundfile as sf

    with sf.SoundFile(str(path)) as handle:
        total_frames = len(handle)
        sample_rate = handle.samplerate
        rms = np.zeros(buckets, dtype="float64")
        peak_linear = 0.0
        frames_per_bucket = max(1, total_frames // buckets)

        blocks = handle.blocks(blocksize=frames_per_bucket, dtype="float32", always_2d=True)
        for index, block in enumerate(blocks):
            if index >= buckets:
                break
            if block.size:
                mono = block.mean(axis=1)
                rms[index] = float(np.sqrt(np.mean(mono**2)))
                peak_linear = max(peak_linear, float(np.abs(block).max()))

    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(np.maximum(rms, 1e-9))
    db = np.maximum(db, QUIET_DB)
    drawn = np.clip((db - SILENCE_FLOOR_DB) / (0.0 - SILENCE_FLOOR_DB), 0.0, 1.0)
    loudest_db = float(db.max()) if rms.size else QUIET_DB

    return Envelope(
        buckets=buckets,
        duration_s=round(total_frames / sample_rate, 3) if sample_rate else 0.0,
        sample_rate=sample_rate,
        # Rounded: three decimals is well under one pixel of error at any sane height.
        peaks=[round(float(v), 3) for v in drawn],
        db=[round(float(v), 2) for v in db],
        peak_dbfs=round(20.0 * math.log10(peak_linear), 1) if peak_linear > 0 else None,
        # "Silent" means "never rises above the floor", which covers a stem holding
        # nothing but separation artefacts as well as one holding literal zeros.
        silent=bool(loudest_db <= SILENCE_FLOOR_DB),
    )


def difference_db(before: Envelope, after: Envelope) -> list[float]:
    """How much louder each moment got, in dB.

    This is the part a waveform on its own will not tell you. Mastering moves level by a
    couple of dB and shaves the peaks, which on a 55 dB scale is a few pixels; the moments
    where it did most of its work only become visible as a difference.

    Buckets where both sides are below the floor return 0.0 rather than the difference
    between two kinds of silence, which is noise dressed up as a measurement.
    """
    pairs = zip(before.db, after.db, strict=False)
    return [
        0.0 if (a <= SILENCE_FLOOR_DB and b <= SILENCE_FLOOR_DB) else round(b - a, 2)
        for a, b in pairs
    ]
