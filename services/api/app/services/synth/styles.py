"""Styles: one press to the sound of a genre. Sprint 12.

Ryan: *"i want this to sound like the style and i dont know a lot about configuring tones
with synths."* So a style is every choice a producer would make for that genre, made for
him: the tempo, the beat, the kit, the pump, and an instrument for every part. Each part
names a real synth first - a multisampled instrument from `instruments.py`, when it is
installed - and one of this app's own voices to fall back on, so a style works on any
install and sounds best on one with the samples.

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

#: name -> tempo, beat, kit, pump, drop, about, and per part (real synth, fallback voice).
STYLES: dict[str, dict] = {
    "EDM": {
        "tempo": 128, "range": (126, 130),
        "beat": "four on the floor", "kit": "edm", "pump": True, "drop": True,
        "about": "Big-room: a hard bass, a wide stacked lead, strings under the drop.",
        "parts": {"drums": ("", "edm"), "bass": ("hard-bass", "808"),
                  "guitar": ("big-stack", "pluck"), "piano": ("cluster-strings", "pad"),
                  "other": ("cluster-strings", "pad")},
    },
    "House": {
        "tempo": 124, "range": (120, 126), "beat": "house", "kit": "house", "pump": True,
        "drop": False,
        "about": "A MicroBrute bass, TX81Z electric piano and clav stabs, a warm pad.",
        "parts": {"drums": ("", "house"), "bass": ("microbrute-sharp-bass", "808"),
                  "guitar": ("tx81z-clavisynth", "stab"), "piano": ("tx81z-fm-piano", "epiano"),
                  "other": ("mg1-pad", "pad")},
    },
    "Trance": {
        "tempo": 138, "range": (134, 142),
        "beat": "four on the floor", "kit": "edm", "pump": True, "drop": True,
        "about": "A rolling trance bass, a Jupiter-style stack for the hook, synth strings.",
        "parts": {"drums": ("", "edm"), "bass": ("trance-bass", "subbass"),
                  "guitar": ("jupiter-stack", "supersaw"),
                  "piano": ("cluster-strings", "pad"), "other": ("microbrute-strings", "pad")},
    },
    "Drum and bass": {
        "tempo": 174, "range": (168, 178), "beat": "drum and bass", "kit": "dnb",
        "pump": False, "drop": True,
        "about": "A DnB bass under a stack and strings, on a two-step break.",
        "parts": {"drums": ("", "dnb"), "bass": ("dnb-bass", "reese"),
                  "guitar": ("jupiter-stack", "supersaw"), "piano": ("cluster-strings", "pad"),
                  "other": ("cluster-strings", "pad")},
    },
    "Synthwave": {
        "tempo": 110, "range": (95, 118), "beat": "", "kit": "punchy", "pump": False, "drop": False,
        "about": "The drummer kept on a punchy kit, a MicroBrute bass and saw lead, analog "
                 "strings - eighties.",
        "parts": {"drums": ("", "punchy"), "bass": ("microbrute-sharp-bass", "808"),
                  "guitar": ("microbrute-saw-lead", "supersaw"),
                  "piano": ("jupiter-stack", "pad"), "other": ("microbrute-strings", "pad")},
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
    },
    "Hard dance": {
        "tempo": 155, "range": (150, 160), "beat": "four on the floor", "kit": "techno",
        "pump": True, "drop": True,
        "about": "Hard dance: four on the floor at punk speed, a distorted bass and a big "
                 "stack lead - energy kept, not traded for groove.",
        "parts": {"drums": ("", "techno"), "bass": ("hard-bass", "reese"),
                  "guitar": ("big-stack", "supersaw"), "piano": ("cluster-strings", "pad"),
                  "other": ("jupiter-stack", "pad")},
    },
}

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
            "keeps_speed": fitted["keeps_speed"], "fit": fitted["fit"]}
