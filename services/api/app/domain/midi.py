"""Write a standard MIDI file. X0R-503.

No dependency. A MIDI file is a header, a list of tracks, and inside each track a run of
delta-time-prefixed events — all of it bytes this module can pack itself, which keeps
`app/domain/` free of third-party imports under the X0R-102 rule and keeps `mido` out of a
project that would use it for exactly one function.

### Why this card is suddenly load-bearing

It was two points in EPIC-05 next to MusicXML, and it is now the seam of stage 4B. The
measurement that settled that stage found separation leaves recall at 1.000 and pitch
accuracy at the clean ceiling: the notes are *right*. What this application will not do is
re-sequence them or change their tempo, because measuring where a reference's kick sits is
a measurement and moving the user's kick there is composition.

A MIDI file is where those two facts meet. The app hands over notes it can stand behind;
the arrangement happens in a DAW, where it is the user's work and not an inference. That is
a better answer than a re-sequencer this project has argued twice that it should not build.

### What is deliberately not written

* **Tempo, beyond a single set-tempo event.** `TimingEstimate` carries one number for the
  clip, X0R-1319 measured that number to be wrong on live material, and a tempo map exists
  but is not what this takes. Writing a tempo curve nobody has validated into a file that
  looks authoritative in a DAW is worse than writing one honest number and letting the user
  set the grid.
* **Note offsets anybody should trust.** `transcription_score` does not score them and says
  why: *none of this project's transcribers claims to know when a note stopped.* The
  durations here are what the transcriber returned, and that is all they are.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable

from app.domain.notes import NoteEvent

#: Ticks per quarter note. 480 is the common DAW value and divides cleanly by 2, 3, 4 and 5,
#: so a triplet lands on an integer tick instead of a rounding error.
TICKS_PER_BEAT = 480

#: General MIDI puts the drum kit on channel 10, which is index 9. Nothing else about GM is
#: honoured here, but this one is load-bearing: a drum track on any other channel opens in a
#: DAW as a melody played on a piano.
DRUM_CHANNEL = 9

#: GM percussion keys for the four drums this project separates. A kick written as MIDI 36
#: lands on a kick in every sampler ever made; written as its own pitch it lands on nothing.
GM_DRUM_KEYS = {"kick": 36, "snare": 38, "cymbals": 42, "toms": 45, "hihat": 42}


def _varlen(value: int) -> bytes:
    """MIDI's variable-length quantity: seven bits a byte, high bit set to mean 'more'."""
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def _chunk(tag: bytes, body: bytes) -> bytes:
    return tag + struct.pack(">I", len(body)) + body


def _track(
    notes: Iterable[NoteEvent],
    seconds_per_tick: float,
    name: str,
    channel: int,
    pitch_map: dict[int, int] | None = None,
) -> bytes:
    """One track: a name, then every note-on and note-off in time order."""
    events: list[tuple[int, int, int, int]] = []
    for note in notes:
        pitch = (pitch_map or {}).get(note.pitch, note.pitch)
        if not 0 <= pitch <= 127:
            continue
        on = max(0, int(round(note.start_s / seconds_per_tick)))
        off = max(on + 1, int(round(note.end_s / seconds_per_tick)))
        velocity = max(1, min(127, note.velocity))
        # Note-off sorts before note-on at the same tick, so a repeated pitch retriggers
        # instead of the second note-off killing the first note's sound.
        events.append((on, 1, pitch, velocity))
        events.append((off, 0, pitch, 0))
    events.sort(key=lambda e: (e[0], e[1]))

    body = bytearray()
    label = name.encode("ascii", "replace")[:127]
    body += _varlen(0) + b"\xff\x03" + _varlen(len(label)) + label

    previous = 0
    for tick, is_on, pitch, velocity in events:
        body += _varlen(tick - previous)
        body += bytes([(0x90 if is_on else 0x80) | (channel & 0x0F), pitch, velocity])
        previous = tick

    body += _varlen(0) + b"\xff\x2f\x00"
    return _chunk(b"MTrk", bytes(body))


def write_midi(
    tracks: dict[str, list[NoteEvent]],
    tempo_bpm: float = 120.0,
    drum_tracks: Iterable[str] = (),
    drum_keys: dict[str, int] | None = None,
) -> bytes:
    """A multi-track MIDI file, one track per named part.

    Format 1 - a tempo track followed by named instrument tracks, which is what a DAW
    expects when it offers to put each part on its own channel.

    `drum_tracks` names the parts to send to channel 10. `drum_keys` maps a drum's *name* to
    a GM key for the single-pitch case, because a separated kick stem transcribes to whatever
    pitch its fundamental happened to be and that is not a kick anywhere downstream.
    """
    tempo_bpm = tempo_bpm if tempo_bpm > 0 else 120.0
    seconds_per_tick = 60.0 / tempo_bpm / TICKS_PER_BEAT
    microseconds_per_beat = int(round(60_000_000 / tempo_bpm))

    conductor = bytearray()
    conductor += _varlen(0) + b"\xff\x51\x03" + struct.pack(">I", microseconds_per_beat)[1:]
    conductor += _varlen(0) + b"\xff\x58\x04" + bytes([4, 2, 24, 8])
    conductor += _varlen(0) + b"\xff\x2f\x00"

    drums = set(drum_tracks)
    chunks = [_chunk(b"MTrk", bytes(conductor))]
    channel = 0
    for name, notes in tracks.items():
        is_drums = name in drums
        mapped = None
        if is_drums and drum_keys and name in drum_keys:
            # Every pitch in this part collapses to one GM key: a separated kick is one
            # drum however its fundamental was transcribed.
            mapped = {note.pitch: drum_keys[name] for note in notes}
        chunks.append(
            _track(
                notes,
                seconds_per_tick,
                name,
                DRUM_CHANNEL if is_drums else channel,
                mapped,
            )
        )
        if not is_drums:
            channel += 1
            if channel == DRUM_CHANNEL:
                channel += 1  # step over the drum channel rather than land a guitar on it
            channel %= 16

    header = struct.pack(">HHH", 1, len(chunks), TICKS_PER_BEAT)
    return _chunk(b"MThd", header) + b"".join(chunks)
