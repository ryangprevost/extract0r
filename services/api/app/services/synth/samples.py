"""Play a transcribed part on a sample the user brought. X0R-1326.

Ryan: *"also allow for samples to be uploaded for the replacement"*.

### Why this is allowed when shipping a sample library is not

`drums/kit.py` refuses to ship recorded hits, and the argument is about *whose* recording it
is: shipping a library means shipping someone's audio, with the licensing that implies and
no way for anyone to check where it came from. A user's own upload is the one case that was
never in question - it is their file, the way a reference track is their file, and it goes
behind the same rights attestation that `X0R-202` already requires for one.

So the rule this module keeps is narrow and absolute: **nothing here is distributed.**
Samples live outside `storage_dir` so retention cannot delete them, outside the repository
so git cannot carry them, and nothing about them reaches a master's tags or a profile.

### The two modes, and why the user picks rather than the code guessing

A sample played at one pitch and retriggered is a drum machine. A sample repitched per note
is a sampler. Which one somebody wants is not inferable from the audio - a one-second vocal
chop is either, depending on the part - and guessing wrong produces something confidently
wrong rather than obviously wrong.

### The repitch cap is the honest part

Repitching by resampling moves the formants with the pitch, so a sample stretched far enough
stops sounding like itself and starts sounding like a mistake. `MAX_SHIFT_SEMITONES` is where
that is admitted rather than hidden: outside it, the note is dropped and the count of dropped
notes is reported, because a part that silently thinned out is worse than one that says it
could not reach.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.domain.notes import NoteEvent
from app.services.synth.voice import hz

#: How far a sample may be moved from its own pitch, in semitones either way. An octave is
#: already audibly a different instrument; two is a special effect. Beyond this the note is
#: dropped and counted rather than played badly.
MAX_SHIFT_SEMITONES = 12.0

#: A sample longer than this is a loop or a phrase, not an instrument, and triggering it per
#: note produces a wall rather than a part. Refused at upload with that said plainly.
MAX_SAMPLE_S = 10.0

#: Fade on each end of a triggered copy, so retriggering does not click.
EDGE_S = 0.004


@dataclass(frozen=True, slots=True)
class Sample:
    """One uploaded sample and what is known about it."""

    name: str
    path: Path
    sample_rate: int
    duration_s: float
    #: The pitch it was recorded at, as a MIDI number, or None when it has no clear pitch -
    #: a snare, a clap, a noise hit. Detected, then overridable, because the detector is
    #: right most of the time and the user is right all of the time.
    root_midi: float | None = None

    @property
    def pitched(self) -> bool:
        return self.root_midi is not None


def detect_root(samples: np.ndarray, sample_rate: int) -> float | None:
    """The MIDI pitch a sample sits at, or None if it has no clear one.

    A plain spectral peak with a check that the peak is actually dominant. Deliberately not
    a pitch tracker: this runs on upload, librosa is an ML-venv dependency, and the answer
    is overridable by the user anyway. A snare returns None here and that is correct - it
    should be triggered, not transposed.
    """
    mono = samples.mean(axis=1) if samples.ndim > 1 else samples
    if mono.size < sample_rate // 20:
        return None

    windowed = mono[: sample_rate * 2] * np.hanning(min(mono.size, sample_rate * 2))
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(windowed.size, 1 / sample_rate)

    usable = (freqs > 40.0) & (freqs < 4000.0)
    if not usable.any():
        return None
    band = spectrum[usable]
    peak = float(freqs[usable][int(np.argmax(band))])

    # Dominant, not merely largest. Noise has a largest bin too, and calling it a pitch is
    # how a snare ends up transposed across two octaves.
    if band.max() < 6.0 * float(np.median(band)) or peak <= 0:
        return None
    return 69.0 + 12.0 * math.log2(peak / 440.0)


def _resample(audio: np.ndarray, ratio: float) -> np.ndarray:
    """Play the sample faster or slower, which moves its pitch.

    Linear interpolation. It is not the best resampler available and it is the right one
    here: `soxr` is a dependency this project already has, but the whole point of the cap
    above is that we only ever move a sample a little, and over a few semitones the
    difference is inaudible against the far larger change of the formants moving.
    """
    if ratio == 1.0 or audio.size == 0:
        return audio
    length = max(1, int(audio.size / ratio))
    source = np.arange(length) * ratio
    return np.interp(source, np.arange(audio.size), audio).astype(np.float64)


def render_with_sample(
    notes: list[NoteEvent],
    sample: Sample,
    audio: np.ndarray,
    sample_rate: int,
    duration_s: float,
    pitched: bool | None = None,
) -> tuple[np.ndarray, int]:
    """A part, played on the sample. Returns the audio and how many notes were out of range.

    `pitched` overrides the sample's own guess: a user who wants a vocal chop triggered at
    one pitch should get that even when the chop has a clear fundamental.
    """
    out = np.zeros(int(duration_s * sample_rate) + sample_rate)
    mono = audio.mean(axis=1) if audio.ndim > 1 else np.asarray(audio, dtype=np.float64)

    edge = max(1, int(EDGE_S * sample_rate))
    if mono.size > 2 * edge:
        mono = mono.copy()
        mono[:edge] *= np.linspace(0.0, 1.0, edge)
        mono[-edge:] *= np.linspace(1.0, 0.0, edge)

    transpose = sample.pitched if pitched is None else pitched
    out_of_range = 0

    for note in notes:
        if transpose and sample.root_midi is not None:
            shift = float(note.pitch) - sample.root_midi
            if abs(shift) > MAX_SHIFT_SEMITONES:
                out_of_range += 1
                continue
            voice = _resample(mono, hz(note.pitch) / hz(sample.root_midi))
        else:
            voice = mono

        # Cut at the note's own length when the sample outlasts it, so a held sample does
        # not blur into the next note. Shorter samples simply stop, which is what a
        # one-shot does.
        held = max(note.end_s - note.start_s, 0.02)
        keep = min(voice.size, int((held + EDGE_S) * sample_rate))
        piece = voice[:keep].copy()
        if piece.size > edge:
            piece[-edge:] *= np.linspace(1.0, 0.0, edge)

        at = int(note.start_s * sample_rate)
        room = min(piece.size, out.size - at)
        if room > 0:
            out[at : at + room] += piece[:room] * (note.velocity / 127.0)

    peak = float(np.max(np.abs(out)))
    if peak > 1.0:
        out /= peak
    return out[: int(duration_s * sample_rate)], out_of_range
