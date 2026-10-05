"""X0R-306: run the real backends over an eval set and write down what happened.

    cd services/api
    ~/.x0r-venv/Scripts/python.exe tools/benchmark.py --eval-set <folder>

Not a test. It needs the ML extras, it runs Demucs end to end, and on a handful of
three-minute tracks it is a coffee break. It exists so that "is the separation any good"
and "did that change help" stop being questions anybody answers from memory.

**It will run with no eval set at all**, and that is deliberate rather than lenient. A
mixture with no ground truth still measures speed, and speed is a criterion. What it will
not do is let a run without ground truth *look* like a quality measurement: the report
leads with what could not be measured and how to fix it.

**Synthetic audio is not an eval set.** `tools/verify_pipeline.py` exists for wiring and
feeds Demucs sine waves it was never trained on; the first end-to-end run that way
returned a bass an octave high and a controlled check proved the transcriber was innocent.
Nothing in this file should ever be pointed at generated audio and reported as quality.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.domain.notes import StemKind  # noqa: E402
from app.services.benchmark import eval_set as eval_sets  # noqa: E402
from app.services.benchmark import metrics, report  # noqa: E402

log = logging.getLogger("benchmark")

DEFAULT_OUT = Path(__file__).resolve().parents[3] / "docs" / "benchmarks"


def _read(path: Path):
    from app.services.mixdown.encode import read_audio

    buffer = read_audio(Path(path))
    return buffer.samples, buffer.sample_rate


def _check_ground_truth(track, mixture, references: dict, result) -> None:
    """Do these stems actually belong to this mixture?

    The failure this catches is a wrong answer that looks exactly like a right one: a
    stem set exported from a different take, or from the mix before someone redid the
    chorus, scores the difference between two arrangements and reports it as separation
    error. Nothing downstream can tell those apart, and the number would be believed.

    A warning rather than a refusal, because the tolerance is a judgement and the
    operator may know something this does not.
    """
    residual = metrics.reconstruction_db(mixture, references)
    if residual > eval_sets.SUM_TOLERANCE_DB:
        result.skipped.append(
            f"the ground-truth stems sum to {residual:.1f} dB of the mixture, against a "
            f"{eval_sets.SUM_TOLERANCE_DB:.0f} dB tolerance - they may be from a "
            "different take or a different mix, in which case every SDR below is "
            "measuring the arrangement and not the separator"
        )


def _score_stems(track, produced: dict[str, Path], mixture, result) -> None:
    """Ground-truth stems against what the separator produced."""
    references, estimates, rates = {}, {}, set()
    for name, path in track.stems.items():
        if name not in produced:
            result.skipped.append(f"{name}: the separator produced no such stem")
            continue
        reference, rate_a = _read(path)
        estimate, rate_b = _read(produced[name])
        if rate_a != rate_b:
            # Resampling one side to score it would measure the resampler as well. A
            # mismatch is a problem with the eval set, and saying so is more use than
            # silently introducing a second variable.
            result.skipped.append(
                f"{name}: reference is {rate_a} Hz and the estimate {rate_b} Hz; "
                "re-render the reference at the separator's rate"
            )
            continue
        references[name], estimates[name] = reference, estimate
        rates.add(rate_a)

    if not references:
        return
    _check_ground_truth(track, mixture, references, result)
    scores, skipped = metrics.separation_scores(references, estimates)
    result.separation.extend(scores)
    result.skipped.extend(skipped)


def _score_drums(track, drums_stem: Path | None, settings: Settings, result) -> None:
    """DrumSep's four outputs against isolated drums - the bleed figure sprint 2 lacks."""
    if not track.scores_bleed:
        return
    if drums_stem is None:
        result.skipped.append("drums: the separator produced no drums stem to split")
        return

    from app.services.drums import separate as drumsep

    if not drumsep.available(settings.models_dir):
        result.skipped.append(f"drums: {drumsep.why_unavailable(settings.models_dir)}")
        return

    out = drums_stem.parent / "drumsep"
    started = time.perf_counter()
    produced = drumsep.separate(drums_stem, out, settings.models_dir)
    result.speeds.append(
        metrics.speed("per-drum separation", track.seconds, time.perf_counter() - started)
    )

    references, estimates = {}, {}
    for name, path in track.drums.items():
        if name not in produced:
            result.skipped.append(f"{name}: DrumSep produced no such drum")
            continue
        references[name], _ = _read(path)
        estimates[name], _ = _read(produced[name])

    if references:
        scores, skipped = metrics.separation_scores(references, estimates)
        result.drums.extend(scores)
        result.skipped.extend(skipped)


def _score_notes(track, produced: dict[str, Path], settings: Settings, result) -> None:
    """Ground-truth notes against what the transcriber heard in the *separated* stem.

    Through the separation on purpose. Scoring a transcriber against a clean DI measures
    the transcriber; scoring it against the separated stem measures what a user actually
    gets, which is the two stacked. Both are worth knowing and only the second is what
    this product does.
    """
    from app.services.factory import make_transcriber

    for name, notes_path in track.notes.items():
        try:
            kind = StemKind(name)
        except ValueError:
            result.skipped.append(f"{name}: not a stem this project knows about")
            continue
        if name not in produced:
            result.skipped.append(f"{name}: no separated stem to transcribe")
            continue

        reference_notes = eval_sets.read_notes(notes_path)
        transcriber = make_transcriber(settings, kind)
        started = time.perf_counter()
        transcription = transcriber.transcribe(produced[name], kind)
        result.speeds.append(
            metrics.speed(
                f"transcribe {name} ({transcriber.name})",
                track.seconds,
                time.perf_counter() - started,
            )
        )
        result.transcription.append(
            metrics.transcription_score(name, reference_notes, list(transcription.notes))
        )


def run_track(track, settings: Settings, work: Path) -> report.TrackResult:
    from app.services.factory import make_separator

    result = report.TrackResult(
        track_id=track.track_id, seconds=track.seconds, caveats=list(track.caveats)
    )

    samples, rate = _read(track.mixture)
    if not track.seconds:
        track.seconds = round(len(samples) / rate, 2)
        result.seconds = track.seconds

    separator = make_separator(settings)
    if not getattr(separator, "name", "") or separator.name == "stub":
        result.skipped.append(
            "the stub separator is in use, so nothing here measures Demucs. Run from an "
            "interpreter with demucs and torch installed."
        )

    out = work / track.track_id
    started = time.perf_counter()
    separated = separator.separate(track.mixture, out)
    elapsed = time.perf_counter() - started
    result.speeds.append(metrics.speed("separation", track.seconds, elapsed))

    produced = {stem.kind.value: Path(stem.path) for stem in separated.stems}

    # Needs nothing but the mixture and what came out of it, so it is computed on every
    # track including the ones with no ground truth at all.
    try:
        result.reconstruction_db = metrics.reconstruction_db(
            samples, {name: _read(path)[0] for name, path in produced.items()}
        )
    except Exception as failure:
        result.skipped.append(f"reconstruction could not be measured: {failure}")

    _score_stems(track, produced, samples, result)
    _score_drums(track, produced.get("drums"), settings, result)
    _score_notes(track, produced, settings, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-set", type=Path, help="folder of tracks; see eval_set.py")
    parser.add_argument("--work", type=Path, help="where to put separated stems")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write")
    parser.add_argument("--track", action="append", help="only these track ids")
    parser.add_argument("--model", help="override the demucs model")
    parser.add_argument("--backend", default="demucs", help="demucs | stub")
    parser.add_argument(
        "--render",
        type=Path,
        help="re-render an earlier run's .md from its .json, separating nothing",
    )
    parser.add_argument(
        "--transcription", default="auto", help="auto | pyin | basic_pitch | stub"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.render:
        # The prose in the report is part of the result - it is where a figure's limits
        # are stated - so improving it has to be possible without re-running hours of
        # separation or hand-editing a generated file.
        earlier = report.from_json(args.render)
        page, _ = report.write(earlier, args.render.parent)
        print(f"re-rendered {page}")
        return 0

    # The real backends, not the configured ones. `Settings` defaults both to the stub
    # because that is right for a dev server with no ML extras - and a benchmark that
    # silently measured the stub and wrote the numbers to `docs/benchmarks/` is precisely
    # the failure this card exists to stop. `--backend stub` is there for testing the
    # harness itself, and the report says which ran.
    overrides = {
        "_env_file": None,
        "separation_backend": args.backend,
        "transcription_backend": args.transcription,
    }
    if args.model:
        overrides["demucs_model"] = args.model
    settings = Settings(**overrides)

    loaded = None
    if args.eval_set:
        loaded = eval_sets.load(args.eval_set)
        print(f"{loaded.name}: {len(loaded.tracks)} track(s), {loaded.total_seconds} s")
    else:
        print("no --eval-set: this run measures speed and nothing else")

    run = report.BenchmarkRun(
        eval_set=loaded.name if loaded else "no eval set",
        eval_source=loaded.source if loaded else "",
        eval_licence=loaded.licence if loaded else "",
        separation_model=settings.demucs_model,
        separation_backend=settings.separation_backend,
        transcription_backend=settings.transcription_backend,
        versions=report.backend_versions(),
        commit=report.current_commit(),
        machine=report.describe_machine(),
        gaps=eval_sets.describe_missing(loaded),
    )

    work = args.work or (Path(args.out) / "_work")
    work.mkdir(parents=True, exist_ok=True)

    tracks = loaded.tracks if loaded else []
    if args.track:
        tracks = [t for t in tracks if t.track_id in set(args.track)]

    for track in tracks:
        print(f"\n--- {track.track_id} ({track.seconds or '?'} s) ---")
        try:
            result = run_track(track, settings, work)
        except Exception as failure:  # one bad track should not lose the whole run
            log.warning("%s failed: %s", track.track_id, failure, exc_info=True)
            run.tracks.append(
                report.TrackResult(
                    track_id=track.track_id,
                    seconds=track.seconds,
                    skipped=[f"the run failed: {failure}"],
                )
            )
            continue
        run.tracks.append(result)
        # Loud, and on stdout, not only in the file. Somebody who ran this from the wrong
        # interpreter needs to know before they read the numbers, not after.
        for line in result.skipped:
            if "stub separator" in line:
                print(f"   !! {line}")
        for score in result.separation:
            print(f"   {score.stem:8s} SDR {score.sdr_db:7.2f}  SIR {score.sir_db:7.2f}"
                  f"  SAR {score.sar_db:7.2f}")
        for score in result.transcription:
            print(f"   {score.stem:8s} F1 {score.f1:.3f} (octave-tolerant "
                  f"{score.f1_octave_tolerant:.3f})")
        for pace in result.speeds:
            print(f"   {pace.label}: {pace.wall_seconds:.1f} s "
                  f"= {pace.realtime_multiple:.2f}x real time")

    page, data = report.write(run, args.out)
    print(f"\nwrote {page}")
    print(f"      {data}")
    if run.gaps:
        print("\nwhat this run could not measure:")
        for gap in run.gaps:
            print(f"  - {gap}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
