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

from app.domain.notes import StemKind, Transcription
from app.domain.segmentation import nearest_frames, segment_notes

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PitchRange:
    """Search bounds for the tracker. Narrower means faster and fewer octave errors."""

    fmin_hz: float
    fmax_hz: float


# Deliberately tight. A 4-string bass bottoms out at E1 (41 Hz) and a 5-string at B0
# (31 Hz); the top of a bass neck is around G3 (196 Hz). Allowing pYIN to search up to
# 450 Hz just gave it room to lock onto the second harmonic and report everything an
# octave high, which is the classic way bass transcription goes wrong.
RANGES: dict[StemKind, PitchRange] = {
    StemKind.BASS: PitchRange(30.0, 260.0),
    StemKind.GUITAR: PitchRange(75.0, 1200.0),
    StemKind.VOCALS: PitchRange(65.0, 1100.0),
    StemKind.OTHER: PitchRange(55.0, 1200.0),
    StemKind.PIANO: PitchRange(28.0, 4200.0),
}
DEFAULT_RANGE = PitchRange(55.0, 1200.0)


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
        hop_length: int = 256,
        min_note_s: float = 0.05,
        min_confidence: float = 0.08,
        onset_delta: float = 0.2,
    ) -> None:
        # 256 rather than 512: at 44.1 kHz that is 5.8 ms per frame, which is the
        # difference between resolving two eighth notes at 160 BPM and smearing them.
        self.hop_length = hop_length
        self.min_note_s = min_note_s
        # pYIN already decides voicing with its own HMM; `voiced_prob` is a weak secondary
        # signal, not a probability you can threshold at 0.5. Measured on a real bass stem
        # its median is 0.012 and its 90th percentile 0.43 - a 0.4 cut discarded 88% of
        # frames whose pitches were correct, which is why the first pass at this song
        # produced 11 notes in three minutes. Keep this low and let `voiced` do the work.
        self.min_confidence = min_confidence
        # Measured, not guessed. On a sustained 220 Hz tone librosa's onset detector
        # returns 28 onsets at delta=0.07 and 2 at delta=0.2 - and every spurious onset
        # becomes a spurious note split. 0.2 is the point where a held note stays whole.
        self.onset_delta = onset_delta

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

        with np.errstate(invalid="ignore"):
            midi = librosa.hz_to_midi(f0)

        pitches: list[float | None] = [
            None if (not voiced[i] or np.isnan(midi[i])) else float(midi[i])
            for i in range(len(midi))
        ]
        confidences = [
            0.0 if np.isnan(voiced_prob[i]) else float(voiced_prob[i])
            for i in range(len(voiced_prob))
        ]

        # A re-struck note is a new note even at the same pitch, so the pitch track alone
        # cannot say where notes begin. Onsets supply that.
        # `delta` and `wait` matter as much as the detection itself: see onset_delta.
        # `wait` is an additional refractory period, in frames.
        wait_frames = max(1, int(0.08 * sr / self.hop_length))
        onset_times = librosa.onset.onset_detect(
            y=y,
            sr=sr,
            hop_length=self.hop_length,
            backtrack=True,
            units="time",
            delta=self.onset_delta,
            wait=wait_frames,
        )
        onset_frames = nearest_frames(list(onset_times), list(times))

        notes = segment_notes(
            pitches=pitches,
            times=[float(t) for t in times],
            confidences=confidences,
            onset_indices=onset_frames,
            min_duration_s=self.min_note_s,
            min_confidence=self.min_confidence,
        )
        log.info(
            "pyin %s: %d notes from %d onsets over %.1fs",
            stem.value, len(notes), len(onset_frames), float(times[-1]) if len(times) else 0.0,
        )

        return Transcription(
            stem=stem, notes=notes, tempo_bpm=self._estimate_tempo(y, sr), backend=self.name
        )

    def _estimate_tempo(self, y, sr: int) -> float:
        import librosa
        import numpy as np

        try:
            onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
            tempo, _ = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
            value = float(np.atleast_1d(tempo)[0])
            return value if value > 0 else 120.0
        except Exception:
            log.debug("tempo estimation failed; falling back to 120 BPM")
            return 120.0
