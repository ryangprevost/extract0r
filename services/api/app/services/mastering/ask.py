"""Say what you want in your own words, and have it move a real control.

Ryan asked for this: *"it'd be awesome if there was the ability to have a chat prompt and
say things like 'I want this song a little bassier' or 'i want the guitars to pop a little
more'"*. This is that, built the only way this application is allowed to build it.

### What it is not

It is not a model, and it invents no processing. Everything it can do, a user can already
do by dragging something - that is the design rather than a limitation to be fixed later.
A chat box that quietly applied moves with nothing behind them would be the exact thing
this project refuses to be: `extract0r` suggests fractions of *measured* gaps and explains
every one, and a phrase typed into a box is not a measurement.

So the rule is: **the words choose the control, and the comparison still gets the last
word on whether it was a good idea.** "A little bassier" moves the bass fader. If the
comparison has been run and puts your bass 1.8 dB above the reference's, the reply says so
in the same breath as doing what was asked. The user gets what they asked for *and* the
measurement they did not ask for.

### Why a vocabulary and not a language model

No model runs on this machine, there is no key in this repository, and a feature whose
behaviour depended on a network call would make the one deterministic thing about this
application - same input, same output, and a test that holds it there - untrue.

The cost is that it understands a vocabulary rather than English. The honest response to
that cost is to **say so when it fails** and list what it does know, which is what the
`suggestions` on a failed `Answer` are for. A parser that silently did nothing would be
worse than one that cannot parse, because the user could not tell which had happened.

### Where the values land

Straight onto the per-stem controls the comparison screen already drives through
`writeControl` - six stems times nine controls, all of them visible, all of them already
audible through the monitor. Nothing new is invented to receive these moves, which is why
a sentence here and a dragged slider end up in exactly the same place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.notes import StemKind

# --- the controls, as the page defines them ------------------------------------------------

#: Mirrors `MOVE_CONTROLS` in `apps/studio/wwwroot/instruments.js`. A test reads that file
#: and asserts the two agree: a range that exists in two languages drifts, and the half
#: that drifts is always the one without a test runner.
LIMITS: dict[str, tuple[float, float, float]] = {
    # control: (min, max, resting value)
    "gain_db": (-6.0, 6.0, 0.0),
    "compress_db": (0.0, 8.0, 0.0),
    "pan": (-1.0, 1.0, 0.0),
    "width": (0.6, 1.6, 1.0),
    "tone_low_db": (-6.0, 6.0, 0.0),
    "tone_low_mid_db": (-6.0, 6.0, 0.0),
    "tone_high_mid_db": (-6.0, 6.0, 0.0),
    "tone_presence_db": (-6.0, 6.0, 0.0),
    "tone_air_db": (-6.0, 6.0, 0.0),
}

#: One step at the plain amount. A dB is the sort of move this application already deals
#: in - `budget.Limits.max_level_db` is 3.0 - so a plain ask is a third of what the
#: reference match is allowed, and "a lot" is two thirds.
STEP: dict[str, float] = {
    "gain_db": 1.0,
    "width": 0.12,
    "pan": 0.12,
    "compress_db": 1.0,
}
TONE_STEP = 1.0

#: How far this box may take one control from where the conversation found it. A chat box
#: can be asked the same thing nine times, and "bassier" nine times is a thing a person
#: will absolutely do. The faders themselves keep their full range; this is a limit on
#: what *typing* can do without the user ever seeing a number.
CEILING: dict[str, float] = {
    "gain_db": 4.0,
    "width": 0.35,
    "pan": 0.5,
    "compress_db": 4.0,
}
TONE_CEILING = 4.0


def limit_of(control: str) -> tuple[float, float, float]:
    return LIMITS[control]


def step_of(control: str) -> float:
    return TONE_STEP if control.startswith("tone_") else STEP[control]


def ceiling_of(control: str) -> float:
    return TONE_CEILING if control.startswith("tone_") else CEILING[control]


# --- reading the sentence --------------------------------------------------------------

#: Multipliers on a step. "A little" is half rather than a tenth on purpose: a move
#: nobody can hear is not politeness, it is a control that appears broken.
AMOUNTS: tuple[tuple[tuple[str, ...], float, str], ...] = (
    (
        ("a touch", "a hair", "a tad", "slightly", "a little", "a bit", "little", "bit"),
        0.5,
        "a touch",
    ),
    (
        ("a lot", "much", "way", "a ton", "loads", "really", "lots", "significantly",
         "heaps", "far", "massively"),
        2.0,
        "a lot",
    ),
)
PLAIN_AMOUNT = (1.0, "")

UP = (
    "more", "up", "louder", "boost", "raise", "increase", "bring up", "turn up",
    "lift", "push", "add",
)
DOWN = (
    "less", "down", "quieter", "quiet", "cut", "reduce", "lower", "decrease",
    "bring down", "turn down", "tame", "pull back", "back off", "duck", "drop",
    "too much", "soften", "take out", "take off",
)

EXAMPLES: tuple[str, ...] = (
    "a little bassier",
    "make the guitars pop",
    "vocal up a bit",
    "less mud",
    "wider",
    "drums back off a lot",
)


@dataclass(frozen=True, slots=True)
class Target:
    """Something a person can name, and the control it moves.

    `sign` is which way "more of this" goes, which is not always up: "mud" and "harshness"
    name a band by what is wrong with it, so more of what was asked is less of the band.

    `stem` empty means the whole mix, which here is literally every stem - the same band
    moved by the same amount on all six is what a master EQ is, and doing it this way
    means one sentence and one dragged slider land in the same place.
    """

    label: str
    control: str
    stem: str
    sign: float
    words: tuple[str, ...]
    #: Set when the words carry their own direction. Somebody who types "muddy" with no
    #: verb has stated a direction without using a direction word.
    implied: float = 0.0
    #: Said after the move, when there is something true worth adding about the control.
    caveat: str = ""


def _part(stem: StemKind, label: str, *words: str) -> Target:
    return Target(label, "gain_db", stem.value, +1.0, words)


TARGETS: tuple[Target, ...] = (
    # --- the parts -----------------------------------------------------------------------
    _part(StemKind.BASS, "bass", "bass", "bassline", "bass line", "low end", "bottom end",
          "bassier", "bassy"),
    _part(StemKind.VOCALS, "vocal", "vocal", "vocals", "vox", "voice", "singer", "singing",
          "lead vocal"),
    _part(StemKind.DRUMS, "drums", "drums", "drum", "beat", "kit", "percussion"),
    _part(StemKind.GUITAR, "guitars", "guitar", "guitars", "gtr", "gtrs", "riff"),
    _part(StemKind.PIANO, "piano", "piano", "keys", "keyboard", "synth", "pads"),
    _part(StemKind.OTHER, "remaining parts", "everything else", "the rest"),
    # --- the bands, named the way the comparison names them ------------------------------
    Target("weight", "tone_low_db", "", +1.0,
           ("weight", "sub", "subs", "low frequencies", "the lows")),
    Target("body", "tone_low_mid_db", "", +1.0,
           ("body", "warmth", "warmer", "warm", "fuller", "fullness", "thicker",
            "thickness", "beefier"),
           implied=+1.0),
    # `sign` is which way the control goes for MORE of the named thing, and `implied`
    # is what naming it with no verb means. For a complaint word those pull apart: more
    # mud is more low-mid, and somebody typing "muddy" wants less of it. Getting this
    # backwards made "less mud" add low-mid, which a test caught and an ear would have.
    Target("mud", "tone_low_mid_db", "", +1.0,
           ("mud", "muddy", "muddiness", "boxy", "boomy", "boom", "woolly", "cloudy",
            "congested"),
           implied=-1.0,
           caveat="Mud and body are the same band pulled opposite ways, so asking for "
           "both in turn cancels out."),
    Target("midrange", "tone_high_mid_db", "", +1.0,
           ("midrange", "mids", "the middle", "honk")),
    Target("presence", "tone_presence_db", "", +1.0,
           ("presence", "clarity", "definition", "detail", "intelligibility",
            "articulation", "clearer")),
    Target("harshness", "tone_presence_db", "", +1.0,
           ("harsh", "harshness", "piercing", "shrill", "brittle", "fatiguing", "sibilant"),
           implied=-1.0),
    Target("air", "tone_air_db", "", +1.0,
           ("air", "sparkle", "shimmer", "top end", "treble", "brighter", "bright",
            "brightness", "crisper", "crisp", "sheen", "zing")),
    Target("darkness", "tone_air_db", "", -1.0,
           ("darker", "dark", "duller", "dull", "less top", "less treble"),
           implied=+1.0),
    # --- the stereo field ------------------------------------------------------------------
    Target("width", "width", "", +1.0,
           ("wider", "width", "wide", "bigger stereo", "more stereo", "spacious",
            "open it up", "stereo"),
           caveat="The bass is left where it is - spread low end is what makes a mix that "
           "sounds big on headphones and thin on a phone."),
    Target("focus", "width", "", -1.0,
           ("narrower", "narrow", "tighter", "focused", "focus", "more mono", "mono"),
           implied=+1.0),
    Target("steadiness", "compress_db", "", +1.0,
           ("steadier", "steady", "even it out", "more even", "consistent", "level it",
            "squash", "compress", "tighter dynamics"),
           implied=+1.0,
           caveat="This is the Dynamics control, which pulls the loud moments down "
           "rather than lifting the quiet ones."),
)

#: Width is a stereo control, and two of the six stems have no business being widened.
#: The reference match holds both centred for the same reason, so a sentence that widens
#: everything would quietly undo a decision the rest of the application makes on purpose.
NEVER_WIDEN = (StemKind.BASS.value,)

#: Phrases naming a quality *of a part*. "Pop" alone is not a request; "the guitars pop"
#: is - so these refuse without a part to attach to.
#:
#: Each is two moves, because level alone is what somebody does when they have one fader,
#: and it is why mixes end up loud instead of legible.
QUALITIES: dict[str, tuple[str, tuple[tuple[str, float], ...], str]] = {
    "pop": (
        "pop",
        (("gain_db", 1.0), ("tone_presence_db", 0.7)),
        "A part pops by getting clearer as well as louder, so this does both - most of it "
        "on the level, a little on that part's own presence band.",
    ),
    "cut through": ("cut through", (("gain_db", 1.0), ("tone_presence_db", 0.7)), ""),
    "stand out": ("stand out", (("gain_db", 1.0), ("tone_presence_db", 0.7)), ""),
    "buried": ("come forward", (("gain_db", 1.0), ("tone_presence_db", 0.7)), ""),
    "punch": (
        "punch",
        (("gain_db", 0.8), ("tone_low_mid_db", 0.6)),
        "Punch here is level and body. The transient part of punch is the Dynamics "
        "control, and this does not touch it.",
    ),
    "punchier": ("punch", (("gain_db", 0.8), ("tone_low_mid_db", 0.6)), ""),
    "sit back": ("sit back", (("gain_db", -1.0), ("tone_presence_db", -0.7)), ""),
    "sit further back": (
        "sit back", (("gain_db", -1.0), ("tone_presence_db", -0.7)), "",
    ),
}

#: Asked often, honestly out of reach, and worth a straight answer rather than a shrug.
#: Each names the nearest thing this application can actually do, because a bare "no" from
#: a box that invites you to type is a dead end.
OUT_OF_REACH: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("professional", "radio ready", "radio-ready", "like a record", "polished",
         "commercial", "expensive", "studio quality", "mastered properly",
         "make it good", "make it better", "fix it"),
        "There is no dial for that, and anything claiming to be one is guessing. What "
        "this has instead is the reference: load a song that already sounds the way you "
        "mean, and every suggestion becomes the measured difference between it and yours.",
    ),
    (
        ("remove the vocal", "remove vocals", "acapella", "a cappella", "instrumental",
         "karaoke"),
        "That one is the mixer rather than a sentence: mute the vocal lane for an "
        "instrumental, or solo it for the other thing.",
    ),
    (
        ("faster", "slower", "tempo", "key change", "transpose", "pitch it",
         "different key", "retune", "autotune", "auto-tune", "in tune"),
        "Nothing here changes time or pitch. The comparison will *tell* you how far the "
        "vocal sits from a tempered grid and how your tempo compares - it only measures "
        "those, it never rewrites them.",
    ),
    (
        ("add reverb", "more reverb", "bigger room", "add delay", "add echo",
         "double the vocal", "add a harmony", "add harmonies", "add some space"),
        "This adds nothing that was not recorded. Everything it does is a change to what "
        "is already in your file, which is why there is no reverb here to turn up.",
    ),
)


# --- what comes back -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Change:
    """One control on one stem, and where it should end up.

    `to` rather than a delta, so a clamp here cannot disagree with the fader on screen -
    the page sets the value it is given and does no arithmetic of its own.
    """

    control: str
    stem: str
    delta: float
    to: float
    clamped: bool = False


@dataclass(frozen=True, slots=True)
class Answer:
    understood: bool
    reply: str
    changes: tuple[Change, ...] = ()
    #: What it believes it was asked, in its own words, so a wrong reading is visible
    #: rather than mysterious.
    heard: str = ""
    suggestions: tuple[str, ...] = ()


# --- parsing --------------------------------------------------------------------------------

_SPACE = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _SPACE.sub(" ", text.lower().strip().replace("’", "'"))


def _find(text: str, phrases) -> str:
    """The longest phrase from `phrases` present in `text`, as whole words.

    Longest-first keeps "low end" from being read as "low". Whole-word matching keeps
    "air" out of "chair" and "bass" out of "bassoon" - the sort of thing that only turns
    up once somebody types a real sentence.
    """
    for phrase in sorted(phrases, key=len, reverse=True):
        if re.search(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", text):
            return phrase
    return ""


def _direction(text: str) -> tuple[float, str]:
    up, down = _find(text, UP), _find(text, DOWN)
    # Both can appear: "less bass, turn up the drums" is one sentence with two verbs, and
    # this parser is honest that it reads one request at a time. The longer phrase wins,
    # being the more specific claim.
    if up and down:
        return (+1.0, up) if len(up) > len(down) else (-1.0, down)
    if up:
        return +1.0, up
    if down:
        return -1.0, down
    return 0.0, ""


def _amount(text: str) -> tuple[float, str]:
    for words, scale, label in AMOUNTS:
        if _find(text, words):
            return scale, label
    return PLAIN_AMOUNT


def _target(text: str) -> Target | None:
    """The target with the longest matching phrase, chosen across all of them.

    Across all rather than first-match, so "low end" beats "end" and a named part beats a
    band when one sentence contains both.
    """
    best: tuple[int, Target | None] = (0, None)
    for target in TARGETS:
        found = _find(text, target.words)
        if found and len(found) > best[0]:
            best = (len(found), target)
    return best[1]


# --- applying ---------------------------------------------------------------------------------


def _stems_for(control: str, stem: str, lanes: dict) -> tuple[str, ...]:
    if stem:
        return (stem,) if stem in lanes else ()
    if control == "width":
        return tuple(s for s in lanes if s not in NEVER_WIDEN)
    return tuple(lanes)


def _move(
    control: str, stem: str, delta: float, lanes: dict, baseline: dict
) -> Change:
    low, high, rest = limit_of(control)
    now = float(lanes.get(stem, {}).get(control, rest))
    start = float(baseline.get(stem, {}).get(control, rest))
    ceiling = ceiling_of(control)
    wanted = now + delta
    landed = max(low, start - ceiling, min(high, start + ceiling, wanted))
    return Change(
        control=control,
        stem=stem,
        delta=round(landed - now, 3),
        to=round(landed, 3),
        clamped=abs(landed - wanted) > 1e-6,
    )


BAND_LABEL = {
    "tone_low_db": "weight",
    "tone_low_mid_db": "body",
    "tone_high_mid_db": "midrange",
    "tone_presence_db": "presence",
    "tone_air_db": "air",
}

STEM_LABEL = {
    StemKind.VOCALS.value: "vocal",
    StemKind.BASS.value: "bass",
    StemKind.DRUMS.value: "drums",
    StemKind.GUITAR.value: "guitars",
    StemKind.PIANO.value: "piano",
    StemKind.OTHER.value: "the remaining parts",
}


def _units(control: str, value: float) -> str:
    if control == "width":
        return f"{value * 100:+.0f}%"
    return f"{value:+.1f} dB"


def _said(changes: tuple[Change, ...], whole_mix: bool) -> str:
    """The moves, grouped by control, because six identical ones are one decision."""
    by_control: dict[str, list[Change]] = {}
    for change in changes:
        by_control.setdefault(change.control, []).append(change)

    parts = []
    for control, group in by_control.items():
        delta = group[0].delta
        if control in BAND_LABEL:
            what = f"{BAND_LABEL[control]} band"
        elif control == "gain_db":
            what = "level"
        elif control == "width":
            what = "stereo width"
        elif control == "compress_db":
            what = "dynamics"
        else:
            what = control
        where = (
            "on every part"
            if whole_mix and len(group) > 1
            else f"on the {STEM_LABEL.get(group[0].stem, group[0].stem)}"
        )
        line = f"{what} {_units(control, delta)} {where}"
        if any(c.clamped for c in group):
            line += " (as far as typing will take it)"
        parts.append(line)
    return "; ".join(parts)


def _measured_note(changes: tuple[Change, ...], comparison: dict | None) -> str:
    """What the comparison says about what was just done, if it has anything to say.

    This is the sentence the feature exists for. Doing as asked is the easy half; the half
    worth building is telling somebody that what they asked for takes them *away* from the
    record they said they wanted to sound like.
    """
    if not comparison:
        return ""
    name = comparison.get("reference_name") or "the reference"
    wanted = {(c.stem, c.control): c for c in changes}

    for instrument in comparison.get("instruments", ()):
        stem = instrument.get("stem", "")
        for move in instrument.get("moves", ()):
            change = wanted.get((stem, move.get("control") or ""))
            if change is None:
                continue
            gap = float(move.get("measured", 0.0))
            if abs(gap) < 0.1:
                continue
            label = instrument.get("label", stem)
            # `measured` is how far the control must move *toward* the reference, so its
            # sign is the opposite of where yours sits relative to theirs.
            side = "under" if gap > 0 else "over"
            with_it = (gap > 0) == (change.delta > 0)
            verdict = (
                "so this goes the way the comparison was already pointing"
                if with_it
                else "so this moves away from it, which may be exactly what you want"
            )
            return f"The comparison put your {label} {abs(gap):.1f} dB {side} {name}'s, {verdict}."
    return ""


def _answer(
    heard: str,
    changes: tuple[Change, ...],
    caveat: str,
    comparison: dict | None,
    whole_mix: bool,
) -> Answer:
    sentences = [f"{heard[:1].upper()}{heard[1:]}: {_said(changes, whole_mix)}."]
    note = _measured_note(changes, comparison)
    if note:
        sentences.append(note)
    if caveat:
        sentences.append(caveat)
    return Answer(True, " ".join(sentences), changes, heard=heard)


#: Where one request may end and another begin. Splitting is attempted only when both
#: halves stand up on their own - see `interpret`.
JOINERS = (" and then ", " then ", " and ", ", ", "; ", " but ", " & ")


def interpret(
    text: str,
    *,
    lanes: dict | None = None,
    comparison: dict | None = None,
    baseline: dict | None = None,
) -> Answer:
    """Read what was typed and return the control moves it asks for.

    Handles two requests in one sentence - "less bass and more drums" - by splitting on a
    conjunction and applying each in turn, the second against the lanes the first left
    behind. **The split is only kept when both halves parse on their own**, which is what
    stops "a little more bass and warmth" turning into a request for bass and a separate
    confused request for nothing: if either half fails, the whole thing is read as one
    sentence, exactly as before.

    Before this, a sentence with two verbs was resolved by `_direction` picking the longer
    phrase and the rest being silently dropped. Doing half of what was asked without
    saying so is the one behaviour this box is least allowed to have.
    """
    lanes = lanes or {}
    baseline = baseline if baseline is not None else {k: dict(v) for k, v in lanes.items()}

    for joiner in JOINERS:
        if joiner not in _clean(text):
            continue
        whole = _clean(text)
        head, _, tail = whole.partition(joiner)
        # A modifier stated once governs both halves. "bass and drums up a lot" puts the
        # amount at the end and means it about both; without this the first half got a
        # plain step and the second got double, which is the sort of inconsistency a user
        # notices immediately and cannot explain.
        amount = _amount(whole)
        sign, _ = _direction(whole)
        first = _one(head, lanes, baseline, comparison, amount, sign)
        if not first.understood:
            continue
        # The second half sees the faders where the first half left them, so two asks for
        # the same control add up instead of the second overwriting the first.
        moved = {stem: dict(values) for stem, values in lanes.items()}
        for change in first.changes:
            moved.setdefault(change.stem, {})[change.control] = change.to
        second = _one(tail, moved, baseline, comparison, amount, sign)
        if not second.understood:
            continue
        return Answer(
            True,
            first.reply + " " + second.reply,
            first.changes + second.changes,
            heard=f"{first.heard}, then {second.heard}",
        )

    return _one(text, lanes, baseline, comparison)


def _one(
    text: str,
    lanes: dict,
    baseline: dict,
    comparison: dict | None,
    fallback_amount: tuple[float, str] | None = None,
    fallback_sign: float = 0.0,
) -> Answer:
    """One request. `interpret` is what splits a sentence into these.

    The two fallbacks carry a modifier stated once across both halves of a split sentence,
    and are only consulted when this half states none of its own.
    """
    cleaned = _clean(text)

    if not cleaned:
        return Answer(False, "Tell me what you want more or less of.", suggestions=EXAMPLES)

    for phrases, answer in OUT_OF_REACH:
        found = _find(cleaned, phrases)
        if found:
            return Answer(False, answer, heard=found)

    sign, _word = _direction(cleaned)
    if sign == 0.0:
        sign = fallback_sign
    scale, amount_word = _amount(cleaned)
    if (scale, amount_word) == PLAIN_AMOUNT and fallback_amount is not None:
        scale, amount_word = fallback_amount
    quality = _find(cleaned, tuple(QUALITIES))
    target = _target(cleaned)

    if quality:
        return _quality(quality, target, sign, scale, amount_word, lanes, baseline,
                        comparison)

    if target is None:
        return Answer(
            False,
            "I did not find anything in that I know how to move. I understand the parts "
            "by name - bass, vocal, drums, guitars, piano - and the tonal words the "
            "comparison uses: weight, body, midrange, presence, air, mud, harshness, "
            "width.",
            suggestions=EXAMPLES,
        )

    if sign == 0.0:
        # No direction word, so either the target carries one ("muddy") or the plain
        # reading of naming a thing is that you want more of it.
        sign = target.implied or +1.0

    delta = step_of(target.control) * scale * sign * target.sign
    stems = _stems_for(target.control, target.stem, lanes)

    if not stems:
        return Answer(
            False,
            f"There is no {target.label} to move here - separate a track first, and every "
            "part gets its own set of controls.",
            heard=target.label,
        )

    changes = tuple(
        c for c in (_move(target.control, s, delta, lanes, baseline) for s in stems)
        if abs(c.delta) > 1e-6
    )
    if not changes:
        return Answer(
            False,
            f"The {target.label} is already as far as typing will take it. The faders "
            "have more range, and the comparison will put a measurement behind a number "
            "rather than a word.",
            heard=target.label,
        )

    heard = " ".join(w for w in (amount_word, "more" if sign > 0 else "less",
                                target.label) if w)
    return _answer(heard, changes, target.caveat, comparison, not target.stem)


def _quality(
    quality: str,
    target: Target | None,
    sign: float,
    scale: float,
    amount_word: str,
    lanes: dict,
    baseline: dict,
    comparison: dict | None,
) -> Answer:
    """"Make the guitars pop" - a quality, which needs a part to be a quality *of*."""
    label, recipe, caveat = QUALITIES[quality]

    if target is None or target.control != "gain_db":
        return Answer(
            False,
            f"Which part should {label}? I can do that to the bass, the vocal, the drums, "
            'the guitars or the piano - "make the guitars pop" rather than "make it pop", '
            "because the whole mix popping is just the whole mix louder.",
            heard=label,
            suggestions=EXAMPLES,
        )
    if target.stem not in lanes:
        return Answer(
            False,
            f"There is no {target.label} here to work on - separate a track first.",
            heard=label,
        )

    # A direction word reverses a quality: "the vocal shouldn't cut through as much".
    way = -1.0 if sign < 0 else +1.0
    changes = tuple(
        c
        for c in (
            _move(control, target.stem, step_of(control) * scale * share * way,
                  lanes, baseline)
            for control, share in recipe
        )
        if abs(c.delta) > 1e-6
    )
    if not changes:
        return Answer(
            False,
            f"The {target.label} is already as far as typing will take it.",
            heard=label,
        )

    heard = " ".join(w for w in (target.label, amount_word, label) if w)
    return _answer(heard, changes, caveat, comparison, False)
