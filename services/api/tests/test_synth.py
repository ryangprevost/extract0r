"""Playing a transcribed part on something else. X0R-1325.

The bar that matters most here is the dullest one: **a voice must play the note it was
asked to play.** The first `subbass` in this module did not. Its sub-octave was at 0.45 of
the fundamental, which is loud enough to *be* the fundamental, and pYIN transcribed every
note of it exactly twelve semitones flat — note F1 **0.000** against an octave-tolerant F1
of **1.000**, which is the signature of a tracker that is right about the music and wrong
about the register. The tracker was not wrong. The patch was.

That is worth a test rather than an ear, because it sounded fine. A bass patch with a big
sub sounds like a bass patch with a big sub right up until you compare it with the part you
asked for.

These use numpy's FFT rather than a transcriber, so they run on a bare checkout with no ML
install — the X0R-102 rule, one layer out.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domain.notes import NoteEvent
from app.services.synth.voice import (
    MAX_POLYPHONY,
    VOICES,
    PitchedVoice,
    hz,
    render_note,
    render_notes,
)

SR = 44100
PITCHES = [28, 40, 52, 64, 76]


def peak_hz(audio: np.ndarray, sample_rate: int = SR) -> float:
    """The loudest frequency present, which is what a pitch tracker will call the note."""
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(audio.size)))
    return float(np.fft.rfftfreq(audio.size, 1 / sample_rate)[int(np.argmax(spectrum))])


# --- a voice plays the note it was given -------------------------------------------------


@pytest.mark.parametrize("name", sorted(VOICES))
@pytest.mark.parametrize("pitch", PITCHES)
def test_the_loudest_partial_is_the_requested_note(name: str, pitch: int):
    """The regression that the 0.45 sub caused, pinned for every voice at every register.

    Within 3%: a quarter-tone is 1.5%, so this catches an octave, a fifth or a tone and
    tolerates the FFT's own bin width at low pitches.
    """
    audio = render_note(VOICES[name], pitch, 0.6, SR)
    ratio = peak_hz(audio) / hz(pitch)

    assert 0.97 < ratio < 1.03, f"{name} at MIDI {pitch} peaks at {ratio:.3f}x the fundamental"


#: How much sub a voice may carry. Above this the note's *period* doubles even while its
#: loudest partial is still the fundamental, and that is what a pitch tracker follows.
MAX_SUB = 0.25


@pytest.mark.parametrize("name", sorted(VOICES))
def test_no_voice_carries_enough_sub_to_change_its_own_period(name: str):
    """A ceiling, because the FFT test above provably cannot catch this.

    The 0.45 sub was transcribed an octave flat while the fundamental was still the loudest
    thing in the spectrum — pYIN is a YIN tracker and YIN follows **periodicity**, not
    spectral peak, and adding a strong half-frequency component doubles the period whatever
    the magnitudes say. An FFT assertion will happily pass a voice that every pitch tracker
    hears an octave down, which is exactly what happened.

    So the guard is a limit on the parameter rather than a measurement of the output, and
    it is honest about why.
    """
    assert VOICES[name].sub_level <= MAX_SUB


def test_the_fft_check_really_cannot_see_the_sub_problem():
    """Stated as a test so nobody deletes `MAX_SUB` believing the spectral check covers it."""
    sunk = PitchedVoice(partials=(1.0, 0.3), sub_level=0.9)
    assert peak_hz(render_note(sunk, 40, 0.6, SR)) / hz(40) == pytest.approx(1.0, abs=0.05)


def test_a_bass_voice_still_has_weight_below_the_fundamental():
    """The sub was reduced, not removed — the point of it is a bass that carries."""
    audio = render_note(VOICES["subbass"], 40, 0.6, SR)
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(audio.size)))
    freqs = np.fft.rfftfreq(audio.size, 1 / SR)

    sub = spectrum[(freqs > hz(40) / 2 - 4) & (freqs < hz(40) / 2 + 4)].max()
    assert sub > 0.05 * spectrum.max()


# --- notes land where they were played ---------------------------------------------------


def test_nothing_is_quantised_or_moved():
    """The epic's non-goal, asserted in the module best placed to break it by accident.

    A note asked for at an off-grid time comes back starting at that time. If anything here
    ever starts snapping, this is the test that should fail first.
    """
    odd = 0.337
    notes = [NoteEvent(start_s=odd, end_s=odd + 0.2, pitch=48)]
    audio = render_notes(notes, SR, "epiano", duration_s=2.0)

    loud = np.flatnonzero(np.abs(audio) > 0.02)
    assert loud.size
    assert loud[0] / SR == pytest.approx(odd, abs=0.01)


def test_a_part_is_as_long_as_it_was_asked_to_be():
    notes = [NoteEvent(start_s=i * 0.25, end_s=i * 0.25 + 0.2, pitch=45) for i in range(8)]
    assert render_notes(notes, SR, "supersaw", duration_s=4.0).size == 4 * SR


def test_velocity_changes_the_level():
    quiet = render_notes([NoteEvent(0.0, 0.4, 45, velocity=30)], SR, "epiano", duration_s=1.0)
    loud = render_notes([NoteEvent(0.0, 0.4, 45, velocity=120)], SR, "epiano", duration_s=1.0)

    assert np.max(np.abs(loud)) > np.max(np.abs(quiet)) * 2


# --- it stays listenable -----------------------------------------------------------------


def test_nothing_clips():
    """A dense part summing past full scale would distort, and distortion is the one thing
    this cannot be allowed to add — the whole point is to hear the notes."""
    notes = [NoteEvent(i * 0.05, i * 0.05 + 1.5, 40 + i, velocity=127) for i in range(24)]
    assert np.max(np.abs(render_notes(notes, SR, "supersaw", duration_s=4.0))) <= 1.0


def test_polyphony_is_capped_rather_than_piling_up():
    """A transcription that hallucinates a cluster should come out thin and obviously wrong,
    not loud and plausible."""
    stack = [NoteEvent(0.0, 1.0, 40 + i * 3) for i in range(MAX_POLYPHONY + 6)]
    few = [NoteEvent(0.0, 1.0, 40 + i * 3) for i in range(MAX_POLYPHONY)]

    both = [
        np.sqrt((render_notes(n, SR, "epiano", duration_s=1.5) ** 2).mean())
        for n in (few, stack)
    ]
    assert both[1] == pytest.approx(both[0], rel=0.15)


def test_a_note_cut_short_does_not_click():
    """Voice stealing and the end of a clip both truncate a note; neither may crack."""
    audio = render_notes([NoteEvent(0.0, 5.0, 45)], SR, "supersaw", duration_s=0.5)
    assert abs(float(audio[-1])) < 0.02


@pytest.mark.parametrize("name", sorted(VOICES))
def test_no_aliasing_at_the_top_of_the_range(name: str):
    """Partials above Nyquist fold back down and land as audible wrong pitches, which on a
    lead two octaves up is most of them."""
    audio = render_note(VOICES[name], 96, 0.4, SR)
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(audio.size)))
    freqs = np.fft.rfftfreq(audio.size, 1 / SR)

    # Below 0.4x, so the sub-octave a bass voice carries on purpose at 0.5x is not counted
    # as aliasing. Anything down here is a partial that folded back, and nothing else.
    below = spectrum[freqs < hz(96) * 0.4].max()
    assert below < 0.1 * spectrum.max()


def test_an_empty_part_is_silence_of_the_right_length():
    assert np.array_equal(render_notes([], SR, "epiano", duration_s=1.0), np.zeros(SR))
