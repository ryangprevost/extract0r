# Sprint 17 — punch and width

Opened 2026-10-13 from Ryan, on the gritty remix:

> much better! can you redo it with a punchier kick and some stereo wideness? also make the
> snare more punchy and direct. it's getting there for sure

---

## 1. Width — X0R-1471

The sampled and multisampled synths render in **mono**, so every synth sat in the middle, on
top of the vocal and the kick. `synth/width.py` spreads a part the way a stereo synth patch
does:

- **The side signal.** The part's mono sum stays the middle. Two copies of it go through
  short delays (8 and 11 ms) that drift slowly (0.31 and 0.37 Hz, 1 ms deep), and their
  difference is added left and subtracted right.
- **Mono-safe.** Summed to mono it is exactly the part as it was (error 1e-16), so a club's
  mono system never hears the comb filtering a plain Haas delay leaves.
- **Low end centered.** The side is high-passed at 150 Hz; at 55 Hz it sits 29 dB under its
  level at 220 Hz.

`BounceRequest.width` takes `{stem: 0..1}` and is applied after grit (a distorted synth is
spread, rather than a spread one distorted). The account says so, there is a width slider
on every part row, and it is tested in `test_width.py`.

On the remix: synths at 75–85% width moved the whole mix's side from -16.7 to -9.8 dB against
the middle, and its left/right correlation from 0.96 to 0.81.

## 2. Punch — a shaped kit, measured

The punch was measured as the share of each hit's energy in its first 30 ms, plus how long
it takes to fall 20 dB:

| drum | edm kit (before) | punchy kit | **club punch** |
|---|---|---|---|
| kick, front | 23% | 43% | **40%** |
| kick, to -20 dB | 475 ms | 232 ms | **254 ms**, 98% of it in 30–100 Hz |
| snare, front | 16% | 90% | **90%** |
| snare, to -20 dB | 161 ms | 61 ms | **61 ms** |

**club punch** is the punchy kit with the kick's punch, snap and length up and its tune
lowered a little, saved through the ordinary shaped-sound route. It sits in every kit list.
The pump went from 8 to 10 dB, so the synths clear out of the kick's way.

## 3. The finish

A clean limiter could not make the punchier mix loud. Reaching -10.6 LUFS took up to 12.5 dB
of gain riding on the kicks, which flattens exactly the punch that was asked for. Club
masters put a **soft clipper** before the limiter instead: it shaves only the tips of the
transients. That is 0.3% of samples clipped by more than 3.5 dB, and the limiter then
averages 0.2 dB. Both cuts finish at -10.6/-10.7 LUFS with the true peak at -1 dBTP. This
finish is a one-off script for the remix, not yet a feature of the app.

## 4. Then: less boom, wider, legato — X0R-1472

Ryan, on the punchy remix:

> getting there. a little less bass on the kick and more stereo width. feel free to drag out
> the individual notes to have it more side chained and less choppy.

- **Kick.** The new **club punch tight** kit is the same punchy base with the kick shorter and
  slightly higher. Against club punch, its sub is about 5 dB lower relative to its punch, its
  tail falls to -20 dB in 175 ms instead of 254, and 53% of its energy is in the first 30 ms.
- **Width.** Synths at 100%, and the bass at 35% (its sub stays centered by the 150 Hz
  high-pass). The mix's side rose from -8.4 to -5.4 dB against the middle, and left/right
  correlation fell from 0.75 to 0.55. Mono still sums exactly.
- **Legato.** `edit.legato` holds every note towards the next onset in its part. Chords move
  together; a note is never shortened, and never held past two bars. It is available as
  `legato` on `POST /tracks/notes/quantize` and as a **Legato** button in the piano roll.
  Because it is an edit, saved through the note editor, the version's account says the parts
  play your notes rather than the band's.
  - On VaVaVa, average note length went from 0.68 to 1.94 beats on the guitars, 0.63 to 1.86
    on other, and 0.65 to 4.11 on the keys.
  - The pump went from 10 to 11 dB, so the held synths breathe around every kick.

## 5. A wall that pulses — X0R-1473

Ryan, on the legato remix:

> there were some overtones and held out notes that just conflicted with the overall vibe.
> can you side chain them as well? i want it like a wall of pulsating distorted synth

**Why it clashed.** It was not the key: 98–100% of every part's notes were in D major. Each
part's transcription picked its own extra chord tones (overtones read as sevenths and
ninths), and legato held them across the bass's chord changes.

**Follow the bass** (`edit.follow_bass`, `POST /tracks/{id}/parts/{stem}/follow-bass`, and a
piano-roll button):

- Every note moves to the nearest tone of the triad on the bass note under it. The triad is
  built in the song's scale, which is found from the notes.
- Each chord's duplicates go, and at most four notes sound together.
- Legato can hold notes, but only until the next note *or* the bass's next change.
- On VaVaVa it moved or merged 69 guitar notes, 47 keys notes and 108 notes of "other".

**The pump, per part and through the rests:**

- `pump_parts` gives each part its own depth. Here the synths are at 14 dB, the bass at
  11 dB and the vocal at 4 dB.
- `ghost_pump` keeps the pulse on every beat where the arrangement mutes the beat, but not
  through a build.
- The account names each depth.
- Measured per beat, the mix now pulses 9.8 dB in the beat-free teaser (it was 1.6) and
  15.6 dB in the chorus (it was 10.4).

## 6. Matched levels, a gritty lead over clean chords, trimmed notes — X0R-1474

Ryan, over three rounds:

> it does NOT sound like the levels of the mstrkrft refernce track

> it sounds like grinding metal lol ... kill some of the overhead single held out note that's
> high pitched

> try the gritty single-note lead over clean chords. the midi feels a little off maybe trim
> some of the questionable notes

**Levels.** Measured each part against its bass, in "Bounce" and in the remix. The synths sat
14 dB over the bass where "Bounce" has them level with it; the drums were 8 dB and the vocal
6 dB louder than "Bounce"'s balance. Faders were set from the measurements, then the mix was
tonally matched to "Bounce" with the mastering engine's own `matching_curve`. With the
balance right, that curve needed only ±2 dB. Done by a script for now; a "match the
reference's levels" button on the version mixer is the obvious next card.

**The odd high notes.** The sampled "Bounce" synth had clean notes only at F#1, A#1, A#2 and
F5. Over 90% of the keys' and strings' held time came from a recording more than 5
semitones away, and a third of it from more than an octave away. Adding their clean F4
removed every stretch over an octave. The lone high notes (C5 and up: 26 on the strings,
including a G5 held for nearly 4 beats, and 9 on the keys) were taken out.

**Grinding metal was not brightness.** "Bounce" has *more* 2–8 kHz energy than the remix
(-9.6 dB of the total against -13.6). The grind is distortion on whole chords:
intermodulation, tones at the notes' sums and differences that belong to no chord. So now:

- the chords are clean;
- the grit goes on one line, `edit.top_line` (the top note of each chord, G3–B4), played on
  the sampled synth at 65% grit;
- the bass keeps its own grit.

**Trim** (`edit.trim`) takes out ghosts (short and well under the part's median velocity)
and lone leaps (a single note more than 7 semitones from both neighbors). Everything is also
quantized to 1/16: transcription timing was the "off" feel.

Both tools are available as `trim` and `top_line` on the quantize route, and as **Trim** and
**Top line** in the piano roll.

## 7. Complextro: chops and stabs — X0R-1476

Ryan:

> love that much more! great tone. please make it a little more complextro sounding with
> chops and stabs here and there to break up the beat and give it more drive and upbeat
> feeling

**Chops** (`synth/chop.py`, `BounceRequest.chops`):

- **stutter:** the window's first slice retriggered, in eighths, then sixteenths, then
  thirty-seconds.
- **gate:** sixteenths on and off.
- **stop:** silence between two 3 ms fades.

Every chop is linear (a re-read or a multiply), so it is cut the same into the mix and into
every layer, and the layers still sum to the version exactly (tested). The account lists
them by bar.

**Stabs** (`edit.stabs`, `stabs` on the quantize route): the chords that sound at each `x` of a
two-bar sixteenth pattern (`..x..x..x...x.x.` / `..x..x..x..x.xx.`), played short. The
harmony stays the chords'; only the rhythm is new.

**On VaVaVa:**

- **Stabs:** 488 of them, on the strings channel, on the sampled "Bounce" synth with 50% grit.
- **Beat:** the techno groove's sixteenth hats under the club punch tight kit.
- **Chops:** 14 at phrase ends - stutters, gates, and a stop before the bridge - none in the
  builds. Checked in the file:
  - the stop is digital silence;
  - the stutters repeat their slice (0.55 correlation against 0.15 for the music around them).

## 8. Chops and stabs on the page, chops on instruments — X0R-1477

Ryan:

> add the chops and stabs as controls on the page. love them by the way it's a nice touch.
> can you add chops to the instruments as well like stutters and whatnot. something like this
> youtube video at the time i copied

The video is Madeon's "Icarus". Its audio cannot be heard from here; going by what that
record is known for, the chops are cut into *instruments* - a lead retriggering and climbing
in pitch into the next phrase, a vocal chopped, stabs gated - while the beat carries on.

- **A chop on a part.** `Chop.parts` (empty is the whole track) is cut into that part inside
  the bounce, or into the added beat (`"beat"`). Whole-track chops are still cut into the
  mix and every layer.
- **Two new kinds:**
  - **rise:** a stutter in sixteenths, each repeat a semitone higher (tested: two repeats in,
    the pitch has climbed 2 semitones);
  - **tape:** a tape stop, speed falling from 1 to 0 across the window.
- **On the page:**
  - A **Chops** panel under the arrangement. Each row sets the bar, beat, length and kind,
    and whether the chop is on the whole track or one part.
  - **Suggest** fills in a gate, stutter or rise at every fourth bar and skips the two bars
    before a drop.
  - A **Stabs** button sits in the piano roll.

**On VaVaVa:**

- **The lead:** rises into phrase ends, plus stutters.
- **The stabs:** gated.
- **The vocal:** stutters and one rise (chorus cut).
- **The whole track:** a tape stop into the bridge, and a gate to close.

**Retention.** The local `.env` had `RETENTION_HOURS=24`, and the sweep deleted every track
older than a day, the demo track included. With Ryan's go-ahead it is now 168 (7 days,
git-ignored, local only), raised minutes before VaVaVa would have gone.
