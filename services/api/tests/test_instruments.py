"""Real synths: multisampled instruments, and styles that use them. Sprint 12.

The claims: a note is played from the recording nearest it, at the right pitch; a style
names a real synth where one is installed and falls back to this app's own voice where
not; and nothing about an instrument lives outside the samples folder.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf

from app.domain.notes import NoteEvent
from app.services.synth import instruments, styles
from app.services.synth.voice import hz

SR = 22050


def make(tmp_path, ident="test-bass", kind="bass", roots=(48, 52, 55)):
    folder = tmp_path / "instruments" / ident
    folder.mkdir(parents=True)
    t = np.arange(int(1.5 * SR)) / SR
    notes = {}
    for r in roots:
        sf.write(str(folder / f"{r}.wav"), 0.5 * np.sin(2 * np.pi * hz(r) * t), SR)
        notes[str(r)] = f"{r}.wav"
    (folder / "instrument.json").write_text(json.dumps({
        "name": "Test bass", "kind": kind, "about": "a test", "license": "CC0",
        "source": "here", "notes": notes}))
    return instruments.find(ident, tmp_path)


def peak_hz(audio):
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(audio.size)))
    return float(np.fft.rfftfreq(audio.size, 1 / SR)[int(np.argmax(spectrum))])


def test_an_installed_instrument_is_found_with_its_notes(tmp_path):
    inst = make(tmp_path)
    assert inst.kind == "bass" and sorted(inst.notes) == [48, 52, 55]
    assert inst.to_dict()["range"] == [48, 55]
    assert instruments.find("nope", tmp_path) is None


def test_a_note_comes_from_the_nearest_recording_ties_going_below():
    assert instruments.nearest([48, 52, 55], 50) == 48
    assert instruments.nearest([48, 52, 55], 51) == 52
    assert instruments.nearest([48, 52, 55], 60) == 55


@pytest.mark.parametrize("pitch", [48, 50, 53, 57])
def test_every_note_plays_at_its_own_pitch(tmp_path, pitch):
    inst = make(tmp_path)
    audio, far, _ = instruments.render([NoteEvent(0.0, 1.0, pitch, 100)], inst, SR, 1.2)
    assert peak_hz(audio[: SR]) == pytest.approx(hz(pitch), rel=0.02)
    assert far == 0


def test_a_note_far_from_every_recording_is_counted(tmp_path):
    """A part centred in range is not moved, so a note far outside it is still reached from
    the nearest recording - and counted."""
    inst = make(tmp_path)
    notes = [NoteEvent(0.0, 0.5, 50, 100), NoteEvent(0.5, 1.0, 52, 100),
             NoteEvent(1.0, 1.5, 80, 100)]
    _, far, shift = instruments.render(notes, inst, SR, 2.0)
    assert shift == 0 and far == 1


def test_a_pad_lets_go_gently(tmp_path):
    inst = make(tmp_path, ident="test-pad", kind="pad")
    audio, _, _ = instruments.render([NoteEvent(0.0, 0.5, 48, 100)], inst, SR, 1.2)
    after = audio[int(0.5 * SR): int(0.5 * SR) + int(instruments.RELEASE_S["pad"] * SR)]
    assert np.max(np.abs(after[: SR // 20])) > 0.1          # still sounding after the key
    assert np.max(np.abs(audio[int(0.9 * SR):])) == 0.0     # and gone after the release


def test_a_missing_note_file_is_skipped_not_fatal(tmp_path):
    inst = make(tmp_path)
    (inst.folder / "52.wav").unlink()
    assert sorted(instruments.find("test-bass", tmp_path).notes) == [48, 55]


def test_a_style_uses_real_synths_where_installed_and_voices_where_not():
    bare = styles.resolve("House", set())
    assert bare["parts"]["piano"] == "epiano" and bare["real_synths"] == 0
    full = styles.resolve("House", {"tx81z-fm-piano", "microbrute-sharp-bass"})
    assert full["parts"]["piano"] == "tx81z-fm-piano" and full["real_synths"] == 2
    assert full["parts"]["guitar"] == "stab"


@pytest.mark.parametrize("name", list(styles.STYLES))
def test_every_style_falls_back_to_a_voice_or_kit_that_exists(name):
    from app.services.drums.kit import KITS
    from app.services.synth.groove import BUILT_IN
    from app.services.synth.voice import VOICES

    style = styles.resolve(name, set())
    assert style["parts"]["drums"] in KITS
    for stem, voice in style["parts"].items():
        if stem != "drums":
            assert voice in VOICES, (name, stem, voice)
    assert style["beat"] == "" or style["beat"] in BUILT_IN


# --- through the API -----------------------------------------------------------------------------


def test_the_styles_are_listed(client):
    body = client.get("/api/v1/tracks/styles").json()
    assert {s["name"] for s in body["styles"]} == set(styles.STYLES)


def test_an_installed_instrument_is_a_voice_and_can_be_heard(client, settings):
    make(settings.sample_dir)
    voices = {v["id"]: v for v in client.get("/api/v1/tracks/voices").json()["voices"]}
    assert voices["test-bass"]["label"] == "Test bass (real synth)" and voices["test-bass"]["real"]
    preview = client.get("/api/v1/tracks/library/voices/test-bass/preview")
    assert preview.status_code == 200 and preview.headers["content-type"] == "audio/wav"
    body = client.get("/api/v1/tracks/styles").json()
    assert all(s["real_synths"] == 0 for s in body["styles"])     # none of the style's ids


def test_a_part_far_above_the_instrument_moves_down_whole_octaves(tmp_path):
    inst = make(tmp_path, roots=(36, 42, 48))
    chords = [NoteEvent(i * 0.2, i * 0.2 + 0.18, p, 100) for i, p in enumerate([64, 67, 71, 76])]
    assert instruments.octaves_to_fit(chords, inst) == -2
    _, far, shift = instruments.render(chords, inst, SR, 1.0)
    assert shift == -2 and far == 0


def test_a_part_in_range_is_never_moved(tmp_path):
    inst = make(tmp_path)
    notes = [NoteEvent(0.0, 0.5, 50, 100), NoteEvent(0.5, 1.0, 55, 100)]
    assert instruments.octaves_to_fit(notes, inst) == 0
