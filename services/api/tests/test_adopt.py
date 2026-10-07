"""Picking up tracks already on disk. X0R-1423.

Ryan uploaded a song and a reference, waited through both separations and the per-drum
pass, and the API was stopped out from under him. Every file survived; nothing could reach
any of them, because the registry is in memory and had never looked at `storage/`. The
retention sweep would eventually have deleted roughly forty-five minutes of CPU unread.

These cover the recovery and, as carefully, **what is deliberately not recovered**. An
adopted record is thinner than an uploaded one, and the thin parts are thin on purpose:
inventing a rights attestation or guessing which profile a track was aimed at would each be
worse than the inconvenience they save.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.domain.notes import StemKind
from app.services.adopt import adopt_all, adopt_one
from app.services.registry import TrackRegistry

TRACK_ID = "ab3fce1f50d84185901616eb70f65ab5"
SR = 44100


def write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tone = 0.2 * np.sin(2 * np.pi * 220 * np.arange(SR // 4) / SR)
    sf.write(str(path), np.stack([tone, tone], axis=1), SR)
    return path


@pytest.fixture
def on_disk(tmp_path: Path) -> Path:
    """A track directory shaped exactly like the one Ryan lost."""
    d = tmp_path / TRACK_ID
    write(d / "source.mp3")
    write(d / "source.normalized.wav")
    for stem in ("vocals", "drums", "bass", "guitar", "piano", "other"):
        write(d / "stems" / "htdemucs_6s" / "source.normalized" / f"{stem}.wav")
        write(d / "reference_stems" / "htdemucs_6s" / "reference" / f"{stem}.wav")
    write(d / "reference.mp3")
    for side in ("source", "reference"):
        for drum in ("kick", "snare", "cymbals", "toms"):
            write(d / "drum_stems" / side / "49469ca8" / "drums" / f"{drum}.wav")
    return tmp_path


# --- what comes back ---------------------------------------------------------------------


def test_the_expensive_half_is_recovered(on_disk):
    """Both separations, which is minutes of CPU each and the whole point."""
    record = adopt_one(on_disk / TRACK_ID)
    assert record is not None
    assert record.separation is not None
    assert {s.kind for s in record.separation.stems} == set(StemKind)
    assert set(record.reference_stems) == set(StemKind)


def test_the_drum_split_comes_back_too(on_disk):
    """Half the audio's length again per side, and it was already paid for."""
    record = adopt_one(on_disk / TRACK_ID)
    assert set(record.drum_stems) == {"source", "reference"}
    assert set(record.drum_stems["source"]) == {"kick", "snare", "cymbals", "toms"}


def test_the_reference_is_noticed(on_disk):
    record = adopt_one(on_disk / TRACK_ID)
    assert record.reference_name == "reference.mp3"


def test_stem_paths_point_at_files_that_exist(on_disk):
    """A record whose paths are wrong is worse than no record: every route downstream
    opens these."""
    record = adopt_one(on_disk / TRACK_ID)
    for stem in record.separation.stems:
        assert stem.path.exists(), stem.kind
    for path in record.reference_stems.values():
        assert Path(path).exists()


def test_the_route_helper_can_read_an_adopted_record(on_disk):
    """The shape has to satisfy `_stem_path`, which is what every comparison calls."""
    from app.api.routes_master import _stem_path

    record = adopt_one(on_disk / TRACK_ID)
    assert _stem_path(record.separation, StemKind.BASS) is not None
    assert _stem_path(record.reference_stems, StemKind.BASS) is not None


# --- what does not, and why ----------------------------------------------------------------


def test_the_attestation_is_marked_adopted_and_not_invented(on_disk):
    """Fabricating a rights claim would be worse than any inconvenience it avoids."""
    record = adopt_one(on_disk / TRACK_ID)
    assert record.attestation == {"adopted": True}
    assert "owns_or_licensed" not in record.attestation


def test_no_profile_is_guessed(on_disk):
    """A profile a track was aimed at is not on disk. Guessing one would aim a master at
    the wrong record silently, which is the failure X0R-1420 is about."""
    record = adopt_one(on_disk / TRACK_ID)
    assert record.reference_profile is None


def test_nothing_is_written(on_disk):
    """No new file, no format, no database - the directory layout already is the record."""
    before = sorted(p.relative_to(on_disk) for p in on_disk.rglob("*"))
    adopt_all(on_disk, TrackRegistry())
    assert sorted(p.relative_to(on_disk) for p in on_disk.rglob("*")) == before


# --- the scan ------------------------------------------------------------------------------


def test_adopting_puts_it_where_require_can_find_it(on_disk):
    registry = TrackRegistry()
    assert adopt_all(on_disk, registry) == 1
    assert registry.require(TRACK_ID) is not None


def test_a_track_already_known_is_left_alone(on_disk):
    """A restart adopts; a running server must not overwrite what it is using."""
    registry = TrackRegistry()
    adopt_all(on_disk, registry)
    original = registry.require(TRACK_ID)
    assert adopt_all(on_disk, registry) == 0
    assert registry.require(TRACK_ID) is original


def test_a_directory_with_no_source_is_not_a_track(tmp_path):
    empty = tmp_path / ("b" * 32)
    (empty / "exports").mkdir(parents=True)
    assert adopt_one(empty) is None
    assert adopt_all(tmp_path, TrackRegistry()) == 0


def test_strays_in_the_storage_root_are_ignored(on_disk):
    """Anything not named like a track id is not ours, and should cost nothing."""
    (on_disk / "notes").mkdir()
    (on_disk / "README.txt").write_text("hello", encoding="utf-8")
    assert adopt_all(on_disk, TrackRegistry()) == 1


def test_a_missing_storage_root_is_not_an_error(tmp_path):
    assert adopt_all(tmp_path / "nothing-here", TrackRegistry()) == 0


def test_one_bad_directory_does_not_stop_the_others(on_disk, monkeypatch):
    """A boot that fails because one folder is odd is worse than one that adopts the rest."""
    second = on_disk / ("c" * 32)
    write(second / "source.mp3")

    import app.services.adopt as adopt

    real = adopt.adopt_one
    calls = {"n": 0}

    def flaky(directory):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("something odd on disk")
        return real(directory)

    monkeypatch.setattr(adopt, "adopt_one", flaky)
    registry = TrackRegistry()
    assert adopt.adopt_all(on_disk, registry) == 1


def test_adopting_does_not_open_the_audio(on_disk):
    """Six files to fill in two numbers would turn a boot scan into a boot wait, and every
    route that needs a rate or a duration reads the file itself."""
    record = adopt_one(on_disk / TRACK_ID)
    assert all(s.sample_rate == 0 and s.duration_s == 0.0 for s in record.separation.stems)
