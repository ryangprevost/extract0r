"""Styles: one press to the sound of a genre. Sprint 12.

Ryan: *"i want this to sound like the style and i dont know a lot about configuring tones
with synths."* So a style is every choice a producer would make for that genre, made for
him: the tempo, the beat, the kit, the pump, and an instrument for every part. Each part
names a real synth first - a multisampled instrument from `instruments.py`, when it is
installed - and one of this app's own voices to fall back on, so a style works on any
install and sounds best on one with the samples.

Every choice lands in the page's ordinary controls, so the style teaches rather than hides:
somebody can see that house put the keys on a TX81Z FM piano, and change it.
"""

from __future__ import annotations

#: name -> tempo, beat, kit, pump, drop, about, and per part (real synth, fallback voice).
STYLES: dict[str, dict] = {
    "EDM": {
        "tempo": 128, "beat": "four on the floor", "kit": "edm", "pump": True, "drop": True,
        "about": "Big-room: a hard bass, a wide stacked lead, strings under the drop.",
        "parts": {"drums": ("", "edm"), "bass": ("hard-bass", "808"),
                  "guitar": ("big-stack", "pluck"), "piano": ("cluster-strings", "pad"),
                  "other": ("cluster-strings", "pad")},
    },
    "House": {
        "tempo": 124, "beat": "house", "kit": "house", "pump": True, "drop": False,
        "about": "A MicroBrute bass, TX81Z electric piano and clav stabs, a warm pad.",
        "parts": {"drums": ("", "house"), "bass": ("microbrute-sharp-bass", "808"),
                  "guitar": ("tx81z-clavisynth", "stab"), "piano": ("tx81z-fm-piano", "epiano"),
                  "other": ("mg1-pad", "pad")},
    },
    "Trance": {
        "tempo": 138, "beat": "four on the floor", "kit": "edm", "pump": True, "drop": True,
        "about": "A rolling trance bass, a Jupiter-style stack for the hook, synth strings.",
        "parts": {"drums": ("", "edm"), "bass": ("trance-bass", "subbass"),
                  "guitar": ("jupiter-stack", "supersaw"),
                  "piano": ("cluster-strings", "pad"), "other": ("microbrute-strings", "pad")},
    },
    "Drum and bass": {
        "tempo": 174, "beat": "drum and bass", "kit": "dnb", "pump": False, "drop": True,
        "about": "A DnB bass under a stack and strings, on a two-step break.",
        "parts": {"drums": ("", "dnb"), "bass": ("dnb-bass", "reese"),
                  "guitar": ("jupiter-stack", "supersaw"), "piano": ("cluster-strings", "pad"),
                  "other": ("cluster-strings", "pad")},
    },
    "Synthwave": {
        "tempo": 110, "beat": "", "kit": "punchy", "pump": False, "drop": False,
        "about": "The drummer kept on a punchy kit, a MicroBrute bass and saw lead, analog "
                 "strings - eighties.",
        "parts": {"drums": ("", "punchy"), "bass": ("microbrute-sharp-bass", "808"),
                  "guitar": ("microbrute-saw-lead", "supersaw"),
                  "piano": ("jupiter-stack", "pad"), "other": ("microbrute-strings", "pad")},
    },
}


def resolve(name: str, installed: set[str]) -> dict:
    """A style made concrete for this install: each part's real synth if it is there, its
    fallback voice if not, and how many parts are on real synths."""
    style = STYLES[name]
    parts, real = {}, 0
    for stem, (instrument, fallback) in style["parts"].items():
        if instrument and instrument in installed:
            parts[stem] = instrument
            real += 1
        else:
            parts[stem] = fallback
    return {"name": name, "tempo": style["tempo"], "beat": style["beat"], "kit": style["kit"],
            "pump": style["pump"], "drop": style["drop"], "about": style["about"],
            "parts": parts, "real_synths": real}
