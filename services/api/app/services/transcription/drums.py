"""Drum transcription: onset detection plus a band-energy classifier.

Drums have no pitch to track, so instead we find attacks with a spectral-flux onset
detector and classify each one by where its energy sits. Crude next to a trained
model, but it runs anywhere librosa does and it is a real baseline to beat.
"""

from __future__ import annotations

from pathlib import Path

from app.domain.notes import NoteEvent, StemKind, Transcription

# (label, MIDI key, low Hz, high Hz) - bands chosen to separate kick / snare / cymbals.
BANDS = (
    ("kick", 36, 20.0, 120.0),
    ("snare", 38, 150.0, 700.0),
    ("hihat", 42, 5000.0, 14000.0),
)

# Below this share of an onset's total band energy, we assume the hit was bleed.
MIN_BAND_SHARE = 0.25


class OnsetDrumTranscriber:
    name = "onset_drums"

    def __init__(self, hop_length: int = 512, hit_length_s: float = 0.03) -> None:
        self.hop_length = hop_length
        self.hit_length_s = hit_length_s

    def supports(self, stem: StemKind) -> bool:
        return stem is StemKind.DRUMS

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

        y, sr = librosa.load(str(audio), sr=None, mono=True)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=self.hop_length)
        frames = librosa.onset.onset_detect(
            onset_envelope=onset_env, sr=sr, hop_length=self.hop_length, backtrack=True
        )
        times = librosa.frames_to_time(frames, sr=sr, hop_length=self.hop_length)
        tempo, _beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)

        spectrum = np.abs(librosa.stft(y, hop_length=self.hop_length))
        freqs = librosa.fft_frequencies(sr=sr)

        notes: list[NoteEvent] = []
        for time_s, frame in zip(times, frames, strict=False):
            column = spectrum[:, min(int(frame), spectrum.shape[1] - 1)]
            energies = {
                key: float(column[(freqs >= lo) & (freqs < hi)].sum())
                for _label, key, lo, hi in BANDS
            }
            total = sum(energies.values()) or 1.0
            for key, energy in energies.items():
                share = energy / total
                if share < MIN_BAND_SHARE:
                    continue
                notes.append(
                    NoteEvent(
                        start_s=float(time_s),
                        end_s=float(time_s) + self.hit_length_s,
                        pitch=key,
                        velocity=max(1, min(127, int(share * 160))),
                        confidence=share,
                    )
                )

        return Transcription(
            stem=stem, notes=notes, tempo_bpm=float(np.atleast_1d(tempo)[0]), backend=self.name
        )
