"""Writing a standard MIDI file. X0R-503.

Two layers on purpose. Most of these read the bytes with stdlib `struct`, so they run on a
bare checkout and hold the X0R-102 line. The last one parses the file with `mido` — an
independent implementation that knows nothing about how it was written — because a format
test that only uses its own writer's assumptions will happily pass a file no DAW can open.
"""

from __future__ import annotations

import struct

import pytest

from app.domain.midi import DRUM_CHANNEL, GM_DRUM_KEYS, TICKS_PER_BEAT, write_midi
from app.domain.notes import NoteEvent


def part(count: int = 8, pitch: int = 40, step: float = 0.5) -> list[NoteEvent]:
    return [
        NoteEvent(start_s=i * step, end_s=i * step + step * 0.8, pitch=pitch + i)
        for i in range(count)
    ]


#: Index of the first instrument track. 0 is the header, 1 is the conductor track that
#: carries tempo and time signature, and parts start after it.
FIRST_PART = 2
CONDUCTOR = 1


def events(body: bytes) -> list[tuple[int, int, int]]:
    """(status, data1, data2) for every channel message in a track body.

    A real parser rather than a scan for likely-looking bytes. The first version of these
    tests scanned for any byte matching 0x8_ or 0x9_, which is wrong: `_varlen` sets the
    high bit on continuation bytes, so a delta time over 127 emits something like 0x81 and
    reads as a note-off on channel 1. Walking delta times is the only way to know which
    bytes are statuses.
    """
    out, at, running = [], 0, 0
    while at < len(body):
        while body[at] & 0x80:  # delta time
            at += 1
        at += 1
        if at >= len(body):
            break
        byte = body[at]
        if byte == 0xFF:  # meta: type, then a varlen length
            at += 2
            length, shift = 0, 0
            while True:
                length = (length << 7) | (body[at] & 0x7F)
                more = body[at] & 0x80
                at += 1
                shift += 1
                if not more:
                    break
            at += length
            continue
        if byte & 0x80:
            running = byte
            at += 1
        out.append((running, body[at], body[at + 1]))
        at += 2
    return out


def chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """Walk the file the way a reader would: tag, length, body."""
    out, at = [], 0
    while at < len(data):
        tag = data[at : at + 4]
        size = struct.unpack(">I", data[at + 4 : at + 8])[0]
        out.append((tag, data[at + 8 : at + 8 + size]))
        at += 8 + size
    return out


# --- it is a MIDI file -------------------------------------------------------------------


def test_the_header_says_what_it_is():
    found = chunks(write_midi({"bass": part()}))

    assert found[0][0] == b"MThd"
    fmt, tracks, division = struct.unpack(">HHH", found[0][1])
    assert fmt == 1, "format 1: a tempo track plus named parts, which is what a DAW expects"
    assert tracks == 2, "the conductor track counts"
    assert division == TICKS_PER_BEAT


def test_every_chunk_declares_its_own_length():
    """The one structural error that makes a file unopenable rather than merely wrong."""
    data = write_midi({"bass": part(), "guitar": part(pitch=55)})
    assert sum(8 + len(body) for _, body in chunks(data)) == len(data)


def test_one_track_per_part_plus_the_conductor():
    data = write_midi({"bass": part(), "guitar": part(), "piano": part()})
    assert [tag for tag, _ in chunks(data)].count(b"MTrk") == 4


def test_every_track_ends_with_end_of_track():
    for tag, body in chunks(write_midi({"bass": part()})):
        if tag == b"MTrk":
            assert body.endswith(b"\xff\x2f\x00")


# --- the drum rule, which is the one that breaks silently --------------------------------


def test_drums_land_on_channel_ten():
    """Written anywhere else, a drum track opens in a DAW as a melody played on a piano."""
    data = write_midi({"kick": part(pitch=33)}, drum_tracks=["kick"])
    found = events(chunks(data)[FIRST_PART][1])

    assert found
    assert {status & 0x0F for status, _, _ in found} == {DRUM_CHANNEL}


def test_a_separated_drum_collapses_to_its_gm_key():
    """A kick stem transcribes to whatever its fundamental happened to be, and that pitch is
    not a kick in any sampler. Every note in the part becomes one GM key."""
    notes = [NoteEvent(start_s=i * 0.5, end_s=i * 0.5 + 0.1, pitch=30 + i) for i in range(5)]
    data = write_midi(
        {"kick": notes}, drum_tracks=["kick"], drum_keys={"kick": GM_DRUM_KEYS["kick"]}
    )

    found = events(chunks(data)[FIRST_PART][1])
    assert {d1 for status, d1, _ in found if status & 0xF0 == 0x90} == {36}


def test_a_melodic_part_never_lands_on_the_drum_channel():
    """Nine melodic parts would walk onto channel 10 if nothing stepped over it."""
    data = write_midi({f"part{i}": part(count=2, pitch=40 + i) for i in range(12)})

    for _tag, body in chunks(data)[FIRST_PART:]:
        assert DRUM_CHANNEL not in {status & 0x0F for status, _, _ in events(body)}


# --- the notes themselves ----------------------------------------------------------------


def test_a_note_shorter_than_a_tick_still_sounds():
    """A zero-length note is a note-on and note-off at the same instant, which is silence."""
    data = write_midi({"x": [NoteEvent(start_s=0.0, end_s=0.00001, pitch=60)]})
    found = events(chunks(data)[FIRST_PART][1])

    ons = [e for e in found if e[0] & 0xF0 == 0x90 and e[2] > 0]
    assert len(ons) == 1


def test_an_unwritable_pitch_cannot_reach_the_writer():
    """The guard for this lives a layer up, and that is the better place for it.

    `write_midi` skips a pitch outside 0-127 — a byte wraps silently, so 130 would become 2
    and land five octaves down as a wrong note. But `NoteEvent.__post_init__` already
    refuses to construct one, so that branch is unreachable belt-and-braces rather than the
    guarantee. This asserts where the guarantee actually is.
    """
    with pytest.raises(ValueError, match="outside MIDI range"):
        NoteEvent(0.0, 1.0, 130)


def test_velocity_is_never_zero_on_a_note_on():
    """A note-on at velocity zero *is* a note-off in MIDI, so a quiet note would vanish."""
    data = write_midi({"x": [NoteEvent(0.0, 1.0, 60, velocity=0)]})
    found = events(chunks(data)[FIRST_PART][1])

    ons = [e for e in found if e[0] & 0xF0 == 0x90]
    assert ons and all(velocity > 0 for _, _, velocity in ons)


def test_an_empty_part_is_a_valid_empty_track():
    data = write_midi({"silent": []})
    assert chunks(data)[FIRST_PART][0] == b"MTrk"


def test_the_tempo_reaches_the_file():
    body = chunks(write_midi({"x": part()}, tempo_bpm=140.0))[CONDUCTOR][1]
    at = body.index(b"\xff\x51\x03")
    assert int.from_bytes(body[at + 3 : at + 6], "big") == pytest.approx(60_000_000 / 140, rel=1e-4)


def test_a_nonsense_tempo_does_not_produce_a_broken_file():
    """`TimingEstimate` can report zero, and a zero here is a division by zero at best and a
    file no DAW opens at worst."""
    assert chunks(write_midi({"x": part()}, tempo_bpm=0.0))[0][0] == b"MThd"


# --- and one reader that is not us -------------------------------------------------------


def test_an_independent_parser_agrees():
    """Everything above is this module checking its own assumptions. `mido` is not."""
    mido = pytest.importorskip("mido")

    import io

    data = write_midi(
        {"bass": part(), "kick": [NoteEvent(i * 0.5, i * 0.5 + 0.1, 33) for i in range(8)]},
        tempo_bpm=120.0,
        drum_tracks=["kick"],
        drum_keys={"kick": 36},
    )
    parsed = mido.MidiFile(file=io.BytesIO(data))

    assert len(parsed.tracks) == 3
    by_name = {}
    for track in parsed.tracks:
        name = next((m.name for m in track if m.type == "track_name"), None)
        ons = [m for m in track if m.type == "note_on" and m.velocity > 0]
        if name and ons:
            by_name[name] = ons

    assert by_name["bass"][0].channel == 0
    assert by_name["bass"][0].note == 40
    assert by_name["kick"][0].channel == DRUM_CHANNEL
    assert {m.note for m in by_name["kick"]} == {36}
    assert parsed.length == pytest.approx(3.9, abs=0.2)
