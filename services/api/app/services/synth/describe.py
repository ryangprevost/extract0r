"""Describe it: a remix in words, turned into the controls that make it. Sprint 21.

Ryan, 2026-10-14: *"I guess I'm looking for something generative like Suno that takes prompts
and uses a reference track"* - and then, *"keep it free for now but allow architecture to
easily switch to the API as needed."*

### Not a generator

Suno makes new audio from a model trained on other people's records. This makes nothing new:
it reads a sentence into a **recipe** - a fixed set of this application's own controls (style,
tempo, kit, grit, width, pump, stabs, a lead over the chords, legato, following the bass,
chops, the arrangement, the reference's levels) - and the page then sets those controls and
makes the version the ordinary way. Everything it chose is a control the person can see and
change, which is the rule `mastering/ask.py` set for words: the words choose the control.

### Two readers, one recipe

- `VocabularyReader` - the default. Free, offline, deterministic: the same words always make
  the same recipe, and a test holds it there. It knows a vocabulary, not English, and says
  which words it did not use.
- `ClaudeReader` - the same recipe read by Claude, for any wording. Switched on with
  `PROMPT_READER=claude` and `ANTHROPIC_API_KEY` in the local `.env`; off by default, because
  every call costs the key's owner money and needs the network. It can only fill the
  recipe's fields - the schema is the whole of what it may say - and its answer is validated
  like any request before anything is done with it.

`reader_for(settings)` picks one; nothing else in the app knows which.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, Field

PARTS = ("bass", "guitar", "piano", "other", "vocals")


class PartRecipe(BaseModel):
    grit: float | None = Field(None, ge=0.0, le=1.0)
    width: float | None = Field(None, ge=0.0, le=1.0)
    pump_db: float | None = Field(None, ge=0.0, le=24.0)


class ArrangementRecipe(BaseModel):
    #: Section labels to leave out (e.g. "verse").
    skip: list[str] = Field(default_factory=list)
    #: Section labels played without the beat - breakdowns, a subdued post-chorus.
    subdued: list[str] = Field(default_factory=list)
    #: A label to build and drop into, where it first comes back after something quieter.
    drop_at: str | None = None


class Recipe(BaseModel):
    """What a prompt asks for, in this application's controls. Every field is optional:
    None means "leave that control as it is"."""

    style: str | None = None
    #: "keep" the song's own speed, or a tempo in BPM.
    tempo: Literal["keep"] | float | None = None
    beat: str | None = None
    kit: str | None = None
    #: The guitar's chords as clean chords, their top note as a gritty lead on the keys.
    lead_over_chords: bool | None = None
    #: The chords re-cut into short stabs, on the "other" part.
    stabs: bool | None = None
    #: Tidy the notes first: quantize to 1/16 and take out ghosts and stray leaps.
    tidy: bool | None = None
    #: Move the chords onto the bass's chords.
    follow_bass: bool | None = None
    #: Hold notes to the next one.
    legato: bool | None = None
    #: Pump everything on the kick; and keep pulsing where the beat drops out.
    pump: bool | None = None
    ghost_pump: bool | None = None
    parts: dict[str, PartRecipe] = Field(default_factory=dict)
    chops: Literal["none", "few", "some", "lots"] | None = None
    #: Cut chops into instruments (lead rises, gated stabs) rather than only the whole track.
    chop_instruments: bool | None = None
    arrangement: ArrangementRecipe = Field(default_factory=ArrangementRecipe)
    leave_out: list[str] = Field(default_factory=list)
    #: Play the parts on sounds sampled from the reference, where there are any.
    reference_sounds: bool | None = None
    #: Set the faders to the reference's balance after the version is made.
    reference_levels: bool | None = None


@dataclass
class Reading:
    recipe: Recipe
    understood: list[str] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)
    reader: str = "vocabulary"

    def to_dict(self) -> dict:
        return {"recipe": self.recipe.model_dump(exclude_none=True), "understood": self.understood,
                "unused": self.unused, "reader": self.reader}


@dataclass
class Context:
    """What the reader may refer to: the song's section labels, the styles, the kits."""

    labels: list[str] = field(default_factory=list)
    styles: list[str] = field(default_factory=list)
    kits: list[str] = field(default_factory=list)


class Reader(Protocol):
    name: str

    def available(self) -> bool: ...

    def read(self, prompt: str, context: Context) -> Reading: ...


# --- the vocabulary ---------------------------------------------------------------------------

STOP = {
    "a", "also", "an", "and", "are", "as", "be", "bit", "but", "feel", "feeling", "for", "give",
    "i", "i'm", "im", "in", "into", "is", "it", "it's", "its", "just", "keep", "less", "like",
    "little", "lot", "lots", "make", "me", "more", "my", "of", "on", "or", "please", "really",
    "so", "some", "sound", "sounds", "than", "that", "the", "then", "this", "to", "too", "very",
    "want", "was", "with"
}

#: Genre words -> (style, what else they set).
GENRES = {
    "complextro": ("EDM", {"beat": "techno", "lead_over_chords": True, "stabs": True,
                           "chops": "some", "chop_instruments": True, "pump": True,
                           "ghost_pump": True, "tidy": True, "follow_bass": True,
                           "legato": True}),
    "electro": ("EDM", {"beat": "house", "lead_over_chords": True, "pump": True, "tidy": True,
                        "follow_bass": True}),
    "madeon": ("EDM", {"chops": "some", "chop_instruments": True, "stabs": True,
                       "lead_over_chords": True}),
    "edm": ("EDM", {}), "house": ("House", {}), "trance": ("Trance", {}),
    "dnb": ("Drum and bass", {}), "drum and bass": ("Drum and bass", {}),
    "half-time": ("Half-time", {}), "half time": ("Half-time", {}),
    "future bass": ("Half-time", {}), "trap": ("Half-time", {}),
    "hard dance": ("Hard dance", {}), "synthwave": ("Synthwave", {}),
}


def _part_of(text: str) -> list[str]:
    found = []
    for word, part in (("bass", "bass"), ("guitar", "guitar"), ("keys", "piano"),
                       ("piano", "piano"), ("lead", "piano"), ("stab", "other"),
                       ("strings", "other"), ("vocal", "vocals"), ("synth", "guitar")):
        if word in text:
            found.append(part)
    return found


class VocabularyReader:
    """Reads a prompt with a fixed vocabulary. Free, offline and deterministic."""

    name = "vocabulary"

    def available(self) -> bool:
        return True

    def read(self, prompt: str, context: Context) -> Reading:
        # Commas and other clause breaks become " , " so "subdued, drop into the chorus" does
        # not read as "subdued ... chorus".
        clean = re.sub(r"[,;:!?\n]+", " , ", prompt.lower())
        clean = re.sub(r"[^a-z0-9.,\- ]+", " ", clean)
        # A full stop ends a sentence; it is only kept inside a number ("128.5 bpm").
        text = " " + re.sub(r"\.(?!\d)", " ", clean) + " "
        recipe = Recipe()
        said: list[str] = []
        used: set[str] = set()

        def use(*words: str) -> None:
            for w in words:
                used.update(w.split())

        def has(*phrases: str) -> str | None:
            found = [p for p in phrases if f" {p} " in text]
            for p in found:
                use(p)
            if found and ("kick" in text and any("kick" in p or p.startswith("punch")
                                                 for p in found)):
                use("kick")
            return found[0] if found else None

        # Genre first: it sets several controls at once, and later words override it.
        for word, (style, sets) in GENRES.items():
            if f" {word} " in text:
                use(word)
                recipe.style = recipe.style or style
                for k, v in sets.items():
                    setattr(recipe, k, v)
                said.append(f"{word}: the {style} style" + (
                    ", " + ", ".join(k.replace("_", " ") for k in sets) if sets else ""))
        for name in context.styles:
            if f" {name.lower()} " in text and recipe.style is None:
                recipe.style = name
                use(name.lower())
                said.append(f"the {name} style")

        bpm = re.search(r"\b(\d{2,3}(?:\.\d+)?)\s*bpm\b", text)
        if bpm:
            recipe.tempo = float(bpm.group(1))
            use(bpm.group(1), "bpm")
            said.append(f"{recipe.tempo:g} BPM")
        elif has("keep the tempo", "same tempo", "same speed", "own speed", "keep its speed",
                 "don't slow", "dont slow", "not slowed", "upbeat", "fast"):
            recipe.tempo = "keep"
            said.append("the song's own speed")

        if has("gritty", "grit", "distorted", "distortion", "dirty", "fuzzy", "crunchy"):
            if recipe.lead_over_chords:
                recipe.parts.setdefault("piano", PartRecipe()).grit = 0.65
            else:
                for p in ("guitar", "piano"):
                    recipe.parts.setdefault(p, PartRecipe()).grit = 0.45
            recipe.parts.setdefault("bass", PartRecipe()).grit = 0.5
            said.append("grit on the lead and bass")
        if has("clean chords", "clean synths", "less grit", "no grit", "not distorted"):
            # The held chords only: stabs keep their bite unless they are asked to lose it.
            if recipe.lead_over_chords:
                cleaned = ("guitar",) if recipe.stabs else ("guitar", "other")
            else:
                cleaned = ("guitar", "piano") if recipe.stabs else ("guitar", "piano", "other")
            for p in cleaned:
                recipe.parts.setdefault(p, PartRecipe()).grit = 0.0
            said.append("clean chords")
        if has("wide", "wider", "stereo", "spacious", "huge"):
            for p in ("guitar", "other"):
                recipe.parts.setdefault(p, PartRecipe()).width = 1.0
            recipe.parts.setdefault("bass", PartRecipe()).width = 0.35
            said.append("synths wide, the bass a little, low end centered")
        if has("punchy", "punchier", "hard-hitting", "tight kick", "less bass on the kick"):
            recipe.kit = "club punch tight" if "club punch tight" in context.kits else "punchy"
            said.append(f"the {recipe.kit} kit")
        if has("lead over chords", "lead over clean chords", "single-note lead", "lead line"):
            recipe.lead_over_chords = True
            said.append("a single-note lead over the chords")
        if has("stabs", "stab", "chopped chords"):
            recipe.stabs = True
            said.append("chords cut into stabs")
        if has("pulsing", "pulsate", "pump", "pumping", "sidechain", "side chain",
               "side chained", "breathing"):
            recipe.pump = True
            recipe.ghost_pump = True
            for p in ("guitar", "other"):
                recipe.parts.setdefault(p, PartRecipe()).pump_db = 14.0
            recipe.parts.setdefault("piano", PartRecipe()).pump_db = 10.0
            recipe.parts.setdefault("bass", PartRecipe()).pump_db = 11.0
            recipe.parts.setdefault("vocals", PartRecipe()).pump_db = 4.0
            said.append("a deep pump on the synths, light on the vocal, on through breakdowns")
        if has("legato", "held", "sustained", "smooth", "less choppy"):
            recipe.legato = True
            said.append("notes held to the next")
        if has("follow the bass", "no clashing", "in key", "consonant"):
            recipe.follow_bass = True
            said.append("chords on the bass's chords")
        if has("tidy", "trim", "clean up", "quantize", "quantise", "tighter midi",
               "midi feels off", "notes feel off", "sloppy"):
            recipe.tidy = True
            said.append("notes tidied and on the grid")

        if has("no chops", "without chops"):
            recipe.chops = "none"
        elif has("lots of chops", "lots of stutters", "glitchy", "glitch", "heavy chops"):
            recipe.chops = "lots"
        elif has("few chops", "subtle chops", "a few stutters"):
            recipe.chops = "few"
        elif has("chops", "chop", "stutters", "stutter", "glitches"):
            recipe.chops = recipe.chops or "some"
        if recipe.chops and recipe.chops != "none":
            if has("on the instruments", "instrument chops", "on instruments"):
                recipe.chop_instruments = True
            amount = {"few": "a few", "some": "some", "lots": "lots of"}[recipe.chops]
            said.append(f"{amount} chops" + (
                ", on the instruments" if recipe.chop_instruments else ""))

        # The arrangement, by the song's own part names.
        labels = sorted({lab.lower() for lab in context.labels}, key=len, reverse=True)
        if has("no verses", "skip the verses", "without the verses", "no verse", "chorus only",
               "only the chorus", "choruses only"):
            recipe.arrangement.skip.append("verse")
            said.append("no verses")
        # Whole labels only: "chorus" is not the "chorus" in "post-chorus". Longest first, and
        # a label once read is blanked out, so a shorter one cannot match inside it.
        work = text
        for lab in labels:
            word = rf"(?<![a-z-]){re.escape(lab)}(?![a-z-])"
            quiet = "(subdued|quiet|quieter|soft|softer|stripped|breakdown)"
            pattern = rf"{quiet}[a-z ]{{0,20}}{word}|{word}[a-z ]{{0,20}}{quiet}"
            if re.search(pattern, work):
                recipe.arrangement.subdued.append(lab)
                use(lab, "subdued", "quiet", "quieter", "soft", "softer", "stripped",
                    "breakdown")
                said.append(f"the {lab} without the beat")
            if re.search(rf"drop (at|into|on) (the )?{word}", work):
                recipe.arrangement.drop_at = lab
                use("drop", "at", "into", lab)
                said.append(f"a build and drop into the {lab}")
            work = re.sub(word, " ", work)

        if has("instrumental", "no vocals", "without vocals"):
            recipe.leave_out.append("vocals")
            said.append("no vocals")
        if has("their synth", "their sounds", "sampled", "sample the reference",
               "reference sounds", "like the reference sound"):
            recipe.reference_sounds = True
            said.append("sounds sampled from the reference")
        if has("reference levels", "levels like the reference", "like the reference",
               "match the reference", "mixed like", "levels of the reference"):
            recipe.reference_levels = True
            said.append("the reference's levels")

        if recipe.stabs and recipe.parts.setdefault("other", PartRecipe()).grit is None:
            recipe.parts["other"].grit = 0.5
            said.append("grit on the stabs")
        words = [w for w in text.split() if w not in STOP and w not in used and len(w) > 2]
        return Reading(recipe=recipe, understood=said, unused=sorted(set(words)))


# --- Claude, when it is switched on --------------------------------------------------------------

#: The default model for reading prompts: small and fast - this is a form being filled in.
CLAUDE_MODEL = "claude-haiku-5-5"


class ClaudeReader:
    """The same recipe, read by Claude. Off unless `PROMPT_READER=claude` and a key are set.

    Claude is given the recipe's JSON schema and the song's context and must answer with a
    recipe and nothing else; the answer is validated as a `Recipe` before anything uses it,
    so the most it can do is choose controls that already exist."""

    name = "claude"

    def __init__(self, api_key: str, model: str = CLAUDE_MODEL, client=None) -> None:
        self.api_key = api_key
        self.model = model
        self._client = client

    def available(self) -> bool:
        return bool(self.api_key)

    def _messages(self):
        if self._client is None:
            import anthropic  # an optional dependency: only needed when this reader is on

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client.messages

    def read(self, prompt: str, context: Context) -> Reading:
        system = (
            "You turn a request for a remix into a JSON recipe for a remixing app. Answer with "
            "one JSON object matching this schema and nothing else - no prose, no code fences. "
            "Leave out any field the request does not ask for. Use only the section labels, "
            "styles and kits listed.\n"
            f"Schema: {json.dumps(Recipe.model_json_schema())}\n"
            f"Section labels: {context.labels}\nStyles: {context.styles}\nKits: {context.kits}\n"
            'Also include "understood": a list of short phrases saying what you set.')
        reply = self._messages().create(
            model=self.model, max_tokens=1024, system=system,
            messages=[{"role": "user", "content": prompt}])
        raw = "".join(getattr(b, "text", "") for b in reply.content).strip()
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        understood = [str(s) for s in data.pop("understood", [])][:20]
        return Reading(recipe=Recipe.model_validate(data), understood=understood, unused=[],
                       reader=self.name)


def reader_for(settings) -> Reader:
    """The configured reader - Claude only when it is asked for and has a key."""
    if getattr(settings, "prompt_reader", "vocabulary") == "claude":
        reader = ClaudeReader(getattr(settings, "anthropic_api_key", "") or "",
                              getattr(settings, "prompt_model", "") or CLAUDE_MODEL)
        if reader.available():
            return reader
    return VocabularyReader()
