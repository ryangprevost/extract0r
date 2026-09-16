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
                clause=f"{direction} through the {label}",
            )
        )


def _dynamics(result, out: list[Finding]) -> None:
    mine, theirs = result.source_crest_db, result.reference_crest_db
    if not (mine and theirs):
        return
    gap = mine - theirs
    if abs(gap) < SAME_DB:
        out.append(
            Finding("dynamics", "match", "Dynamics are comparable",
                    f"Both sit around {mine:.1f} dB between peaks and average level.",
                    round(gap, 2))
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
                    f"centred.", clause="narrower")
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
    return out


def headline(findings: list[Finding]) -> str:
    """One or two sentences, leading with whatever is furthest off.

    Tone and balance need separate sentences. They do not share a grammatical frame, and
    running them together produced "your mix is thinner through the low mids, your drums
    sits higher" before the clauses were split out.
    """
    real = [f for f in findings if f.severity != "match" and f.clause]
    if not real:
        return (
            "Your mix already tracks the reference closely on tone, dynamics and stereo "
            "image. There is not much for the finishing dials to do."
        )
    real.sort(key=lambda f: abs(f.delta_db), reverse=True)

    def join(parts: list[str]) -> str:
        if len(parts) == 1:
            return parts[0]
        return f"{', '.join(parts[:-1])} and {parts[-1]}"

    sentences = []
    character = [f.clause for f in real if f.area != "balance"][:3]
    if character:
        sentences.append(f"Next to the reference, your mix is {join(character)}.")

    carried = [f.clause for f in real if f.area == "balance"][:3]
    if carried:
        lead = "It also carries" if sentences else "Next to the reference, your mix carries"
        sentences.append(f"{lead} {join(carried)}.")

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
