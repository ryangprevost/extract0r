"""Where does this mix actually differ from the reference, and which dial closes the gap?

The matching stage already moves tone and level toward the reference. This is the part it
cannot do: deciding what the person probably *wants* on top, and saying why in a sentence
they can disagree with.

Every suggestion carries its own reason and the measurement behind it. A dial that moves
on its own without saying why is worse than one that stays put — the number is only useful
if you can check it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.services.mastering.dsp import (
    DEFAULT_N_FFT,
    MatchSettings,
    average_spectrum,
    matching_curve,
    stereo_width,
)
from app.services.mastering.loudness_meter import integrated_loudness
from app.services.mastering.polish import (
    DEFAULT_WARMTH_HZ,
    MAX_AIR_DB,
    MAX_WARMTH_DB,
    MAX_WIDTH,
    Polish,
    bell_ramp,
    shelf_ramp,
)

#: The bands a person actually talks about, rather than octave-spaced ones.
BANDS: dict[str, tuple[float, float]] = {
    "low": (20.0, 250.0),
    "body": (250.0, 800.0),
    "mid": (800.0, 2500.0),
    "presence": (2500.0, 8000.0),
    "air": (8000.0, 18000.0),
}

#: Below this a gap is inside the noise of the measurement and not worth a dial move.
MEANINGFUL_GAP_DB = 1.2

#: How much of a measured gap to actually close. Matching a reference exactly is rarely
#: what someone wants - it is their record, not a copy of someone else's.
CLOSE_FRACTION = 0.7

#: A filter that cannot deliver this fraction of a gap is the wrong tool for it.
MIN_BAND_OVERLAP = 0.25

#: A reference this flattened is a loudness-war master; sitting under it keeps some punch.
SQUASHED_CREST_DB = 7.0


@dataclass(slots=True)
class Reason:
    control: str
    text: str


@dataclass(slots=True)
class Suggestion:
    polish: Polish = field(default_factory=Polish)
    reasons: list[Reason] = field(default_factory=list)
    #: band -> (source share dB, reference share dB, gap)
    bands: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    source_width: float = 0.0
    reference_width: float = 0.0
    reference_crest_db: float = 0.0


def shares_from(power: np.ndarray, freqs: np.ndarray) -> dict[str, float]:
    """Each band's energy as a share of the whole, in dB.

    A share rather than an absolute level, because the two tracks are at different
    volumes and the question is about balance, not loudness.
    """
    total = power.sum() + 1e-20
    return {
        name: float(10.0 * np.log10(power[(freqs >= low) & (freqs < high)].sum() / total + 1e-20))
        for name, (low, high) in BANDS.items()
    }


def matched_shares(
    source: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    settings: MatchSettings,
) -> tuple[dict[str, float], dict[str, float], np.ndarray]:
    """Band shares after matching, plus the power spectrum the dials will act on.

    Suggesting from the raw source double-corrects. Matching already moves tone toward the
    reference - on a real pair it applied +3.2 dB at 500 Hz, right in the body range - so a
    gap it is about to close is not a gap the dials should close again. Measured raw, that
    same pair looked 7.0 dB short of body and the engine wanted the full +4 dB shelf on
    top of a correction that was already coming.

    No audio is rendered: the correction curve is applied to the source's average spectrum,
    which is exactly what `apply_curve` does to the audio itself.
    """
    source_spectrum = average_spectrum(source, settings.n_fft, settings.hop)
    reference_spectrum = average_spectrum(reference, settings.n_fft, settings.hop)
    curve = matching_curve(source_spectrum, reference_spectrum, sample_rate, settings)

    freqs = np.fft.rfftfreq(settings.n_fft, d=1.0 / sample_rate)
    matched_power = (source_spectrum * curve) ** 2
    return (
        shares_from(matched_power, freqs),
        shares_from(reference_spectrum**2, freqs),
        matched_power,
    )


def share_change_db(
    power: np.ndarray, ramp: np.ndarray, inside: np.ndarray, gain_db: float
) -> float:
    """How far a band's *share* of the whole moves when a filter of `gain_db` is applied.

    Share, not absolute energy, because that is what the gaps are measured in - and the
    difference matters: a shelf lifts everything above its corner, so the denominator
    moves too and the band gains less than the filter gives it.
    """
    boosted = power * 10.0 ** (gain_db * ramp / 10.0)
    before = power[inside].sum() / (power.sum() + 1e-30)
    after = boosted[inside].sum() / (boosted.sum() + 1e-30)
    return float(10.0 * np.log10((after + 1e-30) / (before + 1e-30)))


def gain_for(
    ramp: np.ndarray,
    gap_db: float,
    band: str,
    sample_rate: int,
    power: np.ndarray,
    limit_db: float = 12.0,
) -> float:
    """What filter gain moves `band` by `gap_db`, given that filter's shape?

    Solved numerically rather than estimated. Two linear approximations were tried first
    and both undershot by around 40% - averaging the ramp across the band ignores where
    its energy sits, and energy-weighting it still ignores that a shelf lifts the bands
    above the one being measured, which moves the denominator. Bisection over the exact
    expression costs a few dozen operations on a 2049-bin array and cannot be wrong about
    either.

    Returns 0 when the filter barely reaches the band. Dividing by a small overlap is how
    a 1.5 dB gap became a 16 dB demand that clamped to the maximum and looked considered.
    """
    freqs = np.fft.rfftfreq(DEFAULT_N_FFT, d=1.0 / sample_rate)
    low, high = BANDS[band]
    inside = (freqs >= low) & (freqs < high)
    if not inside.any() or gap_db <= 0:
        return 0.0

    reach = share_change_db(power, ramp, inside, limit_db)
    if reach < gap_db * MIN_BAND_OVERLAP:
        return 0.0  # even at full tilt this filter cannot address that band
    if reach <= gap_db:
        return limit_db

    lower, upper = 0.0, limit_db
    for _ in range(24):
        middle = (lower + upper) / 2.0
        if share_change_db(power, ramp, inside, middle) < gap_db:
            lower = middle
        else:
            upper = middle
    return (lower + upper) / 2.0


def suggest(
    source: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    match_strength: float = 1.0,
) -> Suggestion:
    """Compare a mix with its reference and propose where to set the finishing dials.

    The comparison is against the *matched* mix, not the raw one - see `matched_shares`.
    """
    settings = MatchSettings(strength=match_strength)
    mine, theirs, power = matched_shares(source, reference, sample_rate, settings)
    out = Suggestion()
    out.bands = {name: (mine[name], theirs[name], theirs[name] - mine[name]) for name in BANDS}

    # --- brightness: presence first, air second ------------------------------
    #
    # Ordered deliberately. "Not bright enough" is usually a presence problem around
    # 3 kHz - clarity, the sense of the mix being in front of you - and a shelf up at
    # 10 kHz adds sheen without touching it. Recommending air for a presence gap is the
    # commonest way to make a mix shinier and no clearer.
    presence_gap = out.bands["presence"][2]
    air_gap = out.bands["air"][2]

    if presence_gap > MEANINGFUL_GAP_DB:
        hz = 3000.0
        ramp = shelf_ramp(DEFAULT_N_FFT, sample_rate, hz, kind="high")
        gain = gain_for(ramp, presence_gap * CLOSE_FRACTION, "presence", sample_rate, power)
        out.polish.air_db = round(float(np.clip(gain, 0.0, MAX_AIR_DB)), 1)
        out.polish.air_hz = hz
        out.reasons.append(
            Reason(
                "brightness",
                f"Your mix sits {presence_gap:.1f} dB below the reference between 2.5 and "
                f"8 kHz — that band is clarity, not sparkle, so the shelf starts at 3 kHz "
                f"rather than up in the air band.",
            )
        )
    elif air_gap > MEANINGFUL_GAP_DB:
        hz = 8000.0
        ramp = shelf_ramp(DEFAULT_N_FFT, sample_rate, hz, kind="high")
        gain = gain_for(ramp, air_gap * CLOSE_FRACTION, "air", sample_rate, power)
        out.polish.air_db = round(float(np.clip(gain, 0.0, MAX_AIR_DB)), 1)
        out.polish.air_hz = hz
        out.reasons.append(
            Reason(
                "brightness",
                f"Presence is already close to the reference, but the top octave is "
                f"{air_gap:.1f} dB down. An 8 kHz shelf adds air without making the "
                f"midrange harsh.",
            )
        )
    elif presence_gap < -MEANINGFUL_GAP_DB:
        out.reasons.append(
            Reason(
                "brightness",
                f"Left at zero on purpose: your mix is already {abs(presence_gap):.1f} dB "
                f"brighter than the reference through the presence range. Adding more "
                f"would push it further from the sound you picked.",
            )
        )
    else:
        out.reasons.append(
            Reason(
                "brightness",
                "Your top end already tracks the reference within about a decibel, so "
                "the match alone should get you there.",
            )
        )

    # --- warmth ---------------------------------------------------------------
    body_gap = out.bands["body"][2]
    if body_gap > MEANINGFUL_GAP_DB:
        ramp = bell_ramp(DEFAULT_N_FFT, sample_rate, DEFAULT_WARMTH_HZ)
        gain = gain_for(ramp, body_gap * CLOSE_FRACTION, "body", sample_rate, power)
        out.polish.warmth_db = round(float(np.clip(gain, 0.0, MAX_WARMTH_DB)), 1)
        out.reasons.append(
            Reason(
                "warmth",
                f"The reference carries {body_gap:.1f} dB more in the 250-800 Hz range, "
                f"where body and weight live. A bell around 450 Hz fills that in without "
                f"dulling the top or making the bass boomy.",
            )
        )
    elif body_gap < -MEANINGFUL_GAP_DB:
        out.reasons.append(
            Reason(
                "warmth",
                f"Your low mids are {abs(body_gap):.1f} dB fuller than the reference "
                f"already — more would read as boxy rather than warm.",
            )
        )
    else:
        out.reasons.append(Reason("warmth", "Your low mids already match the reference."))

    # --- width ----------------------------------------------------------------
    out.source_width = round(stereo_width(source), 3)
    out.reference_width = round(stereo_width(reference), 3)
    if out.source_width > 1e-6 and out.reference_width > out.source_width * 1.08:
        factor = float(np.clip(out.reference_width / out.source_width, 1.0, MAX_WIDTH))
        # Only close part of the gap: width measured on a whole mix is a blunt number.
        out.polish.width = round(1.0 + (factor - 1.0) * CLOSE_FRACTION, 2)
        out.reasons.append(
            Reason(
                "width",
                f"The reference is wider — {out.reference_width:.2f} against your "
                f"{out.source_width:.2f}. Everything above 250 Hz spreads; the bass stays "
                f"centred so it survives a mono system.",
            )
        )
    elif out.source_width >= out.reference_width:
        out.reasons.append(
            Reason(
                "width",
                f"Left alone: your mix is already as wide as the reference "
                f"({out.source_width:.2f} against {out.reference_width:.2f}). Widening "
                f"past it costs mono compatibility for no gain.",
            )
        )
    else:
        out.reasons.append(Reason("width", "Your stereo image already matches closely."))

    # --- headroom -------------------------------------------------------------
    loudness, _ = integrated_loudness(reference, sample_rate)
    peak = float(np.max(np.abs(reference))) if np.size(reference) else 0.0
    if np.isfinite(loudness) and peak > 0:
        out.reference_crest_db = round(20.0 * np.log10(peak) - float(loudness), 2)

    if 0 < out.reference_crest_db < SQUASHED_CREST_DB:
        out.polish.headroom_db = 1.0
        out.reasons.append(
            Reason(
                "headroom",
                f"Your reference is a heavily limited master — only "
                f"{out.reference_crest_db:.1f} dB between its peaks and its average level. "
                f"Matching it exactly would flatten yours the same way, so this sits 1 dB "
                f"under it and keeps some punch.",
            )
        )
    else:
        out.reasons.append(
            Reason(
                "headroom",
                "Nothing extra needed: the master already stops short of over-driving its "
                "own limiter to reach the reference's loudness. Raise this if you want it "
                "more dynamic than the reference.",
            )
        )

    return out
