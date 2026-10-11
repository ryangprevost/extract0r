"""The build and the drop. X0R-1335.

What has to be true for this to be a drop rather than a noise: the music thins and rises
before the bar, nearly stops just before it, and is all back on it - and the place it suggests
is where a song changes, not an arbitrary bar. Plus the line this project keeps: everything
here is added, and the account says so.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.synth import drop
from app.services.synth.retempo import beat_grid, bounce, four_on_the_floor

SR = 22050
BPM = 128.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT


def db(x: np.ndarray) -> float:
    return 10 * np.log10(np.mean(np.asarray(x) ** 2) + 1e-12)


def section(seconds: float, hz: float, level: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return level * np.sin(2 * np.pi * hz * t)


def song(bars: int = 8, change_at: int = 4) -> np.ndarray:
    """Quiet low verse, then a louder, brighter chorus."""
    verse = section(change_at * BAR, 110.0, 0.15)
    chorus = section((bars - change_at) * BAR, 880.0, 0.4) + section((bars - change_at) * BAR,
                                                                    220.0, 0.3)
    return np.concatenate([verse, chorus])


def grid(bars: int = 8) -> np.ndarray:
    return beat_grid(0.0, BPM, bars * BAR)


def at(t: float) -> int:
    return int(t * SR)


def test_the_drop_is_suggested_where_the_song_changes():
    found = drop.suggest_drops(song(12, change_at=8), SR, grid(12))
    assert found and found[0].bar == 9
    assert found[0].strength == 1.0
    assert abs(found[0].at_s - 8 * BAR) < 1e-6


def test_only_phrase_starts_are_offered():
    """A drop on bar 7 sounds like a mistake. Bars are offered in fours."""
    found = drop.suggest_drops(song(16, change_at=8), SR, grid(16))
    assert all((d.bar - 1) % drop.PHRASE_BARS == 0 for d in found)


def test_a_song_too_short_for_a_build_gets_no_suggestion():
    assert drop.suggest_drops(section(3 * BAR, 220.0), SR, grid(3)) == []


@pytest.mark.parametrize("bar", [1, 2, 99])
def test_a_drop_with_no_room_for_its_build_is_refused_in_words(bar):
    with pytest.raises(ValueError, match="needs 2 bars before it"):
        drop.check(grid(8), bar)


def test_the_build_thins_the_low_end_and_the_drop_brings_it_back():
    audio = np.stack([section(8 * BAR, 60.0)] * 2, axis=1)
    out = drop.sweep(audio, SR, grid(8), drop_bar=5)
    build, drop_s = 2 * BAR, 4 * BAR
    first_half = db(out[at(build): at(build + BAR / 2)])
    last_bar = db(out[at(build + BAR): at(drop_s - BEAT)])
    assert last_bar < first_half - 12        # the filter has risen past 60 Hz
    assert db(out[at(drop_s - BEAT * 0.9): at(drop_s)]) < db(audio[:at(BAR)]) - 15  # the gap
    assert np.allclose(out[at(drop_s):], audio[at(drop_s):])     # everything back, untouched
    assert np.allclose(out[: at(build)], audio[: at(build)])     # and nothing before


def test_the_roll_gets_faster_and_louder_into_the_drop():
    added = drop.build_and_drop(grid(8), BPM, SR, at(8 * BAR), drop_bar=5)[:, 0]
    first_bar = added[at(2 * BAR): at(3 * BAR)]
    second_bar = added[at(3 * BAR): at(4 * BAR)]
    assert db(second_bar) > db(first_bar) + 3
    assert np.max(np.abs(added[at(4 * BAR): at(4 * BAR + 0.3)])) > 0.3   # the impact
    assert not np.any(added[: at(2 * BAR)])                               # silent before


def test_the_added_kick_sits_out_the_build():
    beats = grid(8)
    rest = (2 * BAR, 4 * BAR)
    kick = four_on_the_floor(beats, BPM, SR, at(8 * BAR), rest=rest)[:, 0]
    # The last kick before the build is allowed to ring out into it; no new one starts.
    assert not np.any(kick[at(2 * BAR + 0.5): at(4 * BAR) - 1])
    assert np.any(kick[at(4 * BAR): at(4 * BAR + 0.05)])


def test_a_drop_is_owned_up_to_in_the_account():
    stems = {"bass": np.stack([section(8 * BAR, 55.0)] * 2, axis=1),
             "drums": np.zeros((at(8 * BAR), 2))}
    _, account = bounce(stems, SR, 1.0, {}, beats=grid(8), bpm=BPM, floor_kick=True,
                        drop_bar=5)
    added = {p.stem: p.detail for p in account if p.how == "added"}
    assert "not from your recording" in added["build"]
    assert "bar 5" in added["drop"]
