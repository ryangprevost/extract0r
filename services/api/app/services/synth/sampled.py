"""A sound sampled from the reference, to play your parts on. Sprint 15.

Ryan: *"not loving the synth sounds honestly. can you allow for sampling a note of a synth in
the reference and applying that to the midi? thatd be huge."*

So the reference's separated parts are searched for **clean notes** - one pitch, held,
loud enough to be the part rather than leakage - and the ones you pick become an instrument
like any other in `instruments.py`: every note of your part played from the recording
nearest in pitch.

### What makes a note worth sampling

A separated stem is mostly notes on top of each other, the tail of the last note, and
whatever bled in from the other parts. A sample of that plays back as mush at every pitch.
So each note the transcriber found is scored on:

- **one note at a time** - another note sounding under it is two pitches in one sample;
- **harmonicity** - how much of its energy sits on the harmonics of its own pitch, which is
  high for a synth note and low for a chord, a drum bleeding through, or noise;
- **steadiness** - how far its pitch wanders while it is held, in cents;
- **length** - a longer note gives the sampler more to hold before it has to loop;
- **level** - against the part's own loud passages, so a quiet ghost of the lead in the
  bass stem is not offered as the lead.

### Made playable

A note is cut from just before its attack to the start of the next note, **tuned** to the
nearest semitone (the record may sit a few cents off concert pitch, and every note of your
part would inherit that), and, when it is shorter than a held note needs, **held by
looping** its steady middle with crossfades, the way a hardware sampler sustains.

### This one is sampled

Everywhere else extract0r analyzes the reference and never samples it. This is the one
exception, made because Ryan asked for it, and it is only ever made when you ask: the
person ticks that they may sample the recording, the instrument stays in your own samples
folder, its name says it came from the reference, and a version made with it says so.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
#: Notes shorter than this are hits, not notes a sampler can hold.
MIN_LENGTH_S = 0.18
#: How much of a held note the sampler may loop before it must have a longer source.
HOLD_S = 3.0
#: A candidate whose loud part is this far below the stem's loud passages is leakage.
MIN_LEVEL_DB = -18.0
#: At most this many candidates are offered.
OFFER = 12
#: The stems worth sampling a pitched sound from.
SAMPLEABLE = ("bass", "other", "piano", "guitar", "vocals")


def note_name(midi: int) -> str:
    return f"{NAMES[midi % 12]}{midi // 12 - 1}"


@dataclass
class Candidate:
    n: int
    start_s: float
    end_s: float
    pitch: int
    cents: float          # how far the recording sits from `pitch`
    clarity: float        # 0..1, the score used to rank
    harmonicity: float
    wander_cents: float
    level_db: float
    overlaps: int
    next_s: float         # the next note's start, where the cut must end

    @property
    def name(self) -> str:
        return note_name(self.pitch)

    def to_dict(self) -> dict:
        out = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in asdict(self).items()}
        out["name"] = self.name
        out["length_s"] = round(self.end_s - self.start_s, 2)
        return out

    @classmethod
    def from_dict(cls, data: dict) -> Candidate:
        fields = cls.__dataclass_fields__
        return cls(**{k: data[k] for k in fields})


# --- measuring ------------------------------------------------------------------------------


def _mono(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float64)
    return audio.mean(axis=1) if audio.ndim == 2 else audio


def _db(x: float) -> float:
    return 20.0 * np.log10(max(x, 1e-12))


def refine_hz(segment: np.ndarray, sample_rate: int, expected_hz: float) -> float | None:
    """The pitch of a short frame, searched within a semitone of what the transcriber said:
    the autocorrelation's peak between those lags, sharpened by a parabola through it.
    None when that peak is too weak to be a pitch at all."""
    if segment.size < 64 or expected_hz <= 0:
        return None
    frame = segment - segment.mean()
    energy = float(np.dot(frame, frame))
    if energy <= 1e-12:
        return None
    size = 1 << int(np.ceil(np.log2(2 * frame.size)))
    spectrum = np.fft.rfft(frame, size)
    ac = np.fft.irfft(spectrum * np.conj(spectrum), size)[: frame.size]
    ac /= ac[0]
    semitone = 2 ** (1 / 12)
    lo = max(2, int(sample_rate / (expected_hz * semitone)))
    hi = min(frame.size - 2, int(np.ceil(sample_rate / (expected_hz / semitone))))
    if hi <= lo:
        return None
    lag = lo + int(np.argmax(ac[lo: hi + 1]))
    if ac[lag] < 0.3:
        return None
    a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
    shift = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
    return sample_rate / (lag + float(np.clip(shift, -0.5, 0.5)))


def harmonicity(segment: np.ndarray, sample_rate: int, hz: float) -> float:
    """The share of the segment's energy within 3% of its own harmonics, up to 20 of them."""
    frame = (segment - segment.mean()) * np.hanning(segment.size)
    power = np.abs(np.fft.rfft(frame)) ** 2
    freqs = np.fft.rfftfreq(segment.size, 1.0 / sample_rate)
    band = (freqs > hz * 0.5) & (freqs < min(sample_rate / 2, hz * 21))
    total = float(power[band].sum())
    if total <= 0:
        return 0.0
    near = np.zeros_like(band)
    for k in range(1, 21):
        near |= np.abs(freqs - k * hz) <= 0.03 * k * hz
    return float(power[band & near].sum() / total)


def _pitch_track(mono: np.ndarray, sample_rate: int, start_s: float, end_s: float,
                 expected_hz: float) -> list[float]:
    """The pitch every 40 ms across a note, skipping its attack."""
    frame = int(0.05 * sample_rate)
    hop = int(0.04 * sample_rate)
    out = []
    at = int((start_s + 0.03) * sample_rate)
    stop = int(end_s * sample_rate) - frame
    while at <= stop:
        hz = refine_hz(mono[at: at + frame], sample_rate, expected_hz)
        if hz:
            out.append(hz)
        at += hop
    return out


def find_candidates(audio: np.ndarray, sample_rate: int, notes) -> list[Candidate]:
    """The notes of a stem worth sampling, best first, at most one per pitch and `OFFER` in
    all. `notes` are the transcriber's NoteEvents for the same stem."""
    mono = _mono(audio)
    frame = int(0.05 * sample_rate)
    if mono.size < frame * 4:
        return []
    rms = np.sqrt(np.convolve(mono ** 2, np.ones(frame) / frame, mode="valid")[::frame])
    loud = float(np.percentile(rms, 90)) or 1e-9
    ordered = sorted(notes, key=lambda n: n.start_s)
    starts = [n.start_s for n in ordered]

    found: list[Candidate] = []
    for i, note in enumerate(ordered):
        length = note.end_s - note.start_s
        if length < MIN_LENGTH_S or not 24 <= note.pitch <= 96:
            continue
        overlaps = sum(1 for other in ordered if other is not note
                       and other.start_s < note.end_s - 0.03
                       and other.end_s > note.start_s + 0.03
                       and (other.pitch - note.pitch) % 12 != 0)
        if overlaps > 1:
            continue
        a = int(note.start_s * sample_rate)
        b = int(min(note.end_s, note.start_s + 2.0) * sample_rate)
        segment = mono[a:b]
        if segment.size < frame:
            continue
        level = _db(float(np.sqrt(np.mean(segment ** 2))) / loud)
        if level < MIN_LEVEL_DB:
            continue
        expected = 440.0 * 2 ** ((note.pitch - 69) / 12)
        track = _pitch_track(mono, sample_rate, note.start_s, min(note.end_s, note.start_s + 2.0),
                             expected)
        if len(track) < max(2, int(0.5 * (length - 0.03) / 0.04)):
            continue       # mostly unpitched: noise, a hit, or two notes beating
        cents = 1200 * np.log2(np.asarray(track) / expected)
        middle = float(np.median(cents))
        if abs(middle) > 50:
            continue       # the transcriber's pitch was not this note's
        wander = float(np.std(cents))
        hz = expected * 2 ** (middle / 1200)
        harm = harmonicity(segment, sample_rate, hz)
        steady = max(0.0, 1.0 - wander / 40.0)
        held = min(length, 1.5) / 1.5
        clarity = 0.45 * harm + 0.25 * steady + 0.2 * held + 0.1 * min(1.0, (level + 18) / 18)
        clarity -= 0.15 * overlaps
        next_s = next((s for s in starts[i + 1:] if s > note.start_s + 0.05),
                      len(mono) / sample_rate)
        found.append(Candidate(0, note.start_s, note.end_s, int(note.pitch), middle,
                               float(np.clip(clarity, 0, 1)), harm, wander, level, overlaps,
                               next_s))

    best: dict[int, Candidate] = {}
    for c in sorted(found, key=lambda c: -c.clarity):
        best.setdefault(c.pitch, c)
    offered = sorted(best.values(), key=lambda c: -c.clarity)[:OFFER]
    for n, c in enumerate(offered):
        c.n = n
    return offered


# --- cutting --------------------------------------------------------------------------------


def _attack(mono: np.ndarray, sample_rate: int, around_s: float) -> int:
    """Where the note actually starts: the steepest rise in level within 30 ms of where the
    transcriber put it, so the sample keeps its attack rather than starting inside it."""
    hop = max(1, int(0.002 * sample_rate))
    lo = max(0, int((around_s - 0.03) * sample_rate))
    hi = min(mono.size - hop, int((around_s + 0.03) * sample_rate))
    if hi - lo < 3 * hop:
        return lo
    level = np.array([np.sqrt(np.mean(mono[k: k + hop] ** 2)) for k in range(lo, hi, hop)])
    rise = np.diff(level)
    return max(0, lo + int(np.argmax(rise)) * hop - int(0.005 * sample_rate))


def _retune(signal: np.ndarray, cents: float) -> np.ndarray:
    """Moved by `-cents`, so the note sits on the semitone."""
    if abs(cents) < 1.0:
        return signal
    from app.services.synth.samples import _resample

    return _resample(signal, 2 ** (-cents / 1200))


def _hold(signal: np.ndarray, sample_rate: int, sustain_from: int, sustain_to: int,
          seconds: float) -> np.ndarray:
    """`signal` held to `seconds` by looping [sustain_from, sustain_to) with crossfades."""
    want = int(seconds * sample_rate)
    loop = signal[sustain_from:sustain_to]
    fade = min(int(0.03 * sample_rate), loop.size // 3)
    if signal.size >= want or loop.size < 4 * fade or fade < 8:
        return signal
    out = signal[:sustain_to].copy()
    ramp_in = np.sqrt(np.linspace(0.0, 1.0, fade))
    ramp_out = ramp_in[::-1]
    while out.size < want:
        joined = out[-fade:] * ramp_out + loop[:fade] * ramp_in
        out = np.concatenate([out[:-fade], joined, loop[fade:]])
    return out[:want]


def cut(audio: np.ndarray, sample_rate: int, c: Candidate) -> np.ndarray:
    """A candidate as a playable sample: from its attack to just before the next note,
    tuned to the semitone, held by looping when it is short, faded at the end, normalized."""
    mono = _mono(audio)
    start = _attack(mono, sample_rate, c.start_s)
    end = int(min(c.next_s - 0.005, c.end_s + 0.4, c.start_s + HOLD_S) * sample_rate)
    end = max(end, start + int(MIN_LENGTH_S * sample_rate))
    note = mono[start:end].copy()
    held_to = min(note.size, int((c.end_s - c.start_s) * sample_rate))
    sustain_from = int(0.08 * sample_rate)
    sustain_to = held_to - int(0.03 * sample_rate)
    if sustain_to - sustain_from > int(0.12 * sample_rate) and c.wander_cents < 25:
        tail = note[held_to:]
        body = _hold(note[:held_to], sample_rate, sustain_from, sustain_to, HOLD_S)
        note = np.concatenate([body, tail]) if body.size > held_to else note
    note = _retune(note, c.cents)
    edge = min(note.size, max(1, int(0.002 * sample_rate)))
    note[:edge] *= np.linspace(0.0, 1.0, edge)
    out_len = min(note.size, max(1, int(0.08 * sample_rate)))
    note[-out_len:] *= np.linspace(1.0, 0.0, out_len)
    peak = float(np.max(np.abs(note))) or 1.0
    return note / peak * 0.9


# --- an instrument --------------------------------------------------------------------------


def kind_for(stem: str, candidates: list[Candidate]) -> str:
    if stem == "bass":
        return "bass"
    if stem == "piano":
        return "keys"
    if stem == "guitar":
        return "pluck"
    held = np.median([c.end_s - c.start_s for c in candidates]) if candidates else 0.0
    return "pad" if held > 1.2 else "lead"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "sound"


def make_instrument(sample_dir: Path, name: str, stem: str, reference_name: str,
                    picks: list[tuple[Candidate, np.ndarray]], sample_rate: int,
                    notice: str, track_id: str) -> str:
    """Write `picks` as an instrument in the samples folder - never the repository - and
    return its id. Its name and its `origin` say it came from the reference."""
    import soundfile as sf

    from app.services.synth.instruments import instrument_dir

    base = f"ref-{slug(name)}"
    folder = instrument_dir(sample_dir) / base
    k = 2
    while folder.exists():
        folder = instrument_dir(sample_dir) / f"{base}-{k}"
        k += 1
    folder.mkdir(parents=True)
    notes = {}
    for c, audio in picks:
        file = f"{c.pitch}.wav"
        sf.write(str(folder / file), audio, sample_rate, subtype="PCM_24")
        notes[str(c.pitch)] = file
    names = ", ".join(note_name(c.pitch) for c, _ in sorted(picks, key=lambda p: p[0].pitch))
    meta = {
        "name": name,
        "kind": kind_for(stem, [c for c, _ in picks]),
        "about": f"Sampled from the {stem} of your reference ({reference_name}): {names}.",
        "source": reference_name,
        "license": notice,
        "origin": "reference",
        # Deleted with the track it was sampled from - see `forget_missing`.
        "track_id": track_id,
        "notes": notes,
        "picked": [{"start_s": round(c.start_s, 3), "pitch": c.pitch,
                    "cents": round(c.cents, 1)} for c, _ in picks],
    }
    (folder / "instrument.json").write_text(json.dumps(meta, indent=2), "utf-8")
    return folder.name


def forget_missing(sample_dir: Path | None, storage_root: Path) -> list[str]:
    """Delete every instrument sampled from a reference whose track is gone.

    The terms promise that an upload and everything derived from it are deleted after the
    retention window, or at once when the person deletes the track. A sampled instrument is
    derived from the reference, so it goes with the track: this runs after every retention
    sweep and every delete."""
    import shutil

    from app.services.synth.instruments import instrument_dir

    gone = []
    if sample_dir is None or not instrument_dir(sample_dir).exists():
        return gone
    for meta in instrument_dir(sample_dir).glob("*/instrument.json"):
        try:
            data = json.loads(meta.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        track = data.get("track_id")
        mine = data.get("origin") == "reference" and track
        if mine and not (Path(storage_root) / track).exists():
            shutil.rmtree(meta.parent, ignore_errors=True)
            gone.append(meta.parent.name)
    return gone
