"""The comparison has to read like a person wrote it, and be true.

Most of these are about wording, which is unusual for a test file and deliberate here: the
whole feature is a sentence someone reads and acts on. "Your drums sits higher" and "The
the remaining parts sits" were both real output.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.critique import (
    NOTABLE_DB,
    SAME_DB,
    Finding,
    critique,
    headline,
    severity,
)
from app.services.mastering.suggest import suggest

SR = 44100


def music(seconds=6.0, seed=0, width=0.4):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    white = rng.normal(0, 1.0, n)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, d=1.0 / SR)
    spectrum /= np.maximum(freqs, 20.0) ** 0.5
    mid = np.fft.irfft(spectrum, n)
    mid = 0.2 * mid / (np.abs(mid).max() + 1e-12)
    side = rng.normal(0, 0.02 * width / 0.4, n)
    return np.stack([mid + side, mid - side], axis=1)


# ─────────────────────────────── severity ───────────────────────────────


@pytest.mark.parametrize(
    ("delta", "expected"),
    [(0.0, "match"), (1.0, "match"), (2.0, "slight"), (-2.0, "slight"),
     (5.0, "notable"), (-5.0, "notable")],
)
def test_severity_is_symmetric_and_banded(delta, expected):
    assert severity(delta) == expected


def test_the_boundaries_are_where_the_constants_say():
    assert severity(SAME_DB - 0.01) == "match"
    assert severity(SAME_DB) == "slight"
    assert severity(NOTABLE_DB) == "notable"


# ─────────────────────────────── the verdict ───────────────────────────────


def test_a_matching_mix_is_told_so_rather_than_given_filler():
    matched = [Finding("tone", "match", "Low end matches", "...", 0.2)]
    assert "tracks the reference closely" in headline(matched)


def test_tone_and_balance_get_separate_sentences():
    """They do not share a grammatical frame. Run together they produce
    "your mix is thinner through the low mids, your drums sits higher"."""
    findings = [
        Finding("tone", "notable", "Thinner", "...", 7.0, clause="thinner through the low mids"),
        Finding("balance", "notable", "Drums higher", "...", 5.0, clause="the drums 5.0 dB hotter"),
    ]
    text = headline(findings)

    assert "your mix is thinner through the low mids." in text
    assert "It also carries the drums 5.0 dB hotter." in text
    assert "is thinner through the low mids, the drums" not in text


def test_the_verdict_leads_with_the_biggest_difference():
    findings = [
        Finding("tone", "slight", "a", "...", 2.0, clause="slightly duller"),
        Finding("tone", "notable", "b", "...", 8.0, clause="much thinner"),
    ]
    assert headline(findings).index("much thinner") < headline(findings).index("slightly duller")


def test_findings_that_match_stay_out_of_the_verdict():
    findings = [
        Finding("tone", "match", "fine", "...", 0.1, clause="fine"),
        Finding("tone", "notable", "b", "...", 6.0, clause="thinner"),
    ]
    assert "fine" not in headline(findings)


def test_a_verdict_is_a_sentence():
    findings = [Finding("tone", "notable", "b", "...", 6.0, clause="thinner")]
    text = headline(findings)
    assert text[0].isupper() and text.endswith(".")


# ─────────────────────────── against real measurements ───────────────────────


def test_every_area_is_covered_without_stems():
    source = music(seed=1)
    reference = music(seed=2)
    result = critique(suggest(source, reference, SR))

    areas = {f.area for f in result.findings}
    assert {"tone", "dynamics", "width", "loudness"} <= areas
    assert "balance" not in areas, "balance needs separated stems on both sides"


def test_differences_are_listed_before_things_that_match():
    source = music(seed=3)
    reference = music(seed=4) * 0.5
    result = critique(suggest(source, reference, SR))

    severities = [f.severity for f in result.findings]
    matched_first = severities.index("match") if "match" in severities else len(severities)
    assert all(s != "match" for s in severities[:matched_first])


def test_every_finding_says_something():
    source = music(seed=5)
    reference = music(seed=6)
    for f in critique(suggest(source, reference, SR)).findings:
        assert f.headline.strip() and f.detail.strip()
        assert f.severity in {"match", "slight", "notable"}


def test_the_tone_findings_describe_the_mix_not_the_master():
    """A fact about your mix, measured before the match - otherwise a 7 dB difference
    reads as 1.5 dB and the diagnosis quietly disappears."""
    from app.services.mastering.polish import add_warmth

    source = music(seed=7)
    reference = add_warmth(source, SR, 4.0, 450.0)
    result = suggest(source, reference, SR)

    raw = abs(result.raw_bands["body"][2])
    residual = abs(result.bands["body"][2])
    assert raw > residual, "the match should close most of it"

    body = next(
        f for f in critique(result).findings
        if "low mids" in f.headline.lower() or "low mids" in f.detail.lower()
    )
    assert f"{raw:.1f} dB" in body.detail
    assert "closes about" in body.detail


def test_an_identical_pair_is_reported_as_matching():
    audio = music(seed=8)
    result = critique(suggest(audio, audio, SR))
    assert all(f.severity == "match" for f in result.findings)
    assert "tracks the reference closely" in result.verdict
