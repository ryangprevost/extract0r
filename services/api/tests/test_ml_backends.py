"""Smoke tests for the real ML backends (X0R-302, X0R-405, X0R-406).

Every test here is marked `ml` and skips itself when its backend is not importable, so
the default suite still runs on a bare Python install (ADR-0002). The nightly CI job
installs the extras and runs them for real.

These assert that the adapters *work* — right shapes, right pitches, progress that
behaves — not that separation sounds good. Quality is X0R-306's job, and it needs a
licensed reference set rather than a synthesised tone.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from app.domain.notes import StemKind
from app.services.separation.demucs import DemucsSeparator
from app.services.transcription.basic_pitch import BasicPitchTranscriber
from app.services.transcription.drums import OnsetDrumTranscriber
from app.services.transcription.pyin import PyinTranscriber

pytestmark = pytest.mark.ml

# A4 = 440 Hz = MIDI 69, so 220 Hz is A3 = MIDI 57.
TONE_HZ = 220.0
TONE_MIDI = 57


def write_signal(path: Path, samples, sample_rate: int = 44100) -> Path:
    import numpy as np
    import soundfile as sf

    data = np.asarray(samples, dtype="float32")
    if data.ndim == 1:
        data = np.stack([data, data], axis=1)
    sf.write(str(path), data, sample_rate)
    return path


def sine(seconds: float, frequency: float = TONE_HZ, sample_rate: int = 44100):
    import numpy as np

    t = np.arange(int(seconds * sample_rate)) / sample_rate
    # Fade the edges so the onset detector sees one attack, not a click at each end.
    envelope = np.minimum(1.0, np.minimum(t * 20, (seconds - t) * 20))
    return 0.4 * np.sin(2 * math.pi * frequency * t) * envelope


def click_track(beats: int, interval_s: float = 0.5, sample_rate: int = 44100):
    """Impulses with an exponential decay — a crude but unambiguous drum stand-in."""
    import numpy as np

    total = int((beats * interval_s + 0.5) * sample_rate)
    out = np.zeros(total, dtype="float32")
    for beat in range(beats):
        start = int(beat * interval_s * sample_rate)
        length = min(int(0.05 * sample_rate), total - start)
        decay = np.exp(-np.arange(length) / (0.008 * sample_rate))
        noise = np.random.default_rng(beat).standard_normal(length)
        out[start : start + length] += 0.8 * decay * noise
    return out


# --------------------------------------------------------------------------- Demucs


@pytest.mark.skipif(not DemucsSeparator().available(), reason="demucs/torch not installed")
def test_demucs_separates_into_the_models_stems(tmp_path: Path):
    source = write_signal(tmp_path / "source.wav", sine(6.0))
    separator = DemucsSeparator(model="htdemucs", device="cpu")

    seen: list[float] = []
    result = separator.separate(source, tmp_path / "stems", on_progress=seen.append)

    assert result.backend == "demucs"
    assert {s.kind for s in result.stems} == {
        StemKind.DRUMS,
        StemKind.BASS,
        StemKind.VOCALS,
        StemKind.OTHER,
    }
    for stem in result.stems:
        assert stem.path.exists() and stem.path.stat().st_size > 0
        assert stem.sample_rate == 44100
        assert stem.duration_s == pytest.approx(6.0, abs=0.2)


@pytest.mark.skipif(not DemucsSeparator().available(), reason="demucs/torch not installed")
def test_demucs_progress_is_monotonic_and_completes(tmp_path: Path):
    source = write_signal(tmp_path / "source.wav", sine(6.0))
    seen: list[float] = []
    DemucsSeparator(model="htdemucs", device="cpu").separate(
        source, tmp_path / "stems", on_progress=seen.append
    )

    assert seen, "demucs reported no progress at all"
    assert seen == sorted(seen)
    assert seen[0] >= 0.0 and seen[-1] == pytest.approx(1.0, abs=0.02)


@pytest.mark.skipif(not DemucsSeparator().available(), reason="demucs/torch not installed")
def test_demucs_failure_surfaces_as_a_useful_error(tmp_path: Path):
    missing = tmp_path / "does-not-exist.wav"
    with pytest.raises(RuntimeError) as caught:
        DemucsSeparator(model="htdemucs").separate(missing, tmp_path / "stems")
    # The point is that the tail of Demucs' own output reaches the user.
    assert "demucs failed" in str(caught.value).lower()


# ---------------------------------------------------------------------- basic-pitch


@pytest.mark.skipif(
    not BasicPitchTranscriber().available(), reason="basic-pitch not installed"
)
def test_basic_pitch_finds_the_pitch_it_was_given(tmp_path: Path):
    source = write_signal(tmp_path / "tone.wav", sine(3.0, TONE_HZ))
    result = BasicPitchTranscriber().transcribe(source, StemKind.GUITAR)

    assert result.notes, "basic-pitch found nothing in a clean sustained tone"
    assert result.backend.startswith("basic_pitch")
    # Allow an octave error: octave confusion is a known failure mode, not a bug here.
    detected = {n.pitch % 12 for n in result.notes}
    assert TONE_MIDI % 12 in detected


@pytest.mark.skipif(
    not BasicPitchTranscriber().available(), reason="basic-pitch not installed"
)
def test_basic_pitch_notes_are_well_formed(tmp_path: Path):
    source = write_signal(tmp_path / "tone.wav", sine(3.0))
    result = BasicPitchTranscriber().transcribe(source, StemKind.BASS)

    for note in result.notes:
        assert note.end_s > note.start_s
        assert 0 <= note.pitch <= 127
        assert 0.0 <= note.confidence <= 1.0
    assert all(n.start_s < 3.5 for n in result.notes), "notes past the end of the file"


@pytest.mark.skipif(
    not BasicPitchTranscriber().available(), reason="basic-pitch not installed"
)
def test_basic_pitch_output_survives_the_fretboard_solver(tmp_path: Path):
    """The real integration risk: raw model output fed straight to the solver.

    Notes are passed through unfiltered on purpose. A guitar stem carries bass bleed, so
    out-of-range pitches are normal, and the solver must absorb them rather than abort -
    which is exactly what it used to do.
    """
    from app.domain.tab.fretboard import STANDARD_GUITAR, solve_with_report

    source = write_signal(tmp_path / "tone.wav", sine(3.0))
    result = BasicPitchTranscriber().transcribe(source, StemKind.GUITAR)

    report = solve_with_report(result.notes, STANDARD_GUITAR)
    placed = sum(len(s.positions) for s in report.shapes)
    assert placed + len(report.dropped) == len(result.notes), "notes went missing"


# ------------------------------------------------------------------------- drums


@pytest.mark.skipif(
    not OnsetDrumTranscriber().available(), reason="librosa not installed"
)
def test_onset_drums_finds_roughly_the_right_number_of_hits(tmp_path: Path):
    source = write_signal(tmp_path / "clicks.wav", click_track(beats=8))
    result = OnsetDrumTranscriber().transcribe(source, StemKind.DRUMS)

    assert result.backend == "onset_drums"
    onsets = sorted({round(n.start_s, 2) for n in result.notes})
    assert 6 <= len(onsets) <= 10, f"expected ~8 onsets, got {len(onsets)}"


@pytest.mark.skipif(
    not OnsetDrumTranscriber().available(), reason="librosa not installed"
)
def test_onset_drums_reports_a_detected_tempo(tmp_path: Path):
    """Tempo must come from the audio, not from Transcription's 120 BPM default.

    Asserted with an octave tolerance on purpose. Beat trackers routinely report
    half or double the true tempo — librosa calls this 100 BPM track and a 200 BPM
    one both "99.4" — and that ambiguity is X0R-407's problem to resolve with a time
    signature, not something this adapter can or should fix.
    """
    # 0.6 s between hits is 100 BPM.
    source = write_signal(tmp_path / "clicks.wav", click_track(beats=16, interval_s=0.6))
    detected = OnsetDrumTranscriber().transcribe(source, StemKind.DRUMS).tempo_bpm

    assert detected != 120.0, "looks like the hard-coded default, not a detection"
    ratios = [detected / candidate for candidate in (50.0, 100.0, 200.0)]
    assert any(abs(r - 1.0) < 0.1 for r in ratios), (
        f"{detected:.1f} BPM is not 100 BPM or an octave of it"
    )


@pytest.mark.skipif(
    not OnsetDrumTranscriber().available(), reason="librosa not installed"
)
def test_onset_drums_emits_only_general_midi_drum_keys(tmp_path: Path):
    from app.domain.tab.drum_tab import GM_DRUM_MAP

    source = write_signal(tmp_path / "clicks.wav", click_track(beats=8))
    result = OnsetDrumTranscriber().transcribe(source, StemKind.DRUMS)

    # Anything outside the map would silently vanish when the tab is rendered.
    assert all(n.pitch in GM_DRUM_MAP for n in result.notes)


# -------------------------------------------------------------------------- pYIN


@pytest.mark.skipif(not PyinTranscriber().available(), reason="librosa not installed")
def test_pyin_finds_the_exact_pitch_of_a_bass_note(tmp_path: Path):
    # 220 Hz is A3. pYIN is monophonic, so this should be unambiguous.
    source = write_signal(tmp_path / "bass.wav", sine(2.0, TONE_HZ))
    result = PyinTranscriber().transcribe(source, StemKind.BASS)

    assert result.notes, "pyin found nothing in a clean sustained tone"
    longest = max(result.notes, key=lambda n: n.duration_s)
    assert longest.pitch == TONE_MIDI
    assert longest.duration_s > 1.0


@pytest.mark.skipif(not PyinTranscriber().available(), reason="librosa not installed")
def test_pyin_separates_two_successive_pitches(tmp_path: Path):
    import numpy as np

    # A3 (57) then E4 (64), one second each.
    source = write_signal(
        tmp_path / "line.wav",
        np.concatenate([sine(1.0, 220.0), sine(1.0, 329.63)]),
    )
    result = PyinTranscriber().transcribe(source, StemKind.BASS)

    pitches = [n.pitch for n in result.notes if n.duration_s > 0.2]
    assert 57 in pitches and 64 in pitches, f"got {pitches}"
    assert pitches.index(57) < pitches.index(64), "notes came out in the wrong order"


@pytest.mark.skipif(not PyinTranscriber().available(), reason="librosa not installed")
def test_pyin_ignores_silence(tmp_path: Path):
    import numpy as np

    source = write_signal(tmp_path / "quiet.wav", np.zeros(44100 * 2, dtype="float32"))
    result = PyinTranscriber().transcribe(source, StemKind.BASS)
    assert result.notes == []


@pytest.mark.skipif(not PyinTranscriber().available(), reason="librosa not installed")
def test_pyin_gets_the_octave_right_even_with_a_weak_fundamental(tmp_path: Path):
    """Octave errors are the classic pitch-tracker failure, so pin the behaviour down.

    A real bass often has less energy at the fundamental than at the second harmonic —
    small speakers and cheap pickups both do this — and a tracker that locks onto the
    harmonic reports everything an octave high. Verified here across harmonic balances
    from pure-fundamental to fundamental-swamped.
    """
    import numpy as np

    # E2, A2, D3, G3 - the open strings of a 4-string bass.
    expected = [40, 45, 50, 55]
    balances = {
        "pure": [(1, 1.0)],
        "weak fundamental": [(1, 0.2), (2, 0.8)],
        "realistic": [(1, 1.0), (2, 0.5), (3, 0.3), (4, 0.15)],
    }

    for label, harmonics in balances.items():
        parts = []
        for pitch in expected:
            t = np.arange(int(2.0 * 44100)) / 44100
            wave = sum(
                amp * np.sin(2 * math.pi * (440.0 * 2 ** ((pitch - 69) / 12)) * mult * t)
                for mult, amp in harmonics
            )
            parts.append(wave * np.minimum(1.0, np.minimum(t * 30, (2.0 - t) * 30)))
        audio = np.concatenate(parts)
        source = write_signal(tmp_path / f"bass-{label}.wav", audio / np.max(np.abs(audio)) * 0.8)

        result = PyinTranscriber().transcribe(source, StemKind.BASS)
        detected = [n.pitch for n in result.notes if n.duration_s > 0.3]
        assert detected == expected, f"{label}: got {detected}, expected {expected}"
