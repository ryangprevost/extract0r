"""How much space is around an instrument: width, and how wet it sounds.

Width is measured directly — side energy over mid, which is exact. Wetness is not
measurable directly without the dry signal to compare against, so this estimates it from
what a tail actually does to a signal: **it fills the gaps**.

A dry snare hits and stops, so the moments between hits fall close to silence. Put the
same snare in a room and the gaps are held up by the tail. The distance between a stem's
typical level and its quiet moments is therefore a proxy for how wet it is — a large drop
means dry, a small one means the gaps are being filled.

**What that proxy also catches.** Sustain fills gaps too, so a held pad and a short note
drenched in reverb measure alike. So does heavy compression, and so does separation bleed,
which leaks other instruments into the quiet parts of a stem. On its own the number is
mush.

What makes it usable is comparing like with like: this stem against *the same instrument*
in the reference. Both are drum stems, both came out of the same separator, both carry the
same kind of bleed, so the confounds largely cancel and the difference is meaningful even
though neither absolute number is. Nothing here reports an absolute wetness, only a
comparison, and the wording says "drier than" rather than naming a reverb time.
"""

from __future__ import annotations

import numpy as np

#: Non-overlapping frames. Long enough to be a level rather than a waveform, short enough
#: that the gap between two snare hits is several frames.
FRAME_MS = 20.0

#: Frames this far below the stem's loud sections are silence or a section it does not
#: play in, and counting them would measure the arrangement rather than the tail.
ACTIVE_FLOOR_DB = 40.0

#: Below this many active frames there is not enough of a stem to say anything about it.
MIN_ACTIVE_FRAMES = 50

#: How long after a hit to measure its decay. Long enough for a tail to show, short
#: enough that the next note usually has not arrived.
DECAY_WINDOW_MS = 600.0

#: The decay is fitted between these two levels below each hit's peak, which is how
#: RT20 has always been measured.
#:
#: Bounds by level rather than by time, because the right amount of onset to discard
#: depends on the tail. The moments straight after a hit are the source stopping, not the
#: room continuing, and they are far steeper: fitting from the peak turned a known 1.2 s
#: reverb into 0.58 s. A fixed 80 ms skip fixed that and then read a 0.4 s tail as 0.22 s,
#: because 80 ms is a fifth of a short tail and most of the useful part of it.
DECAY_FROM_DB = 5.0
DECAY_TO_DB = 25.0

#: A hit has to rise at least this much above the preceding frame to count as one.
ONSET_RISE_DB = 6.0

#: Fewer clean decays than this and the median is noise.
MIN_DECAYS = 8

#: Seconds of audio to read for the decay estimate, taken from the middle of the stem.
#:
#: The statistic is a median over individual hits, so it converges long before the track
#: does - a minute holds well over a hundred of them. Reading every stem in full cost
#: 34 seconds for one comparison, almost all of it in the file I/O rather than the maths.
DECAY_SAMPLE_S = 60.0

#: Below this a stem is centred, and a width ratio between two near-mono signals is noise
#: dressed as a finding. Real output before this existed: "your bass is wider than the
#: reference's - yours measures 0.02 across against the reference's 0.00".
MONO_WIDTH = 0.05


#: Instruments whose decay says something about the space around them.
#:
#: Bass is excluded on evidence rather than on principle. Measured against a real
#: reference its bass came out at -5.9 dB/s against this mix's -41.3, which would read as
#: an enormous amount of reverb and is nothing of the kind: a legato bass line simply
#: never stops between notes, so there is no decay to measure. Anything played mostly
#: sustained has the same problem, but bass is the one that fails every time.
DECAY_IS_MEANINGFUL = ("drums", "vocals", "guitar", "piano", "other")

#: Under this, two stems sit in the same amount of space as far as anyone can hear.
SAME_GAP_DB = 2.0

#: Under this, two stems are the same width.
SAME_WIDTH_RATIO = 0.12

#: One stem has to ring on half again as long as the other before it is worth saying.
#: Deliberately blunt: without the dry signal this is an estimate, not a measurement.
SAME_DECAY_RATIO = 1.5


def envelope_db(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Frame-wise RMS in dBFS, as a level over time."""
    audio = np.asarray(samples, dtype=np.float64)
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio

    frame = max(1, int(sample_rate * FRAME_MS / 1000.0))
    count = mono.size // frame
    if count == 0:
        return np.empty(0)

    frames = mono[: count * frame].reshape(count, frame)
    rms = np.sqrt((frames**2).mean(axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-9))


def gap_depth_db(samples: np.ndarray, sample_rate: int) -> float | None:
    """How far a stem drops between its loud moments. Large means dry, small means wet.

    Returns None when there is not enough of the stem playing to say anything.
    """
    db = envelope_db(samples, sample_rate)
    if db.size == 0:
        return None

    # Gate against the stem's own loud sections rather than an absolute level, so a quiet
    # stem is not judged as silence and a section it sits out is not counted as a gap.
    loud = float(np.percentile(db, 95))
    active = db[db > loud - ACTIVE_FLOOR_DB]
    if active.size < MIN_ACTIVE_FRAMES:
        return None

    typical = float(np.percentile(active, 50))
    quiet = float(np.percentile(active, 10))
    return round(typical - quiet, 2)


def describe_space(gap_difference_db: float) -> str:
    """Which way round a gap-depth difference reads, in words.

    Positive means the reference drops further between hits than this stem does, so the
    reference is the drier of the two.
    """
    return "wetter" if gap_difference_db > 0 else "drier"


def width_ratio(mine: float, theirs: float) -> float | None:
    """Reference width over this stem's. None when either is effectively mono.

    Bass is the reason the floor is as high as it is: it is centred on purpose in both
    mixes, and dividing one near-zero by another produces a large ratio that means
    nothing at all.
    """
    if mine < MONO_WIDTH or theirs < MONO_WIDTH:
        return None
    return theirs / mine


def middle_slice(path, seconds: float = DECAY_SAMPLE_S):
    """Read `seconds` from the middle of an audio file, rather than all of it."""
    import soundfile as sf

    with sf.SoundFile(str(path)) as handle:
        rate = handle.samplerate
        wanted = int(seconds * rate)
        if len(handle) > wanted:
            handle.seek((len(handle) - wanted) // 2)
        return handle.read(wanted, dtype="float32", always_2d=True), rate

def decay_slope_db_per_s(samples: np.ndarray, sample_rate: int) -> float | None:
    """Median rate at which the level falls after a hit, in dB per second.

    A more targeted question than `gap_depth_db`: not "how full is this part" but "when
    something stops, how fast does it actually stop". A dry source collapses; a
    reverberant one slides down at the room's rate. Measuring each hit separately means
    the answer does not depend on how many notes are played, which is the arrangement
    rather than the space.

    Steeper (more negative) is drier. Returns None when there are too few clean decays.
    """
    db = envelope_db(samples, sample_rate)
    if db.size < 10:
        return None

    loud = float(np.percentile(db, 95))
    frames = max(2, int(DECAY_WINDOW_MS / FRAME_MS))

    rise = np.diff(db, prepend=db[0])
    # A hit: a real jump up, landing somewhere actually audible.
    onsets = np.flatnonzero((rise >= ONSET_RISE_DB) & (db > loud - ACTIVE_FLOOR_DB))

    slopes = []
    for index in onsets:
        end = min(index + frames, db.size)
        window = db[index:end]
        # Only the part before the next hit, or the decay is measuring the next note.
        nxt = np.flatnonzero(np.diff(window) >= ONSET_RISE_DB)
        if nxt.size:
            window = window[: nxt[0] + 1]
        if window.size < 6:
            continue

        peak = float(window.max())
        below = window <= peak - DECAY_FROM_DB
        if not below.any():
            continue
        start = int(np.argmax(below))

        gone = window[start:] <= peak - DECAY_TO_DB
        stop = start + (int(np.argmax(gone)) + 1 if gone.any() else window.size - start)

        segment = window[start:stop]
        if segment.size < 4:
            continue
        seconds = np.arange(segment.size) * FRAME_MS / 1000.0
        slope = float(np.polyfit(seconds, segment, 1)[0])
        if slope < 0:
            slopes.append(slope)

    if len(slopes) < MIN_DECAYS:
        return None
    return round(float(np.median(slopes)), 1)


#: Longest decay that is credibly a room rather than an instrument holding a note.
#:
#: Reverb on a record is essentially always under three seconds; past that it is a special
#: effect or, far more often here, sustain. Measured against a real reference the guitar
#: stem came back at 6.0 s and the piano at 5.2 s, which are not rooms - they are a
#: strummed chord and a held pedal. Rather than report those as reverb, say nothing.
PLAUSIBLE_MAX_S = 3.0

#: Shortest tail the frame rate can resolve. A 20 ms frame cannot see 20 dB of decay in
#: much less than this, so anything faster is reported as "at the floor" rather than as a
#: number pretending to precision it does not have.
FLOOR_SECONDS = 0.15


def reverb_time_s(samples: np.ndarray, sample_rate: int) -> float | None:
    """Estimated RT60 in seconds: how long a tail takes to fall by 60 dB.

    Validated against tails of known length rather than asserted. Built by convolving dry
    hits with a response decaying by exactly 60 dB over a chosen time, the estimate came
    back within 0.06 s at every length from 0.4 s to 3.0 s, and gave the same answer at
    30% wet as at 60% - which is the property that matters, since the rate a tail decays
    at does not depend on how loud it is.

    What it still cannot separate is a room from an instrument that sustains on its own.
    A held note and a short note in a hall decay alike, so this is an estimate of how long
    the sound takes to die, and reverb is only the usual reason.

    Returns FLOOR_SECONDS when a stem has plenty of hits but none of them ring long enough
    to measure - that is a dry stem, not an unmeasurable one - and None when there was too
    little to go on either way.
    """
    slope = decay_slope_db_per_s(samples, sample_rate)
    if slope is not None:
        seconds = 60.0 / abs(slope)
        # Past the plausible ceiling this is the instrument, not the space.
        return None if seconds > PLAUSIBLE_MAX_S else round(seconds, 2)

    # Distinguish "nothing decayed slowly enough to measure" from "nothing happened".
    db = envelope_db(samples, sample_rate)
    if db.size < 10:
        return None
    loud = float(np.percentile(db, 95))
    rise = np.diff(db, prepend=db[0])
    onsets = int(np.count_nonzero((rise >= ONSET_RISE_DB) & (db > loud - ACTIVE_FLOOR_DB)))
    return FLOOR_SECONDS if onsets >= MIN_DECAYS else None
