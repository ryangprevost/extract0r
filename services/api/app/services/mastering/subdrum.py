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


# ───────────────────────── how clean a separation actually was ─────────────────────────
#
# X0R-1413. Ryan: *"i heard snares in the reference kick when separated"*. He did, and the
# file is why - `compare_all` pairs kick with kick by name, so nothing in the comparison
# could have crossed them over. DrumSep had put an audible snare in the file it labelled
# kick, and the application had no way to know or say so.
#
# **Energy is the wrong measure for this and that is the whole difficulty.** Measured on
# that reference, 87.7% of the kick stem's energy sits below 120 Hz, which reads as a
# perfectly good kick. A kick's fundamental carries so much energy that the audible snare
# ghost was 0.2% of it. What matters is loudness, not share: filtered to the bands a kick
# does not live in, that stem metered **22.6 dB under itself** - and a snare 22 dB below a
# kick, soloed, is exactly what somebody hears.
#
# The same measurement across both sides of that comparison, which is the useful part:
#
# | drum | the source | the reference |
# |---|---:|---:|
# | kick | -38.2 dB | **-22.6 dB** |
# | snare | -13.3 dB | -20.1 dB |
# | cymbals | -31.8 dB | -25.1 dB |
# | toms | -13.5 dB | -15.8 dB |
#
# So this is not "the model is bad". The source's kick came out 15.6 dB cleaner than the
# reference's on the same run, and nothing told anybody which they had got. Snare and toms
# are poor on both sides, which agrees with X0R-1310's finding that the toms stem is
# largely residue.

#: Louder than this, relative to the stem it is in, and foreign content is audible on a
#: solo. One listener on one track puts the audible case at -22.6 dB and a clean one at
#: -38.2, so this sits between them and nearer the clean end. Two data points, said out
#: loud because that is what it is.
AUDIBLE_BLEED_DB = -30.0

#: And above *this*, the file is barely the drum on its label at all.
#:
#: Measured on the same pair, this is not hypothetical: the **toms stems came back at -1.2
#: and -1.5 dB**, meaning what is not toms is within a decibel and a half of what is. That
#: is a different statement from "some bleed" and deserves different words - it is
#: X0R-1310's finding that the toms stem is largely residue, now with a number on it from
#: real material rather than from the Experiment 2 clip.
MOSTLY_FOREIGN_DB = -10.0


#: Where each drum's own sound lives. **Not the inverse of `BAND_RESIDENTS`**, and the
#: first version of this was exactly that mistake.
#:
#: The two tables answer different questions. `BAND_RESIDENTS` is for *attribution* - given
#: a finding in this band, which drum should I suspect is behind it - and it is right that
#: `low` names only the kick, because a low-band finding on the snare almost always is the
#: kick. This table asks "which bands should this drum have energy in", and inverting the
#: other one gets exactly one drum badly wrong.
#:
#: **Toms.** Ryan, on seeing the toms stems measured as 98% foreign: *"the toms are ok i
#: think they're more of an EQ range than an instrument."* He is right, and the physics
#: says why - a floor tom's fundamental is 55 to 100 Hz, squarely inside `low`, and rack
#: toms sit at 100 to 250 Hz across the `low`/`low_mid` boundary. Deriving from
#: `BAND_RESIDENTS` counted a real tom's own fundamental as content that did not belong in
#: the toms file, which is why they came back at -1.2 dB and looked like pure residue.
#:
#: Cymbal wash reaches down to about 500 Hz, so `high_mid` is home for those too.
HOME_BANDS: dict[str, tuple[str, ...]] = {
    "kick": ("low", "low_mid"),
    "snare": ("low_mid", "high_mid", "presence"),
    "cymbals": ("high_mid", "presence", "air"),
    "toms": ("low", "low_mid", "high_mid"),
}


def foreign_bands(drum: str) -> tuple[str, ...]:
    """The bands this drum's own sound does not reach.

    Listed rather than derived, for the reason on `HOME_BANDS`: the table that looks like
    it should supply this answers a different question, and using it put a floor tom's
    fundamental in the foreign column.
    """
    home = HOME_BANDS.get(drum, ())
    return tuple(band for band, _low, _high in _bands() if band not in home)


def _bands():
    from app.services.mastering.instrument import BANDS

    return BANDS


def bleed_db(samples, sample_rate: int, drum: str) -> float | None:
    """How loud the content that does not belong in this stem is, relative to the stem.

    Negative, and more negative is cleaner. None when the stem is too quiet to say
    anything about, which is the honest answer for a drum the record barely plays.
    """
    import numpy as np
    from scipy import signal as sg

    from app.services.mastering.instrument import BANDS
    from app.services.mastering.loudness_meter import integrated_loudness

    audio = np.asarray(samples, dtype=np.float64)
    if audio.size == 0:
        return None
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio

    def meter(signal) -> float:
        value, _ = integrated_loudness(np.stack([signal, signal], axis=-1), sample_rate)
        return float(value)

    whole = meter(mono)
    if not np.isfinite(whole) or whole < -60.0:
        return None

    edges = {name: (low, high) for name, low, high in BANDS}
    nyquist = sample_rate / 2.0
    kept = np.zeros_like(mono)
    for band in foreign_bands(drum):
        low, high = edges[band]
        high = min(high, nyquist * 0.98)
        if low >= high:
            continue
        sos = sg.butter(4, [low, high], btype="bandpass", fs=sample_rate, output="sos")
        kept += sg.sosfilt(sos, mono)

    foreign = meter(kept)
    if not np.isfinite(foreign):
        return None
    return round(foreign - whole, 1)


def bleed_warning(drum: str, level: float | None) -> str:
    """One sentence about what is in this file besides the drum on its label, or none.

    Distinct from `bleed_note`, which is the caveat attached to a single finding and names
    the neighbour most likely to be behind that band. This one is about the file.

    Said only when it is loud enough to hear, because a line on every row saying
    separation is imperfect is a line nobody reads by the third drum.
    """
    if level is None or level < AUDIBLE_BLEED_DB:
        return ""
    others = sorted({
        name
        for band in foreign_bands(drum)
        for name in BAND_RESIDENTS.get(band, ())
        if name != drum
    })
    neighbours = (
        " and ".join(filter(None, [", ".join(others[:-1]), others[-1]]))
        if others
        else "other drums"
    )
    if level >= MOSTLY_FOREIGN_DB:
        # Not a caveat. At this level the file is not really this drum, and a sentence
        # that merely warned about bleed would be understating it by a wide margin.
        return (
            f"**This file is barely the {drum}.** What is not {drum} in it - "
            f"{neighbours} - sits only {abs(level):.0f} dB below what is, so most of what "
            f"you hear when you solo it is other drums. Read every finding on this row as "
            "a fact about a separation rather than about the record, and prefer your ears "
            "to the numbers here."
        )

    return (
        f"Soloed, this file has {neighbours} audible under its own {drum} - "
        f"{abs(level):.0f} dB below it. That is the separation rather than the record, "
        "and the findings here read the whole file, so one in another drum's register "
        "may be that drum arriving late."
    )
