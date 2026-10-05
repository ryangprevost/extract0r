"""The recordings a benchmark is run against, and where they came from.

**A benchmark with no stated provenance is a number nobody can argue with**, which sounds
like a strength and is the opposite of one. Six months from now the only question that
matters about an SDR of 6.1 dB is "on what?", and if the answer is not written down next
to it, the number cannot be reproduced, cannot be compared with the next model, and
cannot be defended to anybody who asks. So an eval set here is a folder *plus* a manifest
that says what the audio is, who owns it, and how to get it again.

**Why not just point at MUSDB18.** It is the right dataset and the card names it, and it
is also 22 GB, CC BY-NC-SA, and has to be accepted and downloaded by a person. The design
here is that MUSDB is *one possible* eval set rather than the only one, because the
fastest route to ground truth for this project is the one X0R-306 already identified:
record a few DI parts. A DI bass played against a click gives an exact reference stem and
an exact note list, costs twenty minutes, and sidesteps the licensing question entirely.
`describe_missing` is what tells somebody that.

**What a track can carry, and what each part is for:**

* `mixture` - the file the separator is run on. Required; everything else is optional, and
  a track with only a mixture still contributes a timing measurement.
* `stems/<name>.wav` - the ground-truth stems, named for `StemKind`. These give SDR, SIR
  and SAR. They have to sum to roughly the mixture, and the benchmark checks it with
  `metrics.reconstruction_db` before scoring anything: a stem set from a different mix or
  a different take scores the difference between two arrangements and reports it as
  separation error, which is a wrong answer that looks exactly like a right one.
* `drums/<kick|snare|cymbals|toms>.wav` - isolated drums, which give the **one number
  sprint 2 could not produce**: DrumSep's per-stem bleed, as SIR. Every per-drum finding
  currently carries a caveat saying some of what was measured may be another drum, and
  cannot say how much. This is how it learns to.
* `notes/<name>.csv` - `onset_s,offset_s,midi` per line, the ground truth for
  transcription. From a DI part this is exact; from a hand-written tab it is exact about
  pitch and approximate about time, and the manifest should say which.

Nothing in here reads audio. Loading is the caller's job, so this module stays importable
without soundfile and the manifest can be checked on a machine with no eval set on it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

MANIFEST = "manifest.json"

#: The four drums DrumSep returns. Named here rather than imported so this module does
#: not depend on the mastering package, which pulls numpy.
DRUM_NAMES = ("kick", "snare", "cymbals", "toms")

#: How far the ground-truth stems may sum away from the mixture before they are probably
#: not the stems *of* that mixture. Checked by the runner, which has the audio.
#:
#: Deliberately generous. A reference mix usually has bus compression and a limiter on it
#: that no sum of its stems reproduces, so a perfectly honest stem set can sit well above
#: a separator's own residual - this project's six Demucs stems reconstruct to about
#: -22 to -26 dB and a real multitrack can be worse. The point is to catch the wrong
#: take, not to audit somebody's mastering: above -12 dB the sum is a *different piece of
#: music*, not a differently mastered one.
SUM_TOLERANCE_DB = -12.0


@dataclass(slots=True)
class Track:
    """One recording and whatever ground truth came with it."""

    track_id: str
    mixture: Path
    #: Ground-truth stems by `StemKind` name.
    stems: dict[str, Path] = field(default_factory=dict)
    #: Isolated drums by DrumSep name, for the bleed measurement.
    drums: dict[str, Path] = field(default_factory=dict)
    #: Ground-truth note lists by stem name.
    notes: dict[str, Path] = field(default_factory=dict)
    seconds: float = 0.0
    #: Anything a reader needs to interpret this track's numbers: the tuning, whether the
    #: note times are exact or tabbed, whether the stems predate bus processing.
    caveats: list[str] = field(default_factory=list)

    @property
    def scores_separation(self) -> bool:
        # Two, because SIR is about the *other* sources and one stem has none.
        return len(self.stems) >= 2

    @property
    def scores_bleed(self) -> bool:
        return len(self.drums) >= 2

    @property
    def scores_transcription(self) -> bool:
        return bool(self.notes)


@dataclass(slots=True)
class EvalSet:
    """A folder of tracks, and the provenance without which they are not evidence."""

    name: str
    root: Path
    #: Where this audio came from, in enough detail to get it again.
    source: str = ""
    #: What license it carries, and therefore what may be done with it. A benchmark set
    #: that cannot be redistributed is still perfectly usable; one whose terms nobody
    #: wrote down is a problem waiting for somebody else.
    license: str = ""
    notes: str = ""
    tracks: list[Track] = field(default_factory=list)

    @property
    def total_seconds(self) -> float:
        return round(sum(t.seconds for t in self.tracks), 1)


def load(root: Path) -> EvalSet:
    """Read an eval set from a folder, by manifest where there is one and by convention
    where there is not.

    Convention alone is enough to run - a folder of `<track>/mixture.wav` and
    `<track>/stems/*.wav` works - but a set with no manifest gets an empty `source` and
    `license`, and the report says so rather than letting an unattributed number through
    looking like an attributed one.
    """
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"no eval set at {root}")

    data: dict = {}
    manifest = root / MANIFEST
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
    else:
        log.info("no %s in %s; reading by convention and leaving provenance empty",
                 MANIFEST, root)

    described = {entry.get("id"): entry for entry in data.get("tracks", []) if entry.get("id")}

    tracks: list[Track] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        mixture = _first(folder, ("mixture.wav", "mixture.flac", "mix.wav"))
        if mixture is None:
            log.info("skipping %s: no mixture file", folder.name)
            continue
        entry = described.get(folder.name, {})
        tracks.append(
            Track(
                track_id=folder.name,
                mixture=mixture,
                stems=_audio_in(folder / "stems"),
                drums={
                    name: path
                    for name, path in _audio_in(folder / "drums").items()
                    if name in DRUM_NAMES
                },
                notes={
                    path.stem: path
                    for path in sorted((folder / "notes").glob("*.csv"))
                },
                seconds=float(entry.get("seconds", 0.0)),
                caveats=list(entry.get("caveats", [])),
            )
        )

    return EvalSet(
        name=data.get("name") or root.name,
        root=root,
        source=data.get("source", ""),
        license=data.get("license", ""),
        notes=data.get("notes", ""),
        tracks=tracks,
    )


def _first(folder: Path, names) -> Path | None:
    for name in names:
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


def _audio_in(folder: Path) -> dict[str, Path]:
    if not folder.is_dir():
        return {}
    out: dict[str, Path] = {}
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() in (".wav", ".flac") and path.is_file():
            out[path.stem.lower()] = path
    return out


def read_notes(path: Path):
    """A ground-truth note list: `onset_s,offset_s,midi` per line.

    CSV rather than MIDI, deliberately. A MIDI file carries a tempo map, a resolution and
    a channel layout, and every one of those is a way for a ground truth to be subtly
    wrong about *when* a note happened. Three numbers per line can be checked by reading
    them, which is the property a reference needs most.

    A header line is tolerated, blank lines are skipped, and a malformed line is skipped
    with a log rather than raising - a reference with one bad row should cost that row.
    """
    from app.domain.notes import NoteEvent

    notes = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        try:
            onset, offset, midi = float(parts[0]), float(parts[1]), int(round(float(parts[2])))
        except (ValueError, IndexError):
            if number == 1:
                continue  # a header
            log.info("skipping line %d of %s: %r", number, path.name, line)
            continue
        notes.append(NoteEvent(start_s=onset, end_s=offset, pitch=midi))
    notes.sort(key=lambda n: (n.start_s, n.pitch))
    return notes


def describe_missing(eval_set: EvalSet | None) -> list[str]:
    """What this eval set cannot answer, and the shortest way to fix each one.

    Written as instructions rather than as complaints, because the reader is whoever has
    to go and record something, and "no transcription ground truth" is not an instruction.
    """
    if eval_set is None or not eval_set.tracks:
        return [
            "There is no eval set, so nothing here is a measurement of quality - only of "
            "speed. The fastest fix is not a dataset: record a DI bass and a DI guitar "
            "against a click, mix them with drums, and you have exact stems and exact "
            "notes in under an hour, with no license to accept.",
        ]

    missing: list[str] = []
    if not eval_set.source or not eval_set.license:
        missing.append(
            f"{MANIFEST} is missing `source` or `license`. A number whose provenance is "
            "not written next to it cannot be reproduced or defended later."
        )
    if not any(t.scores_separation for t in eval_set.tracks):
        missing.append(
            "No track has two or more ground-truth stems, so there is no SDR, SIR or "
            "SAR. Put the stems in `<track>/stems/<vocals|drums|bass|...>.wav`."
        )
    if not any(t.scores_transcription for t in eval_set.tracks):
        missing.append(
            "No track has a ground-truth note list, so there is no note F1 and no cents "
            "accuracy. Put one in `<track>/notes/<stem>.csv` as `onset_s,offset_s,midi`. "
            "A DI part played to a click gives this exactly."
        )
    if not any(t.scores_bleed for t in eval_set.tracks):
        missing.append(
            "No track has isolated drums, so DrumSep's per-stem bleed stays unmeasured - "
            "which is the figure every per-drum finding in sprint 2 is currently "
            "caveating without. Put close-miked kick, snare, cymbals and toms in "
            "`<track>/drums/`, or record four passes of one kit."
        )
    return missing
