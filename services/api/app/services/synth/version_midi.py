"""The version as MIDI: every part of the remix as notes, at the new tempo. Sprint 4, X0R-1342.

The hand-off to a DAW. `GET /midi` already writes the *transcribed* song at its own tempo;
this writes the *remix* - the parts that were re-played, at the tempo they were re-played
at, plus the drummer's strokes and everything that was added (the beat, the roll into the
drop) - so somebody can open what they made in Ableton or FL Studio and keep going: swap a
synth, move a note, re-sequence a drum. That last one is the user's own work, and the reason
the file exists rather than a reason to do it here.

One track per part, named the way the page names it, drums on channel 10 with General MIDI
keys so any drum rack plays them as drums. Added parts say so in the track name, the same
promise the version's account makes.

What is not here, said rather than discovered: the riser and the impact are sounds rather
than notes, and the pump is a level change rather than a note - a DAW gets those from its
own sidechain and FX, and the file's account lists them.
"""

from __future__ import annotations

from app.domain.midi import write_midi
from app.domain.notes import NoteEvent
from app.services.drums.detect import Hit

#: General MIDI drum keys for the drums this application knows by name.
GM = {"kick": 36, "snare": 38, "hihat": 42, "cymbals": 42, "toms": 45, "crash": 49}
#: How long a drum note is held. Drum racks ignore it; some DAWs draw a zero-length note as
#: nothing at all.
DRUM_NOTE_S = 0.1


def _velocity(value: float) -> int:
    return int(max(1, min(127, round(value * 127))))


def drummer(hits: list[Hit]) -> list[NoteEvent]:
    """The drummer's strokes as GM drum notes, velocity from how hard each was struck."""
    loudest = max((h.strength for h in hits), default=0.0) or 1.0
    out = []
    for hit in hits:
        for kind in dict.fromkeys(hit.kinds):
            if kind in GM:
                out.append(NoteEvent(hit.time_s, hit.time_s + DRUM_NOTE_S, GM[kind],
                                     _velocity(hit.strength / loudest)))
    return out


def added_beat(strokes: list[tuple[float, str, float]]) -> list[NoteEvent]:
    """An added beat's strokes, from `groove.events`."""
    return [NoteEvent(t, t + DRUM_NOTE_S, GM[kind], _velocity(v))
            for t, kind, v in strokes if kind in GM]


def build(roll: list[tuple[float, float]], drop_s: float | None) -> list[NoteEvent]:
    """The snare roll into the drop, and a crash on its downbeat where the impact lands."""
    loudest = max((g for _, g in roll), default=1.0) or 1.0
    out = [NoteEvent(t, t + DRUM_NOTE_S, GM["snare"], _velocity(g / loudest)) for t, g in roll]
    if drop_s is not None:
        out.append(NoteEvent(drop_s, drop_s + 1.0, GM["crash"], 120))
    return out


def write(tempo_bpm: float, pitched: dict[str, list[NoteEvent]],
          drums: list[NoteEvent] | None = None, beat: list[NoteEvent] | None = None,
          beat_name: str = "beat", roll: list[NoteEvent] | None = None) -> tuple[bytes, list]:
    """The file, and what is in it as [(track, notes)] for the page to list."""
    tracks: dict[str, list[NoteEvent]] = {}
    for stem, notes in pitched.items():
        if notes:
            tracks[stem] = notes
    drum_tracks = []
    for name, notes in ((f"{beat_name} (added)", beat), ("drums (your drummer)", drums),
                        ("build into the drop (added)", roll)):
        if notes:
            tracks[name] = notes
            drum_tracks.append(name)
    return (write_midi(tracks, tempo_bpm=tempo_bpm, drum_tracks=drum_tracks),
            [(name, len(notes)) for name, notes in tracks.items()])
