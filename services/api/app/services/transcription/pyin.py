"""Monophonic pitch transcription with pYIN (probabilistic YIN), via librosa.

Why this exists alongside basic-pitch: **bass lines are monophonic**. Running a
polyphonic neural transcriber over a bass stem is both slower and less accurate than a
good monophonic pitch tracker, and pYIN needs nothing beyond librosa — no TensorFlow, no
ONNX runtime, no model download.

basic-pitch remains the right tool for guitar and piano, where several notes sound at
once. The factory picks between them per stem.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.domain.notes import NoteEvent, StemKind, Transcription

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PitchRange:
    """Search bounds for the tracker. Narrower means faster and fewer octave errors."""

    fmin_hz: float
    fmax_hz: float


# Bass guitar low B is ~31 Hz; guitar's top fret is ~1200 Hz. Padded a little either way.
RANGES: dict[StemKind, PitchRange] = {
    StemKind.BASS: PitchRange(28.0, 450.0),
    StemKind.GUITAR: PitchRange(70.0, 1400.0),
    StemKind.VOCALS: PitchRange(65.0, 1100.0),
    StemKind.OTHER: PitchRange(55.0, 1400.0),
    StemKind.PIANO: PitchRange(28.0, 4200.0),
}
DEFAULT_RANGE = PitchRange(55.0, 1400.0)


def frame_length_for(fmin_hz: float, sample_rate: int) -> int:
    """Smallest power-of-two frame holding two periods of ``fmin_hz``.

    pYIN is an autocorrelation method: it cannot see a period longer than its analysis
    frame. librosa's default 2048 samples is only 46 ms, which is under two cycles of a
    5-string bass low B (~31 Hz) — exactly the note this transcriber exists to catch.
    Too small a frame does not error, it just returns wrong pitches, so this is computed
    rather than left to the default.
    """
    needed = 2.0 * sample_rate / max(fmin_hz, 1.0)
    frame = 2048
    while frame < needed:
        frame *= 2
    return frame


class PyinTranscriber:
    """Monophonic only. Chords will come out as a single wandering line."""

    name = "pyin"

    def __init__(
        self,
        hop_length: int = 512,
        min_note_s: float = 0.06,
        min_confidence: float = 0.5,
    ) -> None:
        self.hop_length = hop_length
        # Shorter than this and it is a pitch-tracker wobble, not a note.
        self.min_note_s = min_note_s
        self.min_confidence = min_confidence

    def supports(self, stem: StemKind) -> bool:
        # Deliberately not PIANO or OTHER: those are usually polyphonic.
        return stem in (StemKind.BASS, StemKind.VOCALS)

    def available(self) -> bool:
        try:
            import librosa  # noqa: F401
            import numpy  # noqa: F401
        except ImportError:
            return False
        return True

    def transcribe(self, audio: Path, stem: StemKind) -> Transcription:
        import librosa
        import numpy as np

        bounds = RANGES.get(stem, DEFAULT_RANGE)
        y, sr = librosa.load(str(audio), sr=None, mono=True)

        f0, voiced, voiced_prob = librosa.pyin(
            y,
            fmin=bounds.fmin_hz,
            fmax=bounds.fmax_hz,
            sr=sr,
            hop_length=self.hop_length,
            frame_length=frame_length_for(bounds.fmin_hz, sr),
        )
        times = librosa.times_like(f0, sr=sr, hop_length=self.hop_length)

        # Quantise each frame to the nearest semitone, then merge runs of equal pitch.
        with np.errstate(invalid="ignore"):
            midi = np.round(librosa.hz_to_midi(f0))
        notes = self._segment(midi, voiced, voiced_prob, times)

        tempo = self._estimate_tempo(y, sr)
        return Transcription(stem=stem, notes=notes, tempo_bpm=tempo, backend=self.name)

    def _segment(self, midi, voiced, voiced_prob, times) -> list[NoteEvent]:
        """Turn a per-frame pitch track into discrete note events."""
        import numpy as np

        notes: list[NoteEvent] = []
        start_index: int | None = None

        def close(end_index: int) -> None:
            if start_index is None:
                return
            pitch = int(midi[start_index])
            start_s = float(times[start_index])
            end_s = float(times[min(end_index, len(times) - 1)])
            confidence = float(np.nanmean(voiced_prob[start_index:end_index]) or 0.0)
            if end_s - start_s >= self.min_note_s and confidence >= self.min_confidence:
                notes.append(
                    NoteEvent(
                        start_s=start_s,
                        end_s=end_s,
                        pitch=max(0, min(127, pitch)),
                        velocity=max(1, min(127, int(confidence * 127))),
                        confidence=confidence,
                    )
                )

        for index in range(len(midi)):
            active = bool(voiced[index]) and not np.isnan(midi[index])
            changed = (
                start_index is not None
                and active
                and midi[index] != midi[start_index]
            )
            if not active or changed:
                close(index)
                start_index = index if active else None
            elif start_index is None:
                start_index = index
        close(len(midi) - 1)

        return notes

    def _estimate_tempo(self, y, sr: int) -> float:
        import librosa
        import numpy as np

        try:
            onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=self.hop_length)
            tempo, _ = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
            value = float(np.atleast_1d(tempo)[0])
            return value if value > 0 else 120.0
        except Exception:
            log.debug("tempo estimation failed; falling back to 120 BPM")
            return 120.0
