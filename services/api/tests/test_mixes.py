"""Saved mixes. Sprint 10.

The rule this holds: a mix put on another version either carries over exactly or says what
did not - a part the version lacks, a point past its end - and *fit* stretches the lanes in
proportion so a sweep over the first verse is still over the first verse.
"""

from __future__ import annotations

import pytest

from app.api.routes_master import ChannelIn
from app.services.synth import mixes
from app.services.synth.mixer import LAYERS, Channel

MIX = {
    "bass": {"gain_db": -2.0, "automation": {"high_cut_hz": [[0, 300], [32, 20000]]}},
    "vocals": {"reverb": 0.4},
}


def test_a_mix_on_a_version_of_the_same_length_carries_over_exactly():
    out, notes = mixes.fit(MIX, ["bass", "vocals"], 64.0, 64.0, stretch=True)
    assert out["bass"]["automation"] == MIX["bass"]["automation"]
    assert out["vocals"] == {**MIX["vocals"], "automation": {}}
    assert notes == []


def test_a_part_the_version_lacks_is_named_and_left_out():
    out, notes = mixes.fit(MIX, ["bass", "drums"], 64.0, 64.0, stretch=False)
    assert "vocals" not in out
    assert notes == ["This version has no vocals, so that part of the mix is left out."]


def test_as_saved_keeps_bars_and_counts_what_falls_off_the_end():
    out, notes = mixes.fit(MIX, ["bass"], 16.0, 64.0, stretch=False)
    assert out["bass"]["automation"]["high_cut_hz"] == [[0, 300]]
    assert any("1 point past the end" in n for n in notes)


def test_fit_stretches_the_lanes_in_proportion():
    out, notes = mixes.fit(MIX, ["bass"], 128.0, 64.0, stretch=True)
    assert out["bass"]["automation"]["high_cut_hz"] == [[0.0, 300], [64.0, 20000]]
    assert "Moving settings stretched to fit: 16 bars became 32." in notes


def test_a_saved_mix_is_described_by_what_it_holds():
    assert mixes.describe(MIX) == "2 parts, 1 moving setting"


@pytest.mark.parametrize("name", list(mixes.STARTERS))
def test_every_starter_mix_is_a_valid_mix_for_every_layer(name):
    starter = mixes.STARTERS[name]
    assert starter["about"]
    for layer, channel in starter["channels"].items():
        assert layer in LAYERS or layer == "master"
        checked = ChannelIn(**channel).model_dump()
        Channel(**checked)               # the mixer accepts it as it is


def test_mixes_live_in_the_samples_folder(tmp_path):
    mixes.save_mix(tmp_path, "mine", MIX, 64.0, 128.0)
    assert (tmp_path / "mixes" / "mine.json").exists()
    assert mixes.saved_mixes(tmp_path)["mine"]["beats"] == 64.0
    assert mixes.delete_mix(tmp_path, "mine") and mixes.saved_mixes(tmp_path) == {}


def test_the_whole_mix_strip_carries_over_to_every_version():
    out, notes = mixes.fit({"master": {"gain_db": -3.0}}, ["bass"], 16.0, 16.0, stretch=False)
    assert out["master"]["gain_db"] == -3.0 and notes == []
