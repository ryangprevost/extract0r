"""Playing a part on something else, through the API. X0R-1327, X0R-503.

The measurement that justifies this route is in `synth/voice.py` and on the card: through
demucs and basic-pitch, recall is 1.000 and pitch accuracy matches a clean DI, while
precision is 0.462 before cleaning and 0.727 after. The notes are right and there are too
many of them, which is why `clean` exists and why it defaults on here and stays off on the
tab path.

These cover the exposure rather than the measurement - that a stem can be re-voiced, that
the result can be fetched back, and that the one URL this adds cannot be used to read
something it should not.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

ATTESTED = {"owns_or_licensed": "true", "personal_use_only": "true"}


@pytest.fixture
def track(client, sample_wav: Path) -> str:
    with sample_wav.open("rb") as handle:
        response = client.post(
            "/api/v1/tracks",
            files={"file": ("song.wav", handle, "audio/wav")},
            data=ATTESTED,
        )
    assert response.status_code == 201, response.text
    return response.json()["track_id"]


@pytest.fixture
def separated(client, track: str) -> str:
    started = client.post(f"/api/v1/tracks/{track}/separate")
    assert started.status_code in (200, 202), started.text
    assert finish(client, started.json()["job_id"])["state"] == "succeeded"
    return track


def finish(client, job_id: str, timeout_s: float = 240.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body["state"] in ("succeeded", "failed"):
            return body
        time.sleep(0.2)
    raise AssertionError("job never finished")


# --- the vocabulary ----------------------------------------------------------------------


def test_the_voices_are_listed_with_something_to_choose_between(client):
    body = client.get("/api/v1/tracks/voices").json()

    assert {v["id"] for v in body["voices"]} == {
        "supersaw", "subbass", "epiano", "pluck", "pad", "808", "reese", "stab", "bell", "square"
    }
    assert all(v["about"] for v in body["voices"]), "a picker needs more than three nouns"


# --- re-voicing --------------------------------------------------------------------------


def test_an_unknown_voice_is_refused_rather_than_silently_defaulted(client, separated):
    answer = client.post(f"/api/v1/tracks/{separated}/revoice?stem=bass&voice=hammond")

    assert answer.status_code == 400
    assert "hammond" in answer.json()["detail"]


def test_revoicing_before_separating_says_which_step_is_missing(client, track):
    answer = client.post(f"/api/v1/tracks/{track}/revoice?stem=bass&voice=subbass")

    assert answer.status_code == 409
    assert "separate" in answer.json()["detail"].lower()


def test_an_unknown_track_is_a_404(client):
    answer = client.post("/api/v1/tracks/" + "f" * 32 + "/revoice?stem=bass&voice=subbass")
    assert answer.status_code == 404


@pytest.mark.ml
def test_a_stem_comes_back_as_a_playable_render(client, separated):
    started = client.post(f"/api/v1/tracks/{separated}/revoice?stem=bass&voice=subbass")
    result = finish(client, started.json()["job_id"])["result"]

    if not result.get("notes"):
        pytest.skip(result.get("why", "nothing pitched in the fixture"))

    assert result["voice"] == "subbass"
    assert result["url"].endswith("bass.subbass.wav")

    fetched = client.get(result["url"])
    assert fetched.status_code == 200
    assert fetched.headers["content-type"].startswith("audio/")


@pytest.mark.ml
def test_the_count_of_merged_fragments_is_reported(client, separated):
    """Nobody can hear a precision figure. The number of pieces put back together is the
    one thing on screen that says how much repair happened."""
    started = client.post(f"/api/v1/tracks/{separated}/revoice?stem=bass&voice=subbass")
    result = finish(client, started.json()["job_id"])["result"]

    if not result.get("notes"):
        pytest.skip("nothing pitched in the fixture")
    assert result["fragments_merged"] == result["notes_before_cleaning"] - result["notes"]
    assert result["fragments_merged"] >= 0


# --- the new URL cannot read anything it should not --------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../../../../etc/passwd",
        "..%2Fmaster.mp3",
        "master.mp3",
        "bass.supersaw.mp3",
        "bass.hammond.wav",
        "notastem.supersaw.wav",
    ],
)
def test_the_render_url_refuses_anything_that_is_not_a_render(client, separated, name):
    """This directory also holds the user's masters, so the name is rebuilt from a known
    stem and a known voice rather than taken as given."""
    assert client.get(f"/api/v1/tracks/{separated}/revoiced/{name}").status_code in (404, 400)


def test_a_render_that_was_never_made_is_a_404(client, separated):
    answer = client.get(f"/api/v1/tracks/{separated}/revoiced/piano.epiano.wav")
    assert answer.status_code == 404


# --- MIDI --------------------------------------------------------------------------------


def test_midi_before_separating_says_so(client, track):
    answer = client.get(f"/api/v1/tracks/{track}/midi")
    assert answer.status_code == 409


@pytest.mark.ml
def test_midi_comes_back_as_a_file_a_daw_would_open(client, separated):
    answer = client.get(f"/api/v1/tracks/{separated}/midi")
    if answer.status_code == 409:
        pytest.skip("nothing pitched in the fixture")

    assert answer.status_code == 200
    assert answer.content[:4] == b"MThd"
    assert "attachment" in answer.headers["content-disposition"]


# --- Sprint 3: a part at a different tempo -----------------------------------------------


def test_the_tempo_endpoint_offers_somewhere_to_aim(client, separated):
    """A number alone is not a choice. "house / EDM · 128" is."""
    body = client.get(f"/api/v1/tracks/{separated}/tempo").json()

    assert body["tempo_bpm"] >= 0
    labels = {s["label"] for s in body["suggestions"]}
    assert "house / EDM" in labels
    assert all(40 < s["bpm"] < 250 for s in body["suggestions"])


def test_a_tempo_for_an_unknown_track_is_a_404(client):
    assert client.get("/api/v1/tracks/" + "e" * 32 + "/tempo").status_code == 404


def test_a_move_too_far_is_refused_before_any_work_happens(client, separated):
    """Refused at the request rather than inside the job: a move this cannot make should
    say so now, not after paying for a transcription."""
    client.get(f"/api/v1/tracks/{separated}/tempo")
    answer = client.post(
        f"/api/v1/tracks/{separated}/revoice?stem=bass&voice=subbass&target_bpm=20"
    )

    assert answer.status_code in (400, 409)
    if answer.status_code == 400:
        assert "same playing" in answer.json()["detail"]


@pytest.mark.ml
def test_drums_come_back_as_strokes_on_a_kit(client, separated):
    """Drums take a different door: they are strokes rather than notes, so they take a kit
    rather than a voice and never touch a transcriber."""
    started = client.post(f"/api/v1/tracks/{separated}/revoice?stem=drums&kit=punchy")
    body = finish(client, started.json()["job_id"])
    # Hit detection needs a real onset backend, which the fast CI job does not install.
    if body["state"] == "failed":
        pytest.skip(body.get("error", "no onset backend"))
    result = body["result"]

    if not result.get("notes"):
        pytest.skip(result.get("why", "no strokes in the fixture"))
    assert result["voice"] == "punchy"
    assert result["backend"] == "kit"
    assert result["url"].endswith("drums.punchy.wav")
    assert client.get(result["url"]).status_code == 200


@pytest.mark.ml
def test_a_part_played_at_a_new_tempo_says_what_it_did(client, separated):
    """The claim is the product: re-played, not stretched. If this wording drifts, either
    the thing changed or it is being described wrongly."""
    client.get(f"/api/v1/tracks/{separated}/tempo")
    started = client.post(
        f"/api/v1/tracks/{separated}/revoice?stem=drums&kit=tight&target_bpm=90"
    )
    body = finish(client, started.json()["job_id"])
    if body["state"] == "failed":
        pytest.skip(body.get("error", "no tempo for the fixture"))
    result = body["result"]

    if not result.get("notes"):
        pytest.skip("no strokes in the fixture")
    assert "rather than stretched" in result["moved"]
    assert result["duration_s"] > 0


# --- hardening: saying the tempo, bouncing the version, fetching it back ---------------------


def test_the_person_who_can_hear_the_song_gets_the_last_word_on_its_tempo(client, separated):
    said = client.put(f"/api/v1/tracks/{separated}/tempo?bpm=85")
    assert said.status_code == 200, said.text
    assert said.json() == {"tempo_bpm": 85.0, "set_by": "you"}

    read = client.get(f"/api/v1/tracks/{separated}/tempo").json()
    assert read["tempo_bpm"] == 85.0
    assert read["confidence"] == 1.0


@pytest.mark.parametrize("bpm", [0, 20, 300, 1000])
def test_a_tempo_nobody_plays_at_is_refused(client, separated, bpm):
    assert client.put(f"/api/v1/tracks/{separated}/tempo?bpm={bpm}").status_code == 422


def test_correcting_an_unknown_track_is_a_404(client):
    assert client.put("/api/v1/tracks/" + "e" * 32 + "/tempo?bpm=120").status_code == 404


def test_a_version_of_an_unknown_track_is_a_404(client):
    assert client.post("/api/v1/tracks/" + "e" * 32 + "/bounce", json={}).status_code == 404


def test_a_version_before_separating_says_which_step_is_missing(client, track):
    response = client.post(f"/api/v1/tracks/{track}/bounce", json={})
    assert response.status_code == 409
    assert "Separate" in response.json()["detail"]


def test_a_version_names_the_parts_that_have_not_been_played_yet(client, separated):
    response = client.post(
        f"/api/v1/tracks/{separated}/bounce", json={"parts": {"bass": "808", "drums": "edm"}}
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "bass" in detail and "drums" in detail


def test_a_version_too_far_from_the_song_is_refused_before_any_work(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    response = client.post(f"/api/v1/tracks/{separated}/bounce", json={"target_bpm": 30})
    assert response.status_code == 400
    assert "120 to 30" in response.json()["detail"]


def test_a_version_at_the_same_tempo_is_a_mixdown_that_can_be_fetched(client, separated):
    started = client.post(f"/api/v1/tracks/{separated}/bounce", json={})
    body = finish(client, started.json()["job_id"])
    assert body["state"] == "succeeded", body
    result = body["result"]
    assert result["ok"] is True
    assert result["wav"].endswith("version.same.wav")
    assert "not a master" in result["note"]

    wav = client.get(result["wav"])
    assert wav.status_code == 200
    assert wav.headers["content-type"] == "audio/wav"
    mp3 = client.get(result["mp3"])
    assert mp3.status_code == 200
    assert mp3.headers["content-type"] == "audio/mpeg"


def test_an_added_kick_is_owned_up_to_in_the_version(client, separated):
    """Four on the floor is added, not the band - and the account has to say so, or a
    listener hears a kick their drummer never played and is told it was theirs.

    At the song's own tempo, so nothing needs stretching and this runs without the ML extras."""
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    started = client.post(
        f"/api/v1/tracks/{separated}/bounce",
        json={"target_bpm": 120, "pump": True, "four_on_the_floor": True},
    )
    body = finish(client, started.json()["job_id"])
    assert body["state"] == "succeeded", body
    result = body["result"]
    assert result["wav"].endswith("version.120.wav")
    added = [p for p in result["parts"] if p["how"] == "added"]
    assert added and "not from your recording" in added[0]["detail"]
    assert any(p["how"] == "pumped" for p in result["parts"])


@pytest.mark.parametrize(
    "name",
    ["version.128.flac", "version.1.wav", "version.1280.wav", "drums.edm.wav", "..%2Fsecret.wav"],
)
def test_the_version_url_refuses_anything_that_is_not_a_version(client, separated, name):
    assert client.get(f"/api/v1/tracks/{separated}/version/{name}").status_code == 404


def test_a_version_that_was_never_bounced_is_a_404(client, separated):
    response = client.get(f"/api/v1/tracks/{separated}/version/version.174.wav")
    assert response.status_code == 404
    assert "Not bounced" in response.json()["detail"]


def test_without_a_stretcher_a_new_tempo_says_which_parts_to_re_play(
    client, separated, monkeypatch
):
    """Found by these tests: on an install without the ML extras, a bounce at a new tempo
    died inside the job with `No module named 'librosa'`. Now it is refused before it starts,
    with the parts that would have needed stretching named."""
    import app.services.synth.retempo as retempo

    monkeypatch.setattr(retempo, "stretcher_available", lambda: "")
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    response = client.post(f"/api/v1/tracks/{separated}/bounce", json={"target_bpm": 128})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "re-played" in detail and "vocals" in detail


# --- X0R-1335: the build and the drop ---------------------------------------------------------


def test_drop_suggestions_count_bars_from_one(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    body = client.get(f"/api/v1/tracks/{separated}/drops").json()
    assert body["build_bars"] == 2
    for found in body["suggestions"]:
        assert found["bar"] >= 1 + body["build_bars"]
        assert 0 <= found["strength"] <= 1
    assert body["why"]


def test_drops_for_an_unknown_track_is_a_404(client):
    assert client.get("/api/v1/tracks/" + "e" * 32 + "/drops").status_code == 404


def test_a_drop_with_no_room_for_a_build_is_refused_before_any_work(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    response = client.post(f"/api/v1/tracks/{separated}/bounce", json={"drop_bar": 2})
    assert response.status_code == 400
    assert "needs 2 bars before it" in response.json()["detail"]


def test_bar_zero_is_not_a_bar(client, separated):
    response = client.post(f"/api/v1/tracks/{separated}/bounce", json={"drop_bar": 0})
    assert response.status_code == 422


# --- Sprint 4: beats, grooves and a reference's recipe ------------------------------------


def test_the_built_in_beats_are_listed_as_drum_machine_rows(client):
    body = client.get("/api/v1/tracks/grooves").json()
    names = [g["name"] for g in body["grooves"]]
    assert "house" in names and "four on the floor" in names
    for groove in body["grooves"]:
        assert all(len(row) == 16 for row in groove["grid"].values())
    assert "alongside" in body["note"]


def test_a_recipe_without_a_reference_says_what_to_do(client, separated):
    response = client.post(f"/api/v1/tracks/{separated}/reference/recipe")
    assert response.status_code == 409
    assert "reference" in response.json()["detail"]


def test_your_drummer_s_groove_is_described_or_the_missing_piece_named(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    response = client.get(f"/api/v1/tracks/{separated}/beat")
    if response.status_code == 409:
        assert "ML extras" in response.json()["detail"]
        return
    assert response.status_code == 200
    body = response.json()
    assert set(body["grid"]) == {"kick", "snare", "hihat"}
    assert 50 <= body["swing_percent"] <= 67


def test_an_unknown_beat_is_refused(client, separated):
    response = client.post(f"/api/v1/tracks/{separated}/bounce", json={"beat": "polka"})
    assert response.status_code == 400


def test_the_reference_beat_needs_the_reference_read_first(client, separated):
    response = client.post(f"/api/v1/tracks/{separated}/bounce", json={"beat": "reference"})
    assert response.status_code == 409
    assert "Read the reference first" in response.json()["detail"]


def test_leaving_out_a_stem_that_is_not_there_is_refused(client, separated):
    response = client.post(f"/api/v1/tracks/{separated}/bounce", json={"leave_out": ["tuba"]})
    assert response.status_code == 400


def test_a_built_in_beat_instead_of_the_drummer_is_owned_up_to(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    started = client.post(
        f"/api/v1/tracks/{separated}/bounce",
        json={"target_bpm": 120, "beat": "house", "swing": 0.3, "leave_out": ["drums"]},
    )
    body = finish(client, started.json()["job_id"])
    assert body["state"] == "succeeded", body
    lines = " ".join(body["result"]["lines"])
    assert "a house beat, swung at" in lines and "not from your recording" in lines
    assert "Left out, by your choice: drums" in lines


# --- X0R-1342: the version as MIDI ---------------------------------------------------------


def test_a_midi_version_needs_something_to_play(client, separated):
    response = client.post(f"/api/v1/tracks/{separated}/version/midi", json={})
    assert response.status_code == 409


def test_a_midi_version_of_a_beat_comes_back_as_a_file(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    started = client.post(f"/api/v1/tracks/{separated}/version/midi",
                          json={"target_bpm": 120, "beat": "house"})
    body = finish(client, started.json()["job_id"])
    assert body["state"] == "succeeded", body
    result = body["result"]
    assert [t["name"] for t in result["tracks"]] == ["house beat (added)"]
    assert result["tracks"][0]["notes"] > 0
    midi = client.get(result["midi"])
    assert midi.status_code == 200
    assert midi.headers["content-type"] == "audio/midi"
    assert midi.content.startswith(b"MThd")
    assert any("riser" in note for note in result["notes"])


def test_an_added_beat_can_play_on_your_own_kit(client, separated):
    import io

    import numpy as np
    import soundfile as sf

    from app.services.drums.kit import KITS, render_voice

    buffer = io.BytesIO()
    hit = render_voice(KITS["techno"]["kick"], 44100)
    sf.write(buffer, np.stack([hit, hit], axis=1), 44100, format="WAV")
    client.post("/api/v1/tracks/samples",
                files={"file": ("k.wav", buffer.getvalue(), "audio/wav")},
                data={"owns_or_licensed": "true", "name": "my kick"})
    client.post("/api/v1/tracks/library/kits", json={"name": "mine", "kick": "my kick"})
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    started = client.post(f"/api/v1/tracks/{separated}/bounce",
                          json={"target_bpm": 120, "beat": "house", "beat_kit": "mine"})
    assert finish(client, started.json()["job_id"])["state"] == "succeeded"
    refused = client.post(f"/api/v1/tracks/{separated}/bounce",
                          json={"beat": "house", "beat_kit": "nobody's"})
    assert refused.status_code == 400


def test_a_humanized_beat_says_so(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    started = client.post(f"/api/v1/tracks/{separated}/bounce",
                          json={"target_bpm": 120, "beat": "trap", "humanize": 0.8,
                                "pump": True})
    body = finish(client, started.json()["job_id"])
    lines = " ".join(body["result"]["lines"])
    assert "a trap beat, played with a human feel" in lines
    assert "Pumping with the added beat's kick" in lines


# --- Sprint 5: rearranging the song -----------------------------------------------------------


def test_the_song_s_sections_are_listed_in_bars(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    body = client.get(f"/api/v1/tracks/{separated}/sections").json()
    sections = body["sections"]
    assert sections and sections[0]["start_bar"] == 1
    for a, b in zip(sections, sections[1:], strict=False):
        assert b["start_bar"] == a["start_bar"] + a["bars"]
    assert "guesses" in body["note"]


def test_sections_of_an_unknown_track_is_a_404(client):
    assert client.get("/api/v1/tracks/" + "e" * 32 + "/sections").status_code == 404


def test_an_arrangement_naming_a_section_that_is_not_there_is_refused(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    response = client.post(f"/api/v1/tracks/{separated}/bounce",
                           json={"arrangement": [{"section": "s99"}]})
    assert response.status_code == 400
    assert "s99" in response.json()["detail"]


def test_an_arrangement_muting_a_part_that_is_not_there_is_refused(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    response = client.post(f"/api/v1/tracks/{separated}/bounce",
                           json={"arrangement": [{"section": "s1", "mute": ["kazoo"]}]})
    assert response.status_code == 400


def test_a_drop_with_nothing_before_it_is_refused(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    response = client.post(f"/api/v1/tracks/{separated}/bounce",
                           json={"arrangement": [{"section": "s1", "drop": True}]})
    assert response.status_code == 400
    assert "no room" in response.json()["detail"]


def test_a_section_played_twice_makes_a_longer_version(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    first = client.get(f"/api/v1/tracks/{separated}/sections").json()["sections"][0]
    started = client.post(
        f"/api/v1/tracks/{separated}/bounce",
        json={"target_bpm": 120, "beat": "house",
              "arrangement": [{"section": first["id"], "mute": ["beat"]},
                              {"section": first["id"]}]})
    body = finish(client, started.json()["job_id"])
    assert body["state"] == "succeeded", body
    result = body["result"]
    # Twice the section, plus the song's ring-out once at the end if it is the last one.
    seconds = first["end_s"] - first["start_s"]
    assert abs(result["duration_s"] - (2 * seconds + first["tail_s"])) < 0.15
    assert any(line.startswith("Rearranged: 2 blocks") for line in result["lines"])


def test_the_midi_follows_the_arrangement(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    first = client.get(f"/api/v1/tracks/{separated}/sections").json()["sections"][0]
    once = finish(client, client.post(
        f"/api/v1/tracks/{separated}/version/midi",
        json={"target_bpm": 120, "beat": "house",
              "arrangement": [{"section": first["id"]}]}).json()["job_id"])
    twice = finish(client, client.post(
        f"/api/v1/tracks/{separated}/version/midi",
        json={"target_bpm": 120, "beat": "house",
              "arrangement": [{"section": first["id"]}, {"section": first["id"]}]}
    ).json()["job_id"])
    # The beat over the song's ring-out comes once, at the end, so not quite double.
    assert twice["result"]["tracks"][0]["notes"] > 1.5 * once["result"]["tracks"][0]["notes"]


def test_a_section_can_be_heard_before_it_is_placed(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    first = client.get(f"/api/v1/tracks/{separated}/sections").json()["sections"][0]
    heard = client.get(f"/api/v1/tracks/{separated}/sections/{first['id']}/preview")
    assert heard.status_code == 200 and heard.headers["content-type"] == "audio/wav"
    assert client.get(f"/api/v1/tracks/{separated}/sections/s99/preview").status_code == 404


# --- Sprint 6: editing a part's notes ----------------------------------------------------------


def played(client, track, stem, notes):
    """Put a part into the state "played": its notes as transcribed, in beats."""
    import json

    out = client.storage.exports_dir(track)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.played.json").write_text(json.dumps({"notes": notes}), "utf-8")


PLAYED = [{"beat": 0.0, "length": 0.5, "pitch": 40, "velocity": 100},
          {"beat": 1.04, "length": 0.5, "pitch": 43, "velocity": 90}]


def test_notes_before_the_part_is_played_say_what_to_do(client, separated):
    response = client.get(f"/api/v1/tracks/{separated}/parts/bass/notes")
    assert response.status_code == 409
    assert "Play the bass" in response.json()["detail"]


def test_a_played_part_opens_as_played(client, separated):
    played(client, separated, "bass", PLAYED)
    body = client.get(f"/api/v1/tracks/{separated}/parts/bass/notes").json()
    assert body["edited"] is False and body["drums"] is False
    assert [n["pitch"] for n in body["notes"]] == [40, 43]
    assert "1/16" in body["grids"]


def test_an_edit_is_kept_and_an_unchanged_save_is_not_an_edit(client, separated):
    played(client, separated, "bass", PLAYED)
    url = f"/api/v1/tracks/{separated}/parts/bass/notes"
    same = client.put(url, json={"notes": PLAYED}).json()
    assert same["edited"] is False
    changed = [dict(PLAYED[0]), {**PLAYED[1], "pitch": 45}]
    assert client.put(url, json={"notes": changed}).json()["edited"] is True
    body = client.get(url).json()
    assert body["edited"] is True and body["notes"][1]["pitch"] == 45
    assert client.delete(url).status_code == 204
    assert client.get(url).json()["edited"] is False


@pytest.mark.parametrize("note", [{"beat": 0, "length": 0, "pitch": 40},
                                  {"beat": 0, "length": 1, "pitch": 200}])
def test_impossible_notes_are_refused(client, separated, note):
    played(client, separated, "bass", PLAYED)
    response = client.put(f"/api/v1/tracks/{separated}/parts/bass/notes",
                          json={"notes": [note]})
    assert response.status_code == 422


def test_quantise_swing_and_transpose_in_one_call(client):
    body = client.post("/api/v1/tracks/notes/quantize", json={
        "notes": [{"beat": 0.27, "length": 0.2, "pitch": 60}], "grid": "1/16",
        "strength": 1.0, "swing": 1.0, "transpose": 12}).json()
    note = body["notes"][0]
    assert note["pitch"] == 72
    assert note["beat"] == pytest.approx(0.25 + 1 / 12, abs=1e-3)


def test_an_unknown_grid_names_the_real_ones(client):
    response = client.post("/api/v1/tracks/notes/quantize",
                           json={"notes": [], "grid": "1/7"})
    assert response.status_code == 400 and "1/16" in response.json()["detail"]


def test_an_edited_part_is_played_from_your_notes_and_named_as_yours(client, separated):
    """With an edit saved, re-playing the part skips transcription and plays the edit - and
    the version says the part is yours."""
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    played(client, separated, "bass", PLAYED)
    mine = [{"beat": b, "length": 0.5, "pitch": 40 + b, "velocity": 100} for b in range(8)]
    client.put(f"/api/v1/tracks/{separated}/parts/bass/notes", json={"notes": mine})
    started = client.post(f"/api/v1/tracks/{separated}/revoice?stem=bass&voice=808")
    result = finish(client, started.json()["job_id"])["result"]
    assert result["edited"] is True and result["backend"] == "your edits"
    assert result["notes"] == 8
    bounced = finish(client, client.post(f"/api/v1/tracks/{separated}/bounce",
                                         json={"parts": {"bass": "808"}}).json()["job_id"])
    lines = " ".join(bounced["result"]["lines"])
    assert "Edited by you, so these play your notes rather than the band's: bass" in lines


def test_a_beat_you_wrote_is_added_and_named_as_yours(client, separated):
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    started = client.post(f"/api/v1/tracks/{separated}/bounce", json={
        "target_bpm": 120,
        "custom_beat": {"based_on": "house",
                        "rows": {"kick": "x..x..x...x.....", "hihat": "..x...x...x...x."}}})
    body = finish(client, started.json()["job_id"])
    assert body["state"] == "succeeded", body
    assert "Added: your beat (from house) — not from your recording." in body["result"]["lines"]


@pytest.mark.parametrize("rows", [{"cowbell": "x..."}, {"kick": "x..y"}, {"kick": "x" * 17}])
def test_a_beat_row_that_is_not_a_row_is_refused(client, separated, rows):
    response = client.post(f"/api/v1/tracks/{separated}/bounce",
                           json={"custom_beat": {"rows": rows}})
    assert response.status_code == 400


# --- Sprint 7: mixing each part ----------------------------------------------------------------


def bounced(client, track, body=None):
    client.put(f"/api/v1/tracks/{track}/tempo?bpm=120")
    started = client.post(f"/api/v1/tracks/{track}/bounce",
                          json=body or {"target_bpm": 120, "beat": "house"})
    result = finish(client, started.json()["job_id"])
    assert result["state"] == "succeeded", result
    return result["result"]


def test_a_version_comes_with_its_layers(client, separated):
    result = bounced(client, separated)
    names = [layer["name"] for layer in result["layers"]]
    assert "beat" in names and "drums" in names
    assert result["label"] == "120" and result["layer_gain"] >= 1.0
    layer = client.get(result["layers"][0]["url"])
    assert layer.status_code == 200 and layer.headers["content-type"] == "audio/flac"


def test_a_flat_mix_is_the_version_it_came_from(client, separated):
    import io

    import numpy as np
    import soundfile as sf

    result = bounced(client, separated)
    before, _ = sf.read(io.BytesIO(client.get(result["wav"]).content), always_2d=True)
    mixed = finish(client, client.post(f"/api/v1/tracks/{separated}/version/120/mix",
                                       json={"channels": {}}).json()["job_id"])["result"]
    assert mixed["headline"].startswith("Mixed flat")
    after, _ = sf.read(io.BytesIO(client.get(mixed["wav"]).content), always_2d=True)
    assert before.shape == after.shape
    # Only 16-bit rounding of each layer, summed: measured at -72 dBFS, held under -60.
    assert np.max(np.abs(before - after)) < 1e-3


def test_a_mix_is_bounced_and_described(client, separated):
    bounced(client, separated)
    started = client.post(f"/api/v1/tracks/{separated}/version/120/mix", json={"channels": {
        "beat": {"gain_db": -6, "pan": 0.3}, "drums": {"mute": True}}})
    result = finish(client, started.json()["job_id"])["result"]
    assert "Added beat: -6.0 dB, panned 30% right." in result["lines"]
    assert "Drums: muted." in result["lines"]


def test_mixing_a_layer_the_version_does_not_have_is_refused(client, separated):
    bounced(client, separated)
    response = client.post(f"/api/v1/tracks/{separated}/version/120/mix",
                           json={"channels": {"build": {"gain_db": -3}}})
    assert response.status_code == 400 and "no build" in response.json()["detail"]


def test_mixing_before_making_the_version_says_so(client, separated):
    response = client.post(f"/api/v1/tracks/{separated}/version/99/mix", json={})
    assert response.status_code == 409


@pytest.mark.parametrize("label, name", [("120", "kazoo"), ("../x", "beat"), ("1200", "beat")])
def test_the_layer_url_refuses_anything_that_is_not_a_layer(client, separated, label, name):
    assert client.get(f"/api/v1/tracks/{separated}/version/{label}/layers/{name}").status_code \
        == 404


def test_the_reverb_impulse_is_served_for_the_page(client):
    response = client.get("/api/v1/tracks/mixer/impulse?rate=22050")
    assert response.status_code == 200 and response.headers["content-type"] == "audio/wav"


# --- Sprint 8: shaped sounds ---------------------------------------------------------------


def test_a_kept_kit_is_a_kit_everywhere(client, separated):
    client.post("/api/v1/tracks/sounds", json={
        "kind": "kit", "base": "house", "knobs": {"kick": {"tune": -0.4}}, "name": "low house"})
    kits = {k["name"]: k for k in client.get("/api/v1/tracks/library").json()["kits"]}
    assert kits["low house"]["yours"] and "kick lower" in kits["low house"]["about"]
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    started = client.post(f"/api/v1/tracks/{separated}/bounce",
                          json={"target_bpm": 120, "beat": "house", "beat_kit": "low house"})
    assert finish(client, started.json()["job_id"])["state"] == "succeeded"


# --- Sprint 9: automation -------------------------------------------------------------------------


def test_a_mix_with_moving_settings_is_bounced_and_described(client, separated):
    result = bounced(client, separated)
    assert "first_beat_s" in result
    started = client.post(f"/api/v1/tracks/{separated}/version/120/mix", json={"channels": {
        "beat": {"automation": {"gain_db": [[0, -60], [8, 0]], "high_cut_hz": [[0, 400],
                                                                                [8, 20000]]}}}})
    mixed = finish(client, started.json()["job_id"])["result"]
    assert "Added beat: level, high cut moving over the song." in mixed["lines"]


@pytest.mark.parametrize("lane", [
    {"wobble": [[0, 1]]},
    {"gain_db": [[-1, 0]]},
    {"pan": [[i, 0] for i in range(300)]},
])
def test_a_lane_that_cannot_be_is_refused(client, separated, lane):
    bounced(client, separated)
    response = client.post(f"/api/v1/tracks/{separated}/version/120/mix",
                           json={"channels": {"beat": {"automation": lane}}})
    assert response.status_code == 422


# --- Sprint 10: saved mixes ----------------------------------------------------------------------


def test_a_mix_is_saved_listed_and_put_on_a_version(client, separated):
    bounced(client, separated)
    saved = client.post("/api/v1/tracks/mixes", json={
        "name": "my club", "beats": 16, "tempo_bpm": 120,
        "channels": {"beat": {"gain_db": -3, "automation": {"pan": [[0, -1], [8, 1]]}},
                     "vocals": {"reverb": 0.5}}})
    assert saved.status_code == 201, saved.text
    listed = client.get("/api/v1/tracks/mixes").json()
    assert {m["name"] for m in listed["starters"]} == set(
        __import__("app.services.synth.mixes", fromlist=["x"]).STARTERS)
    assert listed["yours"][0]["about"] == "2 parts, 1 moving setting"
    applied = client.post(f"/api/v1/tracks/{separated}/version/120/mix/apply",
                          json={"name": "my club"}).json()
    assert applied["channels"]["beat"]["gain_db"] == -3
    assert applied["channels"]["beat"]["automation"]["pan"][1] == [8, 1]
    assert client.delete("/api/v1/tracks/mixes/my club").status_code == 204


def test_a_starter_mix_can_be_put_on_a_version(client, separated):
    bounced(client, separated)
    applied = client.post(f"/api/v1/tracks/{separated}/version/120/mix/apply",
                          json={"name": "Tight and dry"})
    assert applied.status_code == 200
    assert applied.json()["channels"]["bass"]["gain_db"] == 1.5


def test_a_bounced_mix_comes_back_after_a_reload(client, separated):
    bounced(client, separated)
    assert client.get(f"/api/v1/tracks/{separated}/version/120/mix").json() == {"channels": {}}
    finish(client, client.post(f"/api/v1/tracks/{separated}/version/120/mix",
                               json={"channels": {"beat": {"gain_db": -4}}}).json()["job_id"])
    kept = client.get(f"/api/v1/tracks/{separated}/version/120/mix").json()["channels"]
    assert kept["beat"]["gain_db"] == -4


@pytest.mark.parametrize("name, code", [("Wide and spacious", 409), ("../x", 400)])
def test_a_mix_name_that_cannot_be_is_refused(client, name, code):
    assert client.post("/api/v1/tracks/mixes", json={"name": name}).status_code == code


def test_putting_an_unknown_mix_on_a_version_is_a_404(client, separated):
    bounced(client, separated)
    assert client.post(f"/api/v1/tracks/{separated}/version/120/mix/apply",
                       json={"name": "nope"}).status_code == 404


# --- Sprint 11: the whole mix ------------------------------------------------------------------


def test_a_whole_mix_lane_is_bounced(client, separated):
    bounced(client, separated)
    started = client.post(f"/api/v1/tracks/{separated}/version/120/mix", json={"channels": {
        "master": {"automation": {"gain_db": [[0, -60], [8, 0]]}}}})
    result = finish(client, started.json()["job_id"])["result"]
    assert "Whole mix: level moving over the song." in result["lines"]


# --- Sprint 11: what pr0ducer reads is read once ---------------------------------------------


def _track_dir(client, track):
    return client.storage.exports_dir(track).parent


def test_the_tempo_is_kept_beside_the_track_and_a_correction_updates_it(client, separated):
    import json

    client.get(f"/api/v1/tracks/{separated}/tempo")
    kept = _track_dir(client, separated) / "timing.json"
    assert kept.exists()
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=97")
    assert json.loads(kept.read_text())["tempo_bpm"] == 97.0


def test_sections_and_drops_are_worked_out_once_per_tempo(client, separated):
    import json

    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    first = client.get(f"/api/v1/tracks/{separated}/sections").json()
    shape = _track_dir(client, separated) / "shape.json"
    assert json.loads(shape.read_text())["key"][0] == 120.0
    assert client.get(f"/api/v1/tracks/{separated}/drops").status_code == 200
    assert client.get(f"/api/v1/tracks/{separated}/sections").json() == first
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=90")
    client.get(f"/api/v1/tracks/{separated}/sections")
    assert json.loads(shape.read_text())["key"][0] == 90.0       # a new grid, read again


# --- Sprint 12: real synths ---------------------------------------------------------------------


def test_a_part_plays_on_a_real_synth(client, separated, settings, tmp_path):
    from tests.test_instruments import make

    make(settings.sample_dir)
    client.put(f"/api/v1/tracks/{separated}/tempo?bpm=120")
    played(client, separated, "bass", PLAYED)
    mine = [{"beat": b, "length": 0.5, "pitch": 48 + b, "velocity": 100} for b in range(4)]
    client.put(f"/api/v1/tracks/{separated}/parts/bass/notes", json={"notes": mine})
    started = client.post(f"/api/v1/tracks/{separated}/revoice?stem=bass&voice=test-bass")
    result = finish(client, started.json()["job_id"])["result"]
    assert result["voice"] == "test-bass" and result["notes"] == 4
    assert client.get(result["url"]).status_code == 200
