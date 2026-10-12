# Sprint 10 — saved mixes

Opened 2026-10-12 from Ryan:

> go ahead with saving a mix to reuse next

---

## What was built — X0R-1400

| | |
|---|---|
| **Save a mix** | *Save this mix as …* keeps every strip that is not flat - level, pan, mute, solo, cuts, sends and their automation lanes - with the length of the version it was made on, in `samples/mixes/`, outside the repository like your sounds and kits. Listed as "6 parts, 5 moving settings". |
| **Use it on another version** | *Use this mix* puts it on the strips - heard before anything is bounced. Parts it names are set; every other part goes flat. **As saved** keeps each automation point on its bar; **fit to this version** stretches the lanes in proportion, so a sweep over the first verse is still over the first verse. |
| **Says what did not carry over** | "This version has no vocals, so that part of the mix is left out." "1 point past the end of this version was left out - try fitting it to the version instead." "Moving settings stretched to fit: 16 bars became 32." Nothing half-applies silently. |
| **Starter mixes** | *Wide and spacious*, *Tight and dry*, *Filter-up intro* - for somebody who does not know where to start, each saying what it does. Each is checked to be a valid mix for the mixer. |
| **A reload keeps the mix** | Opening a version restores the mix it was last bounced with. |
| **API** | `GET/POST /tracks/mixes`, `DELETE /tracks/mixes/{name}`, `POST /tracks/{id}/version/{label}/mix/apply`, `GET /tracks/{id}/version/{label}/mix`. |

`synth/mixes.py`.

Tested in the page on the demo track (by id): a starter applied as five high-cut lanes; a mix
saved, the strips reset, the mix applied back with *fit*, and deleted - the samples folder left
as it was found.

---

## Still open

1. Automation on the whole mix (a master lane), and on the build/drop layer's own sweep.
2. Velocity editing in the piano roll; a two-bar step grid; shaping uploaded samples.
