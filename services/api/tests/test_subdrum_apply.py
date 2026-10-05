"""Taking a per-drum suggestion: moving one drum inside a drums stem.

The whole card turns on one criterion, and it is the one that is not negotiable: a master
exported with every per-drum dial at zero has to be the same file as a master exported
with the feature off. Four sub-stems plus a residual re-summed is *not* automatically the
drums you started with - separation is lossy, so the four do not add up - and getting that
wrong would mean every render silently replaced the drums with a reconstruction.

So the change is applied rather than the sum: shape a sub-stem, subtract the original,
add the shaped one. The residual is in neither term and cancels. That makes the null case
a property of the arithmetic rather than a tolerance, and these tests say so by asking for
exact equality rather than `allclose`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.domain.notes import StemKind
from app.services.mastering.instrument import StemShape
from app.services.mastering.pipeline import (
    MasterRequest,
    StemSetting,
    _apply_per_drum,
    _describe_shape,
)

SR = 44100


def _wav(path: Path, hz: float, seconds: float = 2.0, amplitude: float = 0.3) -> Path:
    t = np.arange(int(seconds * SR)) / SR
    wave = amplitude * np.sin(2 * np.pi * hz * t)
    sf.write(str(path), np.stack([wave, wave], axis=1), SR)
    return path


def _drums(seconds: float = 2.0) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    mix = 0.3 * np.sin(2 * np.pi * 60 * t) + 0.2 * np.sin(2 * np.pi * 220 * t)
    return np.stack([mix, mix], axis=1)


def _request(tmp_path: Path, shapes: dict, drums: dict | None = None) -> MasterRequest:
    stems = {StemKind.DRUMS: _wav(tmp_path / "drums.wav", 60)}
    return MasterRequest(
        stems=stems,
        settings=[StemSetting(stem=StemKind.DRUMS)],
        drum_stems=drums if drums is not None else {},
        drum_shapes=shapes,
    )


def _silent_report(*_args, **_kwargs) -> None:
    pass


# --- the criterion that is not negotiable ------------------------------------------------


def test_no_per_drum_move_leaves_the_drums_exactly_as_they_were(tmp_path):
    """Not close. The same samples. A reconstruction that is 0.01 dB out is still a
    reconstruction, and it would be happening on every export anybody ever ran."""
    drums = _drums()
    request = _request(tmp_path, {}, {"kick": _wav(tmp_path / "kick.wav", 60)})
    out, notes = _apply_per_drum(request, drums, SR, _silent_report)
    assert np.array_equal(out, drums)
    assert notes == []


def test_a_dial_at_zero_is_the_same_as_no_dial_at_all(tmp_path):
    """What the user sees when they open the panel, read it, and change nothing."""
    drums = _drums()
    shapes = {name: StemShape() for name in ("kick", "snare", "cymbals", "toms")}
    stems = {name: _wav(tmp_path / f"{name}.wav", 100) for name in shapes}
    request = _request(tmp_path, shapes, stems)
    out, notes = _apply_per_drum(request, drums, SR, _silent_report)
    assert np.array_equal(out, drums)
    assert notes == []


def test_an_identity_shape_never_even_reads_the_audio(tmp_path, monkeypatch):
    """The strongest form of the same promise, and the one that keeps it true as the
    code changes: if the file is not opened, nothing it contains can leak into the mix.

    A later version that "optimised" by always reading and then comparing would pass the
    two tests above and fail this one, which is the point.
    """
    opened: list[str] = []
    import app.services.mastering.pipeline as module

    real = module.read_audio
    monkeypatch.setattr(
        module, "read_audio", lambda path: opened.append(str(path)) or real(path)
    )
    request = _request(
        tmp_path, {"kick": StemShape()}, {"kick": _wav(tmp_path / "kick.wav", 60)}
    )
    _apply_per_drum(request, _drums(), SR, _silent_report)
    assert opened == []


# --- and that it does something when it is asked to --------------------------------------


def test_moving_the_kick_changes_the_drums_by_exactly_the_kick_s_own_change(tmp_path):
    """The arithmetic, stated as a test. The drums move by `shaped - raw` and by nothing
    else, so whatever separation failed to account for is carried through untouched."""
    from app.services.mastering.instrument import apply_shape
    from app.services.mixdown.encode import read_audio

    kick = _wav(tmp_path / "kick.wav", 60, amplitude=0.25)
    shape = StemShape(gain_db=3.0)
    drums = _drums()
    request = _request(tmp_path, {"kick": shape}, {"kick": kick})

    out, notes = _apply_per_drum(request, drums, SR, _silent_report)
    raw = np.asarray(read_audio(kick).samples, dtype=np.float64)
    expected = drums + (apply_shape(raw, SR, shape) - raw)

    assert not np.array_equal(out, drums), "a move that changes nothing is not a move"
    assert np.allclose(out, expected)
    assert notes == ["kick: +3.0 dB"]


def test_the_other_three_drums_are_not_touched(tmp_path):
    """Moving the kick must not move the snare. The sub-stems are never re-summed, so
    this is true by construction - and this test is what says so if that ever changes."""
    from app.services.mixdown.encode import read_audio

    stems = {
        "kick": _wav(tmp_path / "kick.wav", 60),
        "snare": _wav(tmp_path / "snare.wav", 220),
    }
    drums = _drums()
    request = _request(tmp_path, {"kick": StemShape(gain_db=4.0)}, stems)
    out, _ = _apply_per_drum(request, drums, SR, _silent_report)

    snare = np.asarray(read_audio(stems["snare"]).samples, dtype=np.float64)
    # The difference the move made contains the kick's frequency and not the snare's.
    delta = out - drums
    spectrum = np.abs(np.fft.rfft(delta[:, 0]))
    freqs = np.fft.rfftfreq(len(delta), d=1.0 / SR)
    peak = freqs[int(np.argmax(spectrum))]
    assert 55 < peak < 65, f"the change should be the kick's 60 Hz, not {peak:.0f} Hz"
    assert snare.shape  # read for the fixture's sake; nothing of it should be in `delta`


def test_two_drums_moved_at_once_both_land(tmp_path):
    stems = {
        "kick": _wav(tmp_path / "kick.wav", 60),
        "snare": _wav(tmp_path / "snare.wav", 220),
    }
    request = _request(
        tmp_path,
        {"kick": StemShape(gain_db=2.0), "snare": StemShape(tone_air_db=2.0)},
        stems,
    )
    _, notes = _apply_per_drum(request, _drums(), SR, _silent_report)
    assert len(notes) == 2
    assert any(n.startswith("kick:") for n in notes)
    assert any(n.startswith("snare:") for n in notes)


# --- failing without taking the export down ----------------------------------------------


def test_a_move_on_a_drum_that_was_never_split_says_so_and_exports_anyway(tmp_path):
    """A render is the last step of somebody's evening. Losing it because one sub-stem
    went missing - a cleaned temp folder, a track re-separated since - is the wrong trade
    against a drums stem that is one move short and says which."""
    drums = _drums()
    request = _request(tmp_path, {"toms": StemShape(gain_db=2.0)}, {})
    out, notes = _apply_per_drum(request, drums, SR, _silent_report)
    assert np.array_equal(out, drums)
    assert notes == ["toms: asked for, but that drum was not split out"]


def test_an_unreadable_sub_stem_costs_its_own_move_and_nothing_else(tmp_path):
    junk = tmp_path / "snare.wav"
    junk.write_bytes(b"not audio")
    stems = {"kick": _wav(tmp_path / "kick.wav", 60), "snare": junk}
    request = _request(
        tmp_path,
        {"kick": StemShape(gain_db=2.0), "snare": StemShape(gain_db=2.0)},
        stems,
    )
    out, notes = _apply_per_drum(request, _drums(), SR, _silent_report)
    assert not np.array_equal(out, _drums()), "the kick's move should still have landed"
    assert any("could not be read" in n for n in notes)


def test_a_shorter_sub_stem_does_not_run_off_the_end(tmp_path):
    """The sub-stems come out of a separator and are not guaranteed to be sample-exact
    against the stem they came from."""
    short = _wav(tmp_path / "kick.wav", 60, seconds=1.0)
    request = _request(tmp_path, {"kick": StemShape(gain_db=3.0)}, {"kick": short})
    drums = _drums(seconds=2.0)
    out, _ = _apply_per_drum(request, drums, SR, _silent_report)
    assert out.shape == drums.shape
    # The back half, which the sub-stem does not reach, is untouched.
    assert np.array_equal(out[SR:], drums[SR:])


# --- what the report says ----------------------------------------------------------------


def test_a_move_is_described_in_the_words_the_dial_used():
    said = _describe_shape(StemShape(gain_db=-1.5, tone_low_db=2.0, compress_db=1.0))
    assert "-1.5 dB" in said
    assert "low +2.0 dB" in said
    assert "1.0 dB of range taken out" in said


def test_a_band_name_reads_as_words_rather_than_as_a_field():
    assert "low mid" in _describe_shape(StemShape(tone_low_mid_db=1.0))


# --- the route's refusals ------------------------------------------------------------------


def test_a_sideways_move_on_a_kick_is_refused_rather_than_ignored():
    """The same rule that stops the comparison offering one. A dial that reports success
    and does nothing is worse than one that says no."""
    from fastapi import HTTPException

    from app.api.routes_master import DrumMixSetting, _drum_shapes

    with pytest.raises(HTTPException) as caught:
        _drum_shapes(
            [DrumMixSetting(drum="kick", pan=0.4)], {"kick": Path("kick.wav")}
        )
    assert caught.value.status_code == 422
    assert "mono" in caught.value.detail


def test_cymbals_may_be_moved_sideways():
    from app.api.routes_master import DrumMixSetting, _drum_shapes

    shapes = _drum_shapes(
        [DrumMixSetting(drum="cymbals", pan=0.4, width=1.2)],
        {"cymbals": Path("cymbals.wav")},
    )
    assert shapes["cymbals"].pan == 0.4
    assert shapes["cymbals"].width == 1.2


def test_a_drum_that_is_not_one_of_the_four_is_a_422():
    from fastapi import HTTPException

    from app.api.routes_master import DrumMixSetting, _drum_shapes

    with pytest.raises(HTTPException) as caught:
        _drum_shapes([DrumMixSetting(drum="cowbell", gain_db=1.0)], {})
    assert caught.value.status_code == 422


def test_a_move_on_an_unsplit_drum_names_the_step_that_was_missed():
    from fastapi import HTTPException

    from app.api.routes_master import DrumMixSetting, _drum_shapes

    with pytest.raises(HTTPException) as caught:
        _drum_shapes([DrumMixSetting(drum="kick", gain_db=1.0)], {})
    assert caught.value.status_code == 409
    assert "drum-by-drum comparison" in caught.value.detail


def test_no_moves_at_all_is_an_empty_dict_and_not_a_refusal():
    from app.api.routes_master import _drum_shapes

    assert _drum_shapes([], {}) == {}
    assert _drum_shapes(None, {}) == {}
