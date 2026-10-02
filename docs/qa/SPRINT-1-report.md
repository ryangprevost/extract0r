# Sprint 1 — QA report

**Card:** X0R-1123 · Verify the unreviewed work in a browser
**Tested:** 2026-10-01
**Verdict for the card: FAILED.** Three of seven acceptance criteria fail. Criterion 5 —
the one the developer was least sure of — is the strongest pass in the set.

## How it was tested

Both services were already listening and were **not** restarted, so the API was running
whatever was loaded before this session began. It was serving the new `per_stem` field on
`GET /api/v1/tracks/reference/profiles`, which is the uncommitted work, so the running
build includes it. The developer is editing `services/api/app/services/mixdown/encode.py`
concurrently; nothing in this report depends on that module beyond using `write_mp3` to cut
test clips.

Browser: built-in pane at `http://localhost:5080`, viewport pinned to 1100x900 and
`window.innerWidth` confirmed as 1100 before every layout or canvas measurement. Console
checked with `onlyErrors` after every run: **no console errors at any point.** Network log
checked: no failed requests.

Material: 22-second clips cut from `C:\Users\rprevost\Downloads\extract0r` (the configured
`LIBRARY_DIR`), because `storage/` was empty — the retention sweep had removed the track
folder the card's instructions pointed at (`storage/735fd1c5699f4a7c94616590e36ba5de/`).
Source = `01LieToMe.mp3` @40 s, reference = `02OhFreakSomeMore.mp3` @40 s.

Four full runs, each with its own upload and separation:

| Run | Track | Reference | Covers |
|---|---|---|---|
| A | `d761b8e0…` | `qa-reference.mp3` file, then separated | 1, 2, 6, 7 |
| B | (reloaded) | `MSTRKRFT Bounce - full` chosen up front | 3, 4 |
| C | `cb3a4d41…` | `MSTRKRFT Bounce - club target` from the master page | 5, and 6/7 on a second pair |
| D | (reloaded) | `MSTRKRFT Bounce - full` from the master page | 3, 4 on the second route |

Fixtures removed afterwards: both clips deleted from `apps/studio/wwwroot/`, and the two
profiles created during testing (`QA1123 whole mix`, `QA1123 with instruments`) deleted
from `profiles/`. Four track folders (~154 MB) remain under `storage/`; the 24-hour
retention sweep will clear them.

---

## Verdict per acceptance criterion

### 1. Profile captured from a separated reference — FAILED

The second half passes: after saving, the row reads **"6 instruments"**, and the
confirmation says *"including all 6 of the reference's instruments."*

The first half fails. **The save box does not state, before the click, that the profile
will include its instruments.** After separating the reference it still showed the
whole-mix wording: *"This reference has not been separated, so its instruments will not be
in it."* See defect **D1**.

### 2. Profile captured from a non-separated reference — PASSED WITH A MINOR DEFECT

The save box states the instruments will not be included, and the row reads **"whole mix
only"**. Both correct.

It also "says how to change that", but says the wrong thing: *"turn on
instrument-by-instrument matching above first"* points at a checkbox that is disabled at
that moment. See defect **D2**.

### 3. Fresh song aimed at an instrument-carrying profile — FAILED

No second split, confirmed: `state.referenceSeparated === false`,
`reference_kind === "profile"`, and the whole run (upload + one separation + comparison)
took 44.7 s — about the cost of a single 22 s separation.

Two failures against the criterion's wording:

- **The "Reading every stem on both sides" wait does appear**, on the master-page route.
  See defect **D3**.
- **Not every instrument shows its findings and dials.** Guitar shows neither, and states
  something its own numbers contradict. See defect **D4**.

### 4. "▶ theirs" absent, explanation present, "▶ yours" still plays — PASSED

Verified on both routes (Run B up-front, Run D master page):

- `[data-hear="theirs"]` count is **0**, and 0 disabled — absent, not present-and-disabled.
- The line above the cards is visible and reads: *"Compared against the saved profile
  MSTRKRFT Bounce - full, whose instruments were measured when it was saved — which is why
  there was no second split to wait for. Its stems cannot be played back: a profile keeps
  the measurements, not the music."*
- "▶ yours" present on all 6 and genuinely plays: after a real click, the vocals lane's
  audio advanced 14.21 s → 15.71 s, `paused: false`, `muted: false`, vocals soloed, button
  marked `.on`, stop button shown, preview timer set. `stopPreview()` cleared the solo on
  all six lanes and un-marked the button.

Dials from a profile also work: applying the vocals gain move set `lane.gainDb` to −0.71,
the button became "Applied ✓", a second click returned it to 0, the per-instrument undo
appeared, and the automatic per-stem checkbox stood itself down.

### 5. A profile saved before this change — PASSED

This is the criterion the developer flagged as least certain. It is the cleanest pass of
the seven, and it is defended at both layers.

- Whole-mix match works end to end: verdict rendered (*"Next to the reference, your mix is
  more scooped through the midrange…"*), 5 findings with measured numbers and nudge
  language (*"The tonal match closes about 1.1 dB"*), suggestions applied, master rendered.
- **Downloadable MP3 confirmed**: HTTP 200, `audio/mpeg`, 883,076 bytes, first three bytes
  `49 44 33` (`ID3`).
- The instrument comparison is **absent**, with a stated reason on screen: *"Not available
  from this profile. It was saved from a reference that had not been separated, so there
  are no reference instruments in it to compare yours against. Load that song as a
  reference with instrument-by-instrument matching on, and save the profile again to
  include them."* The checkbox is disabled, the "Separate the reference" button is hidden,
  and the save-profile box is hidden.
- Never empty or broken. The API also refuses independently: `POST
  /reference/instruments` returns **409** with a stated reason, so a bypassed or stale UI
  still cannot reach a blank screen.
- The spectrum panel works from a profile too — the reference curve is built from the saved
  measurements and labelled with the profile's name.

### 6. Spectrum panel: three curves, inside the chart, chips work, hover tracks — FAILED

Passing parts:

- Three named curves drawn, verified by pixel sampling against predicted positions.
  158 of 160 predicted points of the dashed source curve have a matching pixel within 3 px.
- Both chips change what is drawn: canvas hash 2738412185 → 2120418602, the key changes
  from three entries to two, the note text changes, and `spectrumLines()` returns 3 lines
  vs 2.
- Hover reports a frequency and a value per curve that track the pointer, on the Balance
  view. `mouseleave` clears the readout.

Failing parts:

- **Curves do not stay inside the chart at both ends**, on both views and on both
  song/reference pairs. See defect **D5** — this is the headline defect.
- **On the Difference view the hover readout reports the wrong curves.** See defect **D6**.

### 7. Key names each curve, level-matching stated, shift reported per curve — PASSED WITH A MINOR DEFECT

- The key names each curve and its swatches match the drawn lines exactly: source
  `rgb(154,167,184)` dashed, master `rgb(53,224,138)` solid, reference `rgb(122,162,247)`
  solid — identical to the colours sampled off the canvas.
- Level-matching is stated: *"Level-matched and smoothed to a third of an octave…"*, plus
  *"Your master is 1.6 dB quieter than the reference; that difference is taken out here so
  the shapes can be compared."*
- **The shift applied per curve is not reported.** The legend reports each curve's
  pre-match loudness (−9.6 / −11.4 / −9.8 LUFS); the shift actually applied was +9.56 /
  +11.36 / +9.75 dB. See defect **D7**.

---

## Defects → developer

### D1 · Save box still says "has not been separated" after the reference is separated — MAJOR

Criterion 1's first clause. The statement is false at the moment it matters, and the app
contradicts itself across the click.

**Reproduce:** upload a song → on the master page load a reference *file* → press
**Separate the reference** → wait for it to finish → read the "keep this reference as a
profile" box.

**Expected:** *"…a loudness, two peaks, **and each of its instruments**…"*
**Got:** *"…About 6 KB, no audio… This reference has not been separated, so its instruments
will not be in it; turn on instrument-by-instrument matching above first if you want them."*

**Evidence:** immediately after the split, `state.referenceSeparated === true` while
`#profile-what` still held the whole-mix text. Calling `refreshProfilePanels()` by hand
flipped it to the correct wording, so the text logic is right — the refresh call is
missing. `separateReference()` (`app.js:1229`) calls `refreshPerStemState()` but not
`refreshProfilePanels()`; the only two callers are `app.js:499` (upload time) and
`app.js:1145` (`afterReferenceUpload`), neither of which runs after a split from the master
page. There is no `localStorage`/`sessionStorage`, so a reload does not recover it either —
a reload loses the track. **There is no user route to the correct wording on this flow.**

Then, after saving, the confirmation correctly says *"including all 6 of the reference's
instruments"* — so the user is told two opposite things about the same profile, before and
after one click.

### D2 · The remedy sentence names a disabled control — MINOR

Criterion 2. The save box tells the user to *"turn on instrument-by-instrument matching
above first"*. At that moment `#per-stem-match` has `disabled === true`; the control that
actually does the job is the enabled **"Separate the reference"** button beside it. The
post-save message gets this right — *"separate it and save again to include them"* — so the
two sentences in the same box disagree about the remedy.

### D3 · "Reading every stem on both sides" appears when aiming at a profile — MAJOR

Criterion 3 says this wait must not appear. It does, and its content is false.

**Reproduce:** upload a song with no reference → on the master page, under "or aim at a
saved profile", press **Aim at this** on an instrument-carrying profile (e.g. `MSTRKRFT
Bounce - full`).

**Evidence:** sampling `#instrument-working` every 400 ms, it was on screen — not hidden,
`offsetParent !== null`, progress screen hidden, `#instrument-compare` visible — for 9
consecutive samples, from 800 ms to 4000 ms after the click. Text: *"Reading every stem on
both sides, end to end. Around half a minute."*

Wrong on three counts: the criterion forbids it; it is **not** reading every stem on both
sides (the reference's stems were measured when the profile was saved — that is the
feature); and "around half a minute" describes a roughly four-second operation. It appears
again on every press of **Compare again**.

The up-front route (choosing the profile on the upload screen) does **not** show it — there
the progress screen reads *"Comparing the instruments…"*, which is correct. Only
`useProfile()` in `profiles.js:180` and the `Compare again` button reach
`loadInstrumentComparison()` with the master page on screen.

### D4 · A silent instrument is reported as already matching — MAJOR

Criterion 3's "every instrument shows its findings and dials", and the explanation-integrity
rule. The sentence is contradicted by the two numbers printed directly beneath it.

**Reproduce:** aim any song whose guitar stem is near-silent at a profile whose guitar is
not. Reproduced identically in Run B and Run D against `MSTRKRFT Bounce - full`.

The guitar card says: **"Your guitar in qa-source already sits where the reference's
does."** Directly under it: **"yours: −58.2 LU in the mix · reference: −6.0 LU in the
mix"** — a 52.2 LU gap. `in_reference: true`, `moves: []`, no dials. The moves panel then
repeats the claim: *"Nothing to change. This one already sits where the reference's does, in
every dimension measured."*

The server returned zero moves for that stem without a reason, and `summariseMoves()`
(`instruments.js:226`) treats "no moves" as "already matched". The piano case is handled
properly — `in_reference: false` produces *"The reference barely plays piano, so there is
nothing to compare it with"* — so the gap is specifically **mine is silent, theirs is
not**. That case needs its own sentence and the server needs to say why it declined.

This logic is pre-existing (not in the uncommitted diff), but it is on the screen criterion
3 asks for, and per-instrument matching from a profile is what makes a reference with a
full band easy to aim at, so it is newly easy to hit.

### D5 · Curves leave the chart at both ends, on both views — MAJOR

Criterion 6: *"Every curve stays inside the chart at both ends."* They do not. This fails
worse the **better** the audible-band match is, which is why one song against one reference
did not show it.

**Pair 1** (Run A, `qa-source` vs `qa-reference.mp3` file):

- Balance view, range `[0.2, 38.8]`: the reference curve reaches −24.69 dB at 20 kHz, the
  source −12.28 dB. Three points each outside.
- Pixel confirmation at the right-hand plot edge: only the master line is painted, at
  y≈136–138 reading `rgb(53,224,138)` — exactly the predicted y of 137.2. The source
  (predicted y 282.6) and reference (predicted y 348.8) are both below the plot bottom of
  y=216 and are absent from the column.
- Difference view, range `[−12, 12]`: master-vs-reference reaches +39.65 dB at 20 kHz
  (4 points outside); source-vs-reference exits the bottom at 32 Hz (−12.49).

**Pair 2** (Run C, `qa-source` vs the saved `MSTRKRFT Bounce - club target` profile) — much
worse:

- Difference view auto-scaled to `[−4, +4]` because the 97th percentile over 25 Hz–18 kHz
  is small. Against an 8 dB-tall chart, master-vs-reference reaches **+51.78 dB** at
  19.15 kHz — 47.78 dB beyond the ceiling, 7 points outside; source-vs-reference reaches
  +48.31 dB, 11 points outside. Both also exit the bottom at 20 Hz.
- Pixel confirmation across the plot (chart height 206 px): painted curve pixels per column
  go 10/5 at 15 kHz → **60/2 at 16.5 kHz** (the line rocketing vertically) → **0/0 at
  17.5 kHz, 19 kHz and 19.9 kHz**. The right-hand ~15% of the Difference view contains no
  curve at all, only gridlines.
- Balance view, range `[−9.6, 35.4]`: the reference curve is at −41.4 / −52.65 / −52.96 dB
  at 18.3 / 19.15 / 20 kHz — up to 43.4 dB below the floor. Pixel counts for the reference
  go 31 at 17 kHz → **0 at 18.3 kHz, 19.15 kHz and 20 kHz**. At 20 kHz all three curves are
  gone.

Two compounding causes, both structural rather than incidental:

1. **The chart draws 20 Hz–20 kHz but both scales are fitted only to 25 Hz–18 kHz.**
   `spectrumRange()` (`spectrum.js:260`) uses `fit_low_hz`/`fit_high_hz`; `window()`
   (`spectrum_view.py:194`) uses `FIT_LOW_HZ`/`FIT_HIGH_HZ`. Everything outside that band is
   unbounded by construction, and the top octave is exactly where an MP3's lowpass makes
   two recordings differ by tens of dB.
2. **Even inside the fit band the range cannot contain the curves.** The Difference view's
   97th percentile leaves ~3% of in-band points outside by definition; pair 1 had points at
   17556 Hz (+12.59 against a +12 ceiling) and 32 Hz (−12.49) outside. On the Balance view,
   `window()` is documented as *"A shared vertical range that fits every curve"* but
   computes `db[db > db.max() - FLOOR_BELOW_PEAK_DB]` per curve — it deliberately discards
   each curve's quietest points, so the range it returns does not fit them.

The code comment at `spectrum.js:285` accepts clipping *past the 18 dB cap* as "clipped and
correct". That is not what is happening here: pair 2 clips at ±4, well below the cap, and
loses the last sixth of the chart.

### D6 · On the Difference view the hover readout reports the balance curves — MAJOR

Criterion 6's *"a value per curve"*. The readout does not change between views at all; it
is byte-identical for the same frequency on Balance and Difference.

**Reproduce:** master with a reference, press **Difference**, hover the chart.

At 59 Hz the readout reads:

> `59 Hz · Your song 31.7 · Master 32.9 · qa-reference.mp3 36.6 — yours has 3.7 dB less here (was 4.9 dB out)`

The chart at that moment draws two lines, keyed in the legend as **"Your song vs
reference"** and **"Master vs reference"**, sitting at −4.87 and −3.70. None of the three
numbers in the readout (31.7, 32.9, 36.6) is on the chart, and the third name
(`qa-reference.mp3`) is not a curve on the chart at all. A user matching the readout to the
lines cannot.

Cause: `onSpectrumHover()` (`spectrum.js:395`) maps over `data.curves`, which is always the
balance set, rather than over `spectrumLines(data)`, which is what was drawn.

The same function also happily reports values for points that have been clipped off the
chart — at 19.1 kHz it printed *"Your song −4.3 · … qa-reference.mp3 −9.9"* for two lines
that are not visible anywhere, with nothing saying they had left the plot.

### D7 · The shift applied per curve is not reported — MINOR

Criterion 7's last clause. The legend reports each curve's pre-match loudness, not the
shift that was applied: `−9.6 / −11.4 / −9.8 LUFS`, where the shifts were `+9.56 / +11.36 /
+9.75 dB`. It is the negation, so a reader who knows that can derive it, but the panel does
not state it.

The server already sends it. `Curve.shifted_db` is populated in `_levelled()`
(`spectrum_view.py:181–189`) and is present in the payload; **`shifted_db` appears nowhere
in any file under `apps/studio/wwwroot/`.**

### D8 · "(was N dB out)" is shown for improvements and silently omitted for regressions — MAJOR

The developer asked for this one specifically. The sentence never contradicts itself, but it
is one-directional, so the panel reports only good news.

The clause is gated on `Math.abs(started) > size + 0.5` (`spectrum.js:411`) — it appears
only when the gap *shrank*. Where mastering made a band worse, the readout says nothing
about it.

At 8.0 kHz in Run A the readout reads:

> `8.0 kHz · … — yours has 6.9 dB more here`

with no trailing clause. The numbers: it started **2.98 dB** out and is now **6.93 dB**
out — mastering widened that gap by 3.95 dB, and the readout is silent. A band that was
always 6.9 dB out and a band the master pushed from 3.0 to 6.9 read identically.

Not a one-off: inside the 25 Hz–18 kHz band, **13 of 151 points got worse by more than
0.5 dB** (131 improved). Worst regressions: 17556 Hz by 7.73 dB (4.86 → 12.59), 8032 Hz by
3.95 dB, 8388 Hz by 3.88 dB, 7690 Hz by 3.28 dB, 16810 Hz by 3.13 dB. The panel's own
docstring says the source line exists "so the improvement is visible rather than asserted";
the symmetric case needs the same treatment, e.g. *"(was 3.0 dB out — this moved away)"*.

### D9 · The saved-profile picker's intro now contradicts the feature — MINOR

Visible on screen in Run C, directly above rows reading "6 instruments":

> *"Whole-mix matching only: comparing instrument by instrument needs the reference's own
> audio."*

That is the static copy in `#profile-pick` (`index.html:239`). It is pre-existing text, and
it is **not** in the uncommitted diff — but this change is what made it false. It is the
first thing a user reads before choosing the profile whose whole point is that it does drive
the instrument comparison.

### D10 · "−1.7 dB louder" in the before/after panel — MINOR, pre-existing, outside this card

Found while checking that the new panel had not broken the old one. The comparison note read:

> *"Overall the master is **−1.7 dB** louder than your mix."*

`app.js:2060` hardcodes "louder" and passes the delta through `signed()`, so a quieter
master reads as negatively louder. Confirmed **not** in the uncommitted diff — pre-existing
and not caused by this work, reported because it is the same defect class the product cannot
afford.

### D11 · Applying a move leaves the mixer fader off its own label — MINOR, pre-existing

Applying the vocals gain suggestion set `lane.gainDb` to −0.71 and the fader's label to
"−0.7 dB", but the fader element's value to **−0.5**, because `[data-gain]` has `step="0.5"`
while instrument moves resolve to 0.1. Audio uses the lane value, so only the knob position
is wrong — up to 0.25 dB of visual disagreement between a slider and its own readout.

### D12 · Low-confidence: the profile picker was empty on arrival once — needs the developer's eye

In Run D the master page arrived with `#profile-list` empty; calling
`refreshProfilePanels()` by hand populated all five rows. In Run C, same flow, it populated
on its own. I could not reproduce it deliberately and the network log shows every
`GET /api/v1/tracks/reference/profiles` returning **200** — so this is not the silent
`catch { pick.hidden = true }` in `renderProfileList()` firing on a failed fetch, though
that path would produce the same symptom with no message. Recording it rather than dropping
it; I could not establish the cause. The same log also shows that endpoint being fetched 12
times in under half a second, which looks redundant.

---

## Did the new work break the old work?

**No.** The before/after waveform comparison directly above the new panel still renders
correctly, and in the right order (`#master-spectrum` follows `#master-compare` in document
order). All three canvases paint: "Your mix" 39,592 non-transparent pixels at 892x66,
"Mastered" 39,220 at 892x66, "What changed" 14,153 at 892x44. Scale reads 0:00 → 0:22 and
the note renders (its wording aside — D10).

Other regression checks that passed: no console errors in any run; no failed network
requests; a second click on **Compare again** mid-request is ignored (button disabled, no
duplicate cards, no error); `stopPreview()` clears the solo on all six lanes; the
instrument-carrying path correctly stands down the automatic per-stem checkbox when a move
is taken by hand; and the control case still works — with a reference separated for real,
`reference_kind` is `"stems"`, "▶ theirs" is present on all 6, and the profile explanation
line stays hidden.

---

## What could not be verified

- **Whether anything in the card behaves differently against a freshly started API.** The
  API was already running and was deliberately not restarted. It is serving the new
  `per_stem` field, so it has the new code, but I cannot certify it is byte-current with
  the working tree. **If the developer has touched any module since that process started, a
  restart and a re-run of criteria 1, 3 and 5 is warranted.**
- **D12's cause** — observed once, not reproduced, cause not established.
- **Whether the clipping in D5 is visible at other viewport sizes.** All measurements were
  taken at 1100x900 with a canvas of 892x238. A shorter chart makes it worse, not better.
- **The audible result of any of this.** No listening test was performed; this was a
  measurement and behaviour pass.

---

## Suggestions → product manager

Kept separate from the defects above. None of these is a bug.

1. **The top octave is dragging the whole panel around.** Both halves of D5 come from the
   same place: the chart draws 20 Hz–20 kHz, but above ~17 kHz an MP3's lowpass means two
   recordings differ by 40–50 dB for reasons nobody can act on and nobody can hear. The
   scale is then either fitted to that (useless) or not (curves leave the chart). The fix
   is a product decision, not just a clamp: **draw only the band the tool matches on**, and
   say so. Worth considering for X0R-809, which is already going to revisit this panel.

2. **"Balance" and "Difference" are the engineer's names, not the user's.** The Difference
   view is the one that answers "should I change something" — the panel's own docstring says
   so — yet Balance is the default. Consider defaulting to the view that prompts a decision,
   and naming the chips for the question they answer rather than the maths they do.

3. **The panel currently flatters the master.** D8 is a defect as implemented, but the
   underlying question is product-level: when mastering moves a band *away* from the
   reference — 13 of 151 bands here, one by 7.7 dB — does the product say so unprompted?
   For a tool whose entire claim is honest explanation, "we made this worse" is the most
   valuable sentence it could print, and the panel is the only surface that can see it.

4. **A profile's picker row does not say it cannot be auditioned.** The row reads "6
   instruments", which is the good news. The absence of "▶ theirs" is explained only after
   the comparison has already been run. Since a profile is now the *recommended* route (one
   split instead of two), the trade — instant and complete, but silent — belongs on the row
   where the choice is made.

5. **There is no session persistence, and it costs more now.** No `localStorage` or
   `sessionStorage` at all: a reload loses the track, the stems and the reference. That is
   pre-existing, and it is also what makes D1 unrecoverable rather than merely annoying —
   there is no "reload and it is right" escape from a stale panel. With separations costing
   ~45 s for 22 s of audio, restoring the last track on load would pay for itself. Not a
   defect against this card; noting it because the sprint is about to edit these files.

6. **"Reading every stem on both sides, end to end. Around half a minute"** is now wrong
   on one of the two routes rather than merely mis-worded (D3). When it is fixed, the
   profile route deserves its own sentence — something like "Reading your stems against
   measurements taken when the profile was saved" — because the speed *is* the feature and
   the message is the only place it shows.

---

## Summary for the card

| Criterion | Verdict |
|---|---|
| 1 · Separated reference → "N instruments" | **FAILED** (D1) |
| 2 · Non-separated reference → "whole mix only" | PASSED with a minor defect (D2) |
| 3 · Instrument comparison without a second split | **FAILED** (D3, D4) |
| 4 · "▶ theirs" absent, explained, "▶ yours" plays | **PASSED** |
| 5 · Pre-change profile still works end to end | **PASSED** |
| 6 · Spectrum panel draws, stays in frame, chips, hover | **FAILED** (D5, D6) |
| 7 · Key, level-matching stated, shift per curve | PASSED with a minor defect (D7) |

**Card X0R-1123: FAILED.** 4 of 7 criteria pass or pass with a minor defect; 3 fail.

Twelve items: **six major** (D1, D3, D4, D5, D6, D8), **five minor** (D2, D7, D9, and
pre-existing D10, D11), and one unreproduced observation (D12). That is past the sprint's
"more than five defects from X0R-1123" early-warning signal, so the risk table's stated
mitigation — drop X0R-1201 — applies. It is not past ten *in-scope* defects: D10 and D11
are pre-existing and D12 is not confirmed, so on my reading X0R-1124 does not need to go
with it.

Two things worth the developer's attention first, because they are cheap and they are the
ones that make the product look untrustworthy rather than unfinished: **D1** is a missing
`refreshProfilePanels()` call, and **D6** is `data.curves` where it should be
`spectrumLines(data)`. **D5** is the only one that needs a real decision.

The compatibility path the developer was least sure of (criterion 5) is the strongest thing
in the diff. The spectrum panel's auto-scaling, which he suspected, is worse than he
thought — and fails worse the better the match gets.
