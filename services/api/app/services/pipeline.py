"""The orchestration layer: stems in, tab files out.

Routes stay thin by delegating here; this module is where the actual product lives.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from app.config import Settings
from app.domain.notes import Notation, StemKind
from app.domain.tab import ascii_tab, drum_tab
from app.domain.tab.fretboard import TUNINGS, SolverConfig, Tuning, solve_with_report
from app.domain.tab.x0r import Provenance, X0rStem, build, dumps
from app.domain.timing import TimingEstimate
from app.services.audio.probe import AudioInfo, normalize, probe
from app.services.factory import make_separator, make_timing_analyser, make_transcriber
from app.services.separation.base import SeparationResult
from app.services.storage import TrackStorage

log = logging.getLogger(__name__)

# Which tuning we solve against when the user does not pick one.
DEFAULT_TUNING_FOR_STEM = {
    StemKind.BASS: "bass_standard",
    StemKind.GUITAR: "guitar_standard",
    StemKind.OTHER: "guitar_standard",
    StemKind.PIANO: "guitar_standard",
    StemKind.VOCALS: "guitar_standard",
}


@dataclass(slots=True)
class TranscriptionArtifact:
    stem: StemKind
    notation: Notation
    tab_text: str
    note_count: int
    tab_path: Path
    # Notes the instrument physically could not play, and notes moved by whole octaves
    # to make them playable. Surfaced so the UI can say why the tab is thinner than
    # the note count suggests.
    dropped_count: int = 0
    folded_count: int = 0


@dataclass(slots=True)
class TranscriptionBundle:
    track_id: str
    artifacts: list[TranscriptionArtifact]
    x0r_path: Path
    timing: TimingEstimate | None = None


def normalize_source(track_id: str, storage: TrackStorage) -> AudioInfo:
    """Decode the upload once into canonical 44.1 kHz stereo WAV.

    Every stage after this point can assume one format, which is why separation,
    transcription, and mixdown never have to think about codecs.
    """
    source = storage.source_path(track_id)
    if source is None:
        raise FileNotFoundError(f"no source audio for track {track_id}")
    target = storage.normalized_path(track_id)
    if target.exists():
        return probe(target)
    return normalize(source, target)


def separate(
    track_id: str,
    storage: TrackStorage,
    settings: Settings,
    on_progress: Callable[[float], None] | None = None,
) -> SeparationResult:
    normalize_source(track_id, storage)
    return make_separator(settings).separate(
        storage.normalized_path(track_id), storage.stems_dir(track_id), on_progress
    )


def apply_timing_overrides(
    timing: TimingEstimate,
    tempo_bpm: float | None = None,
    beats_per_bar: int | None = None,
) -> TimingEstimate:
    """Let the user correct detection. Their answer wins, and the source records that.

    Detection gets tempo octaves wrong often enough that overriding it is not an escape
    hatch, it is part of the normal workflow - and the person who wrote the song knows.
    """
    if tempo_bpm is None and beats_per_bar is None:
        return timing

    corrected = replace(
        timing,
        tempo_bpm=tempo_bpm if tempo_bpm is not None else timing.tempo_bpm,
        beats_per_bar=(
            beats_per_bar if beats_per_bar is not None else timing.beats_per_bar
        ),
    )
    # A user-set tempo is certain by definition, and the offset detected for the old
    # tempo no longer means anything.
    if tempo_bpm is not None:
        corrected.confidence = 1.0
        corrected.first_beat_s = 0.0
    corrected.source = f"user override (was {timing.tempo_bpm:.1f} BPM from {timing.source})"
    return corrected


def analyse_timing(
    track_id: str, storage: TrackStorage, settings: Settings
) -> TimingEstimate:
    """Tempo, metre, and key for the whole track, read from the full mix.

    Analysing the mix rather than each stem is the point: separate stems disagree about
    tempo, and a tab whose bars drift apart between instruments is worse than one that is
    uniformly a little off.
    """
    normalize_source(track_id, storage)
    return make_timing_analyser(settings).analyse(storage.normalized_path(track_id))


def resolve_tuning(stem: StemKind, tuning_key: str | None) -> Tuning | None:
    if not stem.is_pitched:
        return None
    key = tuning_key or DEFAULT_TUNING_FOR_STEM.get(stem, "guitar_standard")
    if key not in TUNINGS:
        raise KeyError(f"unknown tuning {key!r}; known: {', '.join(sorted(TUNINGS))}")
    return TUNINGS[key]


def transcribe(
    track_id: str,
    stems: Sequence[StemKind],
    storage: TrackStorage,
    settings: Settings,
    separation: SeparationResult,
    tuning_keys: dict[StemKind, str] | None = None,
    solver: SolverConfig | None = None,
    timing: TimingEstimate | None = None,
) -> TranscriptionBundle:
    """Transcribe each selected stem and write one .txt per stem plus one .x0r."""
    tuning_keys = tuning_keys or {}
    if timing is None:
        timing = analyse_timing(track_id, storage, settings)
    exports = storage.exports_dir(track_id)
    exports.mkdir(parents=True, exist_ok=True)

    source = storage.source_path(track_id)
    source_bytes = source.read_bytes() if source else b""

    artifacts: list[TranscriptionArtifact] = []
    x0r_stems: list[X0rStem] = []
    backends: set[str] = set()

    for stem in stems:
        separated = separation.by_kind(stem)
        if separated is None:
            raise KeyError(f"{stem.value} was not produced by {separation.backend}")

        transcriber = make_transcriber(settings, stem)
        backends.add(transcriber.name)
        result = transcriber.transcribe(separated.path, stem)

        notation = stem.default_notation
        tuning = resolve_tuning(stem, tuning_keys.get(stem))
        title = f"{stem.value.title()} - transcribed by Extract0r"

        # One grid for the whole track. The per-stem tempo a transcriber reports is
        # discarded on purpose - see analyse_timing.
        result.tempo_bpm = timing.tempo_bpm
        result.time_signature = timing.time_signature

        dropped = folded = 0
        if notation is Notation.DRUM_TAB:
            shapes = ()
            text = drum_tab.render(
                result.sorted_notes(),
                tempo_bpm=timing.tempo_bpm,
                title=title,
                time_signature=timing.time_signature,
                first_beat_s=timing.first_beat_s,
            )
        else:
            report = solve_with_report(result.sorted_notes(), tuning, solver)
            shapes, dropped, folded = (
                report.shapes,
                len(report.dropped),
                len(report.folded),
            )
            if dropped or folded:
                # Separation bleed makes this routine, not exceptional.
                log.info(
                    "%s: %d note(s) out of range for %s (%d dropped, %d octave-folded)",
                    stem.value, dropped + folded, tuning.name, dropped, folded,
                )
            text = ascii_tab.render(
                shapes,
                tuning,
                tempo_bpm=timing.tempo_bpm,
                title=title,
                time_signature=timing.time_signature,
                key_name=timing.key.name if timing.key else None,
                first_beat_s=timing.first_beat_s,
            )

        tab_path = exports / f"{stem.value}.txt"
        tab_path.write_text(text, encoding="utf-8")

        artifacts.append(
            TranscriptionArtifact(
                stem=stem,
                notation=notation,
                tab_text=text,
                note_count=len(result.notes),
                tab_path=tab_path,
                dropped_count=dropped,
                folded_count=folded,
            )
        )
        x0r_stems.append(
            X0rStem(
                stem=stem,
                notation=notation.value,
                tuning=tuning,
                transcription=result,
                shapes=shapes,
                rendered_tab=text,
            )
        )

    from app.domain.tab.x0r import sha256_of

    provenance = Provenance(
        source_filename=source.name if source else "unknown",
        source_sha256=sha256_of(source_bytes),
        separation_backend=f"{separation.backend}:{separation.model}",
        transcription_backend=",".join(sorted(backends)) or "none",
        app_version=settings.app_version,
    )
    x0r_path = exports / f"{track_id}.x0r"
    x0r_path.write_text(dumps(build(provenance, x0r_stems, timing)), encoding="utf-8")

    return TranscriptionBundle(
        track_id=track_id, artifacts=artifacts, x0r_path=x0r_path, timing=timing
    )
