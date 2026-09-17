"""Tightening the bottom end.

The numbers come from a home master measured against the record it was aimed at. The
complaint was thin, sloppy bass; the obvious explanation - that matching had cut it - was
wrong, because the levels were within 0.2 dB from 40 to 200 Hz. What differed was that
the bass was 2.6x as wide and its channels agreed far less (0.59 correlation against
0.93), and that there was 3.5 dB more energy below 40 Hz than the record had.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.lowend import (
    DEFAULT_CENTRE_BELOW_HZ,
    DEFAULT_SUBSONIC_HZ,
    MAX_CENTRE_HZ,
    MIN_CENTRE_HZ,
    LowEndReport,
    centre_bass,
    remove_subsonics,
    side_to_mid,
)

SR = 44100


def _wide(hz: float, width: float = 0.8, seconds: float = 4.0) -> np.ndarray:
    """A tone with genuinely decorrelated stereo content at `hz`."""
    t = np.arange(int(SR * seconds)) / SR
    mid = 0.3 * np.sin(2 * np.pi * hz * t)
    side = 0.3 * width * np.sin(2 * np.pi * hz * 1.37 * t + 0.6)
    return np.stack([mid + side, mid - side], axis=1)


def _band(x, low, high):
    from scipy.signal import butter, sosfiltfilt

    sos = butter(4, [low, min(high, SR / 2 * 0.99)], btype="band", fs=SR, output="sos")
    return sosfiltfilt(sos, x, axis=0)


# --- centring -------------------------------------------------------------------------


def test_the_low_end_is_pulled_to_the_centre():
    audio = _wide(80.0) + _wide(4000.0)
    out = centre_bass(audio, SR, hz=150.0, amount=1.0)

    assert side_to_mid(_band(out, 50, 120)) < side_to_mid(_band(audio, 50, 120)) / 4


def test_what_is_above_the_crossover_is_left_alone():
    """Otherwise this would be a width control wearing a narrower name."""
    audio = _wide(80.0) + _wide(4000.0)
    out = centre_bass(audio, SR, hz=150.0, amount=1.0)

    before = side_to_mid(_band(audio, 2000, 6000))
    after = side_to_mid(_band(out, 2000, 6000))
    assert after == pytest.approx(before, rel=0.1)


def test_centring_changes_no_tone():
    """Only the side channel moves, and the mid channel carries nearly all the bass. A
    listener hears more bass because more of it survives, not because any was added."""
    audio = _wide(80.0) + _wide(4000.0)
    out = centre_bass(audio, SR, hz=150.0, amount=1.0)

    mono_before = audio.mean(axis=1)
    mono_after = out.mean(axis=1)
    assert np.abs(mono_after - mono_before).max() < 1e-9


def test_more_survives_being_summed_to_mono():
    audio = _wide(80.0)
    out = centre_bass(audio, SR, hz=150.0, amount=1.0)

    def mono_loss(x):
        return float(np.sqrt(np.mean(x.mean(axis=1) ** 2)) / np.sqrt(np.mean(x**2)))

    assert mono_loss(out) > mono_loss(audio)


def test_the_amount_scales_the_move():
    audio = _wide(80.0)
    full = side_to_mid(_band(centre_bass(audio, SR, 150.0, 1.0), 50, 120))
    half = side_to_mid(_band(centre_bass(audio, SR, 150.0, 0.5), 50, 120))
    none = side_to_mid(_band(centre_bass(audio, SR, 150.0, 0.0), 50, 120))

    assert full < half < none


def test_zero_amount_is_a_true_no_op():
    audio = _wide(80.0)
    assert np.array_equal(centre_bass(audio, SR, 150.0, 0.0), audio)


def test_the_crossover_is_clamped_to_something_musical():
    audio = _wide(80.0)
    report = LowEndReport()
    centre_bass(audio, SR, hz=5000.0, amount=1.0, report=report)
    assert report.centred_below_hz <= MAX_CENTRE_HZ

    report = LowEndReport()
    centre_bass(audio, SR, hz=1.0, amount=1.0, report=report)
    assert report.centred_below_hz >= MIN_CENTRE_HZ


def test_a_mono_input_is_returned_unchanged():
    mono = np.stack([np.sin(np.arange(SR) / 30)] * 2, axis=1)
    out = centre_bass(mono, SR, 150.0, 1.0)
    assert np.abs(out - mono).max() < 1e-9


def test_the_report_says_what_happened():
    report = LowEndReport()
    centre_bass(_wide(80.0), SR, 150.0, 1.0, report)
    assert report.width_before > report.width_after
    assert any("centred" in note for note in report.notes)


# --- subsonics ------------------------------------------------------------------------


def test_rumble_goes_and_the_notes_stay():
    """A bass guitar's lowest string is 41 Hz and a five-string's is 31. The filter has to
    tell those apart from the 20 Hz rumble underneath them."""
    t = np.arange(SR * 4) / SR
    rumble = np.stack([0.3 * np.sin(2 * np.pi * 18 * t)] * 2, axis=1)
    note = np.stack([0.3 * np.sin(2 * np.pi * 60 * t)] * 2, axis=1)

    out = remove_subsonics(rumble + note, SR, hz=30.0)

    def energy(x, low, high):
        return float(np.sqrt(np.mean(_band(x, low, high) ** 2)))

    assert energy(out, 10, 25) < energy(rumble + note, 10, 25) / 3
    # A gentle filter still grazes an octave above its corner; what matters is that the
    # note is essentially intact while the rumble is gone.
    assert energy(out, 50, 80) == pytest.approx(energy(rumble + note, 50, 80), rel=0.12)


def test_removing_nothing_is_a_no_op():
    audio = _wide(80.0)
    assert np.array_equal(remove_subsonics(audio, SR, hz=0.0), audio)


def test_the_filter_reports_how_little_it_took():
    """A big number here means it is eating music, not rumble."""
    report = LowEndReport()
    remove_subsonics(_wide(80.0), SR, DEFAULT_SUBSONIC_HZ, report)
    assert -1.0 < report.subsonic_removed_db <= 0.0
    assert report.subsonic_hz == DEFAULT_SUBSONIC_HZ


def test_defaults_sit_where_the_music_does():
    """41 Hz is the lowest note on a bass guitar; the cut must be below it, and the
    centring crossover above where hearing stops localising."""
    assert DEFAULT_SUBSONIC_HZ < 41.0
    assert 100.0 <= DEFAULT_CENTRE_BELOW_HZ <= 200.0
