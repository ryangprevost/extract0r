# Sprint 4 — remix from a reference: groove, feel, sounds, MIDI

Opened 2026-10-11 from Ryan, after hearing the first remix with a drop:

> Can you keep building on it until I have time to play around with it on my desktop
> tomorrow? Work on midi, sample library for synth and drums, etc, and overall groove and
> feel when remixing. Maybe come up with applying elements of the reference remix track to
> the source and allowing it to extract the essential elements

Run autonomously, committed card by card behind green CI.

---

## The scope line, restated

Re-sequencing - moving the drummer's hits - **stays out**, and nothing below needed it. A
groove read from a reference is *added* as a beat alongside the band, like the
four-on-the-floor; a user who wants it *instead* of their drummer leaves the drums out of
the version, a mute that is theirs to choose and that the account names. The drummer's own
groove is read too, but only to describe it.

Analysed, never sampled: nothing of a reference's audio reaches a remix. Each element is
reduced to numbers and rebuilt from this application's own synthesis.

---

## Cards

| | what | points | status |
|---|---|---|---|
| X0R-1340 | Grooves: read a beat's pattern, accents and feel; six built-in beats; add any of them | 5 | **done** |
| X0R-1341 | Remix like your reference: tempo, beat, swing, pump, kick and bass as a recipe | 5 | **done** |
| X0R-1342 | The version as MIDI, at the new tempo, drums and added parts included | 3 | **done** |
| X0R-1343 | A sample library: more kits and voices, and kits built from your own one-shots | 5 | next |

---

## What the first reference taught

A house track built here at 124 BPM with every ingredient known (`tools/make_house_reference.py`)
was the test. First read, against the truth:

| element | truth | first read | now |
|---|---|---|---|
| tempo | 124 | **186** (3:2) | 124.0 |
| kick / snare pattern | house | wrong grid | exact |
| swing | 55% | 50% | 55% |
| pump | 6 dB | **12 dB** (offbeat bass) | 4.4 dB |
| kit | roomy | punchy | punchy |

* **The tempo** was the estimator's 3:2 error, and every element after it was read against
  the wrong grid. `recipe.dance_tempo` tries the estimate's usual multiples (½, ⅔, ¾, 1, 4⁄3,
  3⁄2, 2), lets the kick decide, and breaks ties inside 95-180 BPM toward 125. Every wrong
  starting point tried - 62, 93, 165, 186, 248 - now lands on 124.0.
* **The pump** was the offbeat house bass - silent on the beat, playing between - which folds
  into a 12 dB "duck". A fold deeper than any pump worth copying is now read as the part's
  own rhythm, and the pad gives the real figure. It reads 4.4 dB against 6 applied (a pure
  tone pumped at 6 reads 5.7): an under-read, in the right direction for a copy.
* **The kit** is still wrong and is left wrong deliberately. Through separation the
  reference's kick measures shorter (225 ms against 325) and clickier than the roomy kick it
  was built on - demucs trims tails and leaks hat into the drums stem. Tuning the matcher to
  one test track would be fitting noise; the page shows the choice and it is one click to
  change.
* **The hit detector mislabels dance drums**, which mattered more than anything else here:
  back-to-back kicks overlap, so some came back labelled only by their click ("hihat"); a hat
  struck with the snare hid the snare; and every kick's click read as a hat. Three checks in
  `groove.read_hits`, each measured on band energy rather than the detector's running-baseline
  rises - which read the same kick at 15 dB and 69 dB a few bars apart.

**Proof it transfers:** the remix of the pop punk demo "like the house reference" reads back
at 123.99 BPM with 54% swing.
