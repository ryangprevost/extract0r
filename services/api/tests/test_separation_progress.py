"""Tests for X0R-303: real progress out of the separator.

The Demucs progress parser is tested against captured CLI output rather than by running
the model — the parser is what breaks when Demucs changes its bar format, and finding
that out should not require a 2 GB download.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.services import pipeline
from app.services.separation.demucs import parse_progress
from app.services.separation.stub import StubSeparator
from app.services.storage import TrackStorage

# Real lines from `python -m demucs.separate`, plus the noise around them.
DEMUCS_OUTPUT = [
    "Important: the default model was recently changed to `htdemucs`",
    "Selected model is a bag of 1 models.",
    "Separated tracks will be stored in /out/htdemucs_6s",
    "Separating track /data/source.normalized.wav",
    "  0%|          | 0.0/241.2 [00:00<?, ?seconds/s]",
    " 12%|#1        | 28.8/241.2 [00:04<00:33,  6.32seconds/s]",
    " 42%|####2     | 100.8/241.2 [00:15<00:21,  6.44seconds/s]",
    "100%|##########| 241.2/241.2 [00:37<00:00,  6.41seconds/s]",
]


def test_parser_ignores_lines_without_a_bar():
    assert parse_progress("Selected model is a bag of 1 models.") is None
    assert parse_progress("") is None


def test_parser_reads_the_fraction():
    assert parse_progress(" 42%|####2     | 100.8/241.2 [00:15<00:21,  6.44seconds/s]") == (
        pytest.approx(100.8 / 241.2)
    )


def test_parser_handles_the_endpoints():
    assert parse_progress("  0%|          | 0.0/241.2 [00:00<?, ?seconds/s]") == 0.0
    assert parse_progress("100%|##########| 241.2/241.2 [00:37<00:00,  6.41seconds/s]") == 1.0


def test_parser_falls_back_to_the_percentage_when_there_is_no_fraction():
    assert parse_progress(" 75%|#######5  |") == pytest.approx(0.75)


def test_parsed_progress_over_a_whole_run_is_monotonic_and_bounded():
    values = [p for p in (parse_progress(line) for line in DEMUCS_OUTPUT) if p is not None]
    assert values == sorted(values)
    assert values[0] == 0.0
    assert values[-1] == 1.0
    assert all(0.0 <= v <= 1.0 for v in values)


def test_parser_never_exceeds_one_on_malformed_input():
    # A bag-of-models run can print a total that has already been passed.
    assert parse_progress(" 999%|##########| 500.0/241.2 [00:37<00:00]") == 1.0


def test_stub_separator_reports_progress_ending_at_one(sample_wav: Path, tmp_path: Path):
    seen: list[float] = []
    StubSeparator().separate(sample_wav, tmp_path / "stems", on_progress=seen.append)

    assert seen == sorted(seen)
    assert seen[-1] == pytest.approx(1.0)
    assert seen.count(1.0) == 1, "progress should reach 1.0 exactly once"


def test_pipeline_forwards_progress_from_the_separator(
    settings: Settings, sample_wav: Path
):
    storage = TrackStorage(settings.storage_dir)
    track_id = storage.save_upload("song.wav", sample_wav.read_bytes()).track_id

    seen: list[float] = []
    pipeline.separate(track_id, storage, settings, on_progress=seen.append)
    assert seen and seen[-1] == pytest.approx(1.0)


def test_separation_runs_against_the_normalised_file(settings: Settings, mono_22k_wav: Path):
    """Downstream stages must never see the raw upload's sample rate."""
    storage = TrackStorage(settings.storage_dir)
    track_id = storage.save_upload("song.wav", mono_22k_wav.read_bytes()).track_id

    result = pipeline.separate(track_id, storage, settings)

    assert storage.normalized_path(track_id).exists()
    assert all(stem.sample_rate == 44100 for stem in result.stems)
    assert all(stem.duration_s > 0 for stem in result.stems)


def test_normalisation_is_not_repeated_on_a_second_run(settings: Settings, sample_wav: Path):
    storage = TrackStorage(settings.storage_dir)
    track_id = storage.save_upload("song.wav", sample_wav.read_bytes()).track_id

    pipeline.normalize_source(track_id, storage)
    stamp = storage.normalized_path(track_id).stat().st_mtime_ns
    pipeline.normalize_source(track_id, storage)

    assert storage.normalized_path(track_id).stat().st_mtime_ns == stamp


def test_pyin_frame_length_holds_two_periods_of_the_lowest_pitch():
    """Regression guard for a silent accuracy bug.

    librosa's default 2048-sample frame is under two cycles of a 5-string bass low B,
    which makes pYIN return wrong pitches without raising anything.
    """
    from app.domain.notes import StemKind
    from app.services.transcription.pyin import RANGES, frame_length_for

    sample_rate = 44100
    for stem, bounds in RANGES.items():
        frame = frame_length_for(bounds.fmin_hz, sample_rate)
        assert frame >= 2 * sample_rate / bounds.fmin_hz, f"{stem.value} frame too short"
        assert frame & (frame - 1) == 0, "frame length should stay a power of two"

    # Bass reaches below 31 Hz, so it must ask for more than the librosa default.
    assert frame_length_for(RANGES[StemKind.BASS].fmin_hz, sample_rate) > 2048
    # A guitar's range fits comfortably in the default.
    assert frame_length_for(RANGES[StemKind.GUITAR].fmin_hz, sample_rate) == 2048


def test_windows_crash_codes_are_named_not_just_numbered():
    """A bare "exit 3221225477" tells nobody anything.

    Demucs' multi-worker mode crashes with an access violation on Windows, which is how
    the -j default came to be 1 there. The message has to point at that.
    """
    from app.services.separation.demucs import describe_exit_code

    described = describe_exit_code(3221225477)
    assert "0xC0000005" in described
    assert "access violation" in described.lower()

    assert "out of memory" in describe_exit_code(0xC0000017).lower()
    # An ordinary non-zero exit stays plain.
    assert describe_exit_code(1) == "exit 1"


def test_demucs_defaults_to_a_single_job_on_windows():
    """Parallel workers segfault on Windows; correctness beats the speedup."""
    import sys

    from app.services.separation.demucs import DemucsSeparator

    jobs = DemucsSeparator().jobs
    if sys.platform == "win32":
        assert jobs == 1
    else:
        assert jobs >= 1


def test_an_explicit_job_count_is_respected():
    """The default is cautious, but an operator who knows their platform can override."""
    from app.services.separation.demucs import DemucsSeparator

    assert DemucsSeparator(jobs=3).jobs == 3
