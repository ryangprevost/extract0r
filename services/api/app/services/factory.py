"""Backend selection, in one place.

Config names a backend; if its dependencies are missing we fall back to the stub and
say so loudly rather than 500-ing at the end of a two-minute job.
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.domain.notes import StemKind

log = logging.getLogger(__name__)


def make_separator(settings: Settings):
    if settings.separation_backend == "demucs":
        from app.services.separation.demucs import DemucsSeparator

        separator = DemucsSeparator(
            model=settings.demucs_model, device=settings.demucs_device
        )
        if separator.available():
            return separator
        log.warning("demucs requested but unavailable; falling back to the stub separator")

    from app.services.separation.stub import StubSeparator

    return StubSeparator()


def make_transcriber(settings: Settings, stem: StemKind):
    if stem is StemKind.DRUMS:
        if settings.drum_backend == "onset":
            from app.services.transcription.drums import OnsetDrumTranscriber

            transcriber = OnsetDrumTranscriber()
            if transcriber.available():
                return transcriber
            log.warning("librosa unavailable; falling back to the stub drum transcriber")
    elif settings.transcription_backend == "basic_pitch":
        from app.services.transcription.basic_pitch import BasicPitchTranscriber

        transcriber = BasicPitchTranscriber()
        if transcriber.available():
            return transcriber
        log.warning("basic-pitch unavailable; falling back to the stub transcriber")

    from app.services.transcription.stub import StubTranscriber

    return StubTranscriber()


def make_mastering_engine(settings: Settings):
    if settings.mastering_backend == "matchering":
        from app.services.mastering.matchering_engine import MatcheringEngine

        engine = MatcheringEngine()
        if engine.available():
            return engine
        log.warning("matchering unavailable; falling back to loudness-only matching")

    from app.services.mastering.loudness import LoudnessMatchEngine

    return LoudnessMatchEngine()
