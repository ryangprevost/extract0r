"""A groove: which sixteenths a beat plays, how hard, and how far off the grid. Sprint 4.

Ryan, after hearing the first remix: work on *"overall groove and feel when remixing. Maybe
come up with applying elements of the reference remix track to the source and allowing it to
extract the essential elements."*

The essential elements of a beat, as a producer would name them, are three, and this module
holds exactly those:

* **The pattern** - which of the sixteen steps in a bar each drum plays. A house beat is a
  kick on every beat and an open hat between; a breakbeat is a kick on one and the "and" of
  three. Stored per step as how *often* it plays there, so a ghost note that appears in one
  bar of four reads as 0.25 rather than vanishing or being promoted to a full hit.
* **The accents** - how hard each step is struck, relative to that drum's loudest.
* **The feel** - how far each step sits from the grid. Swing is the famous case, every
  second sixteenth pushed late; a laid-back snare a dozen milliseconds behind the beat is the
  other. This is the part a quantised MIDI pattern loses and the part people mean by "feel".

### What it is used for, and the line it does not cross

Read from a **reference**, a groove becomes a beat *added* to the remix - their pattern, their
accents, their feel, on a kit - exactly as the four-on-the-floor is added. Read from the
user's **own** drummer, it is a description: "your snare sits 11 ms behind the beat" is the
sort of sentence that makes somebody feel they understand their own record.

What it does not do is move the drummer's hits onto somebody else's grid. That is
re-sequencing, still a non-goal, and the reason is the same as it was: a remix that keeps
the band's playing exactly where they played it is one the band still recognises. A user
who wants the reference's beat *instead of* their drummer's can leave the drums out of the
version - a mute, which is theirs to choose - and the account says that is what happened.

### What it cannot read

Swing is read on sixteenths only. An eighth-note swing at full triplet puts the offbeat
eighth two-thirds of a sixteenth late, which rounds to the *next* sixteenth and reads as a
straight hit there. That is a limit of reading onto a sixteenth grid, said here rather than
discovered by somebody whose shuffle came back straight.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from app.services.drums.detect import Hit
from app.services.drums.kit import KITS, render_voice

#: Sixteenths in a bar of 4/4. Everything here assumes 4/4, which is what dance music is.
STEPS = 16
KINDS = ("kick", "snare", "hihat")
#: Separated drum stems and the hit classifier both say "cymbals"; a beat calls it a hat.
ALIASES = {"cymbals": "hihat"}
#: A step plays in the added beat when it played in at least this share of bars.
PLAYS_FROM = 0.5
#: A sixteenth swung all the way to a triplet sits a third of a sixteenth late.
TRIPLET = 1.0 / 3.0
#: A stroke labelled kick *and* hat keeps the hat only when its top octave is within this
#: many dB of the hats that play alone. A kick's click lifts the top octave too, and on a
#: rendered four-on-the-floor every kick came back "hihat" - harmless for triggering a sample,
#: fatal for reading a pattern. The detector's own rises could not separate them (the same
#: kick read 15 dB and 69 dB a few bars apart, a running baseline), so this measures energy
#: above 7.5 kHz in the 25 ms after each stroke instead. Across three kits: kicks without a
#: hat sat 5-9 dB under the lone hats' median, kicks with one at or above it.
HAT_MARGIN_DB = 4.0
#: A stroke is a kick when its energy below 120 Hz, in the 30 ms after it, is within this
#: many dB of the loudest stroke's and rose at least `KICK_JUMP_DB` over the 30 ms before.
#: Needed because back-to-back dance kicks overlap: the detector measures each against a
#: running baseline that the last kick's tail is still holding up, and labelled some only
#: by their click - "hihat". Measured across three kits and three beats: kicks within 6.7 dB
#: of the loudest, every other stroke 12.8 dB or more below it.
KICK_WITHIN_DB = 4.5
KICK_JUMP_DB = 6.0
#: The same test for a snare, on its rattle band. See `confirm_snares`.
SNARE_WITHIN_DB = 6.0
SNARE_JUMP_DB = 6.0
#: At full humanize, how far a stroke may drift from where it was programmed (standard
#: deviation, seconds) and how much its level may vary. Small on purpose: a few ms is the
#: difference between a drum machine and a drummer; tens of ms is a drummer who is lost.
HUMANIZE_S = 0.006
HUMANIZE_LIMIT_S = 0.012
HUMANIZE_LEVEL = 0.18
#: Level of each drum in an added beat, before accents. Matches `four_on_the_floor`.
GAIN = {"kick": 0.95, "snare": 0.7, "hihat": 0.38}


@dataclass
class Step:
    #: Share of bars that had this drum on this step, 0..1.
    rate: float = 0.0
    #: Mean distance from the grid, in sixteenths (+ is late).
    offset: float = 0.0
    #: Mean strength relative to this drum's loudest, 0..1.
    velocity: float = 0.0


@dataclass
class Groove:
    name: str
    #: Where it came from, in the words the page uses: "your reference", "your drummer",
    #: "built in".
    source: str
    steps: dict[str, list[Step]] = field(default_factory=dict)
    #: How many bars it was read from. Zero for a built-in.
    bars: int = 0
    #: The tempo it was read at, for converting offsets to milliseconds. Zero for a built-in.
    bpm: float = 0.0

    def plays(self, kind: str, threshold: float = PLAYS_FROM) -> list[int]:
        return [i for i, s in enumerate(self.steps.get(kind, [])) if s.rate >= threshold]

    @property
    def swing(self) -> float:
        """0 for straight sixteenths, 1 for full triplet swing. Read off the hats, which is
        where swing lives, falling back to every drum when there are no hats."""
        for kinds in (("hihat",), KINDS):
            late = [
                s.offset
                for kind in kinds
                for i, s in enumerate(self.steps.get(kind, []))
                if i % 2 == 1 and s.rate >= 0.25
            ]
            if late:
                return float(np.clip(np.mean(late) / TRIPLET, 0.0, 1.0))
        return 0.0

    @property
    def swing_percent(self) -> int:
        """Swing the way a drum machine shows it: 50% straight, 67% a triplet."""
        return int(round(50 + 50 * TRIPLET * self.swing))

    def push_ms(self, kind: str) -> float | None:
        """How far ahead (-) or behind (+) the beat this drum sits on the steps it plays
        most, in ms. None for a built-in or a drum that never plays."""
        if not self.bpm:
            return None
        playing = [(i, s) for i, s in enumerate(self.steps.get(kind, []))
                   if s.rate >= PLAYS_FROM]
        # The on-sixteenths, so swing on the off ones is not counted as pushing or dragging.
        chosen = [s for i, s in playing if i % 2 == 0] or [s for _, s in playing]
        if not chosen:
            return None
        sixteenth_ms = 60_000.0 / self.bpm / 4
        return float(np.mean([s.offset for s in chosen]) * sixteenth_ms)

    def grid(self, threshold: float = PLAYS_FROM) -> dict[str, str]:
        """The pattern as a drum machine would show it: x plays, o is a ghost, . is rest."""
        out = {}
        for kind in KINDS:
            row = ""
            for s in self.steps.get(kind, [Step()] * STEPS):
                row += "x" if s.rate >= threshold else ("o" if s.rate >= 0.2 else ".")
            out[kind] = row
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Groove:
        steps = {k: [Step(**s) for s in v] for k, v in data.get("steps", {}).items()}
        return cls(name=data["name"], source=data["source"], steps=steps,
                   bars=data.get("bars", 0), bpm=data.get("bpm", 0.0))


# --- reading one -------------------------------------------------------------------------


def extract(hits: list[Hit], beats: np.ndarray, name: str = "groove",
            source: str = "your reference", bpm: float = 0.0) -> Groove:
    """Read a groove off a list of strokes and the beat grid they were played against.

    Positions come from interpolating along the beats rather than dividing by one tempo, so
    a live drummer drifting a little is measured against where *their* beats were. The bar
    is taken to start on the grid's first beat - the same assumption the drop makes, with
    the same fix when it is wrong.
    """
    beats = np.asarray(beats, dtype=np.float64)
    bars = (len(beats) - 1) // 4
    groove = Groove(name=name, source=source, bars=bars, bpm=bpm,
                    steps={k: [Step() for _ in range(STEPS)] for k in KINDS})
    if bars < 1:
        return groove

    seen: dict[str, dict[int, list[tuple[int, float, float]]]] = {k: {} for k in KINDS}
    for hit in hits:
        if hit.time_s < beats[0] - 0.05 or hit.time_s >= beats[bars * 4]:
            continue
        position = float(np.interp(hit.time_s, beats, np.arange(len(beats)))) * 4
        nearest = int(round(position))
        bar, step = divmod(nearest, STEPS)
        if bar >= bars:
            continue
        for kind in {ALIASES.get(k, k) for k in hit.kinds}:
            if kind in seen:
                seen[kind].setdefault(step, []).append((bar, position - nearest, hit.strength))

    for kind, by_step in seen.items():
        loudest = max((v for hits_at in by_step.values() for _, _, v in hits_at), default=0.0)
        for step, found in by_step.items():
            groove.steps[kind][step] = Step(
                rate=round(min(1.0, len({b for b, _, _ in found}) / bars), 3),
                offset=round(float(np.mean([o for _, o, _ in found])), 4),
                velocity=round(float(np.mean([v for _, _, v in found]) / loudest), 3)
                if loudest > 0 else 0.0,
            )
    return groove


def confirm_hats(hits: list[Hit], audio: np.ndarray, sample_rate: int) -> list[Hit]:
    """Drop the hat from strokes whose "hat" is a kick's or snare's click. See
    `HAT_MARGIN_DB`. Strokes that are only a hat are the yardstick and are never touched."""
    from scipy.signal import butter, sosfilt

    mono = audio.mean(axis=1) if audio.ndim > 1 else np.asarray(audio, dtype=np.float64)
    top = sosfilt(butter(4, 7500.0 / (sample_rate / 2), "highpass", output="sos"), mono)
    width = int(0.025 * sample_rate)

    def level(hit: Hit) -> float:
        at = max(0, int(hit.time_s * sample_rate))
        return 10 * np.log10(np.mean(top[at: at + width] ** 2) + 1e-12)

    def labels(hit: Hit) -> set[str]:
        return {ALIASES.get(k, k) for k in hit.kinds}

    alone = [level(h) for h in hits if labels(h) == {"hihat"}]
    if not alone:
        return hits
    floor = float(np.median(alone)) - HAT_MARGIN_DB
    out = []
    for hit in hits:
        kinds = labels(hit)
        if "hihat" in kinds and kinds != {"hihat"} and level(hit) < floor:
            kept = [k for k in hit.kinds if ALIASES.get(k, k) != "hihat"]
            hit = Hit(time_s=hit.time_s, kinds=kept, strength=hit.strength,
                      rises=dict(hit.rises))
        out.append(hit)
    return out


def _band_levels(hits: list[Hit], audio: np.ndarray, sample_rate: int,
                 sos: np.ndarray) -> list[tuple[float, float]]:
    """(level, rise) in one band for each stroke: dB in the 30 ms after it, and how far
    that is above the 30 ms before."""
    from scipy.signal import sosfilt

    mono = audio.mean(axis=1) if audio.ndim > 1 else np.asarray(audio, dtype=np.float64)
    band = sosfilt(sos, mono)
    width, gap = int(0.03 * sample_rate), int(0.003 * sample_rate)
    out = []
    for hit in hits:
        at = max(0, int(hit.time_s * sample_rate))
        after = np.mean(band[at: at + width] ** 2) + 1e-12
        before = np.mean(band[max(0, at - width): max(1, at - gap)] ** 2) + 1e-12
        out.append((10 * np.log10(after), 10 * np.log10(after / before)))
    return out


def _confirm(hits: list[Hit], measured: list[tuple[float, float]], kind: str,
             within_db: float, rise_db: float) -> list[Hit]:
    """Add `kind` to strokes whose band is near the loudest stroke's and jumped. Only adds."""
    if not measured:
        return hits
    loudest = max(level for level, _ in measured)
    out = []
    for hit, (level, rise) in zip(hits, measured, strict=True):
        if kind not in hit.kinds and level >= loudest - within_db and rise >= rise_db:
            hit = Hit(time_s=hit.time_s, kinds=[*hit.kinds, kind], strength=hit.strength,
                      rises=dict(hit.rises))
        out.append(hit)
    return out


def confirm_kicks(hits: list[Hit], audio: np.ndarray, sample_rate: int) -> list[Hit]:
    """Add the kick to strokes the detector heard only the click of. See `KICK_WITHIN_DB`."""
    from scipy.signal import butter

    sos = butter(4, 120.0 / (sample_rate / 2), output="sos")
    return _confirm(hits, _band_levels(hits, audio, sample_rate, sos), "kick",
                    KICK_WITHIN_DB, KICK_JUMP_DB)


def confirm_snares(hits: list[Hit], audio: np.ndarray, sample_rate: int) -> list[Hit]:
    """Add the snare to strokes where a hat struck at the same instant hid it.

    The classifier calls a stroke a snare only when its rattle band out-jumps the hat band,
    which is right for telling a snare from a hat and wrong when both are struck at once -
    the pop punk backbeat, a hat on every eighth including 2 and 4. On the demo's separated
    drums that read the snare in one bar of eight. Measured there: the snare strokes' rattle
    (1.5-4.5 kHz) sat within 1.6 dB of the loudest stroke's, every other stroke 18 dB or more
    below it.
    """
    from scipy.signal import butter

    nyquist = sample_rate / 2
    sos = butter(4, [1500.0 / nyquist, 4500.0 / nyquist], "bandpass", output="sos")
    return _confirm(hits, _band_levels(hits, audio, sample_rate, sos), "snare",
                    SNARE_WITHIN_DB, SNARE_JUMP_DB)


def read_hits(drums: np.ndarray, sample_rate: int) -> list[Hit]:
    """Every stroke in a drums stem, placed where it starts, with each label checked
    against the audio: kicks the detector heard only the click of, snares a hat hid, and
    hats that were a kick's click."""
    from app.services.drums.detect import find_hits
    from app.services.synth.retempo import refine_hit_times

    mono = drums.mean(axis=1) if drums.ndim > 1 else drums
    hits = refine_hit_times(drums, sample_rate, find_hits(mono, sample_rate))
    hits = confirm_kicks(hits, drums, sample_rate)
    hits = confirm_snares(hits, drums, sample_rate)
    return confirm_hats(hits, drums, sample_rate)


def from_audio(drums: np.ndarray, sample_rate: int, beats: np.ndarray, name: str,
               source: str, bpm: float) -> Groove:
    """Read a groove off a drums stem."""
    return extract(read_hits(drums, sample_rate), beats, name, source, bpm)


def describe(groove: Groove) -> list[str]:
    """What a groove is, in sentences. The page's explanation of a beat."""
    lines = []
    swing = groove.swing_percent
    if swing >= 54:
        lines.append(f"Swung at {swing}% - every second sixteenth is pushed late, which is "
                     f"what makes it bounce rather than march.")
    else:
        lines.append("Straight sixteenths - no swing, so it drives rather than bounces.")
    for kind, word in (("kick", "kick"), ("snare", "snare"), ("hihat", "hats")):
        ms = groove.push_ms(kind)
        if ms is None or abs(ms) < 4:
            continue
        where = "behind" if ms > 0 else "ahead of"
        mood = "laid back" if ms > 0 else "pushing"
        lines.append(f"The {word} sit{'s' if word != 'hats' else ''} {abs(ms):.0f} ms {where} "
                     f"the beat - {mood}.")
    # A ghost under a full hit on another drum cannot be heard - and on separated drums is
    # usually the classifier hearing the kick's harmonics as a snare - so it is not counted.
    full = {i for k in KINDS for i in groove.plays(k)}
    ghosts = sum(1 for k in KINDS for i, s in enumerate(groove.steps.get(k, []))
                 if 0.2 <= s.rate < PLAYS_FROM and i not in full)
    if ghosts:
        lines.append(f"{ghosts} ghost note{'s' if ghosts != 1 else ''} - hits that come and go "
                     f"between bars and keep it from sounding programmed.")
    return lines


# --- built in ----------------------------------------------------------------------------


def _pattern(name: str, rows: dict[str, str], accents: dict[str, str] | None = None) -> Groove:
    """A groove written the way a drum machine shows one: "x...x...x...x..." per drum.
    Accents, optionally, as digits 1-9 per step for velocity."""
    steps = {}
    for kind in KINDS:
        row = rows.get(kind, "." * STEPS)
        accent = (accents or {}).get(kind, "")
        steps[kind] = [
            Step(rate=1.0 if ch == "x" else (0.3 if ch == "o" else 0.0), offset=0.0,
                 velocity=(int(accent[i]) / 9 if i < len(accent) and accent[i].isdigit()
                           else (0.55 if ch == "o" else 1.0)))
            for i, ch in enumerate(row)
        ]
    return Groove(name=name, source="built in", steps=steps)


#: Built-in beats, named by what a listener would call them. Each is the textbook version -
#: the starting point a producer would program before making it their own.
BUILT_IN: dict[str, Groove] = {
    "four on the floor": _pattern("four on the floor", {
        "kick":  "x...x...x...x...",
        "hihat": "..x...x...x...x.",
    }),
    "house": _pattern("house", {
        "kick":  "x...x...x...x...",
        "snare": "....x.......x...",
        "hihat": "o.x.o.x.o.x.o.x.",
    }, {"hihat": "5.9.5.9.5.9.5.9."}),
    "techno": _pattern("techno", {
        "kick":  "x...x...x...x...",
        "snare": "....x.......x...",
        "hihat": "xxxxxxxxxxxxxxxx",
    }, {"hihat": "4848484848484848"}),
    "breakbeat": _pattern("breakbeat", {
        "kick":  "x.........x.....",
        "snare": "....x.......x...",
        "hihat": "x.x.x.x.x.x.x.x.",
    }),
    "drum and bass": _pattern("drum and bass", {
        "kick":  "x.........x.....",
        "snare": "....x.......x..o",
        "hihat": "x.x.x.x.x.x.x.x.",
    }),
    "trap": _pattern("trap", {
        "kick":  "x......x..x.....",
        "snare": "........x.......",
        "hihat": "x.x.x.x.x.xxx.x.",
    }, {"hihat": "7.5.7.5.7.579.5."}),
}


# --- playing one -------------------------------------------------------------------------


def events(groove: Groove, beats: np.ndarray, rest: tuple[float, float] | None = None,
           swing: float | None = None, feel: bool = True,
           threshold: float = PLAYS_FROM,
           humanize: float = 0.0) -> list[tuple[float, str, float]]:
    """Every stroke of the groove along `beats`, as (time, drum, velocity 0..1), in order.

    One place that decides where an added beat's strokes fall, shared by the audio render and
    the MIDI export, so the file a DAW opens is the beat that was heard.

    `feel` keeps each step's measured distance from the grid; off, it is quantised. `swing`
    overrides the feel on the off-sixteenths with a set amount, 0..1, which is the one knob
    everybody reaches for. `rest` is a span with nothing in it - a build before a drop.

    `humanize`, 0..1, nudges every stroke a few milliseconds and varies its level - the
    difference between a programmed beat and a played one. Seeded, so the same settings
    give the same beat twice: a remix that changed every time it was bounced would be
    impossible to judge.
    """
    beats = np.asarray(beats, dtype=np.float64)
    if beats.size < 2:
        return []
    rng = np.random.default_rng(1340)
    period = float(np.median(np.diff(beats)))
    grid = np.append(beats, beats[-1] + period * np.arange(1, 5))
    out = []
    for bar_start in range(0, beats.size, 4):
        for kind in KINDS:
            for step in groove.plays(kind, threshold):
                s = groove.steps[kind][step]
                beat = bar_start + step // 4
                if beat >= beats.size:
                    continue
                sixteenth = (grid[beat + 1] - grid[beat]) / 4
                shift = s.offset if feel else 0.0
                if swing is not None and step % 2 == 1:
                    shift = swing * TRIPLET
                t = float(grid[beat] + ((step % 4) + shift) * sixteenth)
                if rest is not None and rest[0] - 1e-3 <= t < rest[1] - 1e-3:
                    continue
                # A step played a little ahead of the song's very first beat lands before
                # zero. It is still the downbeat - dropping it lost the first kick.
                velocity = max(0.15, s.velocity)
                if humanize > 0:
                    drift = float(np.clip(rng.normal(0.0, HUMANIZE_S * humanize),
                                          -HUMANIZE_LIMIT_S, HUMANIZE_LIMIT_S))
                    t += drift
                    velocity = float(np.clip(
                        velocity * (1 + rng.uniform(-1, 1) * HUMANIZE_LEVEL * humanize), 0.1, 1.0))
                if t < 0:
                    if t < -sixteenth / 2:
                        continue
                    t = 0.0
                out.append((t, kind, velocity))
    return sorted(out)


def render(groove: Groove, beats: np.ndarray, sample_rate: int, length: int,
           kit: str = "edm", rest: tuple[float, float] | None = None,
           swing: float | None = None, feel: bool = True,
           threshold: float = PLAYS_FROM,
           sounds: dict[str, np.ndarray] | None = None,
           humanize: float = 0.0) -> np.ndarray:
    """The groove as stereo audio on a kit, bar after bar along `beats`. See `events`.
    `sounds` is a kit already loaded - the library's, possibly the user's own hits."""
    out = np.zeros((length, 2))
    if sounds is None:
        voices = KITS.get(kit) or KITS["edm"]
        sounds = {k: render_voice(voices[k], sample_rate, seed=20 + i)
                  for i, k in enumerate(KINDS) if k in voices}
    for t, kind, velocity in events(groove, beats, rest, swing, feel, threshold, humanize):
        sound = sounds.get(kind)
        at = int(round(t * sample_rate))
        if sound is None or at >= length:
            continue
        end = min(length, at + sound.size)
        out[at:end] += (sound[: end - at] * GAIN[kind] * velocity)[:, None]
    return out
