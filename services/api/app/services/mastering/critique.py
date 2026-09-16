"""How does this mix compare with that record, in words?

The suggestion engine answers "where should the dials go". This answers the question
underneath it — "what is actually different?" — which is the one worth reading, because it
is about the mix rather than about the tool.

Two rules it holds to.

**Describe the mix as it is, not as matching will leave it.** The gaps here are measured
before the tonal match, because "your low mids are 7 dB lighter than that record" is a fact
about your mix. Where matching is about to close a gap, the finding says so rather than
quietly reporting the residual and making the difference disappear.

**A difference is not a fault.** An unmastered mix having more dynamic range than a
commercial master is normal and expected, not a problem to fix. Findings carry a severity,
and "match" is a legitimate, common result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.domain.notes import StemKind

#: Under this, two numbers are the same number as far as anyone can hear.
SAME_DB = 1.2

#: Over this, a difference is worth leading with.
NOTABLE_DB = 3.0

#: Plain names for the bands, and what a listener notices when one moves.
BAND_WORDS: dict[str, tuple[str, str, str]] = {
    "low": ("low end", "heavier", "lighter"),
    "body": ("low mids", "fuller", "thinner"),
    "mid": ("midrange", "more forward", "more scooped"),
    "presence": ("presence range", "brighter", "duller"),
    "air": ("top octave", "airier", "darker"),
}

#: How each stem is referred to, and whether it takes a plural verb. "Your drums sits
#: higher" and "The the remaining parts sits" were both produced by getting this wrong.
STEM_WORDS: dict[StemKind, tuple[str, bool]] = {
    StemKind.VOCALS: ("vocal", False),
    StemKind.BASS: ("bass", False),
    StemKind.DRUMS: ("drums", True),
    StemKind.GUITAR: ("guitars", True),
    StemKind.PIANO: ("piano", False),
    StemKind.OTHER: ("remaining parts", True),
}


@dataclass(slots=True)
class Finding:
    area: str
    severity: str
    headline: str
    detail: str
    delta_db: float = 0.0
    #: The dial move that addresses this one finding, when there is one. Taken from the
    #: suggestion rather than recomputed, so "fix this" and "apply everything" can never
    #: disagree about what the right number is.
    action: dict | None = None
    #: Set when nothing is offered because the tonal match already covers it. The
    #: midrange is the usual case: it has no dial of its own, and it does not need one.
    handled_by_match: bool = False
    #: A fragment that reads correctly inside a list, for the one-line verdict. Kept apart
    #: from the headline because the two need different grammar: a headline is a sentence
    #: on its own, a clause has to slot into someone else's.
    clause: str = ""


@dataclass(slots=True)
class Critique:
    verdict: str = ""
    findings: list[Finding] = field(default_factory=list)


def severity(delta_db: float) -> str:
    size = abs(delta_db)
    if size < SAME_DB:
        return "match"
    return "notable" if size >= NOTABLE_DB else "slight"


#: Which dial addresses a shortfall in each band, and what to call the offer. Only
#: shortfalls: there is no dial for "you have too much", because cutting to match a
#: reference is what the tonal match already does.
BAND_ACTIONS: dict[str, tuple[str, str]] = {
    "low": ("bass", "Add low end"),
    "body": ("warmth", "Add body"),
    "presence": ("brightness", "Add presence"),
    "air": ("brightness", "Add air"),
}


def _action_for(result, band: str) -> dict | None:
    """The offer attached to a band finding, if the engine recommended anything there.

    Read off the computed suggestion rather than worked out again here. Two places
    deciding the same number independently is two places to disagree, and the user would
    see it as "fix this" and "apply all" doing different things.
    """
    entry = BAND_ACTIONS.get(band)
    if entry is None:
        return None
    control, label = entry
    polish = result.polish

    if control == "bass" and polish.bass_db:
        return {"label": label, "dials": {"bass": polish.bass_db}}
    if control == "warmth" and polish.warmth_db:
        return {"label": label, "dials": {"warmth": polish.warmth_db}}
    if control == "brightness" and polish.air_db:
        # Brightness has one shelf and two bands that could want it; the engine already
        # chose which, so only the band it chose gets the offer.
        wanted_low = band == "presence" and polish.air_hz <= 5000
        wanted_high = band == "air" and polish.air_hz > 5000
        if wanted_low or wanted_high:
            return {
                "label": label,
                "dials": {"brightness": polish.air_db, "brightnessHz": polish.air_hz},
            }
    return None


def _tone(result, out: list[Finding]) -> None:
    """One finding per band, from the pre-match comparison."""
    for name, (_mine, _theirs, gap) in result.raw_bands.items():
        label, more, less = BAND_WORDS[name]
        level = severity(gap)
        if level == "match":
            out.append(
                Finding("tone", "match", f"{label.capitalize()} matches",
                        "Within a decibel of the reference.", round(gap, 2))
            )
            continue

        direction = less if gap > 0 else more
        residual = result.bands[name][2]
        closing = abs(gap) - abs(residual)
        # Only claim matching will help when it measurably will.
        tail = (
            f" The tonal match closes about {closing:.1f} dB of that on its own."
            if closing > 0.5
            else " The tonal match is clamped and will not close much of that by itself."
            if abs(residual) > SAME_DB
            else ""
        )
        out.append(
            Finding(
                "tone",
                level,
                f"{direction.capitalize()} through the {label}",
                f"Your mix is {abs(gap):.1f} dB {direction} than the reference there.{tail}",
                round(gap, 2),
                action=_action_for(result, name) if gap > 0 else None,
                handled_by_match=closing > 0.5,
                clause=f"{direction} through the {label}",
            )
        )


def _headroom_action(result) -> dict | None:
    """The headroom offer, when the engine asked for one.

    Its reason lives in the suggestion rather than in any single finding - it comes from
    the *reference* being heavily limited, not from anything about your mix. Without
    attaching it here the dial moved on "apply all" with nothing in the card accounting
    for it.
    """
    wanted = result.polish.headroom_db
    if not wanted:
        return None
    return {"label": f"Keep {wanted:.1f} dB more headroom", "dials": {"headroom": wanted}}


def _dynamics(result, out: list[Finding]) -> None:
    mine, theirs = result.source_crest_db, result.reference_crest_db
    if not (mine and theirs):
        return
    gap = mine - theirs
    if abs(gap) < SAME_DB:
        out.append(
            Finding("dynamics", "match", "Dynamics are comparable",
                    f"Both sit around {mine:.1f} dB between peaks and average level.",
                    round(gap, 2), action=_headroom_action(result))
        )
    elif gap > 0:
        out.append(
            Finding(
                "dynamics", "match" if gap < NOTABLE_DB else "slight",
                "More dynamic than the reference",
                f"Your mix has {mine:.1f} dB between its peaks and its average level "
                f"against the reference's {theirs:.1f}. That is normal for a mix that has "
                f"not been mastered yet — the limiter will take some of it back, and the "
                f"headroom dial decides how much.",
                round(gap, 2),
                action=_headroom_action(result),
                clause="more dynamic",
            )
        )
    else:
        out.append(
            Finding(
                "dynamics", severity(gap), "Already flatter than the reference",
                f"Your mix has only {mine:.1f} dB between peaks and average against the "
                f"reference's {theirs:.1f}. Something upstream is already compressing "
                f"hard; mastering cannot put that back.",
                round(gap, 2),
                action=_headroom_action(result) or
                {"label": "Keep more headroom", "dials": {"headroom": 1.5}},
                clause="already flatter than the reference",
            )
        )


def _loudness(result, out: list[Finding]) -> None:
    if not (result.source_lufs and result.reference_lufs):
        return
    gap = result.reference_lufs - result.source_lufs
    out.append(
        Finding(
            "loudness",
            "match" if abs(gap) < SAME_DB else "slight",
            "Loudness is handled" if abs(gap) < 12 else "A long way apart in level",
            f"Your mix sits at {result.source_lufs:.1f} LUFS against the reference's "
            f"{result.reference_lufs:.1f}. Level is matched automatically, so this is "
            f"context rather than something to act on.",
            round(gap, 2),
            handled_by_match=True,
        )
    )


def _width(result, out: list[Finding]) -> None:
    mine, theirs = result.source_width, result.reference_width
    if not (mine and theirs):
        return
    ratio = theirs / mine if mine > 1e-6 else 1.0
    if 0.92 <= ratio <= 1.08:
        out.append(
            Finding("width", "match", "Stereo image is comparable",
                    f"Yours measures {mine:.2f} against the reference's {theirs:.2f}.")
        )
    elif ratio > 1:
        out.append(
            Finding("width", "slight", "Narrower than the reference",
                    f"Yours measures {mine:.2f} against the reference's {theirs:.2f}. "
                    f"The width dial spreads everything above 250 Hz and leaves the bass "
                    f"centred.",
                    action={"label": "Widen", "dials": {"width": result.polish.width}}
                    if result.polish.width != 1.0
                    else None,
                    clause="narrower")
        )
    else:
        out.append(
            Finding("width", "slight", "Wider than the reference",
                    f"Yours measures {mine:.2f} against the reference's {theirs:.2f}. "
                    f"Widening further costs mono compatibility for nothing.",
                    clause="wider")
        )


def balance(
    source_stems: dict[StemKind, Path], reference_stems: dict[StemKind, Path]
) -> list[Finding]:
    """How each instrument sits in its own mix, compared with the reference's.

    The most useful part of the whole comparison, and the part band energies cannot give
    you: "your vocal sits 4 dB further back than that record's" is a mix note, not a
    mastering one. It needs both sides separated, so it is only available once the
    reference has been split too.

    Levels are relative to each mix, never absolute — otherwise this would only be
    measuring which file is louder.
    """
    from app.services.mastering.stem_match import ABSENT_BELOW_LU, profile_stems

    mine = profile_stems(source_stems)
    theirs = profile_stems(reference_stems)

    out: list[Finding] = []
    for stem, (word, plural) in STEM_WORDS.items():
        a, b = mine.get(stem), theirs.get(stem)
        if a is None or b is None:
            continue
        if a.relative_lufs < ABSENT_BELOW_LU or b.relative_lufs < ABSENT_BELOW_LU:
            continue  # one of the two does not really contain this instrument

        gap = b.relative_lufs - a.relative_lufs
        sits = "sit" if plural else "sits"
        level = severity(gap)
        if level == "match":
            matches = "do" if plural else "does"
            out.append(
                Finding(
                    "balance", "match",
                    f"Your {word} {sits} where the reference's {matches}",
                    "Within a decibel of the same place in the mix.",
                    round(gap, 2),
                )
            )
            continue

        back = gap > 0
        subject = "They are" if plural else "It is"
        them = "them" if plural else "it"
        out.append(
            Finding(
                "balance",
                level,
                f"Your {word} {sits} {'lower' if back else 'higher'} in the mix",
                f"{subject} {abs(gap):.1f} dB "
                f"{'further back in the mix than' if back else 'further forward than'} "
                f"the reference's, measured against each mix's own level. Per-instrument "
                f"matching moves {them}; the stem fader overrides that.",
                round(gap, 2),
                clause=f"the {word} {abs(gap):.1f} dB "
                       f"{'further back' if back else 'hotter'}",
            )
        )

    # Width and space, for the instruments both sides actually contain.
    for stem, (word, plural) in STEM_WORDS.items():
        a, b = mine.get(stem), theirs.get(stem)
        if a is None or b is None:
            continue
        if a.relative_lufs < ABSENT_BELOW_LU or b.relative_lufs < ABSENT_BELOW_LU:
            continue
        _space(stem, word, plural, a, b, source_stems[stem], reference_stems[stem], out)

    return out


def _space(
    stem: StemKind,
    word: str,
    plural: bool,
    mine,
    theirs,
    source_path: Path,
    reference_path: Path,
    out: list[Finding],
) -> None:
    """Width and decay for one instrument, against the same instrument in the reference.

    Both are comparisons rather than absolutes, and for different reasons. Width is exact
    but only means something next to another mix of the same song's worth of material.
    Decay is an estimate: reverb cannot be measured without the dry signal, so what is
    actually measured is how fast a part stops after each hit, which is the space *and*
    how the part was played. Comparing the same instrument on both sides cancels some of
    that; it does not cancel all of it, and the wording says so.
    """
    from app.services.mastering.space import (
        DECAY_IS_MEANINGFUL,
        SAME_DECAY_RATIO,
        SAME_WIDTH_RATIO,
        decay_slope_db_per_s,
        middle_slice,
        width_ratio,
    )

    verb = "are" if plural else "is"
    sits = "sit" if plural else "sits"

    # --- width ---------------------------------------------------------------
    ratio = width_ratio(mine.width, theirs.width)
    if ratio is not None and abs(ratio - 1.0) > SAME_WIDTH_RATIO:
        wider = ratio > 1.0
        out.append(
            Finding(
                "space",
                "slight" if abs(ratio - 1.0) < 0.4 else "notable",
                f"Your {word} {verb} {'narrower' if wider else 'wider'} than the "
                f"reference's",
                f"Yours measures {mine.width:.2f} across against the reference's "
                f"{theirs.width:.2f}. Per-instrument matching moves this when stereo "
                f"width is ticked; the master width dial moves the whole mix instead.",
                round(20.0 * float(np.log10(max(ratio, 1e-6))), 2),
                clause=f"the {word} {'narrower' if wider else 'wider'}",
            )
        )

    # --- decay ---------------------------------------------------------------
    if stem.value not in DECAY_IS_MEANINGFUL:
        return
    try:
        mine_audio, mine_rate = middle_slice(source_path)
        their_audio, their_rate = middle_slice(reference_path)
    except Exception:  # pragma: no cover - unreadable stem is not worth failing over
        return

    ours = decay_slope_db_per_s(mine_audio, mine_rate)
    hers = decay_slope_db_per_s(their_audio, their_rate)
    if ours is None or hers is None or ours == 0:
        return

    # Steeper is drier. A ratio, because the absolute rates depend on the instrument.
    ratio = hers / ours
    if 1 / SAME_DECAY_RATIO <= ratio <= SAME_DECAY_RATIO:
        out.append(
            Finding(
                "space", "match", f"Your {word} {sits} in a similar amount of space",
                "Both ring on at about the same rate after each hit.",
            )
        )
        return

    reference_drier = abs(hers) > abs(ours)
    out.append(
        Finding(
            "space",
            "slight",
            f"Your {word} {verb} {'wetter' if reference_drier else 'drier'} than the "
            f"reference's",
            f"After each hit yours falls at {ours:.0f} dB per second against the "
            f"reference's {hers:.0f}. "
            + (
                "Longer ringing usually means more room or reverb"
                if reference_drier
                else "Faster decay usually means a drier, closer sound"
            )
            + " — though a part played with more sustain measures the same way, and "
            "Extract0r has no reverb of its own to change it with.",
            0.0,
            clause=f"a {'wetter' if reference_drier else 'drier'} {word}",
        )
    )


def headline(findings: list[Finding]) -> str:
    """Up to three sentences, leading with whatever is furthest off.

    Tone, balance and space each need their own frame. They do not share one, and running
    them together produced "your mix is the bass wider, the vocal wider and thinner
    through the low mids" - which is why clauses are grouped by area rather than sorted
    into one list.
    """
    real = [f for f in findings if f.severity != "match" and f.clause]
    if not real:
        return (
            "Your mix already tracks the reference closely on tone, dynamics, stereo "
            "image and space. There is not much for the finishing dials to do."
        )
    real.sort(key=lambda f: abs(f.delta_db), reverse=True)

    def join(parts: list[str]) -> str:
        if len(parts) == 1:
            return parts[0]
        return f"{', '.join(parts[:-1])} and {parts[-1]}"

    def clauses(area: str | None, limit: int = 3) -> list[str]:
        picked = [
            f.clause for f in real
            if (f.area == area if area else f.area not in ("balance", "space"))
        ]
        # The same instrument can be both wider and wetter; say it once.
        seen, unique = set(), []
        for clause in picked:
            if clause not in seen:
                seen.add(clause)
                unique.append(clause)
        return unique[:limit]

    sentences = []
    character = clauses(None)
    if character:
        sentences.append(f"Next to the reference, your mix is {join(character)}.")

    carried = clauses("balance")
    if carried:
        lead = "It also carries" if sentences else "Next to the reference, your mix carries"
        sentences.append(f"{lead} {join(carried)}.")

    placed = clauses("space", limit=2)
    if placed:
        lead = "It places" if sentences else "Next to the reference, your mix places"
        sentences.append(f"{lead} {join(placed)}.")

    return " ".join(sentences)


def critique(
    result,
    source_stems: dict[StemKind, Path] | None = None,
    reference_stems: dict[StemKind, Path] | None = None,
) -> Critique:
    """Turn a measured comparison into something worth reading."""
    findings: list[Finding] = []
    _tone(result, findings)
    _dynamics(result, findings)
    _width(result, findings)
    _loudness(result, findings)
    if source_stems and reference_stems:
        findings.extend(balance(source_stems, reference_stems))

    # Differences first, largest first; the things that match go at the end where they
    # read as reassurance rather than filler.
    findings.sort(key=lambda f: (f.severity == "match", -abs(f.delta_db)))
    return Critique(verdict=headline(findings), findings=findings)
