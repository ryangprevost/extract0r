"""Pick up the tracks already on disk, so a restart does not strand them.

X0R-1423, and Ryan found it the hard way: he uploaded a song and a reference, waited
through both separations and the per-drum pass, and the API was stopped out from under him.
Every file survived. Nothing could reach any of them, because the registry is in memory and
has never looked at `storage/`, so `GET /tracks/{id}/stems` answered "Unknown track." for a
directory holding six stems, six reference stems and four drums. The retention sweep would
eventually have deleted it unread.

### This is deliberately not EPIC-07

That non-goal is persistence as a *feature* - sessions, accounts, a database, work resumed
days later - and nothing here moves toward it. No new file is written, no format is
invented, and nothing is remembered that was not already sitting on the filesystem. **The
directory layout already is the record**; this only reads it back.

The distinction that makes it worth doing anyway: a tool is allowed not to remember. It is
not really allowed to write a person's audio to disk, lose the only pointer to it, and then
delete it.

### What cannot be recovered, and why that is fine

An adopted record is thinner than one built by an upload:

* **the attestation** - who claimed what rights at upload. Recorded as adopted rather than
  invented, because fabricating a rights claim would be worse than any inconvenience it
  avoids. Routes that need a fresh claim can still ask for one.
* **`audio`** - the probe. Cheap to redo and nothing needs it to list stems.
* **`timing`** - re-measured on demand by whatever wants it.
* **`reference_profile`** - a profile a track was aimed at. Not on disk at all, and
  deliberately not guessed: aiming at the wrong record silently is the exact failure
  X0R-1420 was about.

What *is* recovered is the expensive half - every separation, which is minutes of CPU each -
and that is the whole point.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.domain.notes import StemKind
from app.services.registry import TrackRecord, TrackRegistry
from app.services.separation.base import SeparatedStem, SeparationResult
from app.services.storage import StoredTrack

log = logging.getLogger(__name__)

#: A track id is a 32-character hex uuid. Anything else in `storage/` is not ours and is
#: left alone - a stray folder should cost nothing, not an exception at boot.
ID_LENGTH = 32


def _stems_under(directory: Path) -> tuple[dict[StemKind, Path], str, str]:
    """Every stem in `stems/<backend>/<name>/`, with the backend and model that made it.

    The layout carries both: `stems/htdemucs_6s/source.normalized/bass.wav` says which
    model ran as surely as a database row would, which is the sense in which the directory
    is already the record.
    """
    found: dict[StemKind, Path] = {}
    model = ""
    for path in directory.rglob("*.wav"):
        try:
            kind = StemKind(path.stem)
        except ValueError:
            continue
        found[kind] = path
        if not model:
            # stems/<model>/<name>/x.wav - the model is two levels up from the file.
            model = path.parent.parent.name
    return found, "adopted", model


def _separation_from(found: dict[StemKind, Path]) -> SeparationResult | None:
    """Rebuild a `SeparationResult` without opening the audio.

    Sample rate and duration are left at zero rather than probed. Reading six files to fill
    in two numbers would turn a boot-time scan into a boot-time wait, and every route that
    needs either reads the file itself anyway - `_stem_path` and `profile_all` both take
    paths, not these fields.
    """
    if not found:
        return None
    stems = tuple(
        SeparatedStem(kind=kind, path=path, sample_rate=0, duration_s=0.0)
        for kind, path in sorted(found.items(), key=lambda pair: pair[0].value)
    )
    return SeparationResult(stems=stems, backend="adopted", model="")


def adopt_one(directory: Path) -> TrackRecord | None:
    """One track directory, as much of it as the filesystem can tell us.

    None when there is nothing worth adopting - no source audio means no track, whatever
    else happens to be in the folder.
    """
    track_id = directory.name
    source = next(
        (p for p in directory.glob("source.*") if p.name != "source.normalized.wav"), None
    )
    normalised = directory / "source.normalized.wav"
    if source is None and not normalised.exists():
        return None

    path = source or normalised
    stems, _backend, _model = _stems_under(directory / "stems")
    reference_stems, _, _ = _stems_under(directory / "reference_stems")

    drum_stems: dict[str, dict[str, str]] = {}
    for side in ("source", "reference"):
        side_dir = directory / "drum_stems" / side
        if not side_dir.is_dir():
            continue
        drums = {p.stem: str(p) for p in side_dir.rglob("*.wav")}
        if drums:
            drum_stems[side] = drums

    reference = next((p for p in directory.glob("reference.*")), None)

    return TrackRecord(
        stored=StoredTrack(
            track_id=track_id,
            path=path,
            # The upload's own name is not on disk. Said plainly rather than guessed from
            # the extension, so nothing downstream reports a filename nobody chose.
            original_filename=path.name,
            sha256="",
            size_bytes=path.stat().st_size if path.exists() else 0,
        ),
        # Adopted, not claimed. Fabricating a rights attestation would be worse than any
        # inconvenience it saves.
        attestation={"adopted": True},
        separation=_separation_from(stems),
        reference_stems=dict(reference_stems),
        drum_stems=drum_stems,
        reference_name=reference.name if reference else "",
    )


def adopt_all(storage_root: Path, registry: TrackRegistry) -> int:
    """Every track directory under `storage_root` that is not already known.

    Never raises. A boot that fails because one folder is odd is a worse outcome than a
    boot that adopts the other nine and logs the tenth.
    """
    root = Path(storage_root)
    if not root.is_dir():
        return 0

    adopted = 0
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or len(directory.name) != ID_LENGTH:
            continue
        if registry.get(directory.name) is not None:
            continue
        try:
            record = adopt_one(directory)
        except Exception:
            log.info("could not adopt %s", directory.name, exc_info=True)
            continue
        if record is None:
            continue
        registry.add(record)
        adopted += 1

    if adopted:
        log.info("adopted %d track(s) already on disk", adopted)
    return adopted
