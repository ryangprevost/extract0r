"""A version's parts set to the reference's balance. Sprint 21 (X0R-1475).

Ryan, on a VaVaVa remix: *"it does NOT sound like the levels of the mstrkrft reference
track."* Measured, it did not: the synths sat 14 dB over the bass where "Bounce" has them
level with it. So each group of parts - drums, bass, synths, vocals - is measured against
its own bass, in the reference's separated stems and in the version's layers, and the
difference is the fader move. The bass is the anchor: every other group moves to sit where
the reference puts it relative to *its* bass.

Integrated loudness (BS.1770), because a fader is a loudness decision; and groups rather than
single stems, because a remix's "synths" are a guitar, a keys and an other part where the
reference's are whatever separation put in "other".
"""

from __future__ import annotations

import numpy as np

#: Version layers, and reference stems, that make each group.
LAYER_GROUPS = {"drums": ("beat", "build", "drums"), "bass": ("bass",),
                "synths": ("guitar", "piano", "other"), "vocals": ("vocals",)}
STEM_GROUPS = {"drums": ("drums",), "bass": ("bass",), "synths": ("other", "guitar", "piano"),
               "vocals": ("vocals",)}
#: Fader moves are held inside this range, in dB - the mixer's own.
MOST_DOWN, MOST_UP = -24.0, 12.0
#: A group this far under its bass, in either mix, is not really there - a near-empty stem
#: of leakage. Matching it would turn noise up (the demo's empty "vocals" was moved +5 dB).
ABSENT_LU = -30.0


def _sum(parts: list[np.ndarray]) -> np.ndarray:
    n = min(len(p) for p in parts)
    return sum(np.asarray(p[:n], dtype=np.float64) for p in parts)


def relative_levels(groups: dict[str, tuple[str, ...]], audio: dict[str, np.ndarray],
                    sample_rate: int) -> dict[str, float]:
    """Each group's integrated loudness relative to the bass's, in LU. Groups that are
    silent or missing are left out."""
    from app.services.mastering.loudness_meter import integrated_loudness

    level = {}
    for group, names in groups.items():
        present = [audio[n] for n in names if n in audio]
        if not present:
            continue
        loud, _ = integrated_loudness(_sum(present), sample_rate)
        if np.isfinite(loud) and loud > -70:
            level[group] = loud
    if "bass" not in level:
        return {}
    return {g: v - level["bass"] for g, v in level.items()}


def match(layers: dict[str, np.ndarray], layer_rate: int, stems: dict[str, np.ndarray],
          stem_rate: int) -> dict:
    """The fader move for every layer that brings its group to the reference's balance."""
    theirs = relative_levels(STEM_GROUPS, stems, stem_rate)
    ours = relative_levels(LAYER_GROUPS, layers, layer_rate)
    if not theirs or not ours:
        return {"channels": {}, "said": ["Both need a bass to measure against - nothing moved."]}
    channels, said = {}, []
    for group in ("drums", "synths", "vocals"):
        if group not in theirs or group not in ours:
            continue
        if theirs[group] < ABSENT_LU or ours[group] < ABSENT_LU:
            said.append(f"{group}: left alone - hardly there in "
                        f"{'the reference' if theirs[group] < ABSENT_LU else 'this version'}")
            continue
        move = float(np.clip(theirs[group] - ours[group], MOST_DOWN, MOST_UP))
        for name in LAYER_GROUPS[group]:
            if name in layers:
                channels[name] = {"gain_db": round(move, 1)}
        said.append(f"{group}: {ours[group]:+.1f} LU against the bass, the reference "
                    f"{theirs[group]:+.1f} - moved {move:+.1f} dB")
    channels.setdefault("bass", {"gain_db": 0.0})
    return {"channels": channels, "said": said, "reference": theirs, "version": ours}
