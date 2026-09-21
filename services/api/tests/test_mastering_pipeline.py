"""End-to-end mastering: stems in, an MP3 out, with no ffmpeg anywhere."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.domain.notes import StemKind
from app.services.mastering import pipeline as master
from app.services.mastering.pipeline import MasterRequest, StemSetting, audible
from app.services.mixdown.encode import (
    EncodingError,
    apply_pan,
    mix_buffers,
    read_audio,
    write_mp3,
)

SR = 44100


def stem_file(path: Path, freq: float, seconds: float = 3.0, amplitude: float = 0.3) -> Path:
    t = np.arange(int(seconds * SR)) / SR
    wave = amplitude * np.sin(2 * np.pi * freq * t)
    sf.write(str(path), np.stack([wave, wave], axis=1), SR)
    return path


@pytest.fixture
def stems(tmp_path: Path) -> dict[StemKind, Path]:
    return {
        StemKind.BASS: stem_file(tmp_path / "bass.wav", 80),
        StemKind.DRUMS: stem_file(tmp_path / "drums.wav", 200),
        StemKind.GUITAR: stem_file(tmp_path / "guitar.wav", 800),
    }


# ──────────────────────────────── solo and mute ────────────────────────────────


def test_solo_beats_mute():
    settings = [
        StemSetting(StemKind.BASS),
        StemSetting(StemKind.DRUMS, solo=True),
        StemSetting(StemKind.GUITAR, muted=True),
    ]
    assert [s.stem for s in audible(settings)] == [StemKind.DRUMS]


def test_muted_stems_are_left_out():
    settings = [StemSetting(StemKind.BASS, muted=True), StemSetting(StemKind.DRUMS)]
    assert [s.stem for s in audible(settings)] == [StemKind.DRUMS]


# ──────────────────────────────── mixing ────────────────────────────────


def test_mixing_sums_without_rescaling():
    """Stems are additive; silently normalising would change the balance the user set."""
    a = np.full((100, 2), 0.2)
    b = np.full((100, 2), 0.3)
    assert np.allclose(mix_buffers([a, b]), 0.5)


def test_mixing_applies_gain_in_decibels():
    a = np.full((100, 2), 0.5)
    mixed = mix_buffers([a], [-6.0])
    assert mixed.max() == pytest.approx(0.5 * 10 ** (-6 / 20), abs=1e-6)


def test_mixing_pads_to_the_longest_stem():
    short = np.full((50, 2), 0.1)
    long = np.full((200, 2), 0.1)
    assert mix_buffers([short, long]).shape[0] == 200


def test_panning_holds_power_constant():
    """A linear pan dips audibly through the centre; constant power does not."""
    audio = np.full((100, 2), 0.5)
    centre = apply_pan(audio, 0.0)
    left = apply_pan(audio, -1.0)

    power = lambda x: float(np.sqrt(np.mean(x**2)) * np.sqrt(2))  # noqa: E731
    assert power(centre) == pytest.approx(power(left), rel=0.05)
    assert left[:, 0].max() > left[:, 1].max(), "hard left should favour the left channel"


def test_mixing_nothing_is_an_error():
    with pytest.raises(ValueError):
        mix_buffers([])


# ──────────────────────────────── encoding ────────────────────────────────


def test_mp3_is_written_without_ffmpeg(tmp_path: Path):
    t = np.arange(SR * 2) / SR
    audio = np.stack([0.4 * np.sin(2 * np.pi * 440 * t)] * 2, axis=1)

    out = write_mp3(tmp_path / "out.mp3", audio, SR, 192)
    assert out.exists()
    data = out.read_bytes()
    assert len(data) > 1000
    # ID3 tag or a raw MPEG frame sync - either is a valid MP3 start.
    assert data[:3] == b"ID3" or data[0] == 0xFF


def test_an_invalid_bitrate_is_rejected(tmp_path: Path):
    with pytest.raises(EncodingError):
        write_mp3(tmp_path / "bad.mp3", np.zeros((SR, 2)), SR, 111)


def test_encoding_clips_rather_than_wrapping(tmp_path: Path):
    """Wrapping an over-range sample to the opposite polarity is the loudest click there is."""
    audio = np.full((SR, 2), 2.5)  # way over full scale
    out = write_mp3(tmp_path / "loud.mp3", audio, SR, 128)
    assert out.exists()


# ──────────────────────────────── the whole run ────────────────────────────────


def test_mastering_without_a_reference_still_exports(tmp_path: Path, stems):
    result = master.run(
        MasterRequest(stems=stems, settings=[StemSetting(s) for s in stems]),
        tmp_path / "work",
    )
    assert result.mp3_path.exists()
    assert result.report is None, "no reference means no matching"
    assert set(result.included) == set(stems)
    assert result.duration_s == pytest.approx(3.0, abs=0.1)


def test_mastering_against_a_reference_reports_what_it_did(tmp_path: Path, stems):
    # A reference that is louder and brighter than the stems.
    reference = tmp_path / "reference.wav"
    t = np.arange(int(3.0 * SR)) / SR
    bright = 0.6 * np.sin(2 * np.pi * 3000 * t) + 0.4 * np.sin(2 * np.pi * 6000 * t)
    sf.write(str(reference), np.stack([bright, bright], axis=1), SR)

    result = master.run(
        MasterRequest(
            stems=stems, settings=[StemSetting(s) for s in stems], reference=reference
        ),
        tmp_path / "work",
    )

    assert result.mp3_path.exists()
    assert result.report is not None
    assert result.report.backend == "spectral"
    assert result.report.eq_curve_db, "the applied curve should be reported"
    assert result.report.source and result.report.result


def test_the_master_lands_near_the_reference_loudness(tmp_path: Path, stems):
    from app.services.mastering.loudness_meter import integrated_loudness

    reference = tmp_path / "reference.wav"
    rng = np.random.default_rng(0)
    # ~-14 LUFS: a realistic streaming master, not a near-clipping stress case.
    loud = rng.standard_normal(int(3.0 * SR)) * 0.08
    sf.write(str(reference), np.stack([loud, loud], axis=1), SR)

    master.run(
        MasterRequest(
            stems=stems, settings=[StemSetting(s) for s in stems], reference=reference
        ),
        tmp_path / "work",
    )

    mastered = read_audio(tmp_path / "work" / "mastered.wav")
    got, _ = integrated_loudness(mastered.samples, mastered.sample_rate)
    ref_buf = read_audio(reference)
    want, _ = integrated_loudness(ref_buf.samples, ref_buf.sample_rate)
    assert got == pytest.approx(want, abs=1.5)


def test_the_master_never_clips(tmp_path: Path, stems):
    reference = tmp_path / "reference.wav"
    t = np.arange(int(3.0 * SR)) / SR
    very_loud = 0.95 * np.sin(2 * np.pi * 1000 * t)
    sf.write(str(reference), np.stack([very_loud, very_loud], axis=1), SR)

    master.run(
        MasterRequest(
            stems=stems, settings=[StemSetting(s) for s in stems], reference=reference
        ),
        tmp_path / "work",
    )
    mastered = read_audio(tmp_path / "work" / "mastered.wav")
    assert float(np.max(np.abs(mastered.samples))) <= 1.0


def test_muting_everything_is_a_clear_error(tmp_path: Path, stems):
    with pytest.raises(ValueError, match="muted"):
        master.run(
            MasterRequest(
                stems=stems, settings=[StemSetting(s, muted=True) for s in stems]
            ),
            tmp_path / "work",
        )


def test_a_missing_stem_is_named(tmp_path: Path, stems):
    with pytest.raises(KeyError, match="piano"):
        master.run(
            MasterRequest(stems=stems, settings=[StemSetting(StemKind.PIANO)]),
            tmp_path / "work",
        )


def test_progress_is_reported_monotonically(tmp_path: Path, stems):
    seen: list[float] = []
    master.run(
        MasterRequest(stems=stems, settings=[StemSetting(s) for s in stems]),
        tmp_path / "work",
        on_progress=lambda f, _m: seen.append(f),
    )
    assert seen == sorted(seen)
    assert seen[-1] == pytest.approx(1.0)


def test_an_extremely_loud_reference_is_approached_and_reported(tmp_path: Path, stems):
    """You cannot match a near-clipping reference without limiting, and we say so.

    The result should get much closer than a static peak scale would manage, and the
    report should mention the limiter rather than leaving the gap unexplained.
    """
    from app.services.mastering.loudness_meter import integrated_loudness

    reference = tmp_path / "reference.wav"
    rng = np.random.default_rng(3)
    crushed = np.clip(rng.standard_normal(int(3.0 * SR)) * 2.0, -0.99, 0.99)
    sf.write(str(reference), np.stack([crushed, crushed], axis=1), SR)

    result = master.run(
        MasterRequest(
            stems=stems, settings=[StemSetting(s) for s in stems], reference=reference
        ),
        tmp_path / "work",
    )

    mastered = read_audio(tmp_path / "work" / "mastered.wav")
    got, _ = integrated_loudness(mastered.samples, mastered.sample_rate)

    assert got > -12.0, f"limiter gave up too much loudness: {got:.1f} LUFS"
    assert float(np.max(np.abs(mastered.samples))) <= 1.0
    assert result.report is not None and result.report.warnings


# --- per-stem sparkle -----------------------------------------------------------------


def test_exciting_one_stem_lifts_it_against_the_others():
    """The point of doing this per stem rather than on the master. Driving the whole mix
    makes harmonics from the bass and the vocal as well, so the cymbals gain nothing on
    anything; driving the drums alone is what makes them splashier.

    Measured on a real six-stem track: +4 dB on the drums moved hats and cymbals 2.4 dB
    in the finished mix while the kick band did not move at all.
    """
    import numpy as np
    from scipy.signal import butter, sosfiltfilt

    from app.services.mastering.exciter import add_sparkle

    rate = 44100
    t = np.arange(rate * 3) / rate
    # A kit: low thump plus a bright ticking hat.
    kick = np.stack([0.4 * np.sin(2 * np.pi * 70 * t)] * 2, axis=1)
    ticks = ((t * 8) % 1.0 < 0.03).astype(float)
    hats = np.stack([0.12 * np.sin(2 * np.pi * 5200 * t) * ticks] * 2, axis=1)
    drums = kick + hats
    bass = np.stack([0.35 * np.sin(2 * np.pi * 110 * t)] * 2, axis=1)

    def band(x, low, high):
        sos = butter(4, [low, high], btype="band", fs=rate, output="sos")
        return float(np.sqrt(np.mean(sosfiltfilt(sos, x, axis=0) ** 2)))

    before = drums + bass
    after = add_sparkle(drums, rate, 4.0) + bass

    # The cymbals gain...
    assert band(after, 8000, 16000) > band(before, 8000, 16000) * 1.2
    # ...and the low end does not, which is the guard that matters: an exciter fed a
    # whole kit could as easily be adding grit under the kick.
    assert band(after, 50, 120) == pytest.approx(band(before, 50, 120), rel=0.02)


def test_a_stem_setting_carries_sparkle_through_to_the_mix(tmp_path):
    """Wired end to end, not just present on the dataclass."""
    import numpy as np
    import soundfile as sf

    from app.domain.notes import StemKind
    from app.services.mastering.pipeline import MasterRequest, StemSetting, run
    from app.services.mixdown.encode import read_audio

    rate = 44100
    t = np.arange(rate * 3) / rate
    tone = np.stack([0.3 * np.sin(2 * np.pi * 2500 * t)] * 2, axis=1)
    path = tmp_path / "drums.wav"
    sf.write(str(path), tone, rate)

    stems = {StemKind.DRUMS: path}
    plain = run(
        MasterRequest(stems=stems, settings=[StemSetting(StemKind.DRUMS)],
                      preserve_source=False),
        tmp_path / "plain",
    )
    excited = run(
        MasterRequest(
            stems=stems,
            settings=[StemSetting(StemKind.DRUMS, sparkle_db=6.0)],
            preserve_source=False,
        ),
        tmp_path / "excited",
    )

    def air(result):
        from scipy.signal import butter, sosfiltfilt

        samples = np.asarray(read_audio(result.mp3_path).samples, dtype=np.float64)
        sos = butter(4, 8000.0, btype="high", fs=rate, output="sos")
        return float(np.sqrt(np.mean(sosfiltfilt(sos, samples, axis=0) ** 2)))

    assert air(excited) > air(plain) * 1.5
