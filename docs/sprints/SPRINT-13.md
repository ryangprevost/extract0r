# Sprint 13 — mark the song's parts yourself

Opened 2026-10-12 from Ryan:

> go ahead with marking the song parts myself next

following his note from Sprint 12:

> also please let me determine the parts of the song instead of parsing them.

---

## 1. Why

The arrangement editor (Sprint 5) works on sections the app finds itself: four-bar phrases,
grouped by how they sound, with the loudest group called the chorus. That was tuned on
synthetic songs. On a real song it can split a verse in two, merge a pre-chorus into the
chorus, or give the wrong name. The person knows where the chorus starts, so now they can say so.

## 2. What it does — X0R-1442

**Mark the parts yourself** opens next to *The song's sections*:

- **Every bar of the song**, each as tall as it is loud and colored by the part it belongs to. A
  chorus usually stands taller, so you can see where the song lifts before you hear it.
- **Click a bar** to start a part there. It plays four bars from that point, so you can check the
  part starts where you hear it. A new part gets the name a song usually has next (after a verse
  comes a pre-chorus) and you can change it.
- **Each part has a row**: its bars, a play button, a name box, and quick names (intro, verse,
  pre-chorus, chorus, bridge, drop, breakdown, outro). Parts with the same name count as the same
  part, so the arrangement can reuse them.
- **Use these parts** saves them. **Start from the detected ones** copies the app's guess into the
  editor to correct, and **Go back to the detected ones** throws your marks away.

Once saved, your parts are used **everywhere sections are**: the arrangement lane, section
previews, bounces and the MIDI export. The note under the sections says *Marked by you.*

## 3. How

- `synth/arrange.py` — `sections_from_marks` turns `[(bar, name)]` into sections on the song's
  own beat grid: whole bars, an intro added if nothing starts at bar 1, one group letter per
  name, and the ring-out after the last bar kept on the last part (same rule as Sprint 5).
  `bar_levels` measures every bar's loudness for the strip.
- `routes_master.py` — the song-shape cache (Sprint 11) now also keeps the song's length and the
  bar loudness, and its key gains a version, so old caches rebuild once. Marks are kept as
  `sections.user.json` **beside the track in storage, never in the repository**.
  - `GET /tracks/{id}/sections` also returns `source` (`yours` or `detected`), `bar_db` and
    `detected`.
  - `PUT /tracks/{id}/sections` saves marks (a bar past the end of the song is refused, saying
    how many bars there are). `DELETE` goes back to the detected parts.
  - `GET /tracks/{id}/listen?bar=&bars=` plays a few bars of the original from any bar.
- `arrange.js`, `index.html`, `styles.css` — the editor.

## 4. Checked

- Tests: marks become grouped sections, an intro is added, marks past the end are clamped, bar
  loudness; the API saves, refuses and clears marks, the arrangement uses them, and the listen
  route plays the right slice.
- In the browser, on the demo track only: added a part at bar 7, saved it, and the arrangement,
  previews and note all switched to it. Then went back to the detected parts. Bar 9 of that
  track is a partial bar that only rings out, so the last part reads *bars 7–8* in both the
  editor and the section list.
