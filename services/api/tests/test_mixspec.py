from __future__ import annotations

from pathlib import Path

import pytest

from app.services.mixdown.mixspec import (
    Compressor,
    EqBand,
    MixSpec,
    StemSettings,
    build_filter_complex,
)
from app.services.mixdown.renderer import MixdownRenderer


def spec(*stems: StemSettings, **kwargs) -> MixSpec:
    return MixSpec(stems=list(stems), **kwargs)


def test_solo_overrides_mute_on_other_stems():
    mix = spec(
        StemSettings("drums"),
        StemSettings("bass", solo=True),
        StemSettings("vocals"),
    )
    assert [s.stem for s in mix.active()] == ["bass"]


def test_muted_stems_are_excluded():
    mix = spec(StemSettings("drums", muted=True), StemSettings("bass"))
    assert [s.stem for s in mix.active()] == ["bass"]


def test_filter_complex_wires_every_active_stem_into_the_bus():
    mix = spec(StemSettings("drums", gain_db=-3), StemSettings("bass"))
    graph = build_filter_complex(mix, ["drums", "bass"])
    assert "[0:a]" in graph and "[1:a]" in graph
    assert "amix=inputs=2" in graph
    assert graph.endswith("[out]")


def test_gain_and_eq_appear_in_the_chain():
    mix = spec(
        StemSettings(
            "bass",
            gain_db=2.5,
            eq=[EqBand("peaking", 800, -4.0, 1.2)],
            compressor=Compressor(),
        )
    )
    graph = build_filter_complex(mix, ["bass"])
    assert "equalizer=f=800" in graph
    assert "volume=2.5dB" in graph
    assert "acompressor" in graph


def test_unknown_stem_is_rejected():
    mix = spec(StemSettings("theremin"))
    with pytest.raises(KeyError):
        build_filter_complex(mix, ["drums"])


def test_all_stems_muted_is_an_error():
    mix = spec(StemSettings("drums", muted=True))
    with pytest.raises(ValueError):
        build_filter_complex(mix, ["drums"])


def test_render_command_is_well_formed():
    mix = spec(StemSettings("drums"), StemSettings("bass"), bitrate_kbps=192)
    command = MixdownRenderer().build_command(
        mix,
        {"drums": Path("drums.wav"), "bass": Path("bass.wav")},
        Path("out.mp3"),
    )
    assert command[0] == "ffmpeg"
    assert command.count("-i") == 2
    assert "libmp3lame" in command
    assert "192k" in command
    assert command[-1] == "out.mp3"
