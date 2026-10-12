"""The sound library: built-in kits and voices, previews, and kits of your own hits. X0R-1343.

The claims: every built-in hit is sorted into the drum it is; a kit made of uploaded
one-shots plays wherever a built-in kit does, at any sample rate without changing pitch;
and the rule that makes a library allowable at all - nothing recorded ships - holds,
because your kits live only in your samples folder.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
import soundfile as sf

from app.services.drums.kit import DRUMS, KITS, render_voice
from app.services.synth import library

SR = 44100


@pytest.mark.parametrize("kit", list(KITS))
@pytest.mark.parametrize("drum", DRUMS)
def test_every_built_in_hit_is_sorted_into_its_drum(kit, drum):
    """The first rule called five of the nine snares hats; a snare's rattle really does put
    most of its energy above 5 kHz."""
    assert library.classify(render_voice(KITS[kit][drum], SR), SR)[0] == drum


def test_every_built_in_kit_is_described():
    assert set(library.KIT_ABOUT) == set(KITS)


def write(folder, name, audio, rate=SR):
    folder.mkdir(parents=True, exist_ok=True)
    sf.write(str(folder / f"{name}.wav"), audio, rate)


def test_your_kit_plays_your_hits(tmp_path):
    kick = render_voice(KITS["techno"]["kick"], SR)
    write(tmp_path, "big kick", kick)
    library.save_kit(tmp_path, "mine", {"kick": "big kick"})
    sounds = library.sounds("mine", SR, tmp_path)
    assert np.allclose(sounds["kick"][: kick.size - 200], kick[: kick.size - 200], atol=1e-3)
    # A drum the kit leaves out plays the edm kit's, so the beat is still whole.
    assert set(sounds) == set(DRUMS)


def test_a_hit_at_another_rate_keeps_its_pitch(tmp_path):
    """Rate-converted, not repitched: a 440 Hz tone at 48 kHz is still 440 Hz at 44.1."""
    t = np.arange(int(0.5 * 48000)) / 48000
    write(tmp_path, "tone", np.sin(2 * np.pi * 440 * t), rate=48000)
    library.save_kit(tmp_path, "rated", {"snare": "tone"})
    snare = library.sounds("rated", SR, tmp_path)["snare"]
    spectrum = np.abs(np.fft.rfft(snare))
    peak = np.fft.rfftfreq(snare.size, 1 / SR)[int(np.argmax(spectrum))]
    assert abs(peak - 440) < 5


def test_an_unknown_kit_is_a_key_error_not_a_silent_default(tmp_path):
    with pytest.raises(KeyError):
        library.sounds("nope", SR, tmp_path)
    assert not library.exists("nope", tmp_path)
    assert library.exists("house", tmp_path)


def test_a_kit_can_be_deleted(tmp_path):
    library.save_kit(tmp_path, "gone", {"kick": "x"})
    assert library.delete_kit(tmp_path, "gone")
    assert not library.exists("gone", tmp_path)


def test_previews_are_audible_and_never_clip():
    for kit in ("house", "trap"):
        audio = library.preview_kit(library.sounds(kit, SR), SR)
        assert 0.5 < np.max(np.abs(audio)) <= 0.9
    for voice in ("reese", "bell", "808"):
        audio = library.preview_voice(voice, SR)
        assert 0.5 < np.max(np.abs(audio)) <= 0.9


# --- through the API ---------------------------------------------------------------------


def upload(client, name, audio):
    buffer = io.BytesIO()
    sf.write(buffer, np.stack([audio, audio], axis=1), SR, format="WAV")
    response = client.post(
        "/api/v1/tracks/samples",
        files={"file": ("hit.wav", buffer.getvalue(), "audio/wav")},
        data={"owns_or_licensed": "true", "name": name},
    )
    assert response.status_code == 201, response.text


def test_the_library_lists_kits_voices_and_sorts_your_one_shots(client):
    upload(client, "my kick", render_voice(KITS["house"]["kick"], SR))
    upload(client, "my hat", render_voice(KITS["trap"]["hihat"], SR))
    body = client.get("/api/v1/tracks/library").json()
    assert {k["name"] for k in body["kits"]} >= set(KITS)
    assert {"reese", "stab", "bell", "square"} <= {v["name"] for v in body["voices"]}
    sorted_ = {s["name"]: s["sounds_like"] for s in body["one_shots"]}
    assert sorted_ == {"my kick": "kick", "my hat": "hihat"}


def test_a_kit_of_your_own_is_saved_and_listed(client):
    upload(client, "my kick", render_voice(KITS["house"]["kick"], SR))
    saved = client.post("/api/v1/tracks/library/kits", json={"name": "garage", "kick": "my kick"})
    assert saved.status_code == 201, saved.text
    kits = {k["name"]: k for k in client.get("/api/v1/tracks/library").json()["kits"]}
    assert kits["garage"]["yours"] is True
    preview = client.get("/api/v1/tracks/library/kits/garage/preview")
    assert preview.status_code == 200 and preview.headers["content-type"] == "audio/wav"
    assert client.delete("/api/v1/tracks/library/kits/garage").status_code == 204


@pytest.mark.parametrize("body, code", [
    ({"name": "edm", "kick": "my kick"}, 409),
    ({"name": "../x", "kick": "my kick"}, 400),
    ({"name": "fine"}, 400),
    ({"name": "fine", "kick": "not uploaded"}, 404),
])
def test_a_bad_kit_is_refused_with_the_reason(client, body, code):
    upload(client, "my kick", render_voice(KITS["house"]["kick"], SR))
    assert client.post("/api/v1/tracks/library/kits", json=body).status_code == code


def test_previews_of_things_that_do_not_exist_are_404(client):
    assert client.get("/api/v1/tracks/library/kits/nope/preview").status_code == 404
    assert client.get("/api/v1/tracks/library/voices/nope/preview").status_code == 404
