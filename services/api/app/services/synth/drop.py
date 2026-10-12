"""The build and the drop. X0R-1335.

The third thing a listener identifies a dance record by, after the pump and the kick on every
beat: the music **pulls back and rises** for a bar or two, everything goes quiet for a moment,
and then the whole groove lands at once. Without it a pop punk song at 128 with a dance kit is
still one long verse. With it, the chorus becomes a drop.

Like the four-on-the-floor this is **added, not moved**. Nothing the band played is shifted in
time. A build here is three things a remixer lays over a mix - a high-pass filter rising on the
non-drum parts, a noise riser, a snare roll that doubles in speed - plus an impact on the
downbeat, and the version's account says so in those words.

**Where to put it is a suggestion, not a decision.** `suggest_drops` reads where the music
changes most at a phrase boundary - a verse turning into a chorus - which is where a drop
belongs, and it can be wrong; the page offers the alternatives as chips. It assumes the song's
first beat is a downbeat, which the kick-locked grid usually makes true and a pickup bar will
not.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.services.drums.kit import KITS, render_voice

BEATS_PER_BAR = 4
#: Drops land on the start of a phrase. Four bars is the unit almost all pop and dance music
#: is built from, and a drop anywhere else sounds like a mistake rather than an arrival.
PHRASE_BARS = 4
#: How long the build lasts. Two bars at 128 is 3.75 s - long enough to rise, short enough
#: not to take over an 8-bar chorus's run-up.
BUILD_BARS = 2

#: The rising high-pass on the non-drum parts, start to end. 1.2 kHz at the top thins a mix to
#: a radio but keeps the melody, so the drop is "everything comes back" rather than "the song
#: came back from nowhere".
SWEEP_FROM_HZ = 40.0
SWEEP_TO_HZ = 1200.0
#: The beat before the drop is left almost empty, which is what makes the downbeat land.
GAP_BEATS = 1.0
GAP_DB = 18.0


@dataclass(frozen=True)
class Drop:
    """A suggested place for the drop, in the terms the page shows it in."""

    #: Counted from 1, the way a musician counts bars.
    bar: int
    at_s: float
    #: 0..1, relative to the strongest change in the song.
    strength: float


def bar_times(beats: np.ndarray) -> np.ndarray:
    """Where every bar starts, taking the first beat as a downbeat."""
    return np.asarray(beats, dtype=np.float64)[::BEATS_PER_BAR]


def _bar_features(mono: np.ndarray, sample_rate: int, bars: np.ndarray) -> np.ndarray:
    """One row per bar: the log spectrum in 24 log-spaced bands, plus loudness.

    Bands rather than chroma so this needs only numpy - the CI install has no librosa - and
    because what changes at a drop is as much register and brightness as harmony: the demo's
    chorus is the verse's chords with the line an octave up.
    """
    edges = np.geomspace(60.0, min(12000.0, sample_rate / 2 - 1), 25)
    rows = []
    for start, end in zip(bars[:-1], bars[1:], strict=True):
        piece = mono[int(start * sample_rate): int(end * sample_rate)]
        if piece.size < 64:
            rows.append(np.zeros(25))
            continue
        spectrum = np.abs(np.fft.rfft(piece * np.hanning(piece.size))) ** 2
        freqs = np.fft.rfftfreq(piece.size, 1.0 / sample_rate)
        bands = [spectrum[(freqs >= lo) & (freqs < hi)].sum() for lo, hi in
                 zip(edges[:-1], edges[1:], strict=True)]
        bands = np.log10(np.asarray(bands) + 1e-12)
        loud = np.log10(np.mean(piece**2) + 1e-12)
        rows.append(np.concatenate([bands - bands.mean(), [loud]]))
    return np.asarray(rows)


def suggest_drops(audio: np.ndarray, sample_rate: int, beats: np.ndarray,
                  limit: int = 3) -> list[Drop]:
    """Phrase boundaries where the music changes most, strongest first.

    For each candidate bar, compare the two bars before it with the two after - a Foote-style
    novelty at bar resolution - and favour a change that gets louder, since a drop is an
    arrival and a breakdown is the opposite. Only bars with room for a build before them and
    something to drop into after are considered.
    """
    mono = audio.mean(axis=1) if audio.ndim > 1 else np.asarray(audio, dtype=np.float64)
    starts = bar_times(beats)
    if starts.size < BUILD_BARS + 3:
        return []
    bars = np.append(starts, min(starts[-1] + (starts[-1] - starts[-2]), mono.size / sample_rate))
    features = _bar_features(mono, sample_rate, bars)
    count = len(features)

    scored = []
    for bar in range(PHRASE_BARS, count - 1, PHRASE_BARS):
        if bar < BUILD_BARS:
            continue
        before = features[max(0, bar - 2): bar]
        after = features[bar: bar + 2]
        shape = np.linalg.norm(after[:, :-1].mean(axis=0) - before[:, :-1].mean(axis=0))
        louder = max(0.0, float(after[:, -1].mean() - before[:, -1].mean()))
        scored.append((bar, shape + 2.0 * louder))
    if not scored:
        return []
    top = max(score for _, score in scored) or 1.0
    scored.sort(key=lambda item: -item[1])
    return [Drop(bar=bar + 1, at_s=float(starts[bar]), strength=round(score / top, 3))
            for bar, score in scored[:limit]]


# --- making it ---------------------------------------------------------------------------


def _window(beats: np.ndarray, drop_bar: int) -> tuple[float, float]:
    """Start of the build and the time of the drop, for a drop counted from bar 1."""
    starts = bar_times(beats)
    index = drop_bar - 1
    if index < BUILD_BARS or index >= starts.size:
        raise ValueError(
            f"A drop at bar {drop_bar} needs {BUILD_BARS} bars before it for the build, and "
            f"the song has {starts.size} bars."
        )
    return float(starts[index - BUILD_BARS]), float(starts[index])


def check(beats: np.ndarray, drop_bar: int) -> None:
    """Raise `ValueError`, with the reason in words, if a drop cannot go at `drop_bar`."""
    _window(beats, drop_bar)


def sweep(audio: np.ndarray, sample_rate: int, beats: np.ndarray, drop_bar: int) -> np.ndarray:
    """A high-pass rising across the build, then the gap, then everything back at the drop.

    Filtered in 256-sample blocks with the coefficients stepped and the filter state carried
    across, so the cutoff glides rather than clicking from one setting to the next.
    """
    from scipy.signal import butter, sosfilt, sosfilt_zi

    audio = np.asarray(audio, dtype=np.float64)
    stereo = audio if audio.ndim > 1 else audio[:, None]
    out = stereo.copy()
    build_s, drop_s = _window(beats, drop_bar)
    lo, hi = int(build_s * sample_rate), min(len(stereo), int(drop_s * sample_rate))
    if hi <= lo:
        return audio

    block = 256
    span = hi - lo
    state = None
    for at in range(lo, hi, block):
        end = min(hi, at + block)
        x = (at - lo) / span
        cutoff = SWEEP_FROM_HZ * (SWEEP_TO_HZ / SWEEP_FROM_HZ) ** (x**1.5)
        sos = butter(2, cutoff / (sample_rate / 2), btype="highpass", output="sos")
        if state is None:
            state = np.stack([sosfilt_zi(sos) * stereo[lo, c] for c in range(stereo.shape[1])],
                             axis=-1)
        filtered, state = sosfilt(sos, stereo[at:end], axis=0, zi=state)
        out[at:end] = filtered

    # The gap: the last beat before the drop, almost silent, faded rather than cut.
    beat_s = (drop_s - build_s) / (BUILD_BARS * BEATS_PER_BAR)
    gap = int(min(GAP_BEATS * beat_s * sample_rate, span))
    fade = max(1, int(0.01 * sample_rate))
    floor = 10.0 ** (-GAP_DB / 20.0)
    gain = np.full(gap, floor)
    gain[:min(fade, gap)] = np.linspace(1.0, floor, min(fade, gap))
    out[hi - gap: hi] *= gain[:, None]
    return out if audio.ndim > 1 else out[:, 0]


def _riser(seconds: float, sample_rate: int) -> np.ndarray:
    """White noise opening from a low rumble to a hiss, and getting louder, over `seconds`."""
    from scipy.signal import butter, sosfilt, sosfilt_zi

    n = max(1, int(seconds * sample_rate))
    noise = np.random.default_rng(1335).standard_normal(n)
    out = np.zeros(n)
    block = 256
    state = None
    for at in range(0, n, block):
        end = min(n, at + block)
        x = at / n
        cutoff = 300.0 * (9000.0 / 300.0) ** x
        sos = butter(2, min(cutoff, sample_rate / 2 - 1) / (sample_rate / 2), output="sos")
        if state is None:
            state = sosfilt_zi(sos) * 0.0
        out[at:end], state = sosfilt(sos, noise[at:end], zi=state)
    level = np.linspace(0.0, 1.0, n) ** 2.5
    out *= level
    return 0.22 * out / max(float(np.max(np.abs(out))), 1e-9)


def _impact(sample_rate: int) -> np.ndarray:
    """A sub boom falling in pitch under a splash of high noise - the downbeat of a drop."""
    n = int(1.4 * sample_rate)
    t = np.arange(n) / sample_rate
    pitch = 34.0 + 30.0 * np.exp(-t * 9.0)
    boom = np.sin(2 * np.pi * np.cumsum(pitch) / sample_rate) * np.exp(-t * 3.2)
    from scipy.signal import butter, sosfilt

    splash = sosfilt(butter(2, 4000.0 / (sample_rate / 2), btype="highpass", output="sos"),
                     np.random.default_rng(1336).standard_normal(n))
    splash *= np.exp(-t * 3.0)
    splash /= max(float(np.max(np.abs(splash))), 1e-9)
    return 0.55 * boom + 0.18 * splash


def roll(beats: np.ndarray, bpm: float, drop_bar: int) -> list[tuple[float, float]]:
    """The snare roll into a drop, as (time, gain): eighths for the first bar, sixteenths for
    the second, louder all the way. Shared by the audio and the MIDI export."""
    build_s, drop_s = _window(beats, drop_bar)
    beat_s = 60.0 / bpm
    bar_s = BEATS_PER_BAR * beat_s
    out = []
    for bar in range(BUILD_BARS):
        step = beat_s / (2 ** (bar + 1))
        t = build_s + bar * bar_s
        while t < build_s + (bar + 1) * bar_s - 1e-6:
            progress = (t - build_s) / (drop_s - build_s)
            out.append((t, 0.15 + 0.55 * progress**1.5))
            t += step
    return out


def build_and_drop(beats: np.ndarray, bpm: float, sample_rate: int, length: int,
                   drop_bar: int) -> np.ndarray:
    """The riser, the snare roll and the impact, as stereo audio to add to the mix.

    The roll doubles in speed: eighths for the first bar, sixteenths for the second, getting
    louder all the way - the run-up every dance producer reaches for, because it tells the
    listener exactly when the drop is coming.
    """
    out = np.zeros((length, 2))
    build_s, drop_s = _window(beats, drop_bar)

    def lay(sample: np.ndarray, time_s: float, gain: float) -> None:
        at = int(round(time_s * sample_rate))
        if at < 0 or at >= length:
            return
        end = min(length, at + sample.size)
        out[at:end] += (sample[: end - at] * gain)[:, None]

    riser = _riser(drop_s - build_s, sample_rate)
    lay(riser, build_s, 1.0)

    snare = render_voice(KITS["tight"]["snare"], sample_rate, seed=1335)
    for t, gain in roll(beats, bpm, drop_bar):
        lay(snare, t, gain)

    lay(_impact(sample_rate), drop_s, 1.0)
    return out


def describe(drop_bar: int) -> tuple[str, str]:
    """The two account lines, in the words the version's summary prints after "Added:"."""
    return (
        f"a {BUILD_BARS}-bar build into bar {drop_bar} - a rising filter, a riser and a snare "
        f"roll - not from your recording",
        f"an impact on the downbeat of bar {drop_bar}, where everything comes back",
    )
