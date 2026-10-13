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
