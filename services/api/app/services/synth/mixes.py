"""Saved mixes: a mix kept under a name and put on another version. Sprint 10.

Ryan: *"go ahead with saving a mix to reuse next."* A mix is a channel per layer - level,
pan, mute, solo, cuts, sends and their automation lanes (`synth/mixer.Channel`) - and the
layers are named the same on every version (drums, bass, ... the added beat, the builds and
drops), so a mix made on one version means something on another.

What does not carry over is said, never dropped silently, because a mix that quietly
half-applied would sound wrong with nobody able to say why:

* **A part the version does not have** - a mix that rides the vocals, put on a version
  whose vocals are left out - is listed and skipped.
* **Automation is in beats from the first beat.** On a version the same length it lands
  where it was drawn. On a longer or shorter one, *as saved* keeps every point on its bar
  (points past the end are counted and ignored), and *fit* stretches the lanes in
  proportion, so a filter that opened over the whole first verse still does.

Nothing recorded: a mix is a few hundred bytes of JSON in the user's samples folder, outside
the repository, like their sounds and kits.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

#: Where saved mixes live, inside the samples directory.
MIX_DIR = "mixes"
SAFE_NAME = re.compile(r"^[A-Za-z0-9 _-]{1,32}$")
#: The music layers a starter mix treats alike - everything but the drums and the beat.
MUSIC = ("bass", "guitar", "piano", "vocals", "other")

#: Starter mixes, for somebody who does not know where to begin. Each says what it does.
STARTERS: dict[str, dict] = {
    "Wide and spacious": {
        "about": "Guitars and keys pushed apart, a little reverb on the music, the beat dry "
                 "and centered - room around everything.",
        "channels": {
            "guitar": {"pan": -0.45, "reverb": 0.25},
            "piano": {"pan": 0.45, "reverb": 0.25},
            "other": {"reverb": 0.3},
            "vocals": {"reverb": 0.2},
        },
    },
    "Tight and dry": {
        "about": "No reverb, a low cut on everything but the bass and the kick, so the low "
                 "end is the bass's alone - the club mix.",
        "channels": {**{n: {"low_cut_hz": 150.0} for n in ("guitar", "piano", "vocals",
                                                           "other")},
                     "bass": {"gain_db": 1.5}},
    },
    "Filter-up intro": {
        "about": "The music starts muffled and opens up over the first eight bars, while the "
                 "drums and the beat play through - the classic dance intro.",
        "channels": {n: {"automation": {"high_cut_hz": [[0, 300.0], [32, 20000.0]]}}
                     for n in MUSIC},
    },
}


def mix_dir(sample_dir: Path) -> Path:
    return Path(sample_dir) / MIX_DIR


def saved_mixes(sample_dir: Path | None) -> dict[str, dict]:
    """Every saved mix: name -> {"channels": {...}, "beats": n, "tempo_bpm": t}."""
    out = {}
    if sample_dir is None or not mix_dir(sample_dir).exists():
        return out
    for path in sorted(mix_dir(sample_dir).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data.get("channels"), dict):
                out[path.stem] = data
        except Exception:  # noqa: BLE001 - one unreadable mix should not hide the rest
            continue
    return out


def save_mix(sample_dir: Path, name: str, channels: dict, beats: float,
             tempo_bpm: float) -> Path:
    folder = mix_dir(sample_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps({"channels": channels, "beats": beats, "tempo_bpm": tempo_bpm}),
                    "utf-8")
    return path


def delete_mix(sample_dir: Path, name: str) -> bool:
    path = mix_dir(sample_dir) / f"{name}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def describe(channels: dict) -> str:
    """"5 parts, 3 lanes" - what a saved mix holds, counted."""
    parts = len(channels)
    lanes = sum(len([p for p in (c.get("automation") or {}).values() if p])
                for c in channels.values())
    text = f"{parts} part{'s' if parts != 1 else ''}"
    if lanes:
        text += f", {lanes} moving setting{'s' if lanes != 1 else ''}"
    return text


def fit(channels: dict, layers: list[str], beats: float, saved_beats: float | None,
        stretch: bool) -> tuple[dict, list[str]]:
    """A saved mix made ready for a version: its layers, its length. Returns the channels to
    use and a sentence for everything that did not carry over as it was."""
    notes = []
    missing = sorted(n for n in channels if n not in layers)
    if missing:
        notes.append(f"This version has no {', '.join(missing)}, so "
                     f"{'that part' if len(missing) == 1 else 'those parts'} of the mix "
                     f"{'is' if len(missing) == 1 else 'are'} left out.")
    ratio = 1.0
    if stretch and saved_beats and beats and abs(beats - saved_beats) > 0.5:
        ratio = beats / saved_beats
        notes.append(f"Moving settings stretched to fit: {saved_beats / 4:.0f} bars became "
                     f"{beats / 4:.0f}.")
    out, past = {}, 0
    for name, channel in channels.items():
        if name not in layers:
            continue
        channel = dict(channel)
        lanes = {}
        for setting, points in (channel.get("automation") or {}).items():
            moved = [[b * ratio, v] for b, v in points]
            kept = [p for p in moved if p[0] <= beats] if beats else moved
            past += len(moved) - len(kept)
            if kept:
                lanes[setting] = kept
        channel["automation"] = lanes
        out[name] = channel
    if past:
        notes.append(f"{past} point{'s' if past != 1 else ''} past the end of this version "
                     f"{'was' if past == 1 else 'were'} left out - try fitting it to the "
                     f"version instead.")
    return out, notes
