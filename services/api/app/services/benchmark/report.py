"""Writing a benchmark down so it can be argued with later.

A result that lives in a terminal is a vibe with decimal places. The point of X0R-306 is
that a model or parameter change becomes a measurement, and a measurement is only a
measurement if the next person can tell what produced it - so every run writes two files
into `docs/benchmarks/`: a JSON for diffing against the next run, and a Markdown page for
reading.

**The header is not decoration.** Model, backend versions, commit, machine, and which
recordings - with a stated licence - are the difference between "Demucs scores 6.1 dB
here" and a number somebody can act on. Four of the card's criteria are about the
measurements and the fifth is about this.

**It says what it could not measure, loudly.** A benchmark that reports only what it
managed is the most dangerous kind: it looks complete. Every run prints the gaps, as
instructions, above the results - because the reader is the person who could close them.
"""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.services.benchmark.metrics import SeparationScore, Speed, TranscriptionScore


@dataclass(slots=True)
class TrackResult:
    track_id: str
    seconds: float
    separation: list[SeparationScore] = field(default_factory=list)
    #: SIR here is the bleed between DrumSep's four outputs, which is the figure sprint
    #: 2's per-drum findings caveat without.
    drums: list[SeparationScore] = field(default_factory=list)
    transcription: list[TranscriptionScore] = field(default_factory=list)
    speeds: list[Speed] = field(default_factory=list)
    #: How far the stems sum away from the mixture, in dB. Needs no ground truth, so it
    #: is the one quality figure every run has. `None` when it was not computed.
    reconstruction_db: float | None = None
    skipped: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BenchmarkRun:
    """One run of everything, with enough about the machine to reproduce it."""

    eval_set: str
    eval_source: str = ""
    eval_licence: str = ""
    separation_model: str = ""
    separation_backend: str = ""
    transcription_backend: str = ""
    versions: dict[str, str] = field(default_factory=dict)
    commit: str = ""
    machine: str = ""
    ran_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    tracks: list[TrackResult] = field(default_factory=list)
    #: What this run could not measure, and how to fix each one.
    gaps: list[str] = field(default_factory=list)


def describe_machine() -> str:
    cpu = platform.processor() or platform.machine()
    return f"{platform.system()} {platform.release()}, {cpu}, Python {platform.python_version()}"


def current_commit(repo: Path | None = None) -> str:
    """The commit the numbers were produced at, or a note that the tree was dirty.

    Dirty matters more than the hash does. A benchmark run against uncommitted work is
    not reproducible, and the honest thing is to say so in the file rather than to print
    a hash that does not describe what ran.
    """
    where = str(repo or Path(__file__).resolve().parents[4])
    try:
        head = subprocess.run(
            ["git", "-C", where, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if head.returncode != 0:
            return "not a git checkout"
        commit = head.stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", where, "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        return f"{commit} (working tree dirty)" if dirty.stdout.strip() else commit
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def backend_versions() -> dict[str, str]:
    """What was actually installed, which is what a future run has to match."""
    import importlib

    out: dict[str, str] = {}
    for name in ("demucs", "torch", "librosa", "mir_eval", "numpy", "onnxruntime", "soundfile"):
        try:
            module = importlib.import_module(name)
            out[name] = str(getattr(module, "__version__", "?"))
        except Exception:
            out[name] = "not installed"
    return out


# --- writing ---------------------------------------------------------------------------


def from_json(path: Path) -> BenchmarkRun:
    """Rebuild a run from the JSON it wrote, so the page can be regenerated.

    The reason this exists is not tidiness. The prose in `to_markdown` is part of the
    result - it is where a figure's limitations are stated - and improving it would
    otherwise mean either re-running hours of separation or hand-editing a generated
    file until it no longer matched its own template. Neither is acceptable for a record
    whose entire value is being trustworthy later.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tracks = []
    for track in data.pop("tracks", []):
        tracks.append(
            TrackResult(
                **{
                    **track,
                    "separation": [SeparationScore(**s) for s in track["separation"]],
                    "drums": [SeparationScore(**s) for s in track["drums"]],
                    "transcription": [
                        TranscriptionScore(**s) for s in track["transcription"]
                    ],
                    "speeds": [Speed(**s) for s in track["speeds"]],
                }
            )
        )
    return BenchmarkRun(**data, tracks=tracks)


def write(run: BenchmarkRun, directory: Path) -> tuple[Path, Path]:
    """A JSON for the next run to diff against, and a page for a person. Both, always."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # The model is part of the filename, not only of the header. Two runs of the same set
    # on different models is the commonest thing anybody does with this, and a name that
    # did not distinguish them would quietly overwrite the comparison being made.
    stamp = run.ran_at[:10]
    slug = _slug(run.eval_set) or "run"
    model = _slug(run.separation_model)
    base = f"{stamp}-{slug}" + (f"-{model}" if model else "")

    data = directory / f"{base}.json"
    data.write_text(json.dumps(asdict(run), indent=2), encoding="utf-8")
    page = directory / f"{base}.md"
    page.write_text(to_markdown(run), encoding="utf-8")
    return page, data


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in text).strip("-")


def to_markdown(run: BenchmarkRun) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"# Benchmark — {run.eval_set}")
    add("")
    add(f"**Ran:** {run.ran_at}  ")
    add(f"**Commit:** {run.commit}  ")
    add(f"**Machine:** {run.machine}  ")
    add(f"**Separation:** {run.separation_backend} `{run.separation_model}`  ")
    add(f"**Transcription:** {run.transcription_backend}  ")
    add(f"**Recordings:** {run.eval_source or '*not stated*'}  ")
    add(f"**Licence:** {run.eval_licence or '*not stated*'}")
    add("")
    add("| package | version |")
    add("|---|---|")
    for name, version in run.versions.items():
        add(f"| {name} | {version} |")
    add("")

    if run.gaps:
        add("## What this run could not measure")
        add("")
        add(
            "Above the results on purpose. A benchmark that reports only what it managed "
            "looks complete, and that is the most misleading thing it could do."
        )
        add("")
        for gap in run.gaps:
            add(f"- {gap}")
        add("")

    scored = [t for t in run.tracks if t.separation]
    if scored:
        add("## Separation — SDR, SIR, SAR")
        add("")
        add(
            "Higher is better, all in dB. **SDR** is overall distortion. **SIR** is how "
            "much of the other instruments leaked in. **SAR** is how much of the error is "
            "the model's own invention rather than leakage. A good SDR with a poor SIR is "
            "bleeding; a good SIR with a poor SAR is inventing, and they want opposite "
            "fixes."
        )
        add("")
        add("| track | stem | SDR | SIR | SAR | windows |")
        add("|---|---|---:|---:|---:|---:|")
        for track in scored:
            for score in track.separation:
                add(
                    f"| {track.track_id} | {score.stem} | {score.sdr_db:.2f} | "
                    f"{score.sir_db:.2f} | {score.sar_db:.2f} | {score.windows} |"
                )
        add("")
        add(_averages("Across every track", [s for t in scored for s in t.separation]))
        add("")

    bled = [t for t in run.tracks if t.drums]
    if bled:
        add("## Per-drum separation — the bleed figure")
        add("")
        add(
            "This is the number sprint 2 shipped without. Every per-drum finding carries "
            "a caveat saying some of what was measured may be another drum arriving late; "
            "**SIR is how much**. A kick at 12 dB SIR has a quarter of its energy coming "
            "from somewhere else, and a low-band finding on the snare should be read "
            "accordingly."
        )
        add("")
        add("| track | drum | SDR | SIR | SAR |")
        add("|---|---|---:|---:|---:|")
        for track in bled:
            for score in track.drums:
                add(
                    f"| {track.track_id} | {score.stem} | {score.sdr_db:.2f} | "
                    f"{score.sir_db:.2f} | {score.sar_db:.2f} |"
                )
        add("")

    transcribed = [t for t in run.tracks if t.transcription]
    if transcribed:
        add("## Transcription — notes and pitch")
        add("")
        add(
            "Onsets within 50 ms and pitches within 50 cents count as a match; offsets "
            "are **not** scored, because none of these backends claims to know when a "
            "note stopped. The octave-tolerant column folds every pitch into one octave "
            "first — the gap between the two columns *is* the octave-error rate, which is "
            "the classic pitch-tracker failure and is invisible in any single number. "
            "Cents error is measured over notes matched by onset alone, so it is not "
            "bounded by the pitch tolerance that produced the F1."
        )
        add("")
        add(
            "| track | stem | P | R | F1 | F1 (octave-tolerant) | ref | est "
            "| cents MAE | cents p95 |"
        )
        add("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for track in transcribed:
            for score in track.transcription:
                mae = "—" if score.cents_mae is None else f"{score.cents_mae:.1f}"
                p95 = "—" if score.cents_p95 is None else f"{score.cents_p95:.1f}"
                add(
                    f"| {track.track_id} | {score.stem} | {score.precision:.3f} | "
                    f"{score.recall:.3f} | {score.f1:.3f} | {score.f1_octave_tolerant:.3f} | "
                    f"{score.notes_reference} | {score.notes_estimated} | {mae} | {p95} |"
                )
        add("")

    rebuilt = [t for t in run.tracks if t.reconstruction_db is not None]
    if rebuilt:
        add("## Reconstruction — what separation lost")
        add("")
        add(
            "How far the stems sum away from the track they came out of. **More negative "
            "is better**: -25 dB means what the stems failed to account for sits 25 dB "
            "under the mixture. This needs no ground truth, which is why it is here on "
            "every run — and why it is the weaker question. A separator that put the "
            "whole bass in the vocals file would reconstruct the mixture perfectly and "
            "score well here. It bounds what was lost; SDR is what says whether the rest "
            "went in the right file."
        )
        add("")
        add("| track | residual |")
        add("|---|---:|")
        for track in rebuilt:
            add(f"| {track.track_id} | {track.reconstruction_db:.2f} dB |")
        add("")

    timed = [t for t in run.tracks if t.speeds]
    if timed:
        add("## Speed")
        add("")
        add(
            "As a multiple of real time, which is the only form anybody plans around. "
            "Above 1 is faster than the music."
        )
        add("")
        add(
            "**The first run of a model includes fetching its weights**, which is a "
            "download and not a separation. Run a model once before you time it."
        )
        add("")
        add(
            "**Read a small change as noise.** The same three-minute track and the same "
            "model came back at 1.09x and then 1.24x on this machine on one afternoon - "
            "a 14% spread, whose only cause was what else the laptop was doing. A speed "
            "result is worth acting on when it moves the figure by more than that. "
            "Reconstruction, by contrast, repeated to the decimal place, so a change "
            "there is real."
        )
        add("")
        add("| track | stage | audio | wall clock | × real time |")
        add("|---|---|---:|---:|---:|")
        for track in timed:
            for pace in track.speeds:
                add(
                    f"| {track.track_id} | {pace.label} | {pace.audio_seconds:.1f} s | "
                    f"{pace.wall_seconds:.1f} s | {pace.realtime_multiple:.2f}× |"
                )
        add("")
        for track in timed:
            for pace in track.speeds:
                for note in pace.notes:
                    add(f"- *{track.track_id} / {pace.label}:* {note}")
        add("")

    skipped = [(t.track_id, line) for t in run.tracks for line in t.skipped]
    if skipped:
        add("## Skipped")
        add("")
        for track_id, line in skipped:
            add(f"- **{track_id}** — {line}")
        add("")

    caveats = [(t.track_id, line) for t in run.tracks for line in t.caveats]
    if caveats:
        add("## Caveats carried by the recordings themselves")
        add("")
        for track_id, line in caveats:
            add(f"- **{track_id}** — {line}")
        add("")

    return "\n".join(lines).rstrip() + "\n"


def _averages(label: str, scores: list[SeparationScore]) -> str:
    """The mean of each column, which is what a model comparison actually looks at.

    The mean and not the median, unlike within a track: here every row is a different
    stem of a different song, and a median would quietly discard the stem a model is
    worst at — which is usually the one worth knowing about.
    """
    if not scores:
        return ""
    mean = lambda values: sum(values) / len(values)  # noqa: E731
    return (
        f"**{label}:** SDR {mean([s.sdr_db for s in scores]):.2f} dB · "
        f"SIR {mean([s.sir_db for s in scores]):.2f} dB · "
        f"SAR {mean([s.sar_db for s in scores]):.2f} dB, "
        f"over {len(scores)} stem(s)."
    )
