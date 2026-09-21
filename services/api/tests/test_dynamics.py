"""Dynamic range, and a compressor whose dial is the outcome rather than a threshold.

The measurement half of this file exists because the same mistake has been made in this
codebase three times: reaching for a ratio of two percentiles and calling it dynamics. It
measures density - how typical the typical moment is - and it reads *higher* on a steady
mix than on a swinging one, which is backwards. The first test below is the one that
catches it, and it would fail on every version of that idea.
"""

from __future__ import annotations

import numpy as np

from app.services.mastering.dynamics import (
    MAX_COMPRESSION_DB,
    CompressionReport,
    compress,
    crest_db,
    dynamic_range_db,
    loudest_window_s,
    short_term_db,
)

SR = 44100


def _swinging(seconds: float = 16.0, quiet: float = 0.15, loud: float = 0.6) -> np.ndarray:
    """Four seconds quiet, four loud, repeating - a verse and a chorus."""
    t = np.arange(int(SR * seconds)) / SR
    level = np.where((t % 8.0) < 4.0, quiet, loud)
    hits = ((t * 4) % 1.0 < 0.05).astype(float)
    tone = sum(0.3 * np.sin(2 * np.pi * hz * t) for hz in (110, 330, 900))
    signal = tone * level + hits * level * 0.8 * np.sin(2 * np.pi * 3000 * t)
    return np.stack([signal, signal * 0.97], axis=1)


def _steady(seconds: float = 16.0) -> np.ndarray:
    return _swinging(seconds, quiet=0.4, loud=0.4)


# --- measuring -----------------------------------------------------------------------


def test_a_swinging_part_measures_wider_than_a_steady_one():
    """The whole point of the measure, and the assertion every percentile-ratio version
    of it failed: a part that goes from a verse to a chorus is more dynamic than one that
    sits at a single level, and the number has to say so."""
    assert dynamic_range_db(_swinging(), SR) > dynamic_range_db(_steady(), SR) + 5.0


def test_a_steady_part_measures_near_zero():
    assert dynamic_range_db(_steady(), SR) < 2.0


def test_silence_between_the_parts_is_not_counted_as_range():
    """A guitar that plays in the choruses only is an arrangement, not a dynamic
    performance. Without the gate its silent stretches would make it the most dynamic
    thing in the mix."""
    steady = _steady(seconds=8.0)
    with_gaps = steady.copy()
    with_gaps[: len(steady) // 2] = 0.0

    assert dynamic_range_db(with_gaps, SR) < dynamic_range_db(steady, SR) + 2.0


def test_too_short_to_measure_says_zero_rather_than_guessing():
    assert dynamic_range_db(np.zeros((128, 2)), SR) == 0.0
    assert short_term_db(np.zeros((128, 2)), SR).size == 0


def test_crest_is_about_transients_not_about_range():
    """Two takes at the same dynamic range, one with sharp hits and one without. Crest
    has to separate them - otherwise it is just a second way of measuring range."""
    t = np.arange(SR * 4) / SR
    body = 0.3 * np.sin(2 * np.pi * 200 * t)
    spikes = body + ((t * 8) % 1.0 < 0.004) * 0.6

    flat = np.stack([body, body], axis=1)
    sharp = np.stack([spikes, spikes], axis=1)
    assert crest_db(sharp) > crest_db(flat) + 3.0


# --- compressing ----------------------------------------------------------------------


def test_the_dial_removes_the_range_it_says_it_will():
    """The control is calibrated in dB of range removed, so this is the test that decides
    whether it is telling the truth. Measured: asking for 3 dB takes out 2.94."""
    audio = _swinging()
    for wanted in (1.0, 3.0, 6.0):
        report = CompressionReport()
        compress(audio, SR, wanted, report=report)
        assert abs(report.achieved_db - wanted) < 0.5, (wanted, report.achieved_db)


def test_more_compression_is_always_less_range():
    audio = _swinging()
    ranges = [
        dynamic_range_db(compress(audio, SR, amount), SR) for amount in (0.0, 2.0, 5.0, 8.0)
    ]
    assert ranges == sorted(ranges, reverse=True)


def test_compression_is_a_balance_not_a_volume():
    """Level-matched after the gain reduction, or every A/B of this control is really an
    A/B of loudness and the compressed version wins for the wrong reason."""
    audio = _swinging()
    out = compress(audio, SR, MAX_COMPRESSION_DB)
    change = 20 * np.log10(
        float(np.sqrt(np.mean(out**2))) / float(np.sqrt(np.mean(audio**2)))
    )
    assert abs(change) < 0.5


def test_it_holds_the_loud_parts_down_rather_than_pulling_the_quiet_ones_up():
    """Which way round it works is audible. Pulling the floor up raises the noise and the
    bleed with it; holding the ceiling down and giving the level back does not."""
    audio = _swinging()
    report = CompressionReport()
    out = compress(audio, SR, 6.0, report=report)

    before = short_term_db(audio, SR)
    # Undo the reported make-up, so what is left is only what the gain reduction did. The
    # median is no use for this: the fixture is half quiet and half loud, so its median
    # sits in the gap between the two and moves for reasons of its own.
    after = short_term_db(out, SR) - report.makeup_db

    assert np.percentile(after, 95) < np.percentile(before, 95) - 4.0
    assert abs(np.percentile(after, 10) - np.percentile(before, 10)) < 1.5


def test_it_refuses_to_compress_something_already_flat():
    """A ratio solved against a range of nearly zero is a ratio of nearly infinity. The
    guard is what stops the control turning a steady part into a gate."""
    steady = _steady()
    report = CompressionReport()
    out = compress(steady, SR, MAX_COMPRESSION_DB, report=report)
    assert np.array_equal(out, steady)
    assert report.notes and "nothing to compress" in report.notes[0]


def test_it_will_not_take_out_the_whole_range():
    """Capped at a share of what is there. Removing all of it would mean compressing the
    quiet end into the floor, which is a gate wearing a compressor's name."""
    audio = _swinging()
    before = dynamic_range_db(audio, SR)
    after = dynamic_range_db(compress(audio, SR, MAX_COMPRESSION_DB), SR)
    assert after > before * 0.25


def test_compression_off_is_a_true_no_op():
    audio = _swinging()
    assert np.array_equal(compress(audio, SR, 0.0), audio)


def test_a_mono_input_comes_back_stereo_rather_than_crashing():
    mono = np.sin(np.arange(SR * 2) / 30) * 0.4
    assert compress(mono, SR, 3.0).shape[1] == 2


# --- finding the part worth listening to -------------------------------------------


def test_the_loudest_window_finds_the_busy_stretch_not_the_intro():
    """Auditions used to open at 0:00, which on a real song is an intro or silence, and
    the user had to scrub to find the part the comparison was about."""
    quiet = _swinging(seconds=8.0, quiet=0.02, loud=0.02)
    loud = _swinging(seconds=8.0, quiet=0.5, loud=0.5)
    audio = np.concatenate([quiet, loud], axis=0)

    start = loudest_window_s(audio, SR, seconds=4.0)
    assert 7.0 < start < 13.0, f"expected the second half, got {start:.1f}s"


def test_it_ignores_a_single_loud_hit():
    """The loudest *moment* is a cymbal crash and says nothing about how a part sits. A
    sustained window is what makes this a useful place to start listening."""
    audio = _swinging(seconds=12.0, quiet=0.05, loud=0.05)
    audio[int(SR * 1.0) : int(SR * 1.01)] = 0.99  # one enormous transient near the start
    audio[int(SR * 8.0) :] *= 6.0  # and a genuinely louder final stretch

    assert loudest_window_s(audio, SR, seconds=3.0) > 6.0


def test_material_too_short_to_have_a_busy_part_starts_at_the_beginning():
    assert loudest_window_s(np.zeros((256, 2)), SR) == 0.0
    assert loudest_window_s(_swinging(seconds=2.0), SR, seconds=30.0) == 0.0
