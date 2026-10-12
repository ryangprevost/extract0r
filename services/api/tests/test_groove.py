"""A groove, read and played. Sprint 4.

The claims worth holding: a pattern read off strokes is the pattern that was played; swing
and a laid-back snare come back as numbers a person can be told; and a groove played on a
kit and read back again survives the round trip through audio - which is the only test
that says the reading works on sound rather than on lists.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.drums.detect import Hit
from app.services.synth import groove as g
from app.services.synth.retempo import beat_grid

SR = 44100
BPM = 120.0

try:
    import librosa  # noqa: F401

    HAVE_LIBROSA = True
except ImportError:
    HAVE_LIBROSA = False
#: The hit detector is librosa's onset detector, which comes with the ML extras.
needs_detector = pytest.mark.skipif(not HAVE_LIBROSA, reason="hit detection needs librosa")
BEAT = 60.0 / BPM
SIXTEENTH = BEAT / 4


def played(pattern: dict[str, str], bars: int = 4, swing: float = 0.0,
           late_ms: dict[str, float] | None = None, skip: dict[str, set] | None = None
           ) -> list[Hit]:
    hits = []
    for bar in range(bars):
        for kind, row in pattern.items():
            for step, ch in enumerate(row):
                if ch != "x" or (skip and (bar, step) in skip.get(kind, set())):
                    continue
                t = (bar * 16 + step) * SIXTEENTH
                if step % 2 == 1:
                    t += swing * g.TRIPLET * SIXTEENTH
                t += (late_ms or {}).get(kind, 0.0) / 1000
                hits.append(Hit(time_s=t, kinds=[kind], strength=1.0))
    return sorted(hits, key=lambda h: h.time_s)


def test_the_pattern_read_is_the_pattern_played():
    rows = {"kick": "x...x...x...x...", "snare": "....x.......x...", "hihat": "x.x.x.x.x.x.x.x."}
    read = g.extract(played(rows), beat_grid(0.0, BPM, 4 * 4 * BEAT + 0.01), bpm=BPM)
    assert read.bars == 4
    assert read.grid() == rows


def test_swing_comes_back_as_a_drum_machine_number():
    rows = {"hihat": "xxxxxxxxxxxxxxxx"}
    read = g.extract(played(rows, swing=0.5), beat_grid(0.0, BPM, 16 * BEAT + 0.01), bpm=BPM)
    assert read.swing == pytest.approx(0.5, abs=0.02)
    assert read.swing_percent == 58


def test_a_laid_back_snare_is_measured_in_milliseconds():
    rows = {"kick": "x.......x.......", "snare": "....x.......x..."}
    read = g.extract(played(rows, late_ms={"snare": 12.0}), beat_grid(0.0, BPM, 16 * BEAT + .01),
                     bpm=BPM)
    assert read.push_ms("snare") == pytest.approx(12.0, abs=0.5)
    assert abs(read.push_ms("kick")) < 0.5
    assert any("12 ms behind" in line for line in g.describe(read))


def test_a_note_in_one_bar_of_four_is_a_ghost_not_a_hit():
    rows = {"snare": "....x.......x..x"}
    skip = {"snare": {(0, 15), (1, 15), (2, 15)}}
    read = g.extract(played(rows, skip=skip), beat_grid(0.0, BPM, 16 * BEAT + .01), bpm=BPM)
    assert read.steps["snare"][15].rate == 0.25
    assert read.grid()["snare"] == "....x.......x..o"


@needs_detector
@pytest.mark.parametrize("kit", ["tight", "edm", "punchy"])
def test_a_kick_s_click_is_not_read_as_a_hat(kit):
    """Every kick of a rendered four-on-the-floor came back labelled hat as well."""
    beats = beat_grid(0.0, BPM, 16 * BEAT)
    audio = g.render(g.BUILT_IN["four on the floor"], beats, SR, int(9 * SR), kit=kit)
    read = g.from_audio(audio, SR, beat_grid(0.0, BPM, 16 * BEAT + .01), "x", "test", BPM)
    assert read.plays("hihat") == [2, 6, 10, 14]
    # And the overlapping dance kicks the detector heard only the click of are kicks.
    assert read.plays("kick") == [0, 4, 8, 12]


@needs_detector
@pytest.mark.parametrize("kit", ["tight", "edm", "punchy"])
def test_a_hat_struck_with_the_kick_is_kept(kit):
    beats = beat_grid(0.0, BPM, 16 * BEAT)
    audio = g.render(g.BUILT_IN["techno"], beats, SR, int(9 * SR), kit=kit)
    read = g.from_audio(audio, SR, beat_grid(0.0, BPM, 16 * BEAT + .01), "x", "test", BPM)
    assert {0, 4, 8, 12} <= set(read.plays("hihat"))


def test_cymbals_are_read_as_hats():
    hits = [Hit(time_s=i * BEAT, kinds=["cymbals"], strength=1.0) for i in range(8)]
    read = g.extract(hits, beat_grid(0.0, BPM, 8 * BEAT + .01))
    assert read.plays("hihat") == [0, 4, 8, 12]


@needs_detector
def test_a_groove_survives_a_round_trip_through_audio():
    """Played on a kit, found again by the hit detector, read again: the same beat, the same
    swing. Kicks and hats only - a snare and kick together are one stroke to a detector."""
    source = g.Groove.from_dict(g.BUILT_IN["four on the floor"].to_dict())
    bars = 4
    beats = beat_grid(0.0, BPM, bars * 4 * BEAT)
    audio = g.render(source, beats, SR, int((bars * 4 * BEAT + 1) * SR), kit="tight",
                     swing=0.4)
    read = g.from_audio(audio, SR, beat_grid(0.0, BPM, bars * 4 * BEAT + .01), "x", "t", BPM)
    assert read.plays("kick") == [0, 4, 8, 12]
    # The open hats sit on the "and", an even step: unswung by definition.
    assert read.plays("hihat") == [2, 6, 10, 14]


def test_swing_moves_only_the_off_sixteenths():
    straight = g.render(g.BUILT_IN["techno"], beat_grid(0.0, BPM, 4 * BEAT), SR, SR * 3,
                        kit="tight", swing=0.0)
    swung = g.render(g.BUILT_IN["techno"], beat_grid(0.0, BPM, 4 * BEAT), SR, SR * 3,
                     kit="tight", swing=1.0)
    on_beat = slice(0, int(0.02 * SR))
    assert np.allclose(straight[on_beat], swung[on_beat])
    assert not np.allclose(straight, swung)


def test_the_build_is_left_empty():
    out = g.render(g.BUILT_IN["house"], beat_grid(0.0, BPM, 8 * BEAT), SR, int(5 * SR),
                   kit="edm", rest=(4 * BEAT, 8 * BEAT))
    assert not np.any(out[int((4 * BEAT + 0.5) * SR): int(8 * BEAT * SR) - 1])


def test_every_built_in_beat_has_a_kick():
    for name, beat in g.BUILT_IN.items():
        assert beat.plays("kick"), name
        assert all(len(row) == g.STEPS for row in beat.grid().values()), name


def test_a_groove_survives_being_saved():
    rows = {"kick": "x...x...x...x...", "hihat": "..x...x...x...x."}
    read = g.extract(played(rows, swing=0.3), beat_grid(0.0, BPM, 16 * BEAT + .01), bpm=BPM)
    again = g.Groove.from_dict(read.to_dict())
    assert again.grid() == read.grid()
    assert again.swing == read.swing


# --- feel: humanize, and a pump that follows the kick ---------------------------------------


def test_humanize_off_is_the_programmed_beat():
    beats = beat_grid(0.0, BPM, 8 * BEAT)
    assert g.events(g.BUILT_IN["house"], beats) == g.events(g.BUILT_IN["house"], beats,
                                                            humanize=0.0)


def test_humanize_nudges_every_stroke_a_little_and_the_same_way_twice():
    beats = beat_grid(0.0, BPM, 16 * BEAT)
    straight = g.events(g.BUILT_IN["techno"], beats)
    played = g.events(g.BUILT_IN["techno"], beats, humanize=0.8)
    assert played == g.events(g.BUILT_IN["techno"], beats, humanize=0.8)
    drift = [abs(a[0] - b[0]) for a, b in zip(straight, played, strict=True) if a[0] > 0]
    assert max(drift) <= g.HUMANIZE_LIMIT_S + 1e-9
    assert np.mean(drift) > 0.001
    assert len({round(v, 3) for _, _, v in played}) > 3


def test_the_pump_follows_the_added_beat_s_kick_not_every_beat():
    """A breakbeat kicks on 1 and the "and" of 3. Ducking on every beat fought it."""
    from app.services.synth.retempo import bounce

    seconds = 4 * 4 * BEAT
    t = np.arange(int(seconds * SR)) / SR
    tone = 0.3 * np.sin(2 * np.pi * 220 * t)
    stems = {"other": np.stack([tone, tone], axis=1)}
    beats = beat_grid(0.0, BPM, seconds)
    # The beat plays silent hits, so what is measured is the pumped tone and nothing else.
    silent = {kind: np.zeros(10) for kind in g.KINDS}
    mix, _ = bounce(stems, SR, 1.0, {}, beats=beats, bpm=BPM, pump_db=8.0,
                    added_beat=g.BUILT_IN["breakbeat"], beat_sounds=silent)
    dry, _ = bounce(stems, SR, 1.0, {}, beats=beats, bpm=BPM, pump_db=8.0)

    def level(audio, at_s):
        a = int(at_s * SR)
        return 20 * np.log10(np.sqrt(np.mean(audio[a + 200: a + 1500, 0] ** 2)) + 1e-12)

    one, two = BEAT * 4, BEAT * 5          # bar 2: beat 1 has a kick, beat 2 does not
    assert level(dry, two) < level(dry, two + BEAT * 0.8) - 4     # every-beat pump dips
    assert level(mix, one) < level(mix, one + BEAT * 0.8) - 4     # dips on the kick
    assert abs(level(mix, two) - level(mix, two + BEAT * 0.8)) < 1  # and not where none is


# --- Sprint 6: a beat you wrote ----------------------------------------------------------------


def test_a_beat_written_on_the_grid_plays_what_was_written():
    mine = g.from_rows({"kick": "x...x...x...x...", "snare": "....x..o....x..."})
    assert mine.plays("kick") == [0, 4, 8, 12]
    assert mine.plays("snare") == [4, 7, 12]
    assert mine.steps["snare"][7].velocity == g.SOFT
    assert mine.source == "you" and mine.name == "your beat"


def test_editing_a_beat_keeps_its_feel_on_the_steps_it_already_played():
    swung = g.Groove.from_dict(g.BUILT_IN["techno"].to_dict())
    for i in range(1, 16, 2):
        swung.steps["hihat"][i].offset = 0.2
    edited = g.from_rows({"kick": "x...x...x...x..x", "snare": "....x.......x...",
                          "hihat": "xxxxxxxxxxxxxxxx"}, swung)
    assert edited.steps["hihat"][3].offset == 0.2      # kept
    assert edited.steps["kick"][15].offset == 0.0      # added, on the grid
    assert edited.name == "your beat (from techno)"


def test_a_short_row_is_padded_with_rests():
    assert g.from_rows({"kick": "x"}).plays("kick") == [0]


@needs_detector
@pytest.mark.parametrize("kit", ["tight", "punchy", "edm"])
def test_a_snare_struck_with_a_hat_is_still_a_snare(kit):
    """The pop punk backbeat: a hat on every eighth, the snare on 2 and 4 with one. The bare
    detector found 3 of the demo's 16 snares, so the re-played drummer lost the backbeat."""
    rows = {"kick": "x.....x.x.......", "snare": "....x.......x...",
            "hihat": "x.x.x.x.x.x.x.x."}
    beats = beat_grid(0.0, BPM, 16 * BEAT)
    audio = g.render(g.from_rows(rows), beats, SR, int(9 * SR), kit=kit)
    hits = g.read_hits(audio, SR)
    snares = sorted(round(h.time_s / BEAT, 1) for h in hits if "snare" in h.kinds)
    assert snares == [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0]
