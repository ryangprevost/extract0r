"""Suggesting the finishing moves, from the same measurements that justify them.

The tonal match already answers "is this band too loud". These three questions it cannot
ask, because none of them is a level:

  - Is there anything up top to lift at all, or does it have to be made?
  - Is the bass spread across the image instead of sitting in the middle?
  - Is there rumble under the music, eating headroom nobody hears?

All three are measured on the summed mix and the summed reference, so this runs in the
fast half of the comparison - no separation needed - and every suggestion arrives with
the number that produced it.

A fourth once lived here, offering a short room to close the gaps between hits. The
measurement said it was working and the ear said otherwise - a reverb tail on drums is
obvious long before it shows up as reduced crest - so it was removed rather than tuned.
Brightness and presence are what "cohesion" turned out to mean, and an exciter provides
those without putting anything in the gaps.
"""

from __future__ import annotations

import numpy as np

#: Where a mix stops having recorded top end and starts having whatever the codec left.
AIR_BAND = (8000.0, 16000.0)
#: The range the air is judged against. Comparing air to the whole mix would just measure
#: how bright the music is; comparing it to the upper mids measures how much *sheen* sits
#: on top of the same material.
MIDS_BAND = (1500.0, 6000.0)
#: Below this much air relative to the reference's, a shelf has nothing to lift.
AIR_SHORTFALL_DB = 2.5

#: Where bass should be sitting in the middle.
BASS_BAND = (120.0, 250.0)
#: Wider than the reference by this factor and the low end is spread rather than solid.
BASS_SPREAD_RATIO = 1.35

#: What counts as under the music. A bass guitar's lowest string is 41 Hz.
RUMBLE_BAND = (18.0, 38.0)
#: More rumble than the reference by this much is worth removing.
RUMBLE_EXCESS_DB = 1.5

def _band_rms(samples: np.ndarray, sample_rate: int, low: float, high: float) -> float:
    from scipy.signal import butter, sosfiltfilt

    audio = np.asarray(samples, dtype=np.float64)
    high = min(high, sample_rate / 2 * 0.99)
    if low >= high:
        return 0.0
    sos = butter(4, [low, high], btype="band", fs=sample_rate, output="sos")
    return float(np.sqrt(np.mean(sosfiltfilt(sos, audio, axis=0) ** 2)))


def _side_to_mid(samples: np.ndarray, sample_rate: int, low: float, high: float) -> float:
    from scipy.signal import butter, sosfiltfilt

    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1 or audio.shape[1] < 2:
        return 0.0
    high = min(high, sample_rate / 2 * 0.99)
    sos = butter(4, [low, high], btype="band", fs=sample_rate, output="sos")
    band = sosfiltfilt(sos, audio, axis=0)
    mid = (band[:, 0] + band[:, 1]) / 2.0
    side = (band[:, 0] - band[:, 1]) / 2.0
    return float(np.sqrt(np.mean(side**2)) / (np.sqrt(np.mean(mid**2)) + 1e-12))


def _middle(samples: np.ndarray, sample_rate: int, seconds: float = 60.0) -> np.ndarray:
    audio = np.asarray(samples, dtype=np.float64)
    start = len(audio) // 4
    window = audio[start : start + int(sample_rate * seconds)]
    return window if len(window) > sample_rate else audio


def suggest(
    source: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    reference_rate: int | None = None,
) -> list[dict]:
    """Findings for each finishing move, carrying the dial that answers it."""
    reference_rate = reference_rate or sample_rate
    mine = _middle(source, sample_rate)
    theirs = _middle(reference, reference_rate)
    out: list[dict] = []

    # --- is there any top end to lift? ------------------------------------------------
    my_air = _band_rms(mine.mean(axis=1), sample_rate, *AIR_BAND)
    my_mids = _band_rms(mine.mean(axis=1), sample_rate, *MIDS_BAND)
    their_air = _band_rms(theirs.mean(axis=1), reference_rate, *AIR_BAND)
    their_mids = _band_rms(theirs.mean(axis=1), reference_rate, *MIDS_BAND)
    if my_mids > 1e-9 and their_mids > 1e-9:
        my_sheen = 20 * np.log10((my_air + 1e-12) / my_mids)
        their_sheen = 20 * np.log10((their_air + 1e-12) / their_mids)
        shortfall = float(their_sheen - my_sheen)
        if shortfall >= AIR_SHORTFALL_DB:
            wanted = float(np.clip(shortfall * 0.8, 1.5, 6.0))
            out.append(
                {
                    "area": "finish:sparkle",
                    "severity": "notable" if shortfall >= 5.0 else "slight",
                    "delta_db": round(shortfall, 2),
                    "headline": "There is less on top than the reference has to work with",
                    "detail": (
                        f"Against the same amount of upper-mid content, your mix carries "
                        f"{shortfall:.1f} dB less above 8 kHz than the reference does. "
                        f"Brightness is a shelf and can only lift what is already there, "
                        f"which is why it does so little for parts played from a synth "
                        f"patch or taken direct off a DI - there is nothing up there to "
                        f"raise. Sparkle makes the harmonics instead, from the mix's own "
                        f"upper mids, so what arrives follows the playing."
                    ),
                    "action": {
                        "label": f"Add {wanted:.1f} dB of sparkle",
                        "dials": {"sparkle": round(wanted, 1)},
                    },
                    "clause": "a darker top end",
                }
            )

    # --- is the bass spread? ----------------------------------------------------------
    my_bass = _side_to_mid(mine, sample_rate, *BASS_BAND)
    their_bass = _side_to_mid(theirs, reference_rate, *BASS_BAND)
    if their_bass > 1e-6 and my_bass > their_bass * BASS_SPREAD_RATIO:
        ratio = my_bass / their_bass
        out.append(
            {
                "area": "finish:bass-width",
                "severity": "notable" if ratio >= 2.0 else "slight",
                "delta_db": round(float(20 * np.log10(ratio)), 2),
                "headline": "Your bass is spread where the reference keeps it centred",
                "detail": (
                    f"Between {BASS_BAND[0]:.0f} and {BASS_BAND[1]:.0f} Hz your low end "
                    f"measures {my_bass:.2f} of side against mid where the reference "
                    f"measures {their_bass:.2f} - {ratio:.1f} times as wide. That is "
                    f"usually what a muddy, loose bottom end is, and it is also why the "
                    f"bass can seem to disappear: side content cancels the moment "
                    f"anything sums to mono, so it is loud on headphones and half gone "
                    f"on a phone. Centring it applies no EQ - nothing gets louder, more "
                    f"of it simply survives."
                ),
                "action": {
                    "label": "Centre the bass",
                    "dials": {"centreBass": 150},
                },
                "clause": "a spread low end",
            }
        )

    # --- is there rumble under the music? ---------------------------------------------
    my_rumble = _band_rms(mine.mean(axis=1), sample_rate, *RUMBLE_BAND)
    my_level = float(np.sqrt(np.mean(mine**2)))
    their_rumble = _band_rms(theirs.mean(axis=1), reference_rate, *RUMBLE_BAND)
    their_level = float(np.sqrt(np.mean(theirs**2)))
    if my_level > 1e-9 and their_level > 1e-9:
        excess = float(
            20 * np.log10((my_rumble + 1e-12) / my_level)
            - 20 * np.log10((their_rumble + 1e-12) / their_level)
        )
        if excess >= RUMBLE_EXCESS_DB:
            out.append(
                {
                    "area": "finish:subsonic",
                    "severity": "slight",
                    "delta_db": round(excess, 2),
                    "headline": "There is more under the music than the reference carries",
                    "detail": (
                        f"Below {RUMBLE_BAND[1]:.0f} Hz you have {excess:.1f} dB more "
                        f"than the reference, relative to the rest of the mix. Nothing "
                        f"plays down there - a bass guitar's lowest string is 41 Hz - so "
                        f"it is rumble, handling and room. You will not hear it on most "
                        f"systems, but the limiter hears it perfectly well and spends "
                        f"headroom on it that could have gone to the music."
                    ),
                    "action": {"label": "Cut it", "dials": {"subsonic": 30}},
                    "clause": "rumble under the music",
                }
            )

    out.sort(key=lambda f: -abs(f["delta_db"]))
    return out
