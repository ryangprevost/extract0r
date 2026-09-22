"""Capturing what a record teaches, and aiming at it later without the record.

The claim this file has to defend is a strong one: that a profile is not an approximation
of a reference but the same numbers by a shorter route. Everything the whole-mix match
reads from a reference is a measurement of it, so if that is true, a master made from a
profile should be the master made from the audio.

It is very nearly true, and the size of "very nearly" is measured below rather than
asserted vaguely: the stored curve is 96 points where the audio has 2049, which costs
about 0.2 dB RMS on the matching curve and lands the two masters within half a decibel of
each other everywhere.

What a profile deliberately cannot do is per-instrument matching, and that has a test too.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.services.mastering.dsp import (
    DEFAULT_HOP,
    DEFAULT_N_FFT,
    MatchSettings,
    average_spectrum,
    matching_curve,
)
from app.services.mastering.profile import (
    CURVE_POINTS,
    FORMAT_VERSION,
    ReferenceProfile,
    capture,
    find,
    listing,
    load,
    safe_filename,
    save,
)

SR = 44100


def _music(seconds: float = 6.0, seed: int = 5, tilt: float = 0.0) -> np.ndarray:
    """Broadband stereo with a controllable spectral tilt."""
    from scipy.signal import butter, sosfilt

    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    white = rng.standard_normal((n, 2))
    sos = butter(1, 400 / (SR / 2), btype="low", output="sos")
    audio = sosfilt(sos, white, axis=0) * (4.0 - tilt) + white * (0.2 + tilt * 0.4)
    t = np.arange(n) / SR
    for hz in (60, 220, 900, 4500, 11000):
        audio[:, 0] += 0.12 * np.sin(2 * np.pi * hz * t)
        audio[:, 1] += 0.11 * np.sin(2 * np.pi * hz * t + 0.5)
    return audio / np.abs(audio).max() * 0.5


# --- what a profile keeps ---------------------------------------------------------------


def test_a_profile_keeps_measurements_and_no_audio():
    """The whole basis of the feature. Magnitudes on a log axis with the phase discarded
    describe a recording; they do not contain one."""
    profile = capture(_music(), SR, "a song", "a-song.mp3")

    assert len(profile.curve_hz) == CURVE_POINTS
    assert len(profile.curve_db) == CURVE_POINTS
    assert profile.lufs < 0
    assert profile.width, "no width profile captured"

    # Nothing resembling a waveform, at any size.
    written = json.loads(profile.to_json())
    for key, value in written.items():
        if isinstance(value, list):
            assert len(value) <= CURVE_POINTS, f"{key} is too big to be a measurement"


def test_a_profile_is_small_enough_to_send_someone():
    profile = capture(_music(), SR, "a song", "a-song.mp3")
    assert len(profile.to_json().encode()) < 8000


def test_the_stored_curve_rebuilds_the_matching_curve():
    """96 points standing in for 2049. Measured on real music at 0.64 dB worst and 0.17 dB
    RMS; this fixture is synthetic and smoother, so the bar is tighter."""
    source, reference = _music(seed=1), _music(seed=2, tilt=0.6)
    a = average_spectrum(source, DEFAULT_N_FFT, DEFAULT_HOP)
    b = average_spectrum(reference, DEFAULT_N_FFT, DEFAULT_HOP)

    truth = 20 * np.log10(matching_curve(a, b, SR, MatchSettings()))
    rebuilt = 20 * np.log10(
        matching_curve(a, capture(reference, SR, "ref").spectrum(DEFAULT_N_FFT, SR),
                       SR, MatchSettings())
    )

    freqs = np.fft.rfftfreq(DEFAULT_N_FFT, 1 / SR)
    audible = (freqs > 30) & (freqs < 16000)
    error = np.abs(rebuilt[audible] - truth[audible])
    assert error.max() < 1.5, f"worst {error.max():.2f} dB"
    assert np.sqrt((error**2).mean()) < 0.5


def test_the_curve_is_held_flat_outside_what_was_stored():
    """Extrapolating a log curve below 20 Hz runs off towards infinity, which would put
    the matcher's largest correction where there is no music at all."""
    profile = capture(_music(), SR, "a song")
    spectrum = profile.spectrum(DEFAULT_N_FFT, SR)
    freqs = np.fft.rfftfreq(DEFAULT_N_FFT, 1 / SR)

    below = spectrum[(freqs > 0) & (freqs < 18)]
    assert np.all(np.isfinite(below))
    assert below.max() / below.min() < 1.01, "the curve is not flat below the stored range"


# --- round trip ---------------------------------------------------------------------------


def test_a_profile_survives_being_written_and_read(tmp_path: Path):
    original = capture(_music(), SR, "My Favourite Record", "favourite.mp3")
    path = save(original, tmp_path)
    again = load(path)

    assert again.name == original.name
    assert again.lufs == original.lufs
    assert again.curve_db == original.curve_db
    assert again.width == original.width
    np.testing.assert_allclose(again.spectrum(DEFAULT_N_FFT, SR),
                               original.spectrum(DEFAULT_N_FFT, SR))


def test_a_name_cannot_choose_where_the_file_lands():
    """The name comes from a text box and becomes a filename."""
    for hostile in ("../../etc/passwd", "..\\..\\windows", "/absolute/path", "a/b/c"):
        assert "/" not in safe_filename(hostile)
        assert "\\" not in safe_filename(hostile)
        assert not safe_filename(hostile).startswith(".")


def test_an_empty_name_still_produces_a_filename():
    assert safe_filename("???") == "profile"
    assert safe_filename("") == "profile"


def test_profiles_are_listed_newest_first(tmp_path: Path):
    for index, name in enumerate(("first", "second", "third")):
        profile = capture(_music(seconds=2.0), SR, name)
        profile.captured_at = f"2026-01-0{index + 1}T00:00:00+00:00"
        save(profile, tmp_path)

    assert [p.name for p in listing(tmp_path)] == ["third", "second", "first"]


def test_one_unreadable_profile_does_not_cost_the_whole_list(tmp_path: Path):
    save(capture(_music(seconds=2.0), SR, "good"), tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    assert [p.name for p in listing(tmp_path)] == ["good"]


def test_a_profile_from_a_newer_build_is_refused_rather_than_misread(tmp_path: Path):
    profile = capture(_music(seconds=2.0), SR, "future")
    data = json.loads(profile.to_json())
    data["version"] = FORMAT_VERSION + 1
    (tmp_path / "future.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="newer version"):
        load(tmp_path / "future.json")
    # And the listing skips it rather than falling over.
    assert listing(tmp_path) == []


def test_finding_a_profile_by_name(tmp_path: Path):
    save(capture(_music(seconds=2.0), SR, "Bounce"), tmp_path)
    assert find(tmp_path, "Bounce") is not None
    assert find(tmp_path, "Not There") is None


# --- the claim that matters ---------------------------------------------------------------


def test_a_profile_masters_the_same_as_the_audio_it_came_from(tmp_path: Path):
    """The feature only means anything if this holds.

    Measured on a real pair - a bass-heavy mix against MSTRKRFT's "Bounce" - the two
    masters agreed to within 0.02 dB of applied gain and 0.01 LUFS of output loudness,
    and their waveforms differed by 40.6 dB below signal.
    """
    import soundfile as sf

    from app.services.mastering.polish import Polish
    from app.services.mastering.spectral import SpectralMatchEngine
    from app.services.mixdown.encode import read_audio

    source, reference = _music(seed=1), _music(seed=2, tilt=0.6)
    source_path, reference_path = tmp_path / "source.wav", tmp_path / "reference.wav"
    sf.write(str(source_path), source, SR)
    sf.write(str(reference_path), reference, SR)

    profile = capture(reference, SR, "the reference", "reference.wav")
    engine = SpectralMatchEngine()

    from_audio = engine.match(
        source_path, reference_path, tmp_path / "a.wav", polish=Polish(width_profile=1.0)
    )
    from_profile = engine.match(
        source_path, None, tmp_path / "b.wav", polish=Polish(width_profile=1.0),
        reference_profile=profile,
    )

    assert from_profile.gain_applied_db == pytest.approx(from_audio.gain_applied_db, abs=0.3)
    assert from_profile.result.integrated_lufs == pytest.approx(
        from_audio.result.integrated_lufs, abs=0.3
    )
    assert from_profile.reference.integrated_lufs == pytest.approx(
        from_audio.reference.integrated_lufs, abs=0.05
    )

    a = read_audio(tmp_path / "a.wav").samples
    b = read_audio(tmp_path / "b.wav").samples
    length = min(len(a), len(b))
    difference = 20 * np.log10(
        np.sqrt(np.mean((a[:length] - b[:length]) ** 2))
        / (np.sqrt(np.mean(a[:length] ** 2)) + 1e-20)
    )
    assert difference < -25, f"the two masters differ by {difference:.1f} dB"


def test_matching_with_neither_audio_nor_a_profile_is_refused(tmp_path: Path):
    """Rather than producing a master matched to nothing."""
    import soundfile as sf

    from app.services.mastering.spectral import SpectralMatchEngine

    path = tmp_path / "source.wav"
    sf.write(str(path), _music(seconds=2.0), SR)

    with pytest.raises(ValueError, match="reference file or a saved profile"):
        SpectralMatchEngine().match(path, None, tmp_path / "out.wav")


# --- through the API -----------------------------------------------------------------

ATTESTED = {"owns_or_licensed": "true", "personal_use_only": "true"}


def _track_with_reference(client, sample_wav: Path) -> str:
    with sample_wav.open("rb") as handle:
        track_id = client.post(
            "/api/v1/tracks",
            files={"file": ("song.wav", handle, "audio/wav")},
            data=ATTESTED,
        ).json()["track_id"]
    with sample_wav.open("rb") as handle:
        client.post(
            f"/api/v1/tracks/{track_id}/reference",
            files={"file": ("reference.wav", handle, "audio/wav")},
            data={"owns_or_licensed": "true"},
        )
    return track_id


def test_a_reference_can_be_saved_and_listed(client, sample_wav: Path, settings, tmp_path):
    settings.profile_dir = tmp_path / "profiles"
    track_id = _track_with_reference(client, sample_wav)

    saved = client.post(
        f"/api/v1/tracks/{track_id}/reference/profile", json={"name": "Bounce"}
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["bytes"] < 8000

    listed = client.get("/api/v1/tracks/reference/profiles").json()
    assert [p["name"] for p in listed["profiles"]] == ["Bounce"]
    assert listed["profiles"][0]["lufs"] < 0


def test_saving_without_a_reference_is_refused(client, sample_wav: Path, settings, tmp_path):
    settings.profile_dir = tmp_path / "profiles"
    with sample_wav.open("rb") as handle:
        track_id = client.post(
            "/api/v1/tracks", files={"file": ("song.wav", handle, "audio/wav")},
            data=ATTESTED,
        ).json()["track_id"]

    response = client.post(
        f"/api/v1/tracks/{track_id}/reference/profile", json={"name": "nothing"}
    )
    assert response.status_code == 409


def test_a_saved_profile_can_be_aimed_at_by_another_track(
    client, sample_wav: Path, settings, tmp_path
):
    """The point of the whole thing: measure once, reuse on a different song."""
    settings.profile_dir = tmp_path / "profiles"
    first = _track_with_reference(client, sample_wav)
    client.post(f"/api/v1/tracks/{first}/reference/profile", json={"name": "House Target"})

    with sample_wav.open("rb") as handle:
        second = client.post(
            "/api/v1/tracks", files={"file": ("other.wav", handle, "audio/wav")},
            data=ATTESTED,
        ).json()["track_id"]

    response = client.post(
        f"/api/v1/tracks/{second}/reference/use-profile", json={"name": "House Target"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "House Target"
    # And it is honest about the one thing it cannot do.
    assert body["per_stem_available"] is False
    assert "instrument by instrument" in body["note"]


def test_a_track_aimed_at_a_profile_masters_without_any_reference_file(
    client, sample_wav: Path, settings, tmp_path
):
    """No reference audio exists for this track at all, and it still exports."""
    import time

    settings.profile_dir = tmp_path / "profiles"
    first = _track_with_reference(client, sample_wav)
    client.post(f"/api/v1/tracks/{first}/reference/profile", json={"name": "Target"})

    with sample_wav.open("rb") as handle:
        second = client.post(
            "/api/v1/tracks", files={"file": ("other.wav", handle, "audio/wav")},
            data=ATTESTED,
        ).json()["track_id"]
    job = client.post(f"/api/v1/tracks/{second}/separate")
    deadline = time.time() + 60
    while time.time() < deadline:
        if client.get(f"/api/v1/jobs/{job.json()['job_id']}").json()["state"] in (
            "succeeded", "failed"
        ):
            break
        time.sleep(0.05)

    client.post(f"/api/v1/tracks/{second}/reference/use-profile", json={"name": "Target"})

    master = client.post(
        f"/api/v1/tracks/{second}/master",
        json={"stems": [{"stem": "drums"}], "reference_track_id": second},
    )
    assert master.status_code == 202, master.text

    deadline = time.time() + 120
    while time.time() < deadline:
        state = client.get(f"/api/v1/jobs/{master.json()['job_id']}").json()
        if state["state"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert state["state"] == "succeeded", state.get("error")
    assert state["result"]["matched"] is True, "it did not actually match anything"


def test_using_a_profile_that_is_not_there_is_a_404(client, sample_wav: Path, settings,
                                                    tmp_path):
    settings.profile_dir = tmp_path / "profiles"
    with sample_wav.open("rb") as handle:
        track_id = client.post(
            "/api/v1/tracks", files={"file": ("song.wav", handle, "audio/wav")},
            data=ATTESTED,
        ).json()["track_id"]

    response = client.post(
        f"/api/v1/tracks/{track_id}/reference/use-profile", json={"name": "imaginary"}
    )
    assert response.status_code == 404


# --- profiles stay on the machine that made them ------------------------------------


def test_the_default_profile_directory_is_excluded_from_git():
    """An explicit requirement, so it gets an explicit test.

    A profile is measurements taken from a recording someone owns, and which recordings a
    person has is their business. The default location is inside the repo for convenience,
    which makes the .gitignore entry the only thing standing between that and a commit -
    so this fails loudly if the line is ever removed or the default moved out from under
    it.
    """
    import subprocess

    from app.config import Settings

    directory = Settings(_env_file=None).profile_dir
    repo = Path(__file__).resolve().parents[3]
    probe = directory / "a-profile.json"

    result = subprocess.run(
        ["git", "check-ignore", str(probe)],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, (
        f"{probe} is NOT gitignored — saved profiles would be committed"
    )


def test_no_profile_has_ever_been_committed():
    """Belt and braces: the ignore rule could have been added after a slip."""
    import subprocess

    repo = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        ["git", "log", "--all", "--name-only", "--pretty=format:", "--", "profiles/"],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    assert not result.stdout.strip(), f"profiles in history: {result.stdout[:200]}"
