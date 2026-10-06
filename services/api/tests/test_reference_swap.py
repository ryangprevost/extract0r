"""Swapping a reference must leave nothing behind from the one before it.

X0R-1420. Ryan noticed two of his saved profiles held byte-identical measurements under
different names, and confirmed he had swapped the reference between the two saves.

The bytes on disk are replaced correctly - `storage.save_reference` unlinks every existing
`reference.*` before writing, and an upload-save-upload-save round trip through the API
returns the right duration each time. What is *not* replaced is everything derived from the
previous reference:

* `reference_stems` - the six stems the old reference was separated into;
* `drum_stems["reference"]` - the four drums inside those;
* `reference_profile` - a saved profile the track was aimed at before.

All three are read by name later. So after a swap the whole-mix stage measures the new
record while the instrument comparison, the per-drum comparison and the instrument half of
any profile saved from it all describe the old one - and nothing anywhere says so. A
profile is six kilobytes of numbers with no audio behind it, which is why this survived
from September: there is no way to look at one and tell which record it describes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ATTESTED = {"owns_or_licensed": "true", "personal_use_only": "true"}
REFERENCE_RIGHTS = {**ATTESTED, "reference_rights": "true"}


@pytest.fixture
def track(client, sample_wav: Path) -> str:
    with sample_wav.open("rb") as handle:
        response = client.post(
            "/api/v1/tracks",
            files={"file": ("song.wav", handle, "audio/wav")},
            data=ATTESTED,
        )
    assert response.status_code == 201, response.text
    return response.json()["track_id"]


def put_reference(client, track: str, wav: Path, name: str) -> None:
    with wav.open("rb") as handle:
        response = client.post(
            f"/api/v1/tracks/{track}/reference",
            files={"file": (name, handle, "audio/wav")},
            data=REFERENCE_RIGHTS,
        )
    assert response.status_code in (200, 201), response.text


def test_the_bytes_really_are_replaced(client, track, sample_wav, short_wav):
    """The half that was already right, pinned so a fix for the rest cannot break it."""
    put_reference(client, track, sample_wav, "first.wav")
    first = client.storage.reference_path(track).read_bytes()

    put_reference(client, track, short_wav, "second.wav")
    second = client.storage.reference_path(track).read_bytes()

    assert first != second
    assert second == short_wav.read_bytes()


def test_only_one_reference_file_survives_a_swap(client, track, sample_wav, short_wav):
    """Two files side by side would make `reference_path`'s `next(glob(...))` a lottery."""
    put_reference(client, track, sample_wav, "first.wav")
    put_reference(client, track, short_wav, "second.wav")

    directory = client.storage.track_dir(track)
    assert len(list(directory.glob("reference.*"))) == 1


def test_a_swap_forgets_the_old_reference_s_stems(client, track, sample_wav, short_wav):
    """The bug. Separated stems outlive the reference they came from.

    Without this, the instrument comparison measures the new record on one side and the
    old one on the other, and the profile saved from it carries the old record's
    instruments under the new record's name.
    """
    registry = client.registry
    put_reference(client, track, sample_wav, "first.wav")
    registry.set_reference_stems(track, {"vocals": "/stems/of/the/first.wav"})
    assert registry.require(track).reference_stems, "fixture did not take"

    put_reference(client, track, short_wav, "second.wav")

    assert not registry.require(track).reference_stems, (
        "the new reference inherited the old one's separated stems"
    )


def test_a_swap_forgets_the_old_reference_s_drums(client, track, sample_wav, short_wav):
    """Same shape, one level further in: the four drums inside the old reference."""
    registry = client.registry
    put_reference(client, track, sample_wav, "first.wav")
    registry.set_drum_stems(track, "reference", {"kick": "/drums/of/the/first.wav"})
    registry.set_drum_stems(track, "source", {"kick": "/drums/of/my/own.wav"})

    put_reference(client, track, short_wav, "second.wav")

    drums = registry.require(track).drum_stems or {}
    assert not drums.get("reference"), "the new reference inherited the old one's drums"
    # The source's own drums have nothing to do with the reference and must survive, or
    # a swap would silently throw away a separation the user paid for.
    assert drums.get("source"), "swapping the reference discarded the source's drums"


def test_a_swap_forgets_a_profile_the_track_was_aimed_at(client, track, sample_wav):
    """A reference file and a saved profile are two answers to the same question, and
    the later one wins. Leaving both set makes which one is used depend on the order
    some other function happens to check them in."""
    from app.services.mastering.profile import ReferenceProfile

    registry = client.registry
    registry.set_reference_profile(track, ReferenceProfile(name="an old aim"))
    assert registry.require(track).reference_profile is not None

    put_reference(client, track, sample_wav, "first.wav")

    assert registry.require(track).reference_profile is None, (
        "a reference was uploaded over a profile and both are still set"
    )


def test_a_profile_saved_after_a_swap_describes_the_new_reference(
    client, track, sample_wav, short_wav
):
    """The symptom Ryan actually saw, end to end.

    Two profiles saved either side of a swap must not come out identical.
    """
    put_reference(client, track, sample_wav, "first.wav")
    first = client.post(
        f"/api/v1/tracks/{track}/reference/profile", json={"name": "before"}
    ).json()

    put_reference(client, track, short_wav, "second.wav")
    second = client.post(
        f"/api/v1/tracks/{track}/reference/profile", json={"name": "after"}
    ).json()

    assert first["seconds"] != second["seconds"], (
        "two profiles saved either side of a reference swap describe the same audio"
    )
