"""The criterion 2 measurement, re-runnable. X0R-1319 criterion 6.

The before/after figures on that card were measured on four real drum stems, and **two of
those four were deleted by the retention sweep between two measurement runs minutes apart**.
Twenty-four hours, by design, working correctly. The numbers survived only because somebody
had written them into a docstring, which is a thin kind of evidence: nobody can re-run them,
and nobody can tell whether a later change made them worse.

So the programmed side of criterion 6 is **generated rather than stored**. No `.wav` in the
repository, nothing for retention to delete, and the figures come out the same on any machine
for as long as the code exists. These run the real chain end to end - synthesise audio, detect
onsets with the shipped detector, estimate a tempo the way the application does, then map it -
because a fixture made of onset *times* would skip the two stages most likely to break.

**This does not close criterion 6 on its own.** A synthetic kit is a programmed record. The
live-drummed half cannot be generated honestly - the whole point of a live record is that a
person did something a generator would not - so it still depends on material the person
supplies, and the card says so.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.analysis.tempo_map import fit

librosa = pytest.importorskip("librosa")

pytestmark = pytest.mark.ml

SR = 22050
#: Shared with the measurement script, and every value here was set by measurement.
#:
#: `delta` and `wait` are the density guard: without them, default detection found 1721
#: onsets in a 28-second clip - 61 a second, which no drummer plays - and a residual measured
#: against that texture improved beautifully and meant nothing. `wait` is in frames, so it is
#: scaled with the hop to keep a floor of about 46 ms between hits.
#:
#: **`hop_length` is the one that bit.** Onset times come back *exactly* frame-aligned, so the
#: frame is a hard floor under any residual this file reports. Measured against known hit
#: times, the median error tracks it: 19.19 ms at hop 512, 9.46 at 256, 5.43 at 128, 3.78 at
#: 64. The first version of this file used hop 512 at this sample rate, where the frame is
#: 23.22 ms - and the steady and drifting records both came back at a residual of *exactly*
#: 23.22, because the figure was the detector's own grid rather than the playing. A hop whose
#: frame is larger than the microtiming being measured cannot measure it.
DETECT = {"backtrack": False, "hop_length": 128, "delta": 0.08, "wait": 16}


def frame_floor_ms() -> float:
    """The finest timing difference the detector can express. Any residual at or near this is
    a statement about the analysis, not about the drummer."""
    return DETECT["hop_length"] / SR * 1000.0


def _hit(sample_rate: int, freq: float, length_s: float) -> np.ndarray:
    """A drum, to the standard a transient detector cares about: a loud click that decays."""
    t = np.arange(int(sample_rate * length_s)) / sample_rate
    return np.sin(2 * np.pi * freq * t) * np.exp(-t / (length_s / 5.0))


def render(pattern: list[tuple[float, str]], duration_s: float) -> np.ndarray:
    """A two-piece kit at the given times."""
    out = np.zeros(int(SR * duration_s) + SR)
    for when, piece in pattern:
        start = int(when * SR)
        hit = _hit(SR, 60.0 if piece == "kick" else 200.0, 0.12 if piece == "kick" else 0.08)
        out[start : start + hit.size] += hit
    return out / max(np.max(np.abs(out)), 1e-9) * 0.9


def programmed(bpm: float, bars: int) -> tuple[np.ndarray, float]:
    """Kick on 1 and 3, snare on 2 and 4, dead steady. The control."""
    beat = 60.0 / bpm
    pattern = [
        (bar * 4 * beat + b * beat, "kick" if b in (0, 2) else "snare")
        for bar in range(bars)
        for b in range(4)
    ]
    duration = bars * 4 * beat
    return render(pattern, duration), duration


def drifting(start_bpm: float, end_bpm: float, bars: int) -> tuple[np.ndarray, float]:
    """The same pattern played by someone speeding up evenly."""
    pattern, now = [], 0.0
    total = bars * 4
    for b in range(total):
        pattern.append((now, "kick" if b % 4 in (0, 2) else "snare"))
        now += 60.0 / (start_bpm + (end_bpm - start_bpm) * b / total)
    return render(pattern, now), now


def measure(audio: np.ndarray, duration_s: float):
    """The shipped chain: detect, estimate, map."""
    env = librosa.onset.onset_strength(y=audio, sr=SR)
    bpm = float(np.atleast_1d(librosa.feature.tempo(onset_envelope=env, sr=SR))[0])
    beats = librosa.beat.beat_track(onset_envelope=env, sr=SR, units="time")[1]
    first = float(beats[0]) if len(beats) else 0.0
    anchors = librosa.onset.onset_detect(y=audio, sr=SR, units="time", **DETECT)
    return fit(anchors, bpm, first, duration_s), np.asarray(anchors)


# --- the control -------------------------------------------------------------------------


def test_even_a_drum_machine_is_not_on_the_shipped_grid():
    """The control, and it does not come out the way the card assumed.

    A machine plays dead on the grid, so a residual here can only come from the *analysis*.
    Measured, the shipped global estimate leaves **17.4 ms** on a programmed 129.2 BPM record
    and the map takes it to 7.1 - because `librosa.feature.tempo` returned 129.10, and a tenth
    of a BPM accumulates phase across sixteen bars. The grid was wrong on the easiest possible
    input, which is a stronger case for this card than the live records were.
    """
    audio, duration = programmed(129.2, bars=16)
    mapped, anchors = measure(audio, duration)

    assert anchors.size > 40
    assert mapped.residual_before_ms > 10.0
    assert mapped.residual_after_ms < 10.0
    assert mapped.lock > 0.6


def test_the_residuals_being_reported_are_above_the_detectors_own_resolution():
    """The check that was missing when the real measurement was first run, and it is the
    reason this file exists at this hop. Onset times are frame-aligned exactly, so a residual
    at or below the frame is the detector talking about itself."""
    audio, duration = drifting(124.0, 134.0, bars=16)
    mapped, _anchors = measure(audio, duration)

    assert mapped.residual_after_ms > frame_floor_ms()
    assert frame_floor_ms() < 8.0


def test_onset_times_really_are_frame_aligned():
    """Stated rather than assumed, because the whole hop argument rests on it."""
    audio, duration = programmed(129.0, bars=12)
    _mapped, anchors = measure(audio, duration)

    frames = anchors / (DETECT["hop_length"] / SR)
    assert np.max(np.abs(frames - np.round(frames))) < 1e-6


def test_the_detector_finds_a_plausible_number_of_hits():
    """The guard the real measurement needed and did not have. Four hits a bar at 129 BPM is
    about 8.6 a second; anything near 60 is texture, and a residual measured against texture
    improves for the wrong reason."""
    audio, duration = programmed(129.2, bars=16)
    _mapped, anchors = measure(audio, duration)

    assert 1.0 < anchors.size / duration < 20.0


# --- the thing criterion 2 asks for ------------------------------------------------------


def test_a_drifting_record_gets_closer_to_its_grid_end_to_end():
    """Criterion 2, through the real detector and the real tempo estimate rather than through
    a list of times chosen to be fittable."""
    audio, duration = drifting(124.0, 134.0, bars=16)
    mapped, _anchors = measure(audio, duration)

    assert mapped.fitted
    assert mapped.residual_after_ms < mapped.residual_before_ms


def test_the_drift_is_found_and_reported():
    """A map that improved the residual without reporting any drift would be correcting phase
    and calling it tempo."""
    audio, duration = drifting(124.0, 134.0, bars=16)
    mapped, _anchors = measure(audio, duration)

    assert mapped.drift_bpm > 1.0


def test_the_improvement_is_larger_on_the_drifting_record():
    """The comparison the card is actually about: a machine has nothing to recover, a drifting
    player does. If these came out equal, the map would be fitting something other than drift.
    """
    steady = measure(*programmed(129.0, bars=16))[0]
    drifted = measure(*drifting(124.0, 134.0, bars=16))[0]

    assert drifted.residual_before_ms > steady.residual_before_ms
    assert drifted.improvement_ms > steady.improvement_ms


def test_the_figures_needed_to_write_the_card_up_are_all_present():
    """Criterion 6 is about the numbers being *written down*. These four are the write-up."""
    mapped, _anchors = measure(*drifting(124.0, 134.0, bars=16))

    for value in (
        mapped.residual_before_ms,
        mapped.residual_after_ms,
        mapped.chance_residual_ms,
        mapped.mean_bpm,
    ):
        assert value > 0.0
    assert 0.0 <= mapped.lock <= 1.0
