"""The orchestration layer: stems in, tab files out.

Routes stay thin by delegating here; this module is where the actual product lives.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.domain.notes import Notation, StemKind
from app.domain.tab import ascii_tab, drum_tab
from app.domain.tab.fretboard import TUNINGS, SolverConfig, Tuning, solve
from app.domain.tab.x0r import Provenance, X0rStem, build, dumps
from app.services.factory import make_separator, make_transcriber
from app.services.separation.base import SeparationResult
from app.services.storage import TrackStorage

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


@dataclass(slots=True)
class TranscriptionBundle:
    track_id: str
    artifacts: list[TranscriptionArtifact]
    x0r_path: Path


def separate(track_id: str, storage: TrackStorage, settings: Settings) -> SeparationResult:
    source = storage.source_path(track_id)
    if source is None:
        raise FileNotFoundError(f"no source audio for track {track_id}")
    return make_separator(settings).separate(source, storage.stems_dir(track_id))


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
) -> TranscriptionBundle:
    """Transcribe each selected stem and write one .txt per stem plus one .x0r."""
    tuning_keys = tuning_keys or {}
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

        if notation is Notation.DRUM_TAB:
            shapes = ()
            text = drum_tab.render(
                result.sorted_notes(), tempo_bpm=result.tempo_bpm, title=title
            )
        else:
            shapes = solve(result.sorted_notes(), tuning, solver)
            text = ascii_tab.render(
                shapes, tuning, tempo_bpm=result.tempo_bpm, title=title
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
    x0r_path.write_text(dumps(build(provenance, x0r_stems)), encoding="utf-8")

    return TranscriptionBundle(track_id=track_id, artifacts=artifacts, x0r_path=x0r_path)
