"""Your kick against their kick.

The drum bus is the one stem in the six where the stem is not an instrument. A kick, a
snare and a cymbal play different things in different registers, and averaging them into
one number produces a sentence that describes none of them: "the reference's drums have
2.1 dB more weight" cannot say whether the kick needs sub or the snare is too thin, which
is the only form in which the advice can be taken.

`drums/separate.py` has returned the four drums as audio since X0R-414 and the only thing
that reads them places samples. This module measures them instead, and compares drum to
drum with the same machinery that compares stem to stem - which is why it is two hundred
lines rather than two thousand. `instrument.profile_all` and `instrument.compare` do all
of the work; everything here is the four decisions that make a sub-drum different from a
stem.

**1. They are not `StemKind` members.** `StemKind` is load-bearing in twenty-one modules:
the separation backends map a model's outputs onto it, the transcription backends are
chosen by it, every tab export writes it, and `StemSetting` is keyed by it. One
consequence settles it on its own - `pipeline.run` sums *every* separated stem into an
`untouched` buffer and subtracts it from the original, so sub-drums as members would put
the drums into that sum twice, once as `drums` and once as its four parts. That is not a
migration, it is a different mixdown. So: a nested level, confined to this module, one
route and one card.

**2. Level is measured against the drums, not the mix.** A kick 8 LU under the drum bus is
a statement about the kit's internal balance, which is the thing a user can act on and the
thing that is portable between two records. Against the whole mix it would mostly measure
how loud the drums are, which the drums row already says.

**3. Four dimensions on a kick, six on a cymbal.** See `instrument.NEVER_MOVE_SIDEWAYS`,
which kick and snare now join: a separated kick is the most mono signal this application
handles, and `MIN_MEANINGFUL_WIDTH` exists because a ratio between two near-mono stems is
noise. Overheads genuinely spread, so cymbals and toms keep pan and width.

**4. Every finding carries the bleed caveat.** The stems are not surgically clean - a loud
kick leaves a trace in the snare file, which is what `separate.QUIET_STROKE_DB` exists to
survive. So a low-band finding on the snare may be the kick arriving late, and that belongs
on the finding rather than in a help panel. The size of that bleed is not a measured
number anywhere yet; X0R-306 is what turns it into one, and until then the product says so
instead of implying clean stems.

**What presence means here.** A record with no toms still yields a toms stem: twenty-four
tom strokes in twenty-eight seconds were measured on a programmed electro-house record,
which is residue. A sub-drum is present on its *energy* relative to the drums stem, the
same rule and the same threshold `presence.ABSENT_BELOW_LU` already applies against the
mix - and never on a stroke count, because `separate.QUIET_STROKE_DB` has no knee on the
snare: it slopes smoothly from backbeat into bleed, and snare counts run 4 to 45 across the
gate's range. A count would make a presence verdict a function of where the gate was put.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.mastering import instrument, presence

log = logging.getLogger(__name__)

#: The four drums DrumSep returns, in the order a kit is read in rather than the order the
#: model lists them. Kick and snare first because they are the two a user came to compare.
DRUMS: tuple[str, ...] = ("kick", "snare", "cymbals", "toms")

#: What to call each one, and whether it takes a plural verb. "cymbals ring", "the kick
#: sits". The same shape as `critique.STEM_WORDS`, for the same reason: the comparison
#: writes English sentences and a verb that does not agree reads as a machine wrote it.
DRUM_WORDS: dict[str, tuple[str, bool]] = {
    "kick": ("kick", False),
    "snare": ("snare", False),
    "cymbals": ("cymbals", True),
    "toms": ("toms", True),
}

#: The caveat for the panel as a whole: said once, at the top, as context.
BLEED_CAVEAT = (
    "These four come out of a second separation pass and are not surgically clean - a "
    "loud kick leaves a trace in the other files - so read a finding in another drum's "
    "register as possibly that drum arriving late."
)

#: Which drums actually live in each of the five bands the comparison speaks in.
#:
#: This is what makes the per-finding caveat worth reading rather than boilerplate. A
#: finding about the snare's 20-120 Hz is the one most likely to be the kick, because the
#: kick is what is down there; a finding about the snare's 3-8 kHz is far less likely to
#: be anything but the snare. Naming the specific neighbour turns a disclaimer into a
#: thing to go and listen for.
#:
#: Judgements, and they have to be: the actual bleed between DrumSep's outputs has never
#: been measured. X0R-306 is what turns these into numbers. Until then the product says
#: which drum to suspect rather than implying the stems are clean.
BAND_RESIDENTS: dict[str, tuple[str, ...]] = {
    "low": ("kick",),
    "low_mid": ("kick", "snare", "toms"),
    "high_mid": ("snare", "toms"),
    "presence": ("snare", "cymbals"),
    "air": ("cymbals",),
}

#: For a finding that is not about a band, where there is no neighbour to name.
GENERAL_BLEED_NOTE = (
    "Bleed check: these four come out of a second separation pass and are not surgically "
    "clean, so a little of the other drums is in this file."
)

#: Roughly how long a per-drum pass takes, as a multiple of the audio's own length, on
#: CPU. Measured at 16 s on a 30 s clip, which is where 0.55 comes from. Used only to tell
#: a user what they are about to wait for, so it rounds generously rather than precisely.
PASS_COST_RATIO = 0.55


def words(drum: str) -> tuple[str, bool]:
    return DRUM_WORDS.get(drum, (drum, False))


def estimate_seconds(audio_seconds: float, sides: int = 2) -> float:
    """What a per-drum comparison is about to cost, for saying so before it starts.

    `sides` is 1 when the reference half is already known - from a profile, or from a pass
    that has already run and been cached.
    """
    return round(max(float(audio_seconds), 0.0) * PASS_COST_RATIO * max(sides, 0), 1)


def profile_all(stems: dict[str, Path]) -> dict[str, instrument.InstrumentProfile]:
    """Measure each separated drum, and each one's level against the kit they sum to.

    `instrument.profile_all` does this already and does it correctly: it mixes everything
    it was handed and expresses each part against that sum. Handed four sub-drums it
    expresses each against the drums, which is decision 2 above, and it sets `present`
    with the same threshold used everywhere else. Reusing it is the point - a second
    implementation of "how far under its own mix does this sit" is how two parts of an
    application come to disagree about whether an instrument exists.
    """
    ordered = {name: stems[name] for name in DRUMS if name in stems}
    extra = sorted(set(stems) - set(DRUMS))
    if extra:
        # A model that grew a fifth output should not silently lose it, and should not
        # silently gain a row on a screen built for four either.
        log.info("ignoring unknown separated drums: %s", ", ".join(extra))
    return instrument.profile_all(ordered)


def compare_all(
    mine: dict[str, instrument.InstrumentProfile],
    theirs: dict[str, instrument.InstrumentProfile],
    limits=None,
) -> dict[str, list[instrument.InstrumentMove]]:
    """Every difference between your four drums and theirs.

    Only the drums present on your side get a key at all: a sub-stem that was never
    written is not a drum the user has an opinion about. A drum that is on your side and
    absent on theirs gets an empty list, and `why_absent` is the sentence that goes with
    it.
    """
    out: dict[str, list[instrument.InstrumentMove]] = {}
    for drum in DRUMS:
        a, b = mine.get(drum), theirs.get(drum)
        if a is None:
            continue
        if b is None or not presence.comparable(a.relative_lufs, b.relative_lufs):
            out[drum] = []
            continue
        found = instrument.compare(drum, a, b, words(drum), limits=limits)
        for move in found:
            move.detail = f"{move.detail} {bleed_note(drum, move)}"
        out[drum] = found
    return out


def bleed_note(drum: str, move) -> str:
    """The bleed caveat for one finding, naming the drum most likely to be behind it.

    One sentence per finding rather than the same paragraph eight times. A user reading
    "the reference's snare has more weight" needs to know that 20-120 Hz is where the
    kick lives and that some of what was measured may be the kick in the snare's file -
    which is a thing they can go and listen for. The generic version is not; repeated
    under every row it is wallpaper, and wallpaper is not a caveat.
    """
    neighbours = [
        name
        for name in BAND_RESIDENTS.get(getattr(move, "band", ""), ())
        if name != drum
    ]
    if not neighbours:
        return GENERAL_BLEED_NOTE
    listed = (
        neighbours[0]
        if len(neighbours) == 1
        else " and ".join([", ".join(neighbours[:-1]), neighbours[-1]])
    )
    return (
        f"Bleed check: the {listed} also {'live' if len(neighbours) > 1 else 'lives'} in "
        f"this band, and separation is not surgical - some of what is measured here may "
        f"be the {listed} in the {drum} file."
    )


def why_absent(
    mine: instrument.InstrumentProfile | None,
    theirs: instrument.InstrumentProfile | None,
) -> str:
    """Which side has no such drum, and the figure behind it. Empty when both do.

    Delegates the rule to `presence` and adds only the numbers, because the rule living in
    one place is what X0R-1127 was about and this is its fourth and fifth caller.
    """
    if mine is None:
        return "this drum was not separated out of your drums stem"
    if theirs is None:
        return (
            "the reference's drums were not separated into this one, so there is nothing "
            "to compare it with"
        )
    reason = presence.why_not(mine.relative_lufs, theirs.relative_lufs, _label(mine))
    if not reason:
        return ""
    return (
        f"{reason} - yours measures {mine.relative_lufs:.1f} LU under the drums against "
        f"the reference's {theirs.relative_lufs:.1f}"
    )


def _label(one: instrument.InstrumentProfile) -> str:
    return words(str(one.stem))[0]


# --- kept in a profile, so the reference side is paid for once --------------------------
#
# The same argument as `instrument.snapshot`, one level further in, and it is stronger
# here: the reference's per-drum pass costs about half its length again on CPU, and
# nothing downstream of the comparison reads that audio. Seven numbers per drum is the
# whole of it. See X0R-1317 for the flow that spends them.


def snapshot_all(profiles: dict[str, instrument.InstrumentProfile]) -> dict[str, dict]:
    return instrument.snapshot_all(profiles)


def from_snapshot_all(data: dict[str, dict]) -> dict[str, instrument.InstrumentProfile]:
    """The other direction. Keyed by a plain name, so unlike the stem version there is no
    enum to fail on - an unknown drum is dropped against `DRUMS` instead."""
    out: dict[str, instrument.InstrumentProfile] = {}
    for name, one in (data or {}).items():
        if name not in DRUMS:
            log.info("skipping unknown drum %r in a saved profile", name)
            continue
        out[name] = instrument.from_snapshot(name, one)
    return out
