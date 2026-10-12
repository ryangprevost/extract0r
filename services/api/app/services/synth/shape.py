"""Shaping the sounds: knobs on every synth voice and every drum of every kit. Sprint 8.

Ryan: *"go ahead with shaping the sounds next."* The built-in voices and kits are short lists
of numbers (`synth/voice.PitchedVoice`, `drums/kit.Voice`), and every number does one audible
thing - which is what makes them shapeable at all. But "brightness_decay = 10" means nothing
to somebody who wants a pluck that rings longer, so the knobs here are named for what is
heard, run from -1 to +1 with 0 as the stock sound, and each one turns a small set of the
engine's numbers together.

### Two rules every knob keeps

* **A shaped voice still plays the note it is asked for.** `test_synth` holds the built-ins
  to that under a pitch tracker; the shaped extremes are held to it too. That is why
  brightness tilts the harmonics by a bounded exponent rather than boosting the top
  freely, and why weight stops at `MAX_SUB`.
* **Nothing recorded.** A shaped sound is a base sound's name plus knob positions - a few
  bytes of JSON in the user's samples folder, outside the repository like their kits.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

from app.services.drums.kit import DRUMS, KITS, Voice
from app.services.synth.voice import VOICES, PitchedVoice

#: Where shaped sounds live, inside the samples directory.
SOUND_DIR = "sounds"
SAFE_NAME = re.compile(r"^[A-Za-z0-9 _-]{1,32}$")
#: A voice's sub-octave never goes past this - the same ceiling `test_synth` holds the
#: built-ins to, because a loud sub-octave is heard (and transcribed) as the note below.
MAX_SUB = 0.25
#: How far brightness tilts the harmonics: partial n is scaled by n ** (TILT * knob).
TILT = 0.6
#: Brighter never lifts a harmonic past this share of the fundamental. See `shape_voice`.
BRIGHT_CAP = 0.55
#: Widest detune, in cents.
WIDEST = 30.0

#: Synth knobs: name -> (what it does, in the page's words).
VOICE_KNOBS = {
    "brightness": "Darker ↔ brighter",
    "attack": "Snaps in ↔ swells in",
    "length": "Shorter ↔ longer",
    "sustain": "Fades away ↔ holds",
    "width": "Narrow ↔ wide",
    "drive": "Clean ↔ gritty",
    "pluck": "Stays bright ↔ closes fast",
    "weight": "Light ↔ heavy low end",
}
#: Drum knobs, per drum: name -> what it does.
DRUM_KNOBS = {
    "tune": "Lower ↔ higher (an octave each way)",
    "length": "Tighter ↔ longer ring",
    "snap": "Soft ↔ snappy front",
    "tone": "Darker ↔ brighter noise",
    "punch": "Slow sweep ↔ fast thump",
}


def _knob(knobs: dict, name: str) -> float:
    try:
        return max(-1.0, min(1.0, float(knobs.get(name, 0.0))))
    except (TypeError, ValueError):
        return 0.0


def shape_voice(base: PitchedVoice, knobs: dict) -> PitchedVoice:
    """A built-in voice with the knobs applied. All knobs at 0 is the base voice exactly."""
    k = {name: _knob(knobs, name) for name in VOICE_KNOBS}
    partials = [a * (n ** (TILT * k["brightness"]))
                for n, a in enumerate(base.partials, start=1)]
    # Weight is the voice's own low harmonics, not a sub-octave: the fundamental up to 3 dB
    # and the second up 1.5 dB at +1. A stacked voice's copies partly cancel at the
    # fundamental, and the first version's added sub-octave out-shouted it - the supersaw
    # at +1 weight peaked an octave low at middle C.
    if partials:
        partials[0] *= 2 ** (0.5 * k["weight"])
    if len(partials) > 1:
        partials[1] *= 2 ** (0.25 * k["weight"])
    top = partials[0] or 1.0
    partials = [a / top for a in partials]
    if k["brightness"] > 0:
        # Brighter lifts the upper harmonics but never past CAP of the fundamental - the
        # stock saws sit at 0.5 and play their notes; at +1 tilt uncapped, the pad's octave
        # came out louder than its note.
        partials = [partials[0]] + [min(a, BRIGHT_CAP) for a in partials[1:]]
    partials = tuple(partials)
    # Width: more copies and more spread. A single-copy voice gains a second copy only when
    # widened, so 0 stays exactly the base. Spread stops at WIDEST: at 55 cents the copies
    # were 3% from the note.
    stack, detune = base.stack, base.detune_cents
    if k["width"] > 0:
        stack = max(stack, 2) if base.stack == 1 else stack + round(2 * k["width"])
        detune = min(WIDEST, (detune or 8.0) * (1 + 1.5 * k["width"]))
    elif k["width"] < 0:
        detune = detune * (1 + k["width"])           # -1 is no detune at all
    # A sub-octave only on a single-copy voice, where nothing cancels the note under it.
    sub = base.sub_level + (0.15 * k["weight"] if base.stack == 1 else 0.0)
    return replace(
        base,
        partials=partials,
        attack_s=base.attack_s * 6 ** k["attack"],
        decay_s=base.decay_s * 3 ** k["length"],
        release_s=base.release_s * 3 ** k["length"],
        sustain=min(1.0, max(0.0, base.sustain + 0.5 * k["sustain"])),
        stack=max(1, stack),
        detune_cents=max(0.0, detune),
        drive=min(1.0, max(0.0, base.drive + 0.5 * k["drive"])),
        brightness_decay=base.brightness_decay * 3 ** k["pluck"]
        if base.brightness_decay else max(0.0, 4.0 * k["pluck"]),
        sub_level=min(MAX_SUB, max(0.0, sub)),
    )


def shape_drum(base: Voice, knobs: dict) -> Voice:
    """One drum with the knobs applied. All knobs at 0 is the base drum exactly."""
    k = {name: _knob(knobs, name) for name in DRUM_KNOBS}
    pitch = 2.0 ** k["tune"]                        # an octave each way at the ends
    longer = 2.0 ** k["length"]
    return replace(
        base,
        length_s=base.length_s * longer,
        pitch_from=base.pitch_from * pitch,
        pitch_to=base.pitch_to * pitch,
        pitch_decay=base.pitch_decay * 2.0 ** k["punch"],
        body_decay=base.body_decay / longer,
        noise_decay=base.noise_decay / longer,
        noise_level=min(1.0, base.noise_level * 3.0 ** k["snap"]),
        noise_highpass=base.noise_highpass * 2.0 ** k["tone"],
        noise_lowpass=base.noise_lowpass * 2.0 ** k["tone"] if base.noise_lowpass else 0.0,
    )


def shape_kit(base: str, knobs: dict) -> dict[str, Voice]:
    """A built-in kit with each drum's knobs applied: knobs is {drum: {knob: value}}."""
    return {drum: shape_drum(KITS[base][drum], knobs.get(drum) or {})
            for drum in DRUMS if drum in KITS[base]}


# --- your sounds ------------------------------------------------------------------------------


def sound_dir(sample_dir: Path) -> Path:
    return Path(sample_dir) / SOUND_DIR


def user_sounds(sample_dir: Path | None) -> dict[str, dict]:
    """Every saved sound: name -> {"kind": "voice" | "kit", "base": ..., "knobs": {...}}."""
    out = {}
    if sample_dir is None or not sound_dir(sample_dir).exists():
        return out
    for path in sorted(sound_dir(sample_dir).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("kind") in ("voice", "kit") and data.get("base"):
                out[path.stem] = data
        except Exception:  # noqa: BLE001 - one unreadable sound should not hide the rest
            continue
    return out


def save_sound(sample_dir: Path, name: str, kind: str, base: str, knobs: dict) -> Path:
    folder = sound_dir(sample_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps({"kind": kind, "base": base, "knobs": knobs}), "utf-8")
    return path


def delete_sound(sample_dir: Path, name: str) -> bool:
    path = sound_dir(sample_dir) / f"{name}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def voice_named(name: str, sample_dir: Path | None) -> PitchedVoice | None:
    """A built-in voice, or one of the user's shaped voices, by name. None if neither."""
    if name in VOICES:
        return VOICES[name]
    sound = user_sounds(sample_dir).get(name)
    if sound and sound["kind"] == "voice" and sound["base"] in VOICES:
        return shape_voice(VOICES[sound["base"]], sound.get("knobs") or {})
    return None


def kit_named(name: str, sample_dir: Path | None) -> dict[str, Voice] | None:
    """One of the user's shaped kits, as drum voices. None if it is not one."""
    sound = user_sounds(sample_dir).get(name)
    if sound and sound["kind"] == "kit" and sound["base"] in KITS:
        return shape_kit(sound["base"], sound.get("knobs") or {})
    return None


def describe(kind: str, base: str, knobs: dict) -> str:
    """"the 808, brighter and longer" - what a shaped sound is, from its knobs."""
    words = {
        "brightness": ("darker", "brighter"), "attack": ("snappier", "softer in"),
        "length": ("shorter", "longer"), "sustain": ("fading", "holding"),
        "width": ("narrower", "wider"), "drive": ("cleaner", "grittier"),
        "pluck": ("brighter for longer", "closing faster"), "weight": ("lighter", "heavier"),
        "tune": ("lower", "higher"), "snap": ("softer", "snappier"),
        "tone": ("darker", "brighter"), "punch": ("slower", "punchier"),
    }
    said = []
    flat = [knobs] if kind == "voice" else [knobs.get(d) or {} for d in DRUMS]
    for group, drum in zip(flat, [None] if kind == "voice" else DRUMS, strict=True):
        for name in group:
            v = _knob(group, name)
            if abs(v) >= 0.15 and name in words:
                word = words[name][1 if v > 0 else 0]
                said.append(f"{drum} {word}" if drum else word)
    what = f"the {base}" + (" kit" if kind == "kit" else "")
    return f"{what}, {', '.join(said)}" if said else what
