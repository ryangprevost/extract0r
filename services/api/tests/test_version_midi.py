"""The version as MIDI. Sprint 4, X0R-1342.

What has to hold for the file to be the version that was heard: the tempo is the new tempo,
drums are on channel 10 with keys a drum rack plays as drums, added parts say they were
added, and the strokes of an added beat are exactly where the audio put them.
"""

from __future__ import annotations

import struct

import numpy as np

from app.domain.notes import NoteEvent
from app.services.drums.detect import Hit
from app.services.synth import drop
from app.services.synth import groove as g
from app.services.synth import version_midi as vm
from app.services.synth.retempo import beat_grid


def tracks(data: bytes) -> list[tuple[str, set[int]]]:
    """(name, channels) for each track of a format-1 file, read by hand."""
    out, at = [], 14
    while at < len(data):
        size = struct.unpack(">I", data[at + 4: at + 8])[0]
        body = data[at + 8: at + 8 + size]
        name, channels = "", set()
        if b"\xff\x03" in body:
            i = body.index(b"\xff\x03") + 2
            name = body[i + 1: i + 1 + body[i]].decode("ascii")
        channels = {b & 0x0F for i, b in enumerate(body[:-1])
                    if b & 0xF0 == 0x90 and i > 0}
        out.append((name, channels))
        at += 8 + size
    return out


def tempo_of(data: bytes) -> float:
    i = data.index(b"\xff\x51\x03") + 3
    return 60_000_000 / int.from_bytes(data[i: i + 3], "big")


def test_the_file_is_at_the_version_s_tempo():
    data, _ = vm.write(128.0, {"bass": [NoteEvent(0.0, 0.4, 40, 100)]})
    assert abs(tempo_of(data) - 128.0) < 0.01


def test_drums_and_added_parts_are_named_and_on_channel_ten():
    hits = [Hit(time_s=0.0, kinds=["kick"], strength=1.0),
            Hit(time_s=0.5, kinds=["snare", "hihat"], strength=0.5)]
    beat = vm.added_beat(g.events(g.BUILT_IN["house"], beat_grid(0.0, 128.0, 4.0)))
    data, contents = vm.write(128.0, {"bass": [NoteEvent(0.0, 0.4, 40, 100)]},
                              drums=vm.drummer(hits), beat=beat, beat_name="house beat")
    names = [name for name, _ in contents]
    assert names == ["bass", "house beat (added)", "drums (your drummer)"]
    by_name = dict(tracks(data))
    assert by_name["house beat (added)"] == {9}
    assert by_name["drums (your drummer)"] == {9}
    assert 9 not in by_name["bass"]


def test_the_drummer_s_strokes_become_general_midi_drums():
    notes = vm.drummer([Hit(time_s=0.0, kinds=["kick"], strength=1.0),
                        Hit(time_s=0.5, kinds=["snare", "cymbals"], strength=0.5)])
    assert [(n.pitch, n.velocity) for n in notes] == [(36, 127), (38, 64), (42, 64)]


def test_the_added_beat_is_where_the_audio_put_it():
    beats = beat_grid(0.0, 124.0, 8.0)
    strokes = g.events(g.BUILT_IN["techno"], beats, swing=0.5)
    notes = vm.added_beat(strokes)
    assert [n.start_s for n in notes] == [t for t, _, _ in strokes]


def test_the_build_ends_on_a_crash_where_the_drop_lands():
    beats = beat_grid(0.0, 128.0, 8 * 4 * 60 / 128)
    roll = drop.roll(beats, 128.0, drop_bar=5)
    notes = vm.build(roll, drop._window(beats, 5)[1])
    assert notes[-1].pitch == vm.GM["crash"]
    assert abs(notes[-1].start_s - 4 * 4 * 60 / 128) < 1e-6
    assert all(n.pitch == vm.GM["snare"] for n in notes[:-1])


def test_an_early_first_stroke_is_the_downbeat_not_dropped():
    """A reference's kick played a few ms ahead of its first beat came out before zero and
    was thrown away - the remix lost its first kick."""
    early = g.Groove.from_dict(g.BUILT_IN["four on the floor"].to_dict())
    early.steps["kick"][0].offset = -0.05
    strokes = g.events(early, beat_grid(0.0, 124.0, 4.0))
    assert strokes[0][0] == 0.0 and strokes[0][1] == "kick"


def test_nothing_pitched_and_no_drums_is_an_empty_file_not_an_error():
    data, contents = vm.write(120.0, {})
    assert contents == [] and data.startswith(b"MThd")
    assert np.isfinite(tempo_of(data))
