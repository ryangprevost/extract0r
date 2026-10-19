"""Styles: one press to the sound of a genre. Sprint 12.

Ryan: *"i want this to sound like the style and i dont know a lot about configuring tones
with synths."* So a style is every choice a producer would make for that genre, made for
him: the tempo, the beat, the kit, the pump, and an instrument for every part. Each part
names a real synth first - a multisampled instrument from `instruments.py`, when it is
installed - and one of this app's own voices to fall back on, so a style works on any
install and sounds best on one with the samples.

### A style is a whole recipe (Sprint 26)

Ryan: *"maybe have a style guideline with parameters of what make each type unique in the
background. Styles like techno, trance, electro house, house, complextro, etc. have behind
the scenes configs for each and use them as a starting point for the remix."*

So a style is no longer four settings and a list of sounds. Each one carries a **recipe** -
the same shape `synth/describe.py` reads a sentence into - holding everything that makes the
genre what it is: how hard each part is driven, how wide it sits, how deep it ducks on the
kick, whether the chords become stabs, whether a single gritty line plays over clean chords,
how the notes are tidied and held, and how much the track is chopped.

These are starting points, not rules. Every one of them lands in an ordinary control on the
page, so picking a style and then disagreeing with it is one slider away. The numbers below
come from the measurements this project has already made - the pump depths, the grit
amounts, the kick kits - rather than from a chart somebody copied.

**What separates the genres here**

| style | tempo | its beat | what it does to the parts |
|---|---|---|---|
| House | 120-126 | swung four on the floor | clean and warm, a light pump, offbeat stabs |
| Electro house | 126-130 | four on the floor | bass driven hard, lead stacked wide, deep pump |
| EDM | 126-130 | four on the floor | big room: a hard bass, strings under the drop |
| Complextro | 125-132 | sixteenth hats | the most chopped: stabs, rises, a gritty line |
| Electro | 125-132 | four on the floor | distortion on everything, mid-forward, narrow |
| Techno | 130-140 | relentless sixteenths | dark and even: long notes, little harmony, gates |
| Trance | 134-142 | four on the floor | a rolling bass under supersaws held to the bar |
| Hard dance | 150-160 | four on the floor | punk speed kept, distorted bass, a stack lead |
| Drum and bass | 168-178 | two-step break | a reese bass under chords that move half as fast |
| Half-time | 130-190 | trap | kick and snare at half the rate, at the song's speed |
| Synthwave | 95-118 | the band's own drums | clean and wide, nothing chopped, notes held |

Every choice lands in the page's ordinary controls, so the style teaches rather than hides:
somebody can see that house put the keys on a TX81Z FM piano, and change it.

### A style lives in a range of tempos, and the song has its own (Sprint 15)

Ryan, on a pop-punk song made into EDM: *"it just doesnt seem to translate well it feels
slowed down and boring."* It was: 169 BPM to 129 is every note a quarter slower, and a sung
vocal stretched that far drags. Each style now has the range its records actually sit in,
and `fit` chooses the tempo in that range nearest the song's own - unchanged when the song
is already inside it - and says how far the song has to move. *Half-time* exists for fast
songs: the trap/future-bass beat, kick and snare at half the rate, at the song's own tempo,
so it hits like an 85 BPM drop while the vocal keeps its real speed.
"""

from __future__ import annotations

#: name -> tempo, beat, kit, pump, drop, about, per part (real synth, fallback voice), and
#: `recipe`: everything else that makes the genre itself, in `describe.Recipe`'s own fields.
#:
#: A part's entry in `recipe["parts"]` is how it is *treated* - grit, width, pump depth -
#: while `parts` above is what it is *played on*. The two are separate because a sound and
#: what is done to it are separate choices, and a person may change either.
STYLES: dict[str, dict] = {
    "EDM": {
        "tempo": 128, "range": (126, 130),
        "beat": "four on the floor", "kit": "edm", "pump": True, "drop": True,
        "about": "Big-room: a hard bass, a wide stacked lead, strings under the drop.",
        "parts": {"drums": ("", "edm"), "bass": ("hard-bass", "808"),
                  "guitar": ("big-stack", "pluck"), "piano": ("cluster-strings", "pad"),
                  "other": ("cluster-strings", "pad")},
        "recipe": {
            "tidy": True, "follow_bass": True, "fill": True, "ghost_pump": True,
            "chops": "few",
            "parts": {"bass": {"grit": 0.35, "width": 0.3, "pump_db": 10.0},
                      "guitar": {"grit": 0.2, "width": 0.9, "pump_db": 12.0},
                      "piano": {"width": 0.9, "pump_db": 12.0},
                      "other": {"width": 1.0, "pump_db": 12.0},
                      "vocals": {"pump_db": 4.0}},
        },
    },
    "House": {
        "tempo": 124, "range": (120, 126), "beat": "house", "kit": "house", "pump": True,
        "drop": False,
        "about": "A MicroBrute bass, TX81Z electric piano and clav stabs, a warm pad.",
        "parts": {"drums": ("", "house"), "bass": ("microbrute-sharp-bass", "808"),
                  "guitar": ("tx81z-clavisynth", "stab"), "piano": ("tx81z-fm-piano", "epiano"),
                  "other": ("mg1-pad", "pad")},
        "recipe": {
            "tidy": True, "follow_bass": True, "fill": True, "stabs": True,
            "swing": 0.2, "chops": "none",
            "parts": {"bass": {"width": 0.2, "pump_db": 7.0},
                      "guitar": {"grit": 0.15, "width": 0.7, "pump_db": 8.0},
                      "piano": {"width": 0.6, "pump_db": 8.0},
                      "other": {"width": 0.9, "pump_db": 8.0},
                      "vocals": {"pump_db": 3.0}},
        },
    },
    "Electro house": {
        "tempo": 128, "range": (126, 130),
        "beat": "four on the floor", "kit": "edm", "pump": True, "drop": True,
        "about": "The bass driven hard and the lead stacked wide, ducking deep on every "
                 "kick - the Justice and MSTRKRFT end of house.",
        "parts": {"drums": ("", "edm"), "bass": ("hard-bass", "reese"),
                  "guitar": ("big-stack", "supersaw"), "piano": ("jupiter-stack", "stab"),
                  "other": ("cluster-strings", "pad")},
        "recipe": {
            "tidy": True, "follow_bass": True, "fill": True, "stabs": True,
            "lead_over_chords": True, "ghost_pump": True, "chops": "some",
            "parts": {"bass": {"grit": 0.5, "width": 0.35, "pump_db": 11.0},
                      "guitar": {"grit": 0.0, "width": 1.0, "pump_db": 14.0},
                      "piano": {"grit": 0.6, "width": 0.3, "pump_db": 10.0},
                      "other": {"grit": 0.45, "width": 0.8, "pump_db": 13.0},
                      "vocals": {"pump_db": 4.0}},
        },
    },
    "Complextro": {
        "tempo": 128, "range": (125, 132), "beat": "techno", "kit": "trap", "pump": True,
        "drop": True,
        "about": "The most chopped of them: syncopated stabs off the kick, a gritty single "
                 "line over clean chords, and stutters and rises into every phrase.",
        "parts": {"drums": ("", "trap"), "bass": ("hard-bass", "808"),
                  "guitar": ("big-stack", "supersaw"), "piano": ("jupiter-stack", "square"),
                  "other": ("jupiter-stack", "stab")},
        "recipe": {
            "tidy": True, "follow_bass": True, "fill": True, "stabs": True,
            "lead_over_chords": True, "ghost_pump": True,
            "chops": "lots", "chop_instruments": True,
            "parts": {"bass": {"grit": 0.5, "width": 0.35, "pump_db": 11.0},
                      "guitar": {"grit": 0.0, "width": 1.0, "pump_db": 14.0},
                      "piano": {"grit": 0.65, "width": 0.3, "pump_db": 10.0},
                      "other": {"grit": 0.5, "width": 0.8, "pump_db": 13.0},
                      "vocals": {"pump_db": 4.0}},
        },
    },
    "Electro": {
        "tempo": 128, "range": (125, 132),
        "beat": "four on the floor", "kit": "techno", "pump": True, "drop": True,
        "about": "Distortion on everything and the middle of the spectrum forward - "
                 "narrower and dirtier than house, and it does not let up.",
        "parts": {"drums": ("", "techno"), "bass": ("hard-bass", "reese"),
                  "guitar": ("microbrute-saw-lead", "square"),
                  "piano": ("jupiter-stack", "stab"), "other": ("big-stack", "supersaw")},
        "recipe": {
            "tidy": True, "follow_bass": True, "fill": True, "stabs": True,
            "ghost_pump": True, "chops": "some",
            "parts": {"bass": {"grit": 0.6, "width": 0.2, "pump_db": 11.0},
                      "guitar": {"grit": 0.55, "width": 0.6, "pump_db": 12.0},
                      "piano": {"grit": 0.5, "width": 0.4, "pump_db": 11.0},
                      "other": {"grit": 0.5, "width": 0.7, "pump_db": 12.0},
                      "vocals": {"pump_db": 4.0}},
        },
    },
    "Techno": {
        "tempo": 134, "range": (130, 140), "beat": "techno", "kit": "techno", "pump": True,
        "drop": False,
        "about": "Dark and even: sixteenth hats that never stop, notes held long, and "
                 "almost no harmony to get in the way.",
        "parts": {"drums": ("", "techno"), "bass": ("thick-bass", "subbass"),
                  "guitar": ("microbrute-strings", "pad"),
                  "piano": ("mg1-pad", "pad"), "other": ("cluster-strings", "pad")},
        "recipe": {
            "tidy": True, "follow_bass": True, "fill": True, "legato": True,
            "ghost_pump": True, "chops": "few",
            "parts": {"bass": {"grit": 0.3, "width": 0.15, "pump_db": 9.0},
                      "guitar": {"grit": 0.25, "width": 0.8, "pump_db": 11.0},
                      "piano": {"width": 0.8, "pump_db": 11.0},
                      "other": {"grit": 0.2, "width": 1.0, "pump_db": 11.0},
                      "vocals": {"pump_db": 5.0}},
        },
    },
    "Trance": {
        "tempo": 138, "range": (134, 142),
        "beat": "four on the floor", "kit": "edm", "pump": True, "drop": True,
        "about": "A rolling trance bass, a Jupiter-style stack for the hook, synth strings.",
        "parts": {"drums": ("", "edm"), "bass": ("trance-bass", "subbass"),
                  "guitar": ("jupiter-stack", "supersaw"),
                  "piano": ("cluster-strings", "pad"), "other": ("microbrute-strings", "pad")},
        "recipe": {
            "tidy": True, "follow_bass": True, "fill": True, "legato": True,
            "ghost_pump": True, "chops": "none",
            "parts": {"bass": {"width": 0.15, "pump_db": 10.0},
                      "guitar": {"width": 1.0, "pump_db": 13.0},
                      "piano": {"width": 1.0, "pump_db": 13.0},
                      "other": {"width": 1.0, "pump_db": 13.0},
                      "vocals": {"pump_db": 4.0}},
        },
    },
    "Drum and bass": {
        "tempo": 174, "range": (168, 178), "beat": "drum and bass", "kit": "dnb",
        "pump": False, "drop": True,
        "about": "A DnB bass under a stack and strings, on a two-step break.",
        "parts": {"drums": ("", "dnb"), "bass": ("dnb-bass", "reese"),
                  "guitar": ("jupiter-stack", "supersaw"), "piano": ("cluster-strings", "pad"),
                  "other": ("cluster-strings", "pad")},
        "recipe": {
            "tidy": True, "follow_bass": True, "fill": True, "legato": True,
            "chops": "few",
            "parts": {"bass": {"grit": 0.4, "width": 0.2},
                      "guitar": {"width": 0.9}, "piano": {"width": 0.9},
                      "other": {"width": 1.0}},
        },
    },
    "Synthwave": {
        "tempo": 110, "range": (95, 118), "beat": "", "kit": "punchy", "pump": False,
        "drop": False,
        "about": "The drummer kept on a punchy kit, a MicroBrute bass and saw lead, analog "
                 "strings - eighties.",
        "parts": {"drums": ("", "punchy"), "bass": ("microbrute-sharp-bass", "808"),
                  "guitar": ("microbrute-saw-lead", "supersaw"),
                  "piano": ("jupiter-stack", "pad"), "other": ("microbrute-strings", "pad")},
        "recipe": {
            "tidy": True, "fill": True, "legato": True, "chops": "none",
            "parts": {"bass": {"width": 0.2}, "guitar": {"width": 0.8},
                      "piano": {"width": 0.9}, "other": {"width": 1.0}},
        },
    },
    "Half-time": {
        "tempo": 150, "range": (130, 190), "beat": "trap", "kit": "trap", "pump": True,
        "drop": True,
        "about": "Future bass and trap: kick and snare at half the rate, at the song's own "
                 "speed - a huge, slow-feeling drop under a vocal that does not drag. Made "
                 "for fast songs.",
        "parts": {"drums": ("", "trap"), "bass": ("hard-bass", "808"),
                  "guitar": ("big-stack", "supersaw"), "piano": ("jupiter-stack", "pad"),
                  "other": ("cluster-strings", "pad")},
        "recipe": {
            "tidy": True, "follow_bass": True, "fill": True, "ghost_pump": True,
            "chops": "some", "chop_instruments": True,
            "parts": {"bass": {"grit": 0.45, "width": 0.3, "pump_db": 10.0},
                      "guitar": {"grit": 0.3, "width": 1.0, "pump_db": 13.0},
                      "piano": {"width": 0.8, "pump_db": 12.0},
                      "other": {"width": 1.0, "pump_db": 13.0},
                      "vocals": {"pump_db": 3.0}},
        },
    },
    "Hard dance": {
        "tempo": 155, "range": (150, 160), "beat": "four on the floor", "kit": "techno",
        "pump": True, "drop": True,
        "about": "Hard dance: four on the floor at punk speed, a distorted bass and a big "
                 "stack lead - energy kept, not traded for groove.",
        "parts": {"drums": ("", "techno"), "bass": ("hard-bass", "reese"),
                  "guitar": ("big-stack", "supersaw"), "piano": ("cluster-strings", "pad"),
                  "other": ("jupiter-stack", "pad")},
        "recipe": {
            "tidy": True, "follow_bass": True, "fill": True, "ghost_pump": True,
            "chops": "some",
            "parts": {"bass": {"grit": 0.55, "width": 0.25, "pump_db": 11.0},
                      "guitar": {"grit": 0.4, "width": 1.0, "pump_db": 13.0},
                      "piano": {"width": 0.9, "pump_db": 12.0},
                      "other": {"grit": 0.3, "width": 0.9, "pump_db": 12.0},
                      "vocals": {"pump_db": 4.0}},
        },
    },
}

#: The names a person might use for each style, beyond the style's own name. Read by
#: `synth/describe.py`, so one list serves the picker and the sentence.
ALIASES = {
    "EDM": ("edm", "big room", "festival"),
    "House": ("house", "deep house", "classic house"),
    "Electro house": ("electro house", "bloghouse", "blog house", "justice", "mstrkrft"),
    "Complextro": ("complextro", "madeon", "porter robinson", "glitchy electro"),
    "Electro": ("electro", "dirty electro", "electro dirty"),
    "Techno": ("techno", "warehouse", "peak time"),
    "Trance": ("trance", "uplifting", "progressive trance"),
    "Drum and bass": ("drum and bass", "dnb", "d and b", "jungle", "liquid"),
    "Synthwave": ("synthwave", "retrowave", "eighties", "80s"),
    "Half-time": ("half-time", "half time", "future bass", "trap"),
    "Hard dance": ("hard dance", "hardstyle", "hard"),
}


def recipe_for(name: str) -> dict:
    """A style's recipe - the controls that make it that genre - as plain data."""
    import copy

    return copy.deepcopy(STYLES[name].get("recipe") or {})


#: Within this much of the song's own tempo, a style "keeps its speed".
KEEPS = 0.04
#: Past this much slower, a sung vocal audibly drags.
DRAGS = 0.10


def fit(name: str, song_bpm: float) -> dict:
    """The tempo a style should use for a song, and what that does to the song.

    The song's own tempo when it is inside the style's range - nothing stretched at all -
    else the nearest end of the range. `change` is the speed change as a fraction (-0.24 is
    24% slower)."""
    style = STYLES[name]
    low, high = style.get("range", (style["tempo"], style["tempo"]))
    if not song_bpm or song_bpm <= 0:
        return {"tempo": style["tempo"], "change": 0.0, "keeps_speed": False, "fit": ""}
    target = round(min(max(song_bpm, low), high), 2)
    change = target / song_bpm - 1.0
    pct = round(abs(change) * 100)
    if abs(change) <= KEEPS:
        said = (f"Keeps your song at its own speed ({target:.0f} BPM)." if pct == 0 else
                f"Keeps your song near its own speed ({target:.0f} BPM, {pct}% "
                f"{'faster' if change > 0 else 'slower'}).")
    elif change < 0:
        said = f"Slows your song {pct}% to {target:.0f} BPM."
        if -change >= DRAGS:
            said += " A sung vocal drags at that much - fine for an instrumental."
    else:
        said = f"Speeds your song up {pct}% to {target:.0f} BPM."
        if change >= DRAGS:
            said += " A vocal starts to sound rushed at that much."
    return {"tempo": target, "change": round(change, 4), "keeps_speed": abs(change) <= KEEPS,
            "fit": said}


def suggested(song_bpm: float) -> list[str]:
    """The styles that keep a song at (or near) its own speed, nearest first."""
    if not song_bpm:
        return []
    near = [(abs(fit(n, song_bpm)["change"]), n) for n in STYLES]
    return [n for d, n in sorted(near) if d <= KEEPS]


#: How a part is named to a person, rather than to the separator.
PART_NAMES = {"bass": "bass", "guitar": "guitars", "piano": "keys", "other": "other",
              "vocals": "vocals", "drums": "drums"}


def guide(name: str) -> list[str]:
    """What makes this style itself, in sentences - the recipe read back out.

    Shown under the picker so the style is a thing you can read and argue with rather than
    a word that quietly changes eleven controls."""
    style = STYLES[name]
    recipe = style.get("recipe") or {}
    low, high = style.get("range", (style["tempo"], style["tempo"]))
    lines = [f"Lives at {low}-{high} BPM" + (f", on a {style['beat']} beat"
             if style["beat"] else ", on your own drummer") + f", {style['kit']} kit."]

    treated = recipe.get("parts") or {}
    gritty = [PART_NAMES.get(p, p) for p, t in treated.items() if (t.get("grit") or 0) >= 0.4]
    wide = [PART_NAMES.get(p, p) for p, t in treated.items() if (t.get("width") or 0) >= 0.8]
    pumps = [t["pump_db"] for t in treated.values() if t.get("pump_db")]
    if gritty:
        lines.append(f"Driven hard: {', '.join(gritty)}.")
    elif any((t.get("grit") or 0) > 0 for t in treated.values()):
        lines.append("A touch of grit, no more.")
    else:
        lines.append("Clean - no distortion anywhere.")
    if wide:
        lines.append(f"Spread wide: {', '.join(wide)} (the low end stays centered).")
    if pumps:
        lines.append(f"Ducks on the kick by {min(pumps):.0f}-{max(pumps):.0f} dB"
                     + (", and keeps pulsing where the beat drops out."
                        if recipe.get("ghost_pump") else "."))
    notes = []
    if recipe.get("tidy"):
        notes.append("tidied onto the grid")
    if recipe.get("follow_bass"):
        notes.append("moved onto the bass's chords")
    if recipe.get("fill") or recipe.get("legato"):
        notes.append("held into each other")
    if notes:
        lines.append("Notes " + ", ".join(notes) + ".")
    if recipe.get("lead_over_chords"):
        lines.append("A single gritty line over clean chords, rather than distorted chords.")
    if recipe.get("stabs"):
        lines.append("The chords re-cut into short syncopated stabs.")
    chops = recipe.get("chops")
    if chops and chops != "none":
        lines.append({"few": "A few chops", "some": "Chops", "lots": "Chopped heavily"}[chops]
                     + " at phrase ends"
                     + (", on the instruments as well as the whole track."
                        if recipe.get("chop_instruments") else "."))
    elif chops == "none":
        lines.append("No chops: it runs straight through.")
    if recipe.get("swing"):
        lines.append(f"Swung {recipe['swing'] * 100:.0f}% - it does not sit square.")
    if style.get("drop"):
        lines.append("Builds and drops where you mark them.")
    return lines


def resolve(name: str, installed: set[str], song_bpm: float = 0.0) -> dict:
    """A style made concrete for this install and this song: each part's real synth if it is
    there, its fallback voice if not, how many parts are on real synths, and - given the
    song's tempo - the tempo to use and what it does to the song (see `fit`)."""
    style = STYLES[name]
    parts, real = {}, 0
    for stem, (instrument, fallback) in style["parts"].items():
        if instrument and instrument in installed:
            parts[stem] = instrument
            real += 1
        else:
            parts[stem] = fallback
    fitted = fit(name, song_bpm)
    return {"name": name, "tempo": fitted["tempo"], "range": list(style.get("range", ())),
            "beat": style["beat"], "kit": style["kit"],
            "pump": style["pump"], "drop": style["drop"], "about": style["about"],
            "parts": parts, "real_synths": real, "change": fitted["change"],
            "keeps_speed": fitted["keeps_speed"], "fit": fitted["fit"],
            # Sprint 26: the rest of what makes it this genre, for the page to apply and
            # show. `parts` here is the treatment; `parts` above is what plays it.
            "recipe": recipe_for(name), "aliases": list(ALIASES.get(name, ())),
            "guide": guide(name)}
