# Sprint 5 — rearrange the song

Opened 2026-10-12 from Ryan, after Sprint 4:

> That's a great start but ultimately I'd like the remix to allow for more manipulation

Asked which kind first - editing notes and beats, rearranging the song, mixing each part, or
shaping the sounds - he chose **rearrange the song**. The other three stay open, in that
order of likely value, and are listed at the end.

---

## What was built — X0R-1350

| | |
|---|---|
| **Sections** | `GET /tracks/{id}/sections`. Four-bar phrases on the song's own grid, grouped by how they sound (A, B, C…), runs merged into sections, named by guess. `synth/arrange.py`. |
| **Preview** | `GET /tracks/{id}/sections/{id}/preview` - hear a section of the original before placing it. |
| **Arrangement** | `BounceRequest.arrangement`: a list of `{section, mute, drop}`. Any order, repeats, omissions; per-block mutes of any part or the added beat; a build and drop into any block, as many as wanted. |
| **Editor** | An *Arrangement* panel: the song's sections with ▶ and + add; the running order with move, repeat, remove, mute chips and a drop box per block; presets *As written*, *Start on the chorus*, *Club mix*; length in bars and time at the version's tempo. |
| **MIDI** | The MIDI export follows the same cuts - notes copied per repeat, left out of muted blocks, cut at block ends. |

### The line this keeps

Arrangement moves *sections*; nothing inside a section moves. Editing notes and beats -
re-sequencing - is still the user's DAW's job, and the first of the open options below.

---

## Measured

* **The demo's sections**: verse bars 1-4, chorus bars 5-8 - where they were written. A
  one-loop house track is one section.
* **A cut keeps the grid.** An arranged trap version - beat-only intro, verse, chorus with a
  drop, breakdown, chorus with a drop - is exactly 20 bars plus the ring-out, its drops on
  bars 9 and 17, and the file reads back at 139.99 BPM across all four cuts.
* **Club mix** from the page on the pop punk demo: 6 blocks, 24 bars, 45.5 s at 128, drops
  on bars 9 and 17.

### Found while building it

* **A repeated section carried the song's ring-out with it.** The last section ran to the end
  of the file, so every copy of the chorus put half a second of ring-out into the middle of
  the song - 20.85 bars where 20 were asked for, and the second drop on bar 18 instead of 17.
  Sections now end on their last bar line; the ring-out is added once, at the end.
* **A relative grouping threshold failed both ways.** 0.4 of the largest phrase distance let
  a near-silent scrap after the last bar dominate, merging the demo's verse and chorus; and
  on a song where everything sounds alike it would split anyway. Now an absolute 1.2 - set on
  synthetic songs only (identical phrases 0, the demo's verse and chorus 1.72), said so in
  the code.
* **Loudest-is-chorus tied** on the demo; ties within half a dB go to the later group.

---

## Still open, in order

1. **Edit notes and beats** - a step grid for the added beat; move, delete and quantise the
   re-played notes. This reopens re-sequencing, which needs Ryan's yes.
2. **Mix each part** - level, pan, mute/solo and a filter/reverb/delay per part, live.
3. **Shape the sounds** - knobs on each synth and kit.
