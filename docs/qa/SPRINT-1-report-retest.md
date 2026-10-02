# Sprint 1 — QA re-test report

**Card:** X0R-1123 · Verify the unreviewed work in a browser
**Re-tested:** 2026-10-01, after the fixes for D1, D3, D4, D5, D6, D8
**Previous pass:** [SPRINT-1-report.md](SPRINT-1-report.md) — failed the card on criteria 1, 3 and 6

**Verdict for the card: FAILED — but only just, and for one reason.**

Five of the six defects the developer set out to fix are genuinely fixed, including the
headline one. D5 is fixed at both layers and measured clean on three different
song/reference pairs, including the exact pair that failed worst before. **D4 is not
fixed — it is moved.** The false sentence was corrected in the card's summary and left
verbatim in the card's body, two lines below, so the guitar card now contradicts *itself*
as well as its own numbers. That keeps criterion 3 failed.

---

## How it was tested

Both services had been restarted before this pass and the running code was confirmed
current with the working tree at both layers, which the previous pass could not do:

- **Server:** `GET /master/spectrum` returns `low_hz: 20`, `high_hz: 16000` and a 160-point
  axis ending at 16 kHz — the single band from the D5 change. The four `storage/` track
  folders left by the previous pass are not in the API's registry (`404 Unknown track`),
  which independently confirms a restart.
- **Client:** checked by reading the live function bodies in the page.
  `separateReference` contains `refreshProfilePanels` (D1); `loadInstrumentComparison`
  branches on `profileHasInstruments` (D3); `summariseMoves` tests `yours?.present` (D4);
  `onSpectrumHover` maps `spectrumLines(data)` and contains the "widened" clause (D6, D8);
  `spectrumRange` uses `Math.max(...all)` (D5). `#instrument-working` is empty in the
  served HTML, so the hardcoded text is gone.

Browser: built-in pane at `http://localhost:5080`, viewport pinned to 1100x900,
`window.innerWidth === 1100` confirmed before every layout or canvas measurement. Canvas
892x238, plot area x 38–882 (844 px wide) and y 10–216 (206 px tall) — the same geometry
the previous pass measured, so the numbers are directly comparable.

**Console checked with `onlyErrors` after every run: no console errors at any point.**
Network log: no genuine failures. The only non-200s are the deliberate `409` on
`POST /reference/instruments` and `ERR_ABORTED` on `206` range requests, which is ordinary
`<audio>` preloading and the download anchor.

Material: `storage/` had the previous pass's orphans but no usable track, so two fresh
22-second clips were cut from `LIBRARY_DIR` (`C:\Users\rprevost\Downloads\extract0r`) —
source `01LieToMe.mp3` @40 s, reference `02OhFreakSomeMore.mp3` @40 s, both 320 kbps CBR,
881,893 bytes, different content (md5 `df0cd870…` / `76a8b47f…`).

Four runs, each with its own upload and separation (~20–25 s each):

| Run | Track | Reference | Covers |
|---|---|---|---|
| A | `0f4c1005…` | `qa-rt-reference.mp3` file, then separated | 1, 6, 7; D1, D5 pair 1, D6, D8; the stems control case |
| B | `84ca78f6…` | `qa-rt-reference.mp3` file, **not** separated | 2 |
| C | `649d70aa…` | `MSTRKRFT Bounce - full` profile, from the master page | 3, 4; D3, D4, D5 pair 2 |
| D | `015c1419…` | `MSTRKRFT Bounce - club target` profile (no per-stem data) | 5; D5 pair 3 — the previously worst case |

Fixtures removed afterwards: both clips deleted from `apps/studio/wwwroot/`, and both
profiles created during testing (`QA-RT instruments`, `QA-RT whole mix`) deleted from
`profiles/`. `profiles/` is back to the three it started with; `git status` shows nothing
of mine. Eight track folders (320.6 MB) remain under `storage/` — four from the previous
pass, four from this one; the retention sweep will clear them.

---

## Verdict per acceptance criterion

### 1. Profile captured from a separated reference — PASSED

Both halves now pass.

**Before the click.** Immediately after the split completed (`state.referenceSeparated`
true at t+24.2 s), `#profile-what` read:

> *"Measures it once and stores the numbers — a spectrum, a width profile, a loudness, two
> peaks, **and each of its instruments**. No audio, and enough to aim any future mix at
> this song — including instrument by instrument, with only your own song left to split."*

Sampled again at +1.5 s and +4.5 s: identical. The stale whole-mix wording is gone.

**After saving.** The confirmation reads *"…including all 6 of the reference's
instruments"*, and on the next page load the row reads
`QA-RT instruments · -9.5 LUFS · 6 instruments`.

One note that is not a defect: `refreshProfilePanels()` returns early while a reference is
loaded and hides `#profile-pick`, so the new row cannot appear on the page you saved it
from. The row was verified on the following load, which is the only place a user can see
it. Worth knowing if anyone writes a test against the save screen.

### 2. Profile captured from a non-separated reference — PASSED WITH A MINOR DEFECT

Unchanged from the previous pass, as expected — this was not in scope for the fixes.

The save box states the instruments will not be included, and the row reads
`QA-RT whole mix · -9.5 LUFS · whole mix only`. The post-save message gets the remedy
right (*"separate it and save again to include them"*). The pre-save sentence still points
at `#per-stem-match`, confirmed `disabled === true` at that moment — **D2**, still open.

### 3. Fresh song aimed at an instrument-carrying profile — FAILED

**No second split, confirmed again:** `state.referenceSeparated === false`,
`reference_kind === "profile"`, and the whole comparison took **4.3 s**.

**The forbidden wait is gone.** `#instrument-working` was sampled every 300 ms through the
run. It was visible for 8 samples between t+305 ms and t+2415 ms, and the only text it
ever held was:

> *"Reading your stems and comparing them with the saved profile. A moment."*

The string "Reading every stem on both sides" did not appear anywhere on this route.
**D3 fixed.**

**"Every instrument shows its findings and dials" still fails**, and for the same card as
before. Guitar shows no findings and no dials, and the card now states two opposite
things about itself. See **D4**, which is **not fixed**. Piano is handled correctly
(`in_reference: false`, stated reason, no dials) — that case was accepted last pass and
still is.

Because the criterion is also what the explanation-integrity rule applies to, and because
the contradiction is now internal to a single card rather than between a card and its
numbers, this criterion cannot be passed.

### 4. "▶ theirs" absent, explanation present, "▶ yours" still plays — PASSED

Re-verified on the profile route in Run C:

- `[data-hear="theirs"]` count **0** across all six cards, and 0 disabled.
- `[data-hear="yours"]` present on all **6**.
- `#instrument-source` visible and reads: *"Compared against the saved profile MSTRKRFT
  Bounce - full, whose instruments were measured when it was saved — which is why there
  was no second split to wait for. Its stems cannot be played back: a profile keeps the
  measurements, not the music."*
- **"▶ yours" genuinely plays.** On drums: `lane.solo === true` for drums and `false` for
  the other five during the audition, audio advancing (vocals lane 5.67 s → 7.17 s,
  `paused: false`), button marked `.on`, 6 stop buttons shown. `stopPreview()` cleared
  `solo` on all six lanes, paused every lane and un-marked the button.
- Control case: on the real-stems route (Run A) `reference_kind === "stems"`,
  "▶ theirs" present on all 6, and `#instrument-source` stays hidden.

### 5. A profile saved before this change — PASSED

Re-verified end to end against `MSTRKRFT Bounce - club target` (`per_stem: false`).

- Whole-mix match works: verdict rendered (*"Next to the reference, your mix is more
  scooped through the midrange, darker through the top octave and duller through the
  presence range."*), 5 findings with measured numbers and nudge language (*"The tonal
  match closes about 1.7 dB of that on its own"*), suggestions applied, master rendered.
- **Downloadable MP3 confirmed:** HTTP 200, `audio/mpeg`, 883,082 bytes, first three bytes
  `49 44 33` (`ID3`).
- Instrument comparison **absent** with a stated reason on screen: *"Not available from
  this profile. It was saved from a reference that had not been separated, so there are no
  reference instruments in it to compare yours against. Load that song as a reference with
  instrument-by-instrument matching on, and save the profile again to include them."*
  `#per-stem-match` disabled, `#separate-ref-btn` hidden, `#save-profile` hidden,
  `#instrument-compare` hidden, `#compare-instruments-btn` off-screen.
- The API still refuses independently: `POST /reference/instruments` → **409** with
  *"Comparing instrument by instrument needs the reference separated too, or a saved
  profile that was."*
- The spectrum panel works from a profile: the reference curve is built from the stored
  measurements (`curve.source === "profile"`) and labelled with the profile's name.

### 6. Spectrum panel: three curves, inside the chart, chips work, hover tracks — PASSED

All four clauses now pass. This is the criterion that carried the headline defect.

**Three named curves, drawn where the data says.** Predicted-point matching against the
canvas on Run A: reference **160 of 160** points matched within 3 px, master **158/160**,
source **155/160**. The two master misses and five source misses are at frequencies where
the curves coincide within 0.4 dB (so the pixel is a blend) or inside a dash gap — see the
note under D5.

**Every curve stays inside the chart at both ends.** Measured on three pairs, both views,
by two independent methods — data against the range, and painted pixels per column. Zero
points outside and zero empty columns in all six measurements. Full numbers under **D5**.

**Both chips change what is drawn.** Canvas hash 2718133964 → 2974783666 → 2718133964
(restored exactly on switching back), legend 3 entries → 2, note text changes,
`spectrumLines()` returns 3 lines vs 2.

**Hover reports a frequency and a value per curve that track the pointer**, on both views,
and now reports the curves actually drawn — see **D6**. `mouseleave` clears the readout.
One pixel of dead zone at the extreme left edge (x = 38 exactly, where `share` rounds
very slightly negative and the handler bails); x = 38.5 onward reports normally. Not
worth a defect, recorded for completeness.

### 7. Key names each curve, level-matching stated, shift reported per curve — PASSED WITH A MINOR DEFECT

Unchanged from the previous pass, as expected.

- The key names each curve and the swatches match the drawn lines exactly: source
  `rgb(154,167,184)` dashed, master `rgb(53,224,138)` solid, reference `rgb(122,162,247)`
  solid — identical to the colours sampled off the canvas.
- Level-matching stated: *"Level-matched and smoothed to a third of an octave…"* plus
  *"Your master is 1.4 dB quieter than the reference; that difference is taken out here so
  the shapes can be compared."*
- **The shift applied per curve is still not reported.** The legend prints pre-match
  loudness (−9.3 / −10.9 / −9.5 LUFS) where the shifts applied were +9.31 / +10.90 /
  +9.49 dB. `shifted_db` is in the payload and the string "shifted" appears nowhere in the
  rendered DOM. **D7**, still open.

---

## Confirmed or refuted, defect by defect

| Defect | Status |
|---|---|
| D1 · Save box says "has not been separated" after separation | **FIXED** |
| D3 · "Reading every stem on both sides" on the profile route | **FIXED** |
| D4 · A silent instrument reported as already matching | **NOT FIXED — moved** |
| D5 · Curves leave the chart at both ends | **FIXED**, at both layers, on all three pairs |
| D6 · Difference view's hover reports the balance curves | **FIXED** |
| D8 · "(was N dB out)" only for improvements | **FIXED**, and symmetric on all 160 points |

### D1 — FIXED

`separateReference()` now calls `refreshProfilePanels()` and the box flips with the state.
Verified by text, three samples over 4.5 s after the split. The box went from the
whole-mix wording to *"…**and each of its instruments**…"*, and the post-save confirmation
agrees with it instead of contradicting it. There is no longer a point in the flow where
the two statements disagree.

### D3 — FIXED

Covered under criterion 3 above. The forbidden string is gone from the profile route and
the replacement sentence is accurate: it describes a 4.3-second operation as "a moment",
and it says correctly that only the user's stems are being read.

One residual on the **other** route, which the same change touched — see **D14**: on the
real-stems route the message still says *"Around half a minute"* for an operation I
measured at **5.0 s**. The criterion does not cover that route, so it does not fail a
criterion, but the sentence is still wrong where it is still shown.

### D4 — NOT FIXED. The defect has been moved from the summary to the body.

This is the one to read carefully, because it now has a test and a changelog entry.

`summariseMoves()` is fixed. On the guitar card the summary reads:

> *"There is almost no guitar in your mix — -58 LU under it, against the reference's -6.
> Either you did not record this part, or separation filed it under another stem. Nothing
> is suggested, because matching to it would be matching to silence."*

That is correct, and it is a genuine improvement.

`buildInstrumentCard()` was **not** given the matching branch. Open the same card and the
moves panel reads, verbatim and unchanged from the previous pass:

> *"Nothing to change. This one already sits where the reference's does, in every
> dimension measured."*

**Reproduce:** Run C — upload a song whose guitar stem is near-silent, aim it at
`MSTRKRFT Bounce - full` from the master page, open the guitar card.

**Evidence, all from the one card, simultaneously present in the DOM:**

- summary: *"There is almost no guitar in your mix … Nothing is suggested, because
  matching to it would be matching to silence."*
- numbers: `yours: -58.3 LU in the mix · swings 8.8 dB · 0.61 wide` /
  `reference: -6.0 LU in the mix · swings 7.6 dB · 1.27 wide`
- moves panel: *"Nothing to change. This one already sits where the reference's does, in
  every dimension measured."*
- payload: `in_reference: true`, `yours.present: false`, `yours.relative_lufs: -58.34`,
  `reference.relative_lufs: -6.05`, `moves: []`, 0 sliders.

So the card states that there is almost no guitar in the mix, that nothing is suggested
because matching would be matching to silence, that the two sides are 52 dB apart — and
then that the two sides already sit in the same place in every dimension measured. The
previous report's sentence applies unchanged: *"no differences" was being read as "no
difference", which is not the same statement.* It is still being read that way, one
element lower.

**Cause:** `instruments.js:331–342`. `buildInstrumentCard` branches on
`!instrument.in_reference`, then on `!moves.length`. It needs the same third test
`summariseMoves` was given — `instrument.yours?.present === false` — before the
"Nothing to change" fallback.

This is why the card cannot pass. A user who reads only summaries now gets the truth; a
user who opens the card to look for the dials gets the old falsehood, and the two
sentences are four lines apart.

### D5 — FIXED, and the "fails worse the better the match" failure mode is refuted

Measured the way the previous pass measured it: every point of every drawn line against
the view's own range, then painted curve pixels counted in all 844 columns of the plot,
on both views, on three pairs. Chart geometry identical to last time (844 x 206 plot).

**Pair 1 — `qa-rt-source` vs the `qa-rt-reference.mp3` file (the loosest match):**

| | range | data span | points outside | empty columns |
|---|---|---|---|---|
| Balance | `[-2, 39]` | 0.00 → 36.69 | **0** of 480 | **0** of 844 |
| Difference | `[-14, 14]` | −12.22 → 8.71 | **0** of 320 | **0** of 844 |

Previously: reference reaching −24.69 dB at 20 kHz with three points outside on Balance,
master-vs-reference reaching +39.65 dB on Difference.

**Pair 2 — vs the `MSTRKRFT Bounce - full` profile:**

| | range | data span | points outside | empty columns |
|---|---|---|---|---|
| Balance | `[-2, 35]` | 1.87 → 32.97 | **0** | **0** |
| Difference | `[-8, 8]` | −7.92 → 2.33 | **0** | **0** |

**Pair 3 — vs the `MSTRKRFT Bounce - club target` profile. This is the pair that failed
worst before**, the one that auto-scaled to ±4 and lost the right-hand sixth of the chart:

| | range | data span | points outside | empty columns |
|---|---|---|---|---|
| Balance | `[-2, 36]` | 3.41 → 33.42 | **0** | **0** |
| Difference | `[-10, 10]` | −8.40 → 2.00 | **0** | **0** |

Previously on this pair: `+51.78 dB` against a ±4 ceiling, 7 points outside on one line
and 11 on the other, reference pixel counts going `31 at 17 kHz → 0 at 18.3 / 19.15 /
20 kHz`, and *"the right-hand ~15% of the Difference view contains no curve at all"*.
Now the master-vs-reference line is painted in **every one of the 844 columns** on the
Difference view and the reference line in **every one of the 844** on Balance, with the
last five columns reading 8 / 7 / 7 / 7 / 5 painted pixels — the right-hand edge is full,
not empty.

**Both halves of the fix are load-bearing, and I can show it on this pair.** The 97th
percentile of `|started| ∪ |remaining|` here is **3.77 dB**, so the old client rule would
still pick a ±4 ceiling today — and the real maximum is **8.40 dB**, which would put
**9 points up to 4.4 dB outside** the chart. The new `Math.max` rule picks ±10 and leaves
0 outside. Separately, the server's single 20 Hz–16 kHz band is what removed the
±40–50 dB top-octave excursions that dragged the old percentile down in the first place;
on pair 3 the reference curve's lowest point on Balance is now **+8.19 dB** where it was
**−52.96 dB**.

So the specific thing I was asked to re-check — that it failed worse the better the match
got — does not happen any more, and it does not happen on the very pair that produced it.
The mechanism is removed rather than padded: the range is derived from the extreme of the
data, so a closer match now produces a *tighter* chart that still contains everything.

**Also closed: the open question about other viewport sizes.** At 700x560 the canvas is
612x238 — the width changes, the **height does not** (it is fixed in CSS), so the plot
stays 206 px tall. 0 points outside on both views at that size. "A shorter chart makes it
worse" cannot arise, because the chart does not get shorter.

**Two measurement notes, so the numbers are not over-read.** First, my colour matcher
counts a column as empty for a given line when that line's pixels have blended with
another line crossing it. On pair 1's Balance view the master line showed 29 such
columns; at every one of them `|master − reference| ≤ 0.40 dB` (checked at 83, 150, 202,
413, 468, 998, 1724, 10960 and 14710 Hz), i.e. the two lines are on top of each other and
the master is drawn over the reference. Not a frame exit. Second, the source line is
dashed `[4, 3]`, so 119–243 empty columns per view is the dash pattern, not a gap. The
decisive figures are the **0 points outside the computed range** and the **0 columns with
no curve of any kind**.

One thing worth the developer's eye although it passed: the Difference view's range has
**no padding**, where the server pads the Balance range by ±2 dB and rounds outward. On
pair 2 the source line's deepest point (−7.92 dB against a −8 floor) lands at y = 214.97
with the plot bottom at 216 — painted at y = 213–214, inside, but with 1 px to spare. A
1.5 px stroke at a point that landed on the floor exactly would half-clip. `edge` is
rounded up to an even number so there is normally some slack, but a value just under an
even boundary gets almost none. Cheap to make safe; not a defect today.

### D6 — FIXED

The Difference view's readout now reports the lines it draws. Same pointer position, both
views, pair 1:

| view | readout at 202 Hz |
|---|---|
| Balance | `202 Hz · Your song 26.7 · Master 23.3 · qa-rt-reference.mp3 23.3 — matched here (was 3.5 dB out)` |
| Difference | `202 Hz · Your song vs reference 3.5 · Master vs reference -0.0 — matched here (was 3.5 dB out)` |

The Difference numbers are the two values actually on the chart (`started_db[55] = 3.5`,
`remaining_db[55] = -0.0`), the names match the legend, and the third name that was not a
curve is gone. Verified again on pair 3. The previous failure — byte-identical output on
both views — does not occur.

The previous report's secondary complaint about this function (reporting values for points
clipped off the chart) is moot: there are no clipped points left.

Cosmetic only: `-0.0` is printed for a value that rounds to zero from below.

### D8 — FIXED, and symmetric

The clause now fires in both directions. Checked exhaustively rather than by sample:
hovered **all 160 points** of pair 1 and compared the rendered clause against the
expected branch from `started_db`/`remaining_db`.

- 142 points improved by more than 0.5 dB → all 142 printed `(was N dB out)`.
- **9 points were made worse by more than 0.5 dB → all 9 printed
  `(mastering widened this from N dB)`.**
- 9 points moved less than 0.5 dB either way → all 9 printed no clause.
- 0 disagreements. The one apparent mismatch was my own harness hovering the exact
  leftmost pixel, where the handler bails before writing anything.

The case from the previous report is now reported: at 7.8 kHz the readout reads
*"yours has 6.6 dB more here (mastering widened this from 3.1 dB)"* where it previously
said only *"yours has 6.9 dB more here"*. Confirmed again on pair 3 at its worst
regression (138 Hz, 0.17 → 1.28 dB out): *"yours has 1.3 dB less here (mastering widened
this from 0.2 dB)"*, on both views.

---

## Defects → developer

### D4 (re-opened) · The "already sits where the reference's does" sentence survives in the moves panel — MAJOR

Full detail above. One line of code short of done: `buildInstrumentCard()`
(`instruments.js:331–342`) needs the `instrument.yours?.present === false` branch that
`summariseMoves()` was given, before its `!moves.length` fallback. Until it has one, the
card asserts in its body the exact thing its summary was just fixed to deny.

### D13 · The new silent-instrument sentence prints a double negative — MINOR (new code)

In the sentence added for D4:

> *"There is almost no guitar in your mix — **-58 LU under it**, against the reference's
> **-6**."*

`summariseMoves()` (`instruments.js:228–233`) interpolates
`instrument.yours.relative_lufs.toFixed(0)` into prose that already supplies the word
"under", so a value of −58.34 renders as "−58 LU under it" — which reads as 58 LU *above*
it to anyone who takes the sign seriously. The numbers line beneath is consistent with
itself (`yours: -58.3 LU in the mix`) because "in the mix" carries no direction. The prose
needs `Math.abs()`, or needs to drop the word "under".

### D14 · "Around half a minute" is still wrong on the route that kept it — MINOR

The D3 fix split `#instrument-working` per route and gave the profile route an accurate
sentence. The other branch kept the old one:

> *"Reading every stem on both sides, end to end. Around half a minute."*

**Reproduce:** Run A — upload a song, load a reference *file*, press **Separate the
reference**, then press **Compare instruments**.

**Measured:** the comparison took **5.0 s** (`#instrument-working` sampled every 400 ms;
12 samples total, the message visible throughout). By the time this button can be pressed
both sides are already separated on disk, so this route never costs half a minute either —
it is reading stems that exist, exactly like the profile route, and it is the *same* 4–5
second operation. The "both sides" half is true here; the duration is not, and it is the
discouraging half.

### D15 · The panel never says the reference curve came from stored numbers — MINOR

`spectrum_view.Curve.source` exists for exactly this purpose — its own comment says *"a
profile's curve is 96 stored points rather than a fresh measurement, and a viewer is
entitled to know which they are looking at"*. Confirmed in the payload on Runs C and D:
`source: "profile"` on the reference curve, `"audio"` on the other two. Confirmed absent
from the rendered panel: `renderSpectrumKey()` never reads `curve.source`, and no string
to that effect appears in `#master-spectrum`.

Same shape as D7 — the server computes and sends a disclosure the page drops — and worth
listing beside it so they get fixed together. On Run D the legend reads
`MSTRKRFT Bounce - club target · -6.1 LUFS` with nothing to say that curve is a 96-point
interpolation of a measurement taken on 22 September rather than a reading of audio.

### Still open from the previous pass, unchanged and re-confirmed on screen

Not re-litigated; listed because I saw each of them again and the developer asked me not
to re-raise them, only to note nothing new.

- **D2** · the remedy sentence names `#per-stem-match` while it is disabled — MINOR.
  Re-confirmed in Run B.
- **D7** · the shift applied per curve is not reported — MINOR. Re-confirmed in Run A.
- **D9** · `#profile-pick`'s intro still reads *"Whole-mix matching only: comparing
  instrument by instrument needs the reference's own audio"* directly above rows reading
  "6 instruments" — MINOR. Re-confirmed in Run A and Run D.
- **D10** · *"Overall the master is **-1.3 dB** louder than your mix"* — MINOR,
  pre-existing. Re-confirmed in Run A; Run C showed the correct "+1.8 dB louder", so it is
  still only the negative case.
- **D11** · applying a move leaves the fader off its own label — MINOR, pre-existing. Not
  re-exercised this pass.
- **D12** · the profile picker empty on arrival — **could not reproduce, and I now have a
  benign explanation for what I saw.** In Run D I read `#profile-pick` as hidden with an
  empty list immediately after the master page appeared, then read it again a second later
  and found 5 rows and `hidden === false`. `refreshProfilePanels()` is awaited during
  upload and its fetch can land after the page is on screen, so a reader who looks early
  sees an empty picker that fills itself in. The previous pass's second symptom did not
  reproduce either: `GET /tracks/reference/profiles` was fetched **8 times across 4 page
  loads and 4 tracks**, not 12 times in half a second. I would downgrade D12 to "a
  sub-second flash of an empty picker during load" unless it is seen persisting again.

---

## Did the new work break the old work?

**No.** Checked again on Run C, after the D5 change altered every number the panel draws.

- The before/after waveform comparison still renders above the spectrum panel and in the
  right document order (`#master-spectrum` follows `#master-compare`). All three canvases
  paint: 892x66 with 30,812 non-transparent pixels, 892x66 with 34,648, 892x44 with 1,710.
  Scale reads 0:00 → 0:22 and the note renders.
- No console errors in any of the four runs; no genuine network failures.
- A second and third click on **Compare again** mid-request are ignored: button disabled
  through the request, 6 cards before and 6 after, no duplicate cards, no error, button
  text back to "Compare again".
- `stopPreview()` clears `solo` on all six lanes and pauses every lane.
- The control case still works: with a reference separated for real, `reference_kind` is
  `"stems"`, "▶ theirs" is present on all 6, and the profile explanation line stays
  hidden.
- Criterion 5's full path still reaches a valid MP3 (`ID3`, `audio/mpeg`, 883,082 bytes).

---

## What could not be verified

- **The fourth branch added to `summariseMoves()`** — the "every finding was flagged worth
  hearing first" case. None of the six instruments on any run had `confident === 0` with
  `flagged > 0`; the closest were bass and other, each with 1 flagged *and* 6 confident
  moves. The branch exists in the served code and reads correctly, but no material I have
  reaches it. It is the one part of the D4 change I am reporting on code rather than on
  screen.
- **D11**, not re-exercised — no move was applied by hand this pass.
- **The audible result of any of this.** A measurement and behaviour pass, as before. No
  listening test.
- **Whether D4's contradiction also appears with a reference *file* rather than a
  profile.** It needs `in_reference: true` with `yours.present: false`; on my file pair
  the guitar was absent on *both* sides (`in_reference: false`), which takes the earlier
  and correct branch. The defect is in a code path that does not care where the reference
  came from, but I only reproduced it on the profile route.

---

## Suggestions → product manager

None of these is a bug. Three of the previous pass's six are now resolved by the fixes and
are dropped.

1. **The panel now stops at 16 kHz and does not say so, or why.** This is the right call
   and it is the recommendation from the previous pass's suggestion 1 — *"draw only the
   band the tool matches on, and say so"* — with the second half outstanding. The axis is
   labelled `16k` at its right edge, so nothing on screen is false; but a user who knows
   what a spectrum analyser looks like will notice a missing top octave and has no way to
   learn that it was removed deliberately, that 16 kHz is where `BANDS` and the matcher
   stop, or that what is missing was never advice. One clause in the existing note would
   do it, and it turns a silent omission into the product's best kind of sentence.
2. **"Balance" and "Difference" are still the engineer's names, and Balance is still the
   default.** Carried forward unchanged from the previous pass. The Difference view is the
   one that answers "should I change something", and now that it is trustworthy it is a
   better default than it was last week.
3. **D15 and D7 together are a small, cheap honesty win.** The server already computes
   both the shift it applied to each curve and whether a curve was measured or recalled
   from a profile. Neither reaches the screen. For a panel whose whole claim is that it
   shows its working, "this line is a measurement from 22 September, raised 6.1 dB to
   match" is a stronger sentence than "−6.1 LUFS", and it costs no new control.
4. **A profile's picker row still does not say it cannot be auditioned.** Carried forward.
   The row reads "6 instruments"; the absence of "▶ theirs" is explained only after the
   comparison has run. A profile is the recommended route now — one split instead of two —
   so the trade belongs where the choice is made.
5. **There is still no session persistence.** Carried forward, and it cost me four
   separations to re-test one card. It no longer makes D1 unrecoverable, because D1 is
   fixed, but a reload still loses the track, the stems and the reference.
6. **The silent-instrument sentence is now the most informative thing on that screen, and
   it is also an invitation.** *"Either you did not record this part, or separation filed
   it under another stem"* is exactly the right thing to say, and it raises an obvious
   next question the product could answer: *which* stem did it go to? The measurements to
   answer that already exist on the same screen. Worth a card rather than a fix.

---

## Summary for the card

| Criterion | Previous | Now |
|---|---|---|
| 1 · Separated reference → "N instruments" | **FAILED** (D1) | **PASSED** |
| 2 · Non-separated reference → "whole mix only" | passed w/ minor (D2) | passed w/ minor (D2) |
| 3 · Instrument comparison without a second split | **FAILED** (D3, D4) | **FAILED** (D4) |
| 4 · "▶ theirs" absent, explained, "▶ yours" plays | PASSED | **PASSED** |
| 5 · Pre-change profile still works end to end | PASSED | **PASSED** |
| 6 · Spectrum panel draws, stays in frame, chips, hover | **FAILED** (D5, D6) | **PASSED** |
| 7 · Key, level-matching stated, shift per curve | passed w/ minor (D7) | passed w/ minor (D7) |

**Card X0R-1123: FAILED.** 6 of 7 criteria pass or pass with a minor defect; 1 fails.

Three criteria failed last pass and one fails now. Five of six targeted defects are fixed,
including D5, which was the only one that needed a real decision and which got the right
one — the top octave was removed rather than clamped, and the client scale was made to fit
the data rather than 97% of it. That fix is defended at both layers and holds on the pair
that broke it worst, where the old rule would still fail today.

The one thing standing between this card and a pass is a missing `else if` in
`buildInstrumentCard`. **D4 is the case the developer asked me to watch for: a fix that
moved a defect rather than removing it.** `summariseMoves()` was corrected and the moves
panel four lines below it was not, so the guitar card is now internally inconsistent
rather than merely wrong — which is a slightly worse state than before, because the
corrected summary makes the stale body look authoritative.

Count for the sprint's risk table: **one major in-scope defect open (D4)** and four
minors in or adjacent to this work (D2, D7, D13, D14), plus D15 and the carried-forward
pre-existing items. That is well inside the "more than five defects" early-warning
threshold that was tripped last pass, so on my reading the mitigation that dropped
X0R-1201 can be reconsidered — and D12 should be downgraded rather than left standing as
an unexplained one-off.
