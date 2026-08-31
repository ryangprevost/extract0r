"""Polyphonic transcription via basic-pitch (CQT + neural net).

**Runs on the bundled ONNX model, not TensorFlow.** basic-pitch 0.4.0 declares a hard
`tensorflow<2.15.1` pin, and TensorFlow publishes nothing below 2.16 for Python 3.12, so
a plain `pip install basic-pitch` cannot resolve. The package ships ONNX and TFLite
weights alongside the TF SavedModel, and `ICASSP_2022_MODEL_PATH` resolves to the ONNX
file when TensorFlow is absent — so installing with `--no-deps` plus `onnxruntime` gives
a working, and considerably lighter, inference path. See docs/RUNBOOK.md.

Use this for guitar and piano. Bass and vocals are monophonic and are better served by
:class:`~app.services.transcription.pyin.PyinTranscriber`.

Imports are deferred to call time so the API still boots without any of it installed.
"""

from __future__ import annotations

from pathlib import Path

from app.domain.notes import NoteEvent, StemKind, Transcription


class BasicPitchTranscriber:
    name = "basic_pitch"

    def __init__(
        self,
        onset_threshold: float = 0.5,
        frame_threshold: float = 0.3,
        min_note_len_ms: float = 58.0,
        min_confidence: float = 0.35,
    ) -> None:
        self.onset_threshold = onset_threshold
        self.frame_threshold = frame_threshold
        self.min_note_len_ms = min_note_len_ms
        self.min_confidence = min_confidence

    def supports(self, stem: StemKind) -> bool:
        # Polyphonic model: worth its cost where several notes sound at once.
        return stem in (StemKind.GUITAR, StemKind.PIANO, StemKind.OTHER)

    def available(self) -> bool:
        try:
            from basic_pitch import ICASSP_2022_MODEL_PATH
            from basic_pitch.inference import predict  # noqa: F401
        except ImportError:
            return False
        # basic-pitch imports fine with no inference runtime at all; the model path is
        # what tells us whether one was actually resolved.
        return ICASSP_2022_MODEL_PATH is not None

    def transcribe(self, audio: Path, stem: StemKind) -> Transcription:
        from basic_pitch import ICASSP_2022_MODEL_PATH
        from basic_pitch.inference import predict

        _model_output, _midi_data, note_events = predict(
            str(audio),
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            onset_threshold=self.onset_threshold,
            frame_threshold=self.frame_threshold,
            minimum_note_length=self.min_note_len_ms,
        )

        notes: list[NoteEvent] = []
        for event in note_events:
            start_s, end_s, pitch, amplitude = event[0], event[1], event[2], event[3]
            if amplitude < self.min_confidence:
                continue
            notes.append(
                NoteEvent(
                    start_s=float(start_s),
                    end_s=float(end_s),
                    pitch=int(pitch),
                    velocity=max(1, min(127, int(amplitude * 127))),
                    confidence=float(amplitude),
                )
            )
        runtime = Path(str(ICASSP_2022_MODEL_PATH)).suffix.lstrip(".") or "savedmodel"
        return Transcription(stem=stem, notes=notes, backend=f"{self.name}:{runtime}")
