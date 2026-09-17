"""Finding a reference in music you already own.

The streaming-link version of this feature cannot be built - Spotify withdrew the audio
endpoints for new applications in November 2024 - so what is tested here is the local
one, which needs the audio anyway.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.library import (
    MIN_SECONDS,
    SUFFIXES,
    Profile,
    load_cache,
    profile_of,
    rank,
    save_cache,
    scan,
)

SR = 44100


def _write(path, seconds=70.0, hz=440.0, width=0.4, gain=0.3, rate=SR):
    """A file long enough to profile, with a known image."""
    import soundfile as sf

    t = np.arange(int(rate * seconds)) / rate
    mid = gain * np.sin(2 * np.pi * hz * t)
    side = gain * width * np.sin(2 * np.pi * hz * 1.5 * t)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.stack([mid + side, mid - side], axis=1), rate)
    return path


def _profile(name, bands, width, lufs=-10.0):
    return Profile(
        path=f"C:/music/{name}.mp3",
        name=name,
        seconds=200.0,
        lufs=lufs,
        peak_db=-0.5,
        bands=bands,
        width=width,
    )


FLAT = {n: -9.0 for n in ("sub", "low", "low mid", "body", "mid", "upper mid",
                          "presence", "brilliance", "air")}
STEREO = {n: 0.5 for n in ("sub", "low", "low mid", "body", "mid", "upper mid",
                           "presence", "top")}


# --- measuring ------------------------------------------------------------------------


def test_a_file_is_measured_into_a_profile(tmp_path):
    pytest.importorskip("soundfile")
    got = profile_of(_write(tmp_path / "song.wav"))

    assert got is not None
    assert got.name == "song"
    assert got.bands and got.width
    # A 440 Hz tone belongs in the body band, not spread across the spectrum.
    assert max(got.bands, key=got.bands.get) in ("body", "mid")


def test_something_too_short_to_judge_is_skipped(tmp_path):
    """An interlude, a skit or a sample is not a reference."""
    pytest.importorskip("soundfile")
    assert profile_of(_write(tmp_path / "short.wav", seconds=MIN_SECONDS - 10)) is None


def test_an_unreadable_file_returns_nothing_rather_than_raising(tmp_path):
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not audio at all")
    assert profile_of(broken) is None


def test_tonal_balance_is_measured_independently_of_level(tmp_path):
    """Two takes of the same thing at different volumes must look alike, or every
    quiet file would rank as tonally distant."""
    pytest.importorskip("soundfile")
    loud = profile_of(_write(tmp_path / "loud.wav", gain=0.5))
    quiet = profile_of(_write(tmp_path / "quiet.wav", gain=0.05))

    # Only where there is something to compare. A pure tone leaves most bands at the
    # numerical floor, and down there the epsilon decides the answer, not the audio.
    occupied = [b for b in loud.bands if loud.bands[b] > -40.0]
    assert occupied, "the fixture should put real energy somewhere"
    for band in occupied:
        assert loud.bands[band] == pytest.approx(quiet.bands[band], abs=0.5)


# --- scanning and its cache -----------------------------------------------------------


def test_a_scan_finds_audio_and_caches_it(tmp_path):
    pytest.importorskip("soundfile")
    _write(tmp_path / "a.wav")
    _write(tmp_path / "nested" / "b.wav", hz=880.0)
    (tmp_path / "notes.txt").write_text("not audio")

    first = scan(tmp_path)
    assert len(first) == 2
    assert load_cache(tmp_path), "the scan should have written a cache"

    # Second time nothing is re-measured, and the answer is the same.
    assert {k: v.name for k, v in scan(tmp_path).items()} == {
        k: v.name for k, v in first.items()
    }


def test_a_changed_file_is_measured_again(tmp_path):
    pytest.importorskip("soundfile")
    path = _write(tmp_path / "a.wav", hz=440.0)
    before = scan(tmp_path)
    key = next(iter(before))

    _write(path, hz=3000.0)
    after = scan(tmp_path)
    assert after[key].bands != before[key].bands


def test_a_cache_from_an_older_version_is_discarded(tmp_path):
    import json

    (tmp_path / ".extract0r-library.json").write_text(
        json.dumps({"version": 0, "profiles": {"x": {}}}), encoding="utf-8"
    )
    assert load_cache(tmp_path) == {}


def test_a_corrupt_cache_does_not_stop_a_scan(tmp_path):
    (tmp_path / ".extract0r-library.json").write_text("{ not json", encoding="utf-8")
    assert load_cache(tmp_path) == {}


def test_the_limit_is_respected(tmp_path):
    pytest.importorskip("soundfile")
    for i in range(4):
        _write(tmp_path / f"{i}.wav")
    assert len(scan(tmp_path, limit=2)) == 2


def test_every_accepted_suffix_is_one_the_app_accepts_on_upload():
    from app.services.storage import ALLOWED_SUFFIXES

    assert SUFFIXES <= ALLOWED_SUFFIXES


# --- ranking --------------------------------------------------------------------------


def test_the_closest_tonal_match_ranks_first():
    source = _profile("mine", FLAT, STEREO, lufs=-12.0)
    near = _profile("near", {**FLAT, "air": -8.0}, STEREO, lufs=-8.0)
    far = _profile("far", {**FLAT, "air": 0.0, "sub": -20.0}, STEREO, lufs=-8.0)

    ordered = rank(source, {"a": near, "b": far})
    assert [c.profile.name for c in ordered] == ["near", "far"]


def test_a_candidate_is_described_by_where_it_goes_further():
    """Which is the point: a record that already sounds like the mix teaches it nothing."""
    source = _profile("mine", FLAT, {n: 0.3 for n in STEREO}, lufs=-12.0)
    louder = _profile("louder", FLAT, {n: 0.7 for n in STEREO}, lufs=-6.0)

    best = rank(source, {"a": louder})[0]
    assert best.louder_by_db == pytest.approx(6.0, abs=0.1)
    assert best.wider_above_1k_by_db > 1.0
    assert "louder" in best.why


def test_the_track_itself_is_never_its_own_reference():
    source = _profile("mine", FLAT, STEREO)
    assert rank(source, {"a": source}) == []


def test_a_mono_candidate_reports_no_width_difference_rather_than_minus_170_db():
    """Comparing a stereo image against a file that has none is arithmetically correct
    and completely useless to read."""
    source = _profile("mine", FLAT, {n: 0.4 for n in STEREO})
    mono = _profile("mono", FLAT, {n: 0.0 for n in STEREO})

    best = rank(source, {"a": mono})[0]
    assert best.mono is True
    assert best.wider_above_1k_by_db == 0.0
    assert best.tighter_below_250_by_db == 0.0
    assert "mono" in best.why


def test_stereo_candidates_outrank_a_mono_one_that_matches_better():
    """Half of what a master does is place things across the image, and a mono file has
    no opinion about that to copy."""
    source = _profile("mine", FLAT, {n: 0.4 for n in STEREO})
    perfect_mono = _profile("mono", FLAT, {n: 0.0 for n in STEREO})
    decent_stereo = _profile("stereo", {**FLAT, "air": -7.0}, {n: 0.6 for n in STEREO})

    ordered = rank(source, {"a": perfect_mono, "b": decent_stereo})
    assert [c.profile.name for c in ordered] == ["stereo", "mono"]


def test_ranking_an_empty_library_is_not_an_error():
    assert rank(_profile("mine", FLAT, STEREO), {}) == []


def test_the_cache_round_trips(tmp_path):
    original = {"k": _profile("x", FLAT, STEREO)}
    save_cache(tmp_path, original)
    assert load_cache(tmp_path)["k"].bands == original["k"].bands
