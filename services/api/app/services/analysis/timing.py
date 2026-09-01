"""Feature extraction for tempo, metre, and key.

Analysis runs on the **full mix**, once, and the result is applied to every stem. That is
deliberate: a bass stem and a hi-hat stem will not agree on a tempo if asked separately,
and a tab whose bars drift apart between instruments is worse than one that is uniformly
a little wrong.

All the actual decisions live in :mod:`app.domain.timing`, which is pure. This module only
turns audio into the numbers those decisions need.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.domain.timing import (
    TimingEstimate,
    choose_tempo,
    detect_beats_per_bar,
    estimate_key,
)

log = logging.getLogger(__name__)

HOP_LENGTH = 512


class TimingAnalyser:
    name = "librosa_timing"

    def available(self) -> bool:
        try:
            import librosa  # noqa: F401
            import numpy  # noqa: F401
        except ImportError:
            return False
        return True

    def analyse(self, audio: Path) -> TimingEstimate:
        """Full-mix tempo, metre, and key. Never raises — a bad read falls back to 120."""
        if not self.available():
            return TimingEstimate(tempo_bpm=120.0, source="default (librosa missing)")

        try:
            return self._analyse(audio)
        except Exception:
            log.exception("timing analysis failed for %s; falling back to 120 BPM", audio.name)
            return TimingEstimate(tempo_bpm=120.0, source="default (analysis failed)")

    def _analyse(self, audio: Path) -> TimingEstimate:
        import librosa
        import numpy as np

        y, sr = librosa.load(str(audio), sr=None, mono=True)

        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP_LENGTH)
        onset_frames = librosa.onset.onset_detect(
            onset_envelope=onset_env, sr=sr, hop_length=HOP_LENGTH, backtrack=True
        )
        onsets = [
            float(t)
            for t in librosa.frames_to_time(onset_frames, sr=sr, hop_length=HOP_LENGTH)
        ]
        # Onset *strength* at each detected onset. Metre detection needs this: what marks
        # a bar is that beat one is louder, not that something happens on it.
        strengths = [
            float(onset_env[min(int(f), len(onset_env) - 1)]) for f in onset_frames
        ]

        reported = float(
            np.atleast_1d(
                librosa.feature.tempo(onset_envelope=onset_env, sr=sr, hop_length=HOP_LENGTH)
            )[0]
        )

        # librosa's number is a starting point, not an answer - pick the octave that
        # actually explains the onsets (see app.domain.timing.score_tempo).
        chosen = choose_tempo(onsets, reported)
        beats_per_bar, metre_confidence = detect_beats_per_bar(
            onsets, chosen.bpm, chosen.offset_s, strengths=strengths
        )

        chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP_LENGTH)
        key = estimate_key([float(v) for v in chroma.mean(axis=1)])

        estimate = TimingEstimate(
            tempo_bpm=round(chosen.bpm, 2),
            beats_per_bar=beats_per_bar,
            first_beat_s=round(chosen.offset_s, 4),
            confidence=round(chosen.score, 3),
            key=key,
            source=f"{self.name} (librosa reported {reported:.1f})",
        )
        log.info(
            "timing: %.1f BPM %d/%d, key %s (tempo conf %.2f, metre conf %.2f, "
            "librosa said %.1f)",
            estimate.tempo_bpm, estimate.beats_per_bar, estimate.beat_unit,
            key.name, estimate.confidence, metre_confidence, reported,
        )
        return estimate


class StubTimingAnalyser:
    """Fixed 120 BPM in 4/4, so the pipeline runs with no analysis stack installed."""

    name = "stub_timing"

    def available(self) -> bool:
        return True

    def analyse(self, audio: Path) -> TimingEstimate:
        return TimingEstimate(tempo_bpm=120.0, beats_per_bar=4, source=self.name)
