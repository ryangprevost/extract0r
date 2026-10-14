"""Real synths: multisampled instruments a part can be played on. Sprint 12.

Ryan: *"can you please find some actual synth samples (they're usually just a bunch of C
notes) that can be used as starting points? i want this to sound like the style and i dont
know a lot about configuring tones with synths."*

An instrument is a folder of recorded notes from one real synth patch - a MicroBrute bass, a
TX81Z electric piano, a Jupiter-style stack - with an `instrument.json` saying what it is,
where it came from and under what licence. A part played on it uses, for every note, the
recording nearest in pitch and moves it the rest of the way, so a note is never stretched
far from something the synth actually played: that is what a sampler does, and why a
multisampled instrument sounds like the synth across its whole range where one C note
transposed two octaves sounds like a mistake.

### Nothing recorded ships

The same line `kit.py` and `samples.py` draw. Instruments live in the user's own samples
folder - outside the repository and outside retention - put there by `tools/
import_instruments.py` from sources the user chose, every one public domain or CC0, with the
licence kept beside the notes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.domain.notes import NoteEvent

INSTRUMENT_DIR = "instruments"
#: How far a recording may be moved to reach a note. A multisample is a few semitones apart
#: at most; past this the nearest recording is still used, and counted.
FAR_SEMITONES = 12.0
#: How a note ends when its key is let go, by what kind of instrument it is. A pad that
#: stopped dead would click and sound like a mistake; a bass that rang on would smear.
RELEASE_S = {"pad": 0.35, "strings": 0.3, "keys": 0.12, "lead": 0.08, "stack": 0.12,
             "bass": 0.05, "pluck": 0.05}


@dataclass
class Instrument:
    id: str
    name: str
    kind: str
    about: str
    source: str
    license: str
    #: Recorded notes: MIDI pitch -> file name inside the instrument's folder.
    notes: dict[int, str] = field(default_factory=dict)
    folder: Path | None = None
    #: "reference" for a sound sampled from the person's reference (Sprint 15), else "".
    origin: str = ""
    #: The track whose reference it was sampled from (Sprint 21), else "".
    track_id: str = ""
    #: Sprint 22: how the person tuned it - see `TWEAKS`. Applied whenever it plays; the
    #: recordings themselves are never changed, so "Reset" is always one press away.
    tweak: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind, "about": self.about,
                "source": self.source, "license": self.license,
                "range": [min(self.notes), max(self.notes)] if self.notes else None,
                "recorded_notes": len(self.notes), "origin": self.origin,
                "track_id": self.track_id, "tweak": dict(self.tweak)}


def instrument_dir(sample_dir: Path) -> Path:
    return Path(sample_dir) / INSTRUMENT_DIR


def installed(sample_dir: Path | None) -> dict[str, Instrument]:
    """Every instrument in the samples folder, by id."""
    out = {}
    if sample_dir is None or not instrument_dir(sample_dir).exists():
        return out
    for meta in sorted(instrument_dir(sample_dir).glob("*/instrument.json")):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            notes = {int(k): v for k, v in data["notes"].items()
                     if (meta.parent / v).exists()}
            if not notes:
                continue
            out[meta.parent.name] = Instrument(
                id=meta.parent.name, name=data["name"], kind=data.get("kind", "keys"),
                about=data.get("about", ""), source=data.get("source", ""),
                license=data.get("license", ""), notes=notes, folder=meta.parent,
                origin=data.get("origin", ""), track_id=data.get("track_id", ""),
                tweak=clean_tweak(data.get("tweak") or {}))
        except Exception:  # noqa: BLE001 - one damaged instrument should not hide the rest
            continue
    return out


def find(name: str, sample_dir: Path | None) -> Instrument | None:
    return installed(sample_dir).get(name)


# --- Sprint 22: tuning a sound ------------------------------------------------------------------

#: Ryan: *"the ability to fine tune the EQ, length, pitch, etc on an extracted sample from the
#: reference song would be great."* Each setting: (lowest, highest, what changes nothing).
TWEAKS = {
    "semitones": (-12.0, 12.0, 0.0),     # the whole sound moved, in semitones
    "cents": (-50.0, 50.0, 0.0),         # and finely, in cents
    "start_ms": (0.0, 300.0, 0.0),       # skip into each recording - past a messy attack
    "attack_ms": (0.0, 500.0, 0.0),      # fade each note in
    "max_s": (0.0, 3.0, 0.0),            # cut every note at this length; 0 lets it ring
    "release_ms": (0.0, 2000.0, -1.0),   # how long a note fades after it ends; -1 = its kind's
    "low_cut_hz": (0.0, 1000.0, 0.0),    # high-pass; 0 is off
    "high_cut_hz": (0.0, 20000.0, 0.0),  # low-pass; 0 is off
    "bass_db": (-12.0, 12.0, 0.0),       # low shelf at 200 Hz
    "treble_db": (-12.0, 12.0, 0.0),     # high shelf at 4 kHz
}


def clean_tweak(raw: dict) -> dict:
    """Only known settings, each held in its range; settings at "no change" are dropped."""
    out = {}
    for name, (low, high, neutral) in TWEAKS.items():
        if name not in raw:
            continue
        try:
            value = float(raw[name])
        except (TypeError, ValueError):
            continue
        value = min(max(value, low), high) if not (name == "release_ms" and value < 0) else -1.0
        if value != neutral:
            out[name] = value
    return out


def _shelf(kind: str, hz: float, gain_db: float, sample_rate: int):
    """RBJ shelving biquad, slope 1."""
    a = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * hz / sample_rate
    cos, alpha = np.cos(w0), np.sin(w0) / 2 * np.sqrt(2)
    sq = 2 * np.sqrt(a) * alpha
    if kind == "low":
        b = [a * ((a + 1) - (a - 1) * cos + sq), 2 * a * ((a - 1) - (a + 1) * cos),
             a * ((a + 1) - (a - 1) * cos - sq)]
        d = [(a + 1) + (a - 1) * cos + sq, -2 * ((a - 1) + (a + 1) * cos),
             (a + 1) + (a - 1) * cos - sq]
    else:
        b = [a * ((a + 1) + (a - 1) * cos + sq), -2 * a * ((a - 1) + (a + 1) * cos),
             a * ((a + 1) + (a - 1) * cos - sq)]
        d = [(a + 1) - (a - 1) * cos + sq, 2 * ((a - 1) - (a + 1) * cos),
             (a + 1) - (a - 1) * cos - sq]
    return np.array(b) / d[0], np.array(d) / d[0]


def tweak_recording(audio: np.ndarray, sample_rate: int, tweak: dict) -> np.ndarray:
    """One recording skipped into and faded in. Pitch, length and release act per note in the
    renderer; the EQ on what it plays (`tweak_tone`)."""
    if not tweak:
        return audio
    out = np.asarray(audio, dtype=np.float64)
    start = int(tweak.get("start_ms", 0.0) / 1000 * sample_rate)
    if 0 < start < out.size - 16:
        out = out[start:].copy()
        edge = min(out.size, max(1, int(0.002 * sample_rate)))
        out[:edge] *= np.linspace(0.0, 1.0, edge)
    attack = int(tweak.get("attack_ms", 0.0) / 1000 * sample_rate)
    if attack > 0:
        n = min(attack, out.size)
        out = out.copy()
        out[:n] *= np.linspace(0.0, 1.0, n)
    return out


def tweak_tone(audio: np.ndarray, sample_rate: int, tweak: dict) -> np.ndarray:
    """The EQ, on the played part - after each note is pitched, as a sampler's filter is, so a
    1 kHz cut is at 1 kHz whatever note plays (on the recordings it moved with the pitch)."""
    if not tweak:
        return audio
    from scipy.signal import butter, lfilter, sosfilt

    out = np.asarray(audio, dtype=np.float64)
    nyquist = sample_rate / 2
    if 0 < tweak.get("low_cut_hz", 0) < nyquist * 0.95:
        out = sosfilt(butter(2, tweak["low_cut_hz"] / nyquist, "high", output="sos"), out)
    if 0 < tweak.get("high_cut_hz", 0) < nyquist * 0.95:
        out = sosfilt(butter(2, tweak["high_cut_hz"] / nyquist, "low", output="sos"), out)
    if tweak.get("bass_db"):
        b, d = _shelf("low", 200.0, tweak["bass_db"], sample_rate)
        out = lfilter(b, d, out)
    if tweak.get("treble_db"):
        b, d = _shelf("high", min(4000.0, nyquist * 0.8), tweak["treble_db"], sample_rate)
        out = lfilter(b, d, out)
    return out


def _load(instrument: Instrument, sample_rate: int) -> dict[int, np.ndarray]:
    import soundfile as sf

    out = {}
    for pitch, name in instrument.notes.items():
        audio, rate = sf.read(str(instrument.folder / name), dtype="float64", always_2d=True)
        mono = audio.mean(axis=1)
        if rate != sample_rate:
            from math import gcd

            from scipy.signal import resample_poly

            g = gcd(int(rate), int(sample_rate))
            mono = resample_poly(mono, sample_rate // g, rate // g)
        out[pitch] = tweak_recording(mono, sample_rate, instrument.tweak)
    return out


def nearest(roots: list[int], pitch: float) -> int:
    """The recorded note to play `pitch` from: the closest; between two equally close, the
    one below, because a recording sped up a little keeps its attack where one slowed down
    softens it."""
    return min(roots, key=lambda r: (abs(r - pitch), r > pitch))


def octaves_to_fit(notes: list[NoteEvent], instrument: Instrument) -> int:
    """How many octaves to move a part so it sits in the range the instrument was recorded
    in - 0 when it already does. Whole octaves, so the harmony is unchanged: a producer puts
    a chord part an octave down on a pad sampled lower rather than stretch every note of it.
    Found on the first real-synth remix: a pad recorded from C2 to C4 was given chords
    around E4-G5, and half its notes were stretched more than an octave."""
    if not notes or not instrument.notes:
        return 0
    low, high = min(instrument.notes), max(instrument.notes)
    middle = float(np.median([n.pitch for n in notes]))
    reach = FAR_SEMITONES / 2

    def fits(k: int) -> bool:
        return low - reach <= middle + 12 * k <= high + reach

    # The smallest move that fits: an octave down rather than two, so a chord part on a pad
    # recorded lower keeps as much of its register as it can and does not turn to mud.
    for k in sorted(range(-4, 5), key=abs):
        if fits(k):
            return k
    centre = (low + high) / 2
    return int(round((centre - middle) / 12.0))


def render(notes: list[NoteEvent], instrument: Instrument, sample_rate: int,
           duration_s: float) -> tuple[np.ndarray, int, int]:
    """A part played on the instrument. Returns mono audio, how many notes still had to be
    reached from a recording more than an octave away, and the octaves the part was moved
    to sit in the instrument's range (see `octaves_to_fit`)."""
    from app.services.synth.samples import _resample

    shift = octaves_to_fit(notes, instrument)
    if shift:
        notes = [NoteEvent(n.start_s, n.end_s, n.pitch + 12 * shift, n.velocity)
                 for n in notes]

    out = np.zeros(int(duration_s * sample_rate) + sample_rate)
    recorded = _load(instrument, sample_rate)
    roots = sorted(recorded)
    release = int(RELEASE_S.get(instrument.kind, 0.08) * sample_rate)
    # Sprint 22: the person's tuning - a pitch move, a release, a longest note.
    tw = instrument.tweak
    if tw.get("release_ms", -1.0) >= 0:
        release = int(tw["release_ms"] / 1000 * sample_rate)
    detune = tw.get("semitones", 0.0) + tw.get("cents", 0.0) / 100.0
    longest = int(tw.get("max_s", 0.0) * sample_rate)
    far = 0
    for note in notes:
        root = nearest(roots, note.pitch)
        if abs(note.pitch - root) > FAR_SEMITONES:
            far += 1
        voice = _resample(recorded[root], 2.0 ** ((note.pitch - root + detune) / 12.0))
        held = int(max(note.end_s - note.start_s, 0.02) * sample_rate)
        if longest:
            held = min(held, longest)
        piece = voice[: held + release].copy()
        if piece.size > held:
            tail = piece.size - held
            piece[held:] *= np.linspace(1.0, 0.0, tail)
        edge = min(piece.size, max(1, int(0.002 * sample_rate)))
        piece[:edge] *= np.linspace(0.0, 1.0, edge)
        at = int(note.start_s * sample_rate)
        room = min(piece.size, out.size - at)
        if room > 0:
            out[at: at + room] += piece[:room] * (note.velocity / 127.0)
    out = tweak_tone(out, sample_rate, instrument.tweak)
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 1.0:
        out /= peak
    return out[: int(duration_s * sample_rate)], far, shift


def preview(instrument: Instrument, sample_rate: int) -> np.ndarray:
    """A short phrase in the instrument's own register: an arpeggio, then the chord held."""
    low = instrument.kind == "bass"
    middle = sorted(instrument.notes)[len(instrument.notes) // 2]
    root = 36 if low else max(48, min(60, middle))
    steps = [0, 7, 12, 7] if low else [0, 4, 7, 12]
    notes = [NoteEvent(i * 0.25, i * 0.25 + 0.22, root + s, 100) for i, s in enumerate(steps)]
    notes += [NoteEvent(1.0, 2.4, root + s, 90) for s in ([0] if low else [0, 4, 7])]
    audio, _, _ = render(notes, instrument, sample_rate, 3.0)
    return audio / max(float(np.max(np.abs(audio))), 1e-9) * 0.89
