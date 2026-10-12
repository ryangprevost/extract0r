# Sprint 6 — edit notes and beats

Opened 2026-10-12 from Ryan:

> yes, go ahead with editing notes and beats

This **reopens re-sequencing**, the non-goal every sprint before kept closed. It is opened the
way this application opens things: by the user, visibly. A part nobody edits is exactly as
played; a part somebody edits is named in the version's account - *"Edited by you, so these
play your notes rather than the band's: bass"* - and a beat written on the step grid is
*"your beat (from house) — not from your recording"*.

---

## What was built — X0R-1360

| | |
|---|---|
| **Notes in beats** | A part's notes are saved, when it is played, as beat positions from the song's first beat (`synth/edit.py`). Seconds are worked out only at render time - so an edit made at 128 is still right at 140. Through beats, an unedited part comes out identical to the old `move_notes` path; a test holds that. |
| **Your edits play** | With an edit saved, re-playing the part skips transcription and plays your notes (`"backend": "your edits"`); the MIDI export and bounce use them too. Saving notes identical to the played ones is not an edit. |
| **Piano roll** | *Edit notes* on any played part (*Edit strokes* for drums, on kick / snare / hat lanes): click to add, drag to move, drag the edge to lengthen, shift-click to select several, Delete, arrows to move and transpose, Ctrl+Z, zoom. Quantise to 1/4 … 1/16 triplet at 25-100% strength, optionally the ends too; *Quantise with swing* locks the off-sixteenths to the added beat's swing. *Save and play it*; *Back to as played*. |
| **Step editor** | *Edit the beat*: kick / snare / hat × 16 steps, click to cycle plays → soft → rests, starting from any built-in beat or the reference's. Steps the starting beat already played keep its feel (swing, push, accent); steps you add land on the grid. |
| **API** | `GET/PUT/DELETE /tracks/{id}/parts/{stem}/notes`, `POST /tracks/notes/quantize`, `BounceRequest.custom_beat`. |

---

## Found while building it

**The re-played drummer had been missing most of the backbeat.** Opening the demo's drums in
the stroke editor showed 76 hits where 104 were played. Re-struck drums still read strokes
with the bare detector, which found **3 of 16 snares** - a hat struck with the snare hides it
- and 13 of 24 kicks. Sprint 4 had already built the checks that fix this (`groove.read_hits`)
but only used them for reading grooves. Re-played drums now use them: **16 of 16 snares, 21 of
24 kicks.** Every "Make it EDM" version before this commit had a drummer with most of his
snares missing.

---

## Still open

1. **Mix each part** - level, pan, mute/solo and a filter/reverb/delay per part, live.
2. **Shape the sounds** - knobs on each synth and kit.
3. Editing velocity per note in the roll (it is kept and drawn as opacity, not yet editable),
   and a two-bar step grid for beats that do not repeat every bar.
