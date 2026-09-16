"""Suggestions have to be proportionate, honest, and about the right band.

The engine's job is not to be clever - it is to move a dial by an amount someone can
check, and to say why in a sentence they can disagree with.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.dsp import DEFAULT_N_FFT
from app.services.mastering.polish import (
    MAX_WARMTH_DB,
    add_air,
    add_warmth,
    bell_ramp,
    shelf_ramp,
)
from app.services.mastering.suggest import (
    BANDS,
    MEANINGFUL_GAP_DB,
    gain_for,
    suggest,
)

SR = 44100


def music(seconds=8.0, seed=0, width=0.4):
    """Pink-ish stereo noise: a stand-in with a realistic spectral slope."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    white = rng.normal(0, 1.0, n)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, d=1.0 / SR)
    spectrum /= np.maximum(freqs, 20.0) ** 0.5  # -3 dB/octave
    mid = np.fft.irfft(spectrum, n)
    mid = 0.2 * mid / (np.abs(mid).max() + 1e-12)
    side = rng.normal(0, 0.02 * width / 0.4, n)
    return np.stack([mid + side, mid - side], axis=1)


def band_db(samples, band):
    low, high = BANDS[band]
    mono = samples.mean(axis=1)
    spec = np.abs(np.fft.rfft(mono)) ** 2
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / SR)
    return 10 * np.log10(spec[(freqs >= low) & (freqs < high)].sum() / spec.sum() + 1e-20)


# ─────────────────────────── the gain arithmetic ───────────────────────────


def spectrum_of(samples):
    """The power spectrum on the same bin grid gain_for expects."""
    from app.services.mastering.dsp import average_spectrum

    return average_spectrum(samples, DEFAULT_N_FFT, DEFAULT_N_FFT // 4) ** 2


def test_a_filter_that_barely_reaches_a_band_suggests_nothing():
    """The bug this guards: a 250 Hz low shelf hardly touches the 250-800 Hz band, so
    closing a 1 dB gap 'needed' 16 dB, which clamped to the maximum and looked
    deliberate."""
    audio = music(seed=0)
    # A shelf far below the band, pointing away from it.
    barely = shelf_ramp(DEFAULT_N_FFT, SR, 60.0, kind="low")
    assert gain_for(barely, 2.0, "presence", SR, spectrum_of(audio)) == 0.0


def test_a_well_placed_filter_asks_for_about_the_gap():
    """A filter covering its band needs roughly the gap, not a multiple of it."""
    bell = bell_ramp(DEFAULT_N_FFT, SR, 450.0)
    gain = gain_for(bell, 2.0, "body", SR, spectrum_of(music(seed=0)))
    assert 2.0 <= gain <= 5.0


def test_the_suggested_gain_actually_closes_the_gap_it_was_computed_for():
    """End to end on real audio: apply the number and the band lands where predicted."""
    audio = music(seed=1)
    bell = bell_ramp(DEFAULT_N_FFT, SR, 450.0)
    wanted = 2.0
    gain = gain_for(bell, wanted, "body", SR, spectrum_of(audio))

    moved = add_warmth(audio, SR, gain, 450.0)
    achieved = band_db(moved, "body") - band_db(audio, "body")
    assert achieved == pytest.approx(wanted, abs=0.35)


def test_the_same_holds_for_the_brightness_shelf():
    audio = music(seed=2)
    ramp = shelf_ramp(DEFAULT_N_FFT, SR, 3000.0, kind="high")
    wanted = 2.5
    gain = gain_for(ramp, wanted, "presence", SR, spectrum_of(audio))

    moved = add_air(audio, SR, gain, 3000.0)
    achieved = band_db(moved, "presence") - band_db(audio, "presence")
    assert achieved == pytest.approx(wanted, abs=0.35)


# ─────────────────────────── what it recommends ───────────────────────────


def test_a_dull_mix_against_a_bright_reference_asks_for_brightness():
    """With matching turned down, closing the gap is entirely the dials' job."""
    source = music(seed=3)
    reference = add_air(source, SR, 6.0, 3000.0)

    result = suggest(source, reference, SR, match_strength=0.0)
    assert result.polish.air_db > 0
    assert any(r.control == "brightness" for r in result.reasons)


def test_a_mix_already_brighter_than_its_reference_is_left_alone():
    """And says so, rather than silently doing nothing."""
    reference = music(seed=4)
    source = add_air(reference, SR, 6.0, 3000.0)

    result = suggest(source, reference, SR, match_strength=0.0)
    assert result.polish.air_db == 0.0
    reason = next(r for r in result.reasons if r.control == "brightness")
    assert "brighter than the reference" in reason.text


def test_every_control_gets_a_reason_whether_or_not_it_moved():
    source = music(seed=5)
    reference = music(seed=6)
    result = suggest(source, reference, SR)

    controls = {r.control for r in result.reasons}
    assert controls == {"brightness", "warmth", "width", "headroom"}
    assert all(r.text.strip() for r in result.reasons)


def test_suggestions_stay_inside_the_dials_own_limits():
    """A wild reference must not produce a value the API would reject."""
    source = music(seed=7) * 0.5
    reference = add_air(add_warmth(music(seed=8), SR, 4.0), SR, 6.0, 3000.0)

    p = suggest(source, reference, SR).polish
    assert 0.0 <= p.air_db <= 6.0
    assert 0.0 <= p.warmth_db <= MAX_WARMTH_DB
    assert 0.7 <= p.width <= 1.6
    assert 0.0 <= p.headroom_db <= 6.0


def test_a_squashed_reference_earns_a_headroom_suggestion():
    from app.services.mastering.dsp import apply_gain_db, limit

    source = music(seed=9)
    flattened = limit(apply_gain_db(music(seed=10), 14.0), SR, -1.0)

    result = suggest(source, flattened, SR)
    if result.reference_crest_db < 7.0:
        assert result.polish.headroom_db > 0
        reason = next(r for r in result.reasons if r.control == "headroom")
        assert "limited" in reason.text


def test_a_narrow_mix_against_a_wide_reference_asks_for_width():
    source = music(seed=11, width=0.15)
    reference = music(seed=11, width=1.0)

    result = suggest(source, reference, SR, match_strength=0.0)
    assert result.polish.width > 1.0
    assert result.reference_width > result.source_width


def test_identical_tracks_need_nothing():
    audio = music(seed=12)
    result = suggest(audio, audio, SR)
    assert result.polish.air_db == 0.0
    assert result.polish.warmth_db == 0.0
    assert result.polish.width == 1.0


def test_gaps_are_measured_after_matching_not_before():
    """Matching closes most of a tonal gap on its own; suggesting on the raw source
    double-corrects. A reference that differs only by an EQ the match can undo should
    leave almost nothing for the dials."""
    source = music(seed=13)
    reference = add_warmth(source, SR, 3.5, 450.0)

    result = suggest(source, reference, SR)
    raw_gap = band_db(reference, "body") - band_db(source, "body")
    residual = result.bands["body"][2]

    assert raw_gap > MEANINGFUL_GAP_DB
    assert abs(residual) < raw_gap, "the match was not taken into account"


# ─────────────────────────── through the actual endpoint ───────────────────────
#
# These exist because every test above calls suggest() directly, and the route around it
# shipped reading a field that does not exist. It 500'd on every real request while the
# suite stayed green. A function being right is not the same as an endpoint working.


def upload(client, sample_wav):
    with sample_wav.open("rb") as handle:
        response = client.post(
            "/api/v1/tracks",
            files={"file": ("song.wav", handle, "audio/wav")},
            data={"owns_or_licensed": "true", "personal_use_only": "true"},
        )
    assert response.status_code == 201, response.text
    return response.json()["track_id"]


def attach_reference(client, track, sample_wav):
    with sample_wav.open("rb") as handle:
        response = client.post(
            f"/api/v1/tracks/{track}/reference",
            files={"file": ("ref.wav", handle, "audio/wav")},
            data={"owns_or_licensed": "true"},
        )
    assert response.status_code == 201, response.text


def test_the_endpoint_answers_before_any_separation(client, sample_wav):
    """The normalised copy is only written at separation time, so this has to work off
    the upload itself - which is exactly what broke."""
    track = upload(client, sample_wav)
    attach_reference(client, track, sample_wav)

    response = client.get(f"/api/v1/tracks/{track}/master/suggest")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["available"] is True
    assert set(body["settings"]) >= {"brightness_db", "warmth_db", "width", "headroom_db"}
    assert body["summary"]["verdict"].strip()
    assert body["summary"]["findings"]


def test_every_finding_from_the_endpoint_is_shaped_for_the_ui(client, sample_wav):
    track = upload(client, sample_wav)
    attach_reference(client, track, sample_wav)

    for f in client.get(f"/api/v1/tracks/{track}/master/suggest").json()["summary"]["findings"]:
        assert set(f) == {"area", "severity", "headline", "detail", "delta_db"}
        assert f["severity"] in {"match", "slight", "notable"}


def test_without_a_reference_it_says_so_rather_than_failing(client, sample_wav):
    track = upload(client, sample_wav)
    response = client.get(f"/api/v1/tracks/{track}/master/suggest")
    assert response.status_code == 200
    assert response.json()["available"] is False


def test_an_unknown_track_is_a_404(client):
    assert client.get("/api/v1/tracks/nope/master/suggest").status_code == 404
