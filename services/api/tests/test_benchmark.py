"""Proving the ruler, which is the one job synthetic audio is right for.

X0R-306 exists because sprint 1 finished with every backend running and no idea whether
any of it was accurate, and its central lesson is that **synthetic audio cannot measure
quality** - it exercises the wiring and nothing else. That lesson is about measuring a
*model*. Measuring a *metric* is the opposite case: a signal whose SDR is known by
construction is exactly what proves `separation_scores` reports it, and Demucs has
nothing to do with the question.

So every number in this file is one that can be worked out on paper. If a test here says
SIR should be 20 dB, it is because the interference was mixed in at a tenth of the
amplitude, and twenty times the base-ten log of ten is twenty.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.domain.notes import NoteEvent
from app.services.benchmark import eval_set as eval_sets
from app.services.benchmark import metrics, report

SR = 44100

# The separation and transcription metrics are mir_eval's, and it is listed in
# requirements-dev.txt for exactly this reason - the ruler should be covered by an
# ordinary test run. Guarded anyway, because a venv built before that line existed should
# skip these rather than error, and because `requirements.txt` (the serving path) does
# not and should not carry it.
try:  # noqa: SIM105
    import mir_eval  # noqa: F401

    HAVE_MIR_EVAL = True
except ImportError:  # pragma: no cover - depends on the venv, not on the code
    HAVE_MIR_EVAL = False

needs_mir_eval = pytest.mark.skipif(
    not HAVE_MIR_EVAL, reason="mir_eval is in requirements-dev.txt; pip install it"
)


def _noise(seconds: float = 4.0, amplitude: float = 0.3, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, amplitude, int(SR * seconds))


def _note(start: float, pitch: int, length: float = 0.25) -> NoteEvent:
    return NoteEvent(start_s=start, end_s=start + length, pitch=pitch)


# --- SDR, SIR, SAR: numbers that can be checked on paper --------------------------------


@needs_mir_eval
def test_a_perfect_separation_scores_enormously_and_not_infinitely():
    """The sanity check the whole file rests on. Estimates identical to the references
    leave no error to divide by, so the ratio is bounded only by float precision - and a
    metric that returned something modest here would be measuring the wrong thing."""
    a, b = _noise(seed=1), _noise(seed=2)
    scores, skipped = metrics.separation_scores({"a": a, "b": b}, {"a": a, "b": b})
    assert not skipped
    assert all(s.sdr_db > 100 for s in scores), [(s.stem, s.sdr_db) for s in scores]


@needs_mir_eval
def test_a_tenth_of_the_other_source_measures_twenty_decibels_of_interference():
    """The number this project needs most, with an answer known in advance.

    `a` is handed back with a tenth of `b` mixed into it. A tenth of the amplitude is
    -20 dB, so SIR must be 20 dB - and SAR must stay enormous, because nothing was
    invented, only leaked. The two moving independently is the whole reason both are
    reported.
    """
    a, b = _noise(seed=3), _noise(seed=4)
    scores, _ = metrics.separation_scores({"a": a, "b": b}, {"a": a + 0.1 * b, "b": b})
    bled = next(s for s in scores if s.stem == "a")

    assert bled.sir_db == pytest.approx(20.0, abs=0.5)
    assert bled.sar_db > 100, "nothing was invented, so artefacts should be negligible"
    assert bled.sdr_db == pytest.approx(20.0, abs=0.5)


@needs_mir_eval
def test_interference_and_artefacts_are_told_apart():
    """A good SDR with a poor SIR is bleeding; a good SIR with a poor SAR is inventing.
    They want opposite fixes, so a metric that could not tell them apart would be worse
    than useless - it would point at the wrong repair."""
    a, b = _noise(seed=5), _noise(seed=6)
    invented = _noise(seed=7)

    leaking, _ = metrics.separation_scores({"a": a, "b": b}, {"a": a + 0.1 * b, "b": b})
    inventing, _ = metrics.separation_scores(
        {"a": a, "b": b}, {"a": a + 0.1 * invented, "b": b}
    )
    leaked = next(s for s in leaking if s.stem == "a")
    made_up = next(s for s in inventing if s.stem == "a")

    assert leaked.sir_db < leaked.sar_db - 50, "leakage should show up as interference"
    assert made_up.sar_db < made_up.sir_db - 20, "noise should show up as artefacts"


@needs_mir_eval
def test_the_assignment_of_estimates_to_references_is_not_searched():
    """BSS Eval will by default try every permutation and keep the best, which is right
    for blind separation and wrong here. A model that put source `a` in the `b` file has
    failed, and a benchmark that silently un-swapped them would say it had not."""
    a, b = _noise(seed=8), _noise(seed=9)
    swapped, _ = metrics.separation_scores({"a": a, "b": b}, {"a": b, "b": a})
    assert all(s.sdr_db < 1.0 for s in swapped), [(s.stem, s.sdr_db) for s in swapped]


@needs_mir_eval
def test_a_silent_reference_is_named_rather_than_scored():
    """Digital silence gives BSS Eval nothing to project onto. Dropping it is right;
    dropping it quietly would mean a report claiming six stems and scoring four."""
    a, b = _noise(seed=10), _noise(seed=11)
    scores, skipped = metrics.separation_scores(
        {"a": a, "b": b, "silent": np.zeros_like(a)},
        {"a": a, "b": b, "silent": np.zeros_like(a)},
    )
    assert {s.stem for s in scores} == {"a", "b"}
    assert any("silent" in line and "undefined" in line for line in skipped), skipped


@needs_mir_eval
def test_a_stem_the_separator_never_produced_is_named():
    a, b = _noise(seed=12), _noise(seed=13)
    _, skipped = metrics.separation_scores({"a": a, "b": b, "piano": a}, {"a": a, "b": b})
    assert any("piano" in line for line in skipped), skipped


@needs_mir_eval
def test_one_source_alone_is_refused_because_sir_would_be_meaningless():
    """With no other sources there is no interference, and mir_eval returns infinity - a
    number that reads as a perfect result rather than as a missing comparison."""
    scores, skipped = metrics.separation_scores({"a": _noise(seed=14)}, {"a": _noise(seed=14)})
    assert scores == []
    assert any("at least two" in line for line in skipped), skipped


@needs_mir_eval
def test_stereo_is_folded_to_mono_rather_than_refused():
    """Every stem in this project is stereo. The fold is a stated decision, not an
    accident, and this is where it is stated in code."""
    mono_a, mono_b = _noise(seed=15), _noise(seed=16)
    stereo = lambda x: np.stack([x, x], axis=1)  # noqa: E731
    scores, skipped = metrics.separation_scores(
        {"a": stereo(mono_a), "b": stereo(mono_b)},
        {"a": stereo(mono_a), "b": stereo(mono_b)},
    )
    assert not skipped and len(scores) == 2


@needs_mir_eval
def test_a_long_signal_is_scored_in_windows_and_the_median_reported():
    """BSS Eval's cost grows with the square of the length. Thirty-second windows are
    what SiSEC uses; this asserts the harness actually took that path rather than
    quietly spending minutes on one projection."""
    a, b = _noise(seconds=70, seed=17), _noise(seconds=70, seed=18)
    scores, _ = metrics.separation_scores({"a": a, "b": b}, {"a": a + 0.1 * b, "b": b})
    assert scores[0].windows > 1
    assert next(s for s in scores if s.stem == "a").sir_db == pytest.approx(20.0, abs=1.0)


# --- notes ---------------------------------------------------------------------------


@needs_mir_eval
def test_a_perfect_transcription_scores_one():
    notes = [_note(0.0, 40), _note(0.5, 45), _note(1.0, 47)]
    score = metrics.transcription_score("bass", notes, list(notes))
    assert score.f1 == 1.0 and score.precision == 1.0 and score.recall == 1.0
    assert score.cents_mae == 0.0


@needs_mir_eval
def test_the_octave_tolerant_score_is_where_an_octave_error_shows_up():
    """The classic pitch-tracker failure, and the reason two columns are reported rather
    than one. Sprint 1's first end-to-end run returned a bass line an octave high; a
    single F1 would have called that a total failure and said nothing about why."""
    truth = [_note(0.0, 40), _note(0.5, 45), _note(1.0, 47)]
    an_octave_up = [_note(0.0, 52), _note(0.5, 57), _note(1.0, 59)]

    score = metrics.transcription_score("bass", truth, an_octave_up)
    assert score.f1 == 0.0, "an octave out is a wrong note"
    assert score.f1_octave_tolerant == 1.0, "and it is exactly an octave out"


@needs_mir_eval
def test_the_two_scores_agree_when_the_errors_are_not_octaves():
    """The other half of the pair, so the test above proves a distinction rather than
    that folding makes everything match."""
    truth = [_note(0.0, 40), _note(0.5, 45)]
    wrong = [_note(0.0, 41), _note(0.5, 46)]
    score = metrics.transcription_score("bass", truth, wrong)
    assert score.f1 == 0.0 and score.f1_octave_tolerant == 0.0


@needs_mir_eval
def test_a_missed_note_costs_recall_and_an_invented_one_costs_precision():
    truth = [_note(0.0, 40), _note(0.5, 45)]

    missed = metrics.transcription_score("bass", truth, [_note(0.0, 40)])
    assert missed.recall == 0.5 and missed.precision == 1.0

    invented = metrics.transcription_score(
        "bass", truth, [_note(0.0, 40), _note(0.5, 45), _note(1.0, 47)]
    )
    # Rounded to four places on the way out, so the tolerance is the rounding.
    assert invented.recall == 1.0
    assert invented.precision == pytest.approx(2 / 3, abs=5e-5)


@needs_mir_eval
def test_offsets_are_not_scored():
    """None of these backends claims to know when a note stopped - pYIN's offsets come
    from a voicing decision and basic-pitch's from a threshold. Scoring them would drag
    every F1 down by a constant nobody could act on."""
    truth = [_note(0.0, 40, length=1.0)]
    same_onset_different_length = [_note(0.0, 40, length=0.05)]
    assert metrics.transcription_score("bass", truth, same_onset_different_length).f1 == 1.0


@needs_mir_eval
def test_cents_accuracy_is_not_bounded_by_the_pitch_tolerance_that_produced_the_f1():
    """The subtle one, and the reason `_cents` exists as its own function.

    Matching on pitch and then measuring pitch is circular: the answer can never exceed
    the tolerance, so it always looks reassuring. These notes are a whole semitone out -
    100 cents, twice the 50-cent matching tolerance - and the F1 is correctly zero while
    the cents figure correctly reports 100. An implementation that took its matches from
    the F1 would report nothing at all here, which is the bug this guards.
    """
    truth = [_note(0.0, 40), _note(0.5, 45)]
    sharp = [_note(0.0, 41), _note(0.5, 46)]

    score = metrics.transcription_score("bass", truth, sharp)
    assert score.f1 == 0.0
    assert score.matched_notes == 2
    assert score.cents_mae == pytest.approx(100.0, abs=0.5)


@needs_mir_eval
def test_cents_is_none_rather_than_zero_when_nothing_lined_up():
    """Zero would read as perfect pitch. The distinction matters most in exactly the case
    where the transcriber found nothing at the right time."""
    truth = [_note(0.0, 40)]
    much_later = [_note(9.0, 40)]
    score = metrics.transcription_score("bass", truth, much_later)
    assert score.cents_mae is None and score.matched_notes == 0


@needs_mir_eval
def test_an_empty_estimate_scores_zero_without_raising():
    score = metrics.transcription_score("bass", [_note(0.0, 40)], [])
    assert score.f1 == 0.0 and score.notes_estimated == 0


# --- speed ---------------------------------------------------------------------------


@needs_mir_eval
def test_speed_is_reported_as_a_multiple_of_real_time():
    """"Ninety seconds" means nothing without the length of the song."""
    assert metrics.speed("separation", 180.0, 90.0).realtime_multiple == 2.0
    assert metrics.speed("separation", 180.0, 360.0).realtime_multiple == 0.5


@needs_mir_eval
def test_a_zero_wall_clock_does_not_divide_by_zero():
    assert metrics.speed("x", 10.0, 0.0).realtime_multiple > 0


# --- the eval set ---------------------------------------------------------------------


def _build(root: Path, with_manifest: bool = True) -> Path:
    import soundfile as sf

    track = root / "song-one"
    (track / "stems").mkdir(parents=True)
    (track / "drums").mkdir()
    (track / "notes").mkdir()
    sf.write(str(track / "mixture.wav"), np.zeros((SR, 2)), SR)
    for name in ("vocals", "bass", "drums"):
        sf.write(str(track / "stems" / f"{name}.wav"), np.zeros((SR, 2)), SR)
    for name in ("kick", "snare"):
        sf.write(str(track / "drums" / f"{name}.wav"), np.zeros((SR, 2)), SR)
    (track / "notes" / "bass.csv").write_text(
        "onset_s,offset_s,midi\n0.0,0.5,40\n0.5,1.0,45\n", encoding="utf-8"
    )
    if with_manifest:
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "name": "a test set",
                    "source": "recorded in the test",
                    "licence": "none needed",
                    "tracks": [{"id": "song-one", "seconds": 1.0, "caveats": ["silent"]}],
                }
            ),
            encoding="utf-8",
        )
    return root


def test_an_eval_set_is_read_by_convention_and_described_by_manifest(tmp_path):
    loaded = eval_sets.load(_build(tmp_path))
    assert loaded.name == "a test set"
    assert loaded.licence == "none needed"
    track = loaded.tracks[0]
    assert set(track.stems) == {"vocals", "bass", "drums"}
    assert set(track.drums) == {"kick", "snare"}
    assert set(track.notes) == {"bass"}
    assert track.caveats == ["silent"]
    assert track.scores_separation and track.scores_bleed and track.scores_transcription


def test_a_set_with_no_manifest_still_runs_and_says_its_provenance_is_missing(tmp_path):
    """Convention is enough to measure. It is not enough to cite, and the difference has
    to show up in the report rather than being noticed a year later."""
    loaded = eval_sets.load(_build(tmp_path, with_manifest=False))
    assert loaded.tracks and loaded.tracks[0].stems
    assert loaded.source == "" and loaded.licence == ""
    assert any("licence" in line for line in eval_sets.describe_missing(loaded))


def test_what_is_missing_is_phrased_as_an_instruction(tmp_path):
    """The reader is whoever has to go and record something. "No transcription ground
    truth" is not an instruction; "a DI part played to a click gives this exactly" is."""
    root = tmp_path / "thin"
    (root / "bare").mkdir(parents=True)
    import soundfile as sf

    sf.write(str(root / "bare" / "mixture.wav"), np.zeros((SR, 2)), SR)

    missing = eval_sets.describe_missing(eval_sets.load(root))
    assert any("stems" in line for line in missing)
    assert any("notes" in line for line in missing)
    assert any("DrumSep" in line or "drums" in line for line in missing)


def test_no_eval_set_at_all_says_so_in_one_sentence_a_person_can_act_on():
    [line] = eval_sets.describe_missing(None)
    assert "only of" in line and "speed" in line
    assert "DI" in line, "it should name the fastest route to ground truth"


def test_a_note_file_is_three_numbers_a_line_and_tolerates_a_header(tmp_path):
    path = tmp_path / "bass.csv"
    path.write_text(
        "onset_s,offset_s,midi\n0.0,0.5,40\n\n# a comment\n1.0,1.5,45.0\nrubbish\n",
        encoding="utf-8",
    )
    notes = eval_sets.read_notes(path)
    assert [(n.start_s, n.pitch) for n in notes] == [(0.0, 40), (1.0, 45)]


def test_a_folder_with_no_mixture_is_skipped_rather_than_breaking_the_run(tmp_path):
    root = _build(tmp_path)
    (root / "not-a-track").mkdir()
    assert [t.track_id for t in eval_sets.load(root).tracks] == ["song-one"]


# --- the written record -----------------------------------------------------------------


def test_a_run_writes_both_a_page_and_a_json(tmp_path):
    run = report.BenchmarkRun(
        eval_set="a test set",
        separation_model="htdemucs_6s",
        versions={"demucs": "4.1.0"},
        commit="abc1234",
        machine="a machine",
        tracks=[
            report.TrackResult(
                track_id="song-one",
                seconds=10.0,
                separation=[metrics.SeparationScore("bass", 6.1, 12.0, 7.4, 3)],
                speeds=[metrics.speed("separation", 10.0, 20.0)],
            )
        ],
    )
    page, data = report.write(run, tmp_path)
    text = page.read_text(encoding="utf-8")

    assert "htdemucs_6s" in text and "abc1234" in text
    assert "6.10" in text and "0.50" in text
    assert json.loads(data.read_text(encoding="utf-8"))["tracks"][0]["track_id"] == "song-one"


def test_the_gaps_are_printed_above_the_results(tmp_path):
    """A benchmark that reports only what it managed looks complete, which is the most
    misleading thing it could do."""
    run = report.BenchmarkRun(
        eval_set="thin",
        gaps=["no ground truth, so nothing here measures quality"],
        tracks=[
            report.TrackResult(
                track_id="one",
                seconds=10.0,
                separation=[metrics.SeparationScore("bass", 6.1, 12.0, 7.4, 1)],
            )
        ],
    )
    text = report.to_markdown(run)
    assert text.index("could not measure") < text.index("SDR, SIR, SAR")


def test_an_unstated_licence_is_marked_rather_than_left_blank():
    text = report.to_markdown(report.BenchmarkRun(eval_set="x"))
    assert "*not stated*" in text


def test_a_dirty_tree_is_recorded_as_dirty(tmp_path):
    """A benchmark run against uncommitted work is not reproducible, and a bare hash
    would claim it was."""
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "--allow-empty",
                    "-m", "x", "--no-gpg-sign"], check=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                        "PATH": __import__("os").environ.get("PATH", "")})
    assert "dirty" not in report.current_commit(tmp_path)

    (tmp_path / "new.txt").write_text("x", encoding="utf-8")
    assert "dirty" in report.current_commit(tmp_path)


def test_a_folder_that_is_not_a_checkout_says_so(tmp_path):
    assert report.current_commit(tmp_path) in ("not a git checkout", "unknown")


# --- reconstruction: the quality figure that needs no ground truth ----------------------


def test_stems_that_sum_back_exactly_leave_nothing_behind():
    a, b = _noise(seed=20), _noise(seed=21)
    assert metrics.reconstruction_db(a + b, {"a": a, "b": b}) < -100


def test_a_tenth_of_the_mixture_unaccounted_for_measures_twenty_decibels_down():
    """A number that can be checked on paper: drop a tenth of the mixture's amplitude and
    the residual sits 20 dB under it."""
    mix = _noise(seed=22)
    assert metrics.reconstruction_db(mix, {"a": mix * 0.9}) == pytest.approx(-20.0, abs=0.5)


def test_it_says_nothing_about_whether_the_parts_went_in_the_right_file():
    """The limitation, as a test, because it is the one way this number misleads. Two
    sources swapped between two files reconstruct the mixture perfectly - and BSS Eval,
    which asks the other question, calls the same pair a total failure."""
    a, b = _noise(seed=23), _noise(seed=24)
    swapped = {"a": b, "b": a}

    assert metrics.reconstruction_db(a + b, swapped) < -100, "the sum is unchanged"
    scores, _ = metrics.separation_scores({"a": a, "b": b}, swapped)
    assert all(s.sdr_db < 1.0 for s in scores), "and the separation is worthless"


def test_a_silent_mixture_is_zero_rather_than_a_division():
    assert metrics.reconstruction_db(np.zeros(SR), {"a": np.zeros(SR)}) == 0.0


def test_stems_of_different_lengths_are_trimmed_rather_than_raising():
    mix = _noise(seconds=4, seed=25)
    assert metrics.reconstruction_db(mix, {"a": mix[: SR * 2]}) <= 0.0


def test_the_report_says_which_question_reconstruction_answers(tmp_path):
    run = report.BenchmarkRun(
        eval_set="x",
        tracks=[report.TrackResult(track_id="one", seconds=1.0, reconstruction_db=-25.6)],
    )
    text = report.to_markdown(run)
    assert "-25.60 dB" in text
    assert "weaker question" in text, "the limitation belongs next to the number"


def test_the_tolerance_for_wrong_stems_is_looser_than_a_separator_s_own_residual():
    """The check has to clear honest stem sets. A real multitrack sums worse than a
    perfect reconstruction because the mix it is compared with has bus compression and a
    limiter on it, and this project's own Demucs stems land at about -22 to -26 dB. A
    tolerance tighter than that would flag every correct eval set as wrong."""
    assert eval_sets.SUM_TOLERANCE_DB > -20.0, "tighter than a separator's own residual"
    assert eval_sets.SUM_TOLERANCE_DB < 0.0


def test_stems_from_a_different_take_are_caught_by_the_sum():
    """What the check is for, as the mistake it catches: these stems are internally fine
    and simply are not the stems of that mixture. Every SDR computed from them would be
    measuring the arrangement."""
    a, b = _noise(seed=30), _noise(seed=31)
    other_take = _noise(seed=32)

    right = metrics.reconstruction_db(a + b, {"a": a, "b": b})
    wrong = metrics.reconstruction_db(a + b, {"a": a, "b": other_take})

    assert right < eval_sets.SUM_TOLERANCE_DB
    assert wrong > eval_sets.SUM_TOLERANCE_DB


def test_a_written_run_can_be_rebuilt_from_its_json_and_rendered_again(tmp_path):
    """The prose in a report is part of the result - it is where a figure's limits are
    stated - so improving it must not require re-running hours of separation, and must
    not tempt anybody into hand-editing a generated file until it stops matching its own
    template."""
    run = report.BenchmarkRun(
        eval_set="a set",
        separation_model="htdemucs_6s",
        commit="abc1234",
        tracks=[
            report.TrackResult(
                track_id="one",
                seconds=180.0,
                separation=[metrics.SeparationScore("bass", 6.1, 12.0, 7.4, 6)],
                transcription=[
                    metrics.transcription_score("bass", [_note(0.0, 40)], [_note(0.0, 40)])
                ],
                speeds=[metrics.speed("separation", 180.0, 145.7)],
                reconstruction_db=-21.69,
                skipped=["something"],
                caveats=["a caveat"],
            )
        ],
        gaps=["a gap"],
    )
    _, data = report.write(run, tmp_path)

    rebuilt = report.from_json(data)
    assert report.to_markdown(rebuilt) == report.to_markdown(run)
    assert rebuilt.tracks[0].separation[0].sdr_db == 6.1
    rebuilt_speed, original_speed = rebuilt.tracks[0].speeds[0], run.tracks[0].speeds[0]
    assert rebuilt_speed.realtime_multiple == original_speed.realtime_multiple
    assert rebuilt.tracks[0].reconstruction_db == -21.69


def test_two_models_on_one_set_do_not_overwrite_each_other(tmp_path):
    """Comparing two models on the same recordings is the commonest thing anybody does
    with this, and a filename that did not distinguish them would silently destroy the
    comparison being made."""
    pages = {
        model: report.write(
            report.BenchmarkRun(eval_set="a set", separation_model=model), tmp_path
        )[0]
        for model in ("htdemucs", "htdemucs_6s")
    }
    assert pages["htdemucs"] != pages["htdemucs_6s"]
    assert all(p.exists() for p in pages.values())
