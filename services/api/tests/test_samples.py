"""Bringing your own sample. X0R-1326.

`kit.py` refuses to ship recorded hits, and the argument is about *whose* recording it is: a
library means shipping someone's audio with no way to check where it came from. A user's own
upload is the one case that was never in question — their file, the way a reference track is
their file, behind the same rights attestation.

So these cover two things: that a sample can be played, and that the rules which make it
allowable are actually enforced — attested, kept out of the repository, kept out of the
retention sweep's reach, and never named by something a caller controls.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.domain.notes import NoteEvent
from app.services.synth.samples import (
    MAX_SHIFT_SEMITONES,
    Sample,
    detect_root,
    render_with_sample,
)
from app.services.synth.voice import VOICES, render_note

SR = 44100
ATTESTED = {"owns_or_licensed": "true", "name": "my hit"}


def wav_bytes(audio: np.ndarray, rate: int = SR) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, np.stack([audio, audio], axis=1), rate, format="WAV")
    return buffer.getvalue()


@pytest.fixture
def pitched_audio() -> np.ndarray:
    return render_note(VOICES["epiano"], 57, 0.5, SR)


@pytest.fixture
def noise_audio() -> np.ndarray:
    n = int(SR * 0.2)
    return np.random.default_rng(0).normal(0, 0.3, n) * np.exp(-np.arange(n) / (SR * 0.03))


# --- what has a pitch, and what does not -------------------------------------------------


def test_a_pitched_sample_reports_its_own_note(pitched_audio):
    assert detect_root(pitched_audio, SR) == pytest.approx(57.0, abs=0.5)


def test_an_unpitched_sample_reports_nothing_rather_than_guessing(noise_audio):
    """A snare has a loudest bin like everything else. Calling it a pitch is how a snare
    ends up transposed across two octaves."""
    assert detect_root(noise_audio, SR) is None


def test_something_too_short_to_judge_is_not_judged():
    assert detect_root(np.zeros(100), SR) is None


# --- playing a part on it ----------------------------------------------------------------


def peak_hz(x: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    return float(np.fft.rfftfreq(x.size, 1 / SR)[int(np.argmax(spectrum))])


def test_a_pitched_sample_follows_the_melody(pitched_audio):
    """Transposed, so two different notes come out at two different pitches."""
    held = Sample("s", Path("x"), SR, 0.5, 57.0)
    one, _ = render_with_sample([NoteEvent(0.0, 0.4, 57)], held, pitched_audio, SR, 1.0)
    other, _ = render_with_sample([NoteEvent(0.0, 0.4, 64)], held, pitched_audio, SR, 1.0)

    assert peak_hz(other) > peak_hz(one) * 1.3


def test_an_unpitched_sample_is_triggered_at_one_pitch(noise_audio):
    """A drum machine, not a sampler. Every hit is the same hit."""
    held = Sample("s", Path("x"), SR, 0.2, None)
    out, dropped = render_with_sample(
        [NoteEvent(0.0, 0.2, 40), NoteEvent(0.5, 0.7, 70)], held, noise_audio, SR, 1.5
    )

    first = out[: int(SR * 0.2)]
    second = out[int(SR * 0.5) : int(SR * 0.7)]
    length = min(first.size, second.size)
    assert dropped == 0
    assert np.corrcoef(first[:length], second[:length])[0, 1] > 0.99


def test_the_user_can_override_the_guess(pitched_audio):
    """A vocal chop has a fundamental and may still be wanted as a one-shot. The detector is
    right most of the time; the user is right all of it."""
    held = Sample("s", Path("x"), SR, 0.5, 57.0)
    out, _ = render_with_sample(
        [NoteEvent(0.0, 0.4, 57), NoteEvent(0.5, 0.9, 69)],
        held,
        pitched_audio,
        SR,
        1.5,
        pitched=False,
    )

    a = out[: int(SR * 0.4)]
    b = out[int(SR * 0.5) : int(SR * 0.9)]
    length = min(a.size, b.size)
    assert np.corrcoef(a[:length], b[:length])[0, 1] > 0.99


# --- the cap, which is the honest part ---------------------------------------------------


def test_a_note_too_far_from_the_sample_is_dropped_and_counted(pitched_audio):
    """Repitching moves the formants with the pitch, so far enough and the sample stops
    sounding like itself. A part that silently thinned out is worse than one that says it
    could not reach."""
    held = Sample("s", Path("x"), SR, 0.5, 57.0)
    notes = [
        NoteEvent(0.0, 0.3, 57),
        NoteEvent(0.4, 0.7, int(57 + MAX_SHIFT_SEMITONES + 2)),
        NoteEvent(0.8, 1.1, int(57 - MAX_SHIFT_SEMITONES - 2)),
    ]
    _out, dropped = render_with_sample(notes, held, pitched_audio, SR, 2.0)

    assert dropped == 2


def test_a_note_inside_the_cap_is_played(pitched_audio):
    held = Sample("s", Path("x"), SR, 0.5, 57.0)
    _out, dropped = render_with_sample(
        [NoteEvent(0.0, 0.3, int(57 + MAX_SHIFT_SEMITONES - 1))], held, pitched_audio, SR, 1.0
    )
    assert dropped == 0


def test_nothing_clips(pitched_audio):
    held = Sample("s", Path("x"), SR, 0.5, 57.0)
    stacked = [NoteEvent(i * 0.01, i * 0.01 + 0.5, 57) for i in range(30)]
    out, _ = render_with_sample(stacked, held, pitched_audio, SR, 2.0)
    assert np.max(np.abs(out)) <= 1.0


# --- the rules that make this allowable --------------------------------------------------


def test_an_upload_without_the_attestation_is_refused(client, pitched_audio):
    answer = client.post(
        "/api/v1/tracks/samples",
        files={"file": ("hit.wav", wav_bytes(pitched_audio), "audio/wav")},
        data={"name": "my hit", "owns_or_licensed": "false"},
    )
    assert answer.status_code == 403


def test_an_attested_upload_is_kept_and_described(client, pitched_audio):
    answer = client.post(
        "/api/v1/tracks/samples",
        files={"file": ("hit.wav", wav_bytes(pitched_audio), "audio/wav")},
        data=ATTESTED,
    )

    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert body["pitched"] is True
    assert body["root_midi"] == pytest.approx(57.0, abs=1.0)

    listed = client.get("/api/v1/tracks/samples").json()["samples"]
    assert {s["name"] for s in listed} == {"my hit"}


@pytest.mark.parametrize("name", ["../escape", "a/b", "..", "", "x" * 60, "semi;colon"])
def test_a_sample_name_cannot_become_a_path(client, pitched_audio, name):
    """A name from a form becomes a filename, and a filename from a form is a traversal."""
    answer = client.post(
        "/api/v1/tracks/samples",
        files={"file": ("hit.wav", wav_bytes(pitched_audio), "audio/wav")},
        data={"name": name, "owns_or_licensed": "true"},
    )
    assert answer.status_code in (400, 422)


def test_a_loop_is_refused_with_the_reason(client):
    """Over the limit it is a phrase, not an instrument, and triggering it once a note makes
    a wall rather than a part."""
    long_audio = np.sin(2 * np.pi * 220 * np.arange(int(SR * 12)) / SR) * 0.2
    answer = client.post(
        "/api/v1/tracks/samples",
        files={"file": ("loop.wav", wav_bytes(long_audio), "audio/wav")},
        data=ATTESTED,
    )

    assert answer.status_code == 413
    assert "loop" in answer.json()["detail"]


def test_something_that_is_not_audio_is_refused(client):
    answer = client.post(
        "/api/v1/tracks/samples",
        files={"file": ("x.wav", b"not audio at all", "audio/wav")},
        data=ATTESTED,
    )
    assert answer.status_code == 415


def test_a_sample_can_be_removed(client, pitched_audio):
    client.post(
        "/api/v1/tracks/samples",
        files={"file": ("hit.wav", wav_bytes(pitched_audio), "audio/wav")},
        data=ATTESTED,
    )

    assert client.delete("/api/v1/tracks/samples/my hit").status_code == 204
    assert client.get("/api/v1/tracks/samples").json()["samples"] == []


def test_samples_live_outside_storage_so_retention_cannot_take_them(settings):
    """A sample is audio somebody chose and may have paid for. Losing it a day later because
    it happened to sit beside a track would be a bad surprise."""
    assert settings.storage_dir not in settings.sample_dir.parents
    assert settings.sample_dir != settings.storage_dir


def test_the_samples_folder_is_gitignored():
    """Their audio. The same rule as `profiles/`, and the same reason `kit.py` synthesises
    its drums instead of shipping recordings of them."""
    root = Path(__file__).resolve().parents[3]
    assert "samples/" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()


# --- X0R-1330: telling a sample what note it is ------------------------------------------


def test_the_reach_warning_names_the_arithmetic_and_not_a_false_claim():
    """The first version said a sample was "below where a guitar part usually sits (E2-E5)"
    about a sample at E2 — which is the bottom of E2-E5, so the sentence was simply false.

    What is actually true is the arithmetic: a sample moves at most an octave, a part spans
    more than two, so where it sits decides how much of the part it covers.
    """
    from app.services.synth.samples import reach

    _within, _span, said = reach(40, "guitar")  # E2, the bottom of a guitar's usual span

    assert "in reach" in said
    assert "below" not in said and "above" not in said


def test_a_sample_in_the_right_place_gets_no_warning():
    """A warning that appears every time is furniture."""
    from app.services.synth.samples import reach

    assert reach(40, "bass")[2] == ""


def test_the_same_sample_reaches_more_of_one_part_than_another():
    from app.services.synth.samples import reach

    assert reach(57, "guitar")[0] > reach(57, "bass")[0]


def test_note_names_rather_than_midi_numbers():
    from app.services.synth.samples import note_name

    assert note_name(57) == "A3"
    assert note_name(60) == "C4"
    assert note_name(28) == "E1"


def test_a_root_override_is_remembered_and_used(client, pitched_audio):
    client.post(
        "/api/v1/tracks/samples",
        files={"file": ("hit.wav", wav_bytes(pitched_audio), "audio/wav")},
        data=ATTESTED,
    )
    assert client.patch("/api/v1/tracks/samples/my hit?root_midi=45").status_code == 200

    listed = client.get("/api/v1/tracks/samples").json()["samples"][0]
    assert listed["root_midi"] == 45.0
    assert listed["root_name"] == "A2"


def test_clearing_the_override_goes_back_to_what_was_detected(client, pitched_audio):
    client.post(
        "/api/v1/tracks/samples",
        files={"file": ("hit.wav", wav_bytes(pitched_audio), "audio/wav")},
        data=ATTESTED,
    )
    client.patch("/api/v1/tracks/samples/my hit?root_midi=45")
    client.patch("/api/v1/tracks/samples/my hit")

    assert client.get("/api/v1/tracks/samples").json()["samples"][0]["root_midi"] == pytest.approx(
        57.0, abs=1.0
    )


def test_an_override_does_not_outlive_its_sample(client, pitched_audio):
    """A sidecar left behind would silently re-apply to a different sample uploaded under
    the same name later."""
    for _ in range(2):
        client.post(
            "/api/v1/tracks/samples",
            files={"file": ("hit.wav", wav_bytes(pitched_audio), "audio/wav")},
            data=ATTESTED,
        )
        client.patch("/api/v1/tracks/samples/my hit?root_midi=36")
        client.delete("/api/v1/tracks/samples/my hit")

    client.post(
        "/api/v1/tracks/samples",
        files={"file": ("hit.wav", wav_bytes(pitched_audio), "audio/wav")},
        data=ATTESTED,
    )
    assert client.get("/api/v1/tracks/samples").json()["samples"][0]["root_midi"] == pytest.approx(
        57.0, abs=1.0
    )


def test_setting_a_root_on_a_sample_that_is_not_there_is_a_404(client):
    assert client.patch("/api/v1/tracks/samples/ghost?root_midi=60").status_code == 404
