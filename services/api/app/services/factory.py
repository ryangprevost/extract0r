"""Backend selection, in one place.

Config names a backend; if its dependencies are missing we fall back to the stub and say
so loudly rather than 500-ing at the end of a two-minute job.

The transcription choice is per-stem, not global, because the right tool genuinely
differs: a bass line is monophonic and pYIN beats a polyphonic neural net on it, while a
guitar chord needs basic-pitch. `TRANSCRIPTION_BACKEND=auto` is what you want.
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.domain.notes import StemKind

log = logging.getLogger(__name__)

# Stems where only one note sounds at a time, so a monophonic tracker is the better tool.
MONOPHONIC_STEMS = (StemKind.BASS, StemKind.VOCALS)


def make_separator(settings: Settings):
    if settings.separation_backend == "demucs":
        from app.services.separation.demucs import DemucsSeparator

        separator = DemucsSeparator(
            model=settings.demucs_model,
            device=settings.demucs_device,
            jobs=settings.demucs_jobs,
            overlap=settings.demucs_overlap,
        )
        if separator.available():
            return separator
        log.warning("demucs requested but unavailable; falling back to the stub separator")

    from app.services.separation.stub import StubSeparator

    return StubSeparator()


def _stub_transcriber():
    from app.services.transcription.stub import StubTranscriber

    return StubTranscriber()


def _drum_transcriber(settings: Settings):
    if settings.drum_backend != "onset":
        return _stub_transcriber()

    from app.services.transcription.drums import OnsetDrumTranscriber

    transcriber = OnsetDrumTranscriber()
    if transcriber.available():
        return transcriber
    log.warning("librosa unavailable; falling back to the stub drum transcriber")
    return _stub_transcriber()


def _pitched_transcriber(settings: Settings, stem: StemKind):
    choice = settings.transcription_backend
    if choice == "stub":
        return _stub_transcriber()

    from app.services.transcription.basic_pitch import BasicPitchTranscriber
    from app.services.transcription.pyin import PyinTranscriber

    prefer_mono = choice == "pyin" or (choice == "auto" and stem in MONOPHONIC_STEMS)
    ordered = (
        (PyinTranscriber(), BasicPitchTranscriber())
        if prefer_mono
        else (BasicPitchTranscriber(), PyinTranscriber())
    )

    for transcriber in ordered:
        if transcriber.available() and transcriber.supports(stem):
            return transcriber

    log.warning(
        "no pitched transcriber available for %s (wanted %r); using the stub",
        stem.value,
        choice,
    )
    return _stub_transcriber()


def make_transcriber(settings: Settings, stem: StemKind):
    if stem is StemKind.DRUMS:
        return _drum_transcriber(settings)
    return _pitched_transcriber(settings, stem)


def make_timing_analyser(settings: Settings):
    """Tempo/metre/key analysis for the full mix."""
    if settings.timing_backend == "librosa":
        from app.services.analysis.timing import TimingAnalyser

        analyser = TimingAnalyser()
        if analyser.available():
            return analyser
        log.warning("librosa unavailable; timing falls back to a fixed 120 BPM")

    from app.services.analysis.timing import StubTimingAnalyser

    return StubTimingAnalyser()


def make_mastering_engine(settings: Settings):
    if settings.mastering_backend == "matchering":
        from app.services.mastering.matchering_engine import MatcheringEngine

        engine = MatcheringEngine()
        if engine.available():
            return engine
        log.warning("matchering unavailable; falling back to loudness-only matching")

    from app.services.mastering.loudness import LoudnessMatchEngine

    return LoudnessMatchEngine()
