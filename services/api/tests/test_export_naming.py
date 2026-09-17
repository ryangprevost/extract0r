"""What an exported master is called, and what it remembers.

Every download used to arrive as "extract0r-master.mp3", so a folder of masters was a
folder of identical names, each one overwriting the last.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.api.routes_master import _export_name, _export_tags
from app.services.mixdown.encode import id3v2_tag, write_mp3


class _Stored:
    def __init__(self, name):
        self.original_filename = name


class _Record:
    def __init__(self, name, reference=""):
        self.stored = _Stored(name)
        self.reference_name = reference


# --- the filename ---------------------------------------------------------------------


def test_the_export_is_named_after_the_song():
    assert _export_name(_Record("Ninety Nine Ways Home.mp3")) == (
        "Ninety Nine Ways Home [extract0r].mp3"
    )


def test_any_source_extension_becomes_mp3():
    assert _export_name(_Record("demo.wav")).endswith(" [extract0r].mp3")
    assert _export_name(_Record("demo.m4a")) == "demo [extract0r].mp3"


def test_characters_a_filesystem_will_not_accept_are_removed():
    """A download that cannot be saved is worse than one with a dull name."""
    name = _export_name(_Record('AC/DC: "Live" <demo>.mp3'))
    assert not set(name) & set(r'<>:"/\|?*')
    assert name.endswith("[extract0r].mp3")


def test_a_track_with_no_name_still_produces_something_saveable():
    for record in (_Record(""), _Record("???.mp3"), None):
        name = _export_name(record)
        assert name.endswith(".mp3")
        assert name.strip()


# --- the tag --------------------------------------------------------------------------


def test_the_tag_records_which_reference_was_used():
    """The reference goes in the tag, not the filename: a master is the product of two
    recordings but only one of them is the song."""
    tags = _export_tags(_Record("My Song.mp3", "Some Band - Reference Track.mp3"))
    assert tags["TIT2"] == "My Song"
    assert "Reference Track" in tags["COMM"]
    assert "extract0r" in tags["COMM"]


def test_a_master_with_no_reference_says_only_what_it_knows():
    tags = _export_tags(_Record("My Song.mp3"))
    assert tags["COMM"] == "Mastered with extract0r"
    assert "against" not in tags["COMM"]


def test_the_tag_is_a_valid_id3v2_header():
    raw = id3v2_tag({"TIT2": "Hello", "COMM": "matched against Something"})
    assert raw[:3] == b"ID3"
    assert raw[3:5] == b"\x03\x00"
    # The declared size is synchsafe, so no size byte may have its top bit set - that is
    # what stops a decoder mistaking one for an MPEG frame sync.
    assert all(byte < 0x80 for byte in raw[6:10])
    size = int.from_bytes(
        bytes([(raw[6] << 21 | raw[7] << 14 | raw[8] << 7 | raw[9]) >> s & 0xFF
               for s in (24, 16, 8, 0)]), "big"
    )
    assert size == len(raw) - 10


def test_an_empty_tag_is_no_tag_at_all():
    assert id3v2_tag({}) == b""
    assert id3v2_tag({"TIT2": ""}) == b""


def test_text_survives_accents_and_typographic_punctuation():
    raw = id3v2_tag({"TIT2": "Naïve — Don’t Stop"})
    # UTF-16LE with a byte-order mark, which is what v2.3 specifies beyond Latin-1.
    assert b"\xff\xfe" in raw
    assert "Naïve".encode("utf-16-le") in raw


@pytest.mark.parametrize("reference", ["", "ref.mp3"])
def test_a_tagged_mp3_still_decodes(tmp_path, reference):
    """The tag sits in front of the audio. If that were wrong the file would not play."""
    sf = pytest.importorskip("soundfile")
    pytest.importorskip("lameenc")

    rate = 44100
    t = np.arange(rate) / rate
    tone = np.stack([0.2 * np.sin(2 * np.pi * 440 * t)] * 2, axis=1)

    out = tmp_path / "tagged.mp3"
    write_mp3(out, tone, rate, 320, _export_tags(_Record("Song.mp3", reference)))

    assert out.read_bytes()[:3] == b"ID3"
    samples, read_rate = sf.read(str(out), always_2d=True)
    assert read_rate == rate
    assert len(samples) > rate // 2
    assert np.abs(samples).max() > 0.05
