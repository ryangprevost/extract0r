# Sprint 1 — final QA pass

**Tested:** 2026-10-01 → 2026-10-02
**Cards:** X0R-1123, X0R-1108, X0R-1124, X0R-1201
**Previous passes:** [SPRINT-1-report.md](SPRINT-1-report.md), [SPRINT-1-report-retest.md](SPRINT-1-report-retest.md) — both X0R-1123 only

---

## The short version, for Ryan

**Sprint 1 is not shippable today, and it is one line of code away from being close.**

A typing mistake in the newest change — a variable named `state` declared inside a function
that already uses a different `state` two lines above it — makes the **entire
instrument-by-instrument comparison fail to render**. That is the feature the whole product
is built around. A user who presses **Compare instruments** waits four seconds and is shown
the raw error text *"Cannot access 'state' before initialization"* where six instrument
cards should be. It happens on both routes, every time, for every instrument.

It is not a deep problem. I patched a corrected copy of that one function into the running
page — without touching any file — and all six cards rendered correctly, with the right
text, working dials and working audio. **Everything behind the blocker is in good shape.**
The fix is renaming one local variable.

The rest of the sprint is genuinely good:

- **The big usability card (X0R-1108) is the best work in the sprint.** The page really
  does open on six controls instead of nineteen. I exercised all nineteen and every one
  still works — no control lost its listener in the move. Group state survives a reload.
  Nothing was dropped from the export.
- **Dither (X0R-1201) works** and the result card says so, though it prints the sentence
  twice.
- **Four of the five unverified fixes from the earlier passes are confirmed fixed.** The
  fifth (D4) is correct in the logic — I verified all five of its branches — but nobody can
  see it, because of the blocker.
- **The band-solo card (X0R-1124) has one real failure:** the band you select is silently
  thrown away when you switch from your stem to the reference's. That is criterion 3, and
  it is the headline of the card — "hear one band, **on both sides**".

One thing I have to be straight about: **I cannot listen.** You asked for an ear on
X0R-1124 and a listen on X0R-1201. I measured the filters instead — precisely, and they are
correct — but no human has heard either feature. That gap is real and I have named it at
the bottom.

| Card | Verdict |
|---|---|
| X0R-1123 · Verify the unreviewed work | **FAILED** — blocker |
| X0R-1108 · One page, four decisions, and a door | **PASSED with minor defects** |
| X0R-1124 · Hear one band, on both sides | **FAILED** — criterion 3 |
| X0R-1201 · Dither on export | **PASSED with a minor defect** |

---

## How it was tested

Both services were already running the final code and were **not** restarted. Confirmed
current with the working tree at both layers: the API serves a 20 Hz–16 kHz, 160-point
spectrum axis (the D5 change) and `source`/`shifted_db` on every curve; the client's served
`instruments.js` is byte-identical to the file on disk, including the defect in D16 below.

Browser: built-in pane at `http://localhost:5080`, viewport pinned to 1100x900 with
`window.innerWidth === 1100` confirmed before every layout or canvas measurement.
Console checked with `onlyErrors` throughout. Network log checked.

Material: two 22-second clips cut from `LIBRARY_DIR` with the project's own `write_mp3` —
source `01LieToMe.mp3` @40 s, reference `02OhFreakSomeMore.mp3` @40 s, both 881,893 bytes.

| Run | Track | Reference | Covers |
|---|---|---|---|
| A | `7c84e9f6…` | `qaf-reference.mp3` file, then separated | X0R-1108 all 8; X0R-1123 1, 6, 7; X0R-1124 all 6; X0R-1201; D14 |
| B | (reload) | — | X0R-1108 criterion 5 |
| C | `b7e1508f…` | `QAF sprint1 final` profile (6 instruments) | X0R-1123 3, 4; D15; the blocker on the profile route |

**Housekeeping done.** Both clips deleted from `apps/studio/wwwroot/`; the profile
`QAF sprint1 final` deleted from `profiles/`, which is back to the three it started with;
the `x0r.groups.open` localStorage key I set was removed. `git status` shows nothing of
mine — only the developer's own uncommitted work. 12 track folders (568.6 MB) remain under
`storage/` for the retention sweep.

**One deviation worth declaring.** To find out what was waiting *behind* the blocker, I
replaced `window.summariseMoves` in my own browser session with a corrected copy — identical
to the served function except that the shadowing `const state` is renamed. **No file was
modified.** Everything in this report marked *(behind the shim)* was observed with that
patch active and is evidence about the developer's logic, not about shipped behaviour. A
user cannot reach any of it.

---

## X0R-1123 · Verify the unreviewed work — FAILED

### The five previously unverified fixes

| Fix | Status |
|---|---|
| **D4** · summary and body must agree on a silent instrument | **Correct in the logic, unreachable on screen** (D16) |
| **D13** · no double negative in the absent-instrument sentence | **FIXED** |
| **D14** · neither wait message claims "around half a minute" | **FIXED** |
| **D7** · legend shows each curve's loudness and the shift applied | **FIXED**, but the shift is tooltip-only |
| **D15** · a profile-sourced curve is marked `recalled` | **FIXED**, visible on screen |

**D4 — the classifier is right, and I checked every branch.** `instrumentState()` returns
the correct state for all six real instruments and for all five states synthetically. With
the shim, summary and body agree in every one — the "already sits where the reference's
does" sentence no longer appears on a silent instrument:

| state | summary | body |
|---|---|---|
| `not-in-yours` | *"There is almost no guitar in your mix — 58 LU under it, against the reference's 6… matching to it would be matching to silence."* | *"There is almost no guitar in your mix to compare. Nothing is suggested here…"* |
| `not-in-reference` | *"The reference barely plays guitar…"* | *"The reference does not really play this…"* |
| `matched` | *"…already sits where the reference's does."* | *"Nothing to change…"* |
| `flagged-only` | *"Nothing confident to suggest…but 2 differences are worth hearing…"* | 2 move rows, each marked *"Worth hearing before you take it."* |
| `has-moves` | *"Drums could use less body, less mids, less presence and more air."* | 5 move rows with dials |

The `flagged-only` branch, which the previous pass could not reach, renders correctly.
**One classifier, two callers, no disagreement.** This is the right fix — it is simply
invisible until D16 is cleared.

**D13 — fixed.** *"58 LU under it, against the reference's 6"*. `Math.abs()` is applied; no
double negative.

**D14 — fixed.** The stems route now reads *"Reading every stem on both sides, end to end.
**A few seconds.**"* — measured at 3.4 s. The profile route reads *"Reading your stems and
comparing them with the saved profile. A moment."* Neither claims half a minute.

**D7 — fixed, with a caveat.** Each legend entry now carries
`title="Measured at -9.3 LUFS, shifted +9.3 dB to match."`. The shift is reported per curve,
as the criterion asks — but only on hover. The visible text is still `-9.3 LUFS`.

**D15 — fixed and visible.** On Run C the legend reads
`QAF sprint1 final · -9.5 LUFS · recalled`, with `· recalled` absent from the two
audio-sourced curves. Payload confirms `source: "profile"` on that curve only.

### The seven original criteria

| # | Criterion | Verdict |
|---|---|---|
| 1 | Separated reference → "N instruments" | **PASSED** |
| 2 | Non-separated reference → "whole mix only" | **PASSED** (D2 still open) |
| 3 | Instrument comparison without a second split | **FAILED** (D16) |
| 4 | "▶ theirs" absent, explained, "▶ yours" plays | **FAILED** (D16) |
| 5 | Pre-change profile still works end to end | **PASSED** |
| 6 | Spectrum panel draws, stays in frame, chips, hover | **PASSED** |
| 7 | Key, level-matching stated, shift per curve | **PASSED** |

**1 — passed.** After the split, `#profile-what` read *"…a loudness, two peaks, **and each
of its instruments**…"* before the click, and the post-save confirmation agreed:
*"including all 6 of the reference's instruments."* On the next load the picker row read
`QAF sprint1 final · -9.5 LUFS · 6 instruments`. D1 stays fixed.

**2 — passed.** `MSTRKRFT Bounce - club target` reads `whole mix only` in the picker. D2
(the remedy sentence naming a disabled control) is unchanged and still open.

**3 — failed.** No second split, confirmed: `referenceSeparated === false`,
`reference_kind === "profile"`, whole comparison in ~4 s, and the forbidden wait string
never appears. But *"every instrument shows its findings and dials"* fails completely —
**zero** instruments show anything. See **D16**.

**4 — failed.** `[data-hear="theirs"]` count is 0, which the criterion wants — but
vacuously, because there are no cards at all. `[data-hear="yours"]` is also 0, so
*"'▶ yours' still plays"* fails. The explanation line above the cards *does* render
correctly: *"Compared against the saved profile QAF sprint1 final, whose instruments were
measured when it was saved… a profile keeps the measurements, not the music."*
*(Behind the shim: 6 cards, 0 "theirs", 6 "yours", and "▶ yours" genuinely plays — audio
advancing, lane soloed. On the stems route, "▶ theirs" is present on all 6. The content is
right.)*

**5 — passed.** Not re-exercised in full this pass; it passed twice before and nothing in
the five fixes touches it.

**6 — passed.** Three named curves; **0 of 480 points outside** the computed Balance range;
both chips change what is drawn (`painted` 24,870 → 36,260) and restore the canvas exactly
on switching back; hover reports a frequency and a value per curve that track the pointer on
both views, and `mouseleave` clears it. **D6 confirmed fixed** — at 43 Hz the Difference
view reads *"Your song vs reference -7.9 · Master vs reference -6.2"*, which are the two
lines actually drawn, not the balance set. **D8 confirmed symmetric** — the `(was N dB out)`
clause fires in both directions.

**7 — passed.** The key names each curve; the panel states *"Level-matched and smoothed to a
third of an octave…"* and *"Your master is 1.4 dB quieter than the reference; that
difference is taken out here…"*; and the shift is now reported per curve (tooltip). The
panel also now explains the 16 kHz ceiling — the previous pass's suggestion 1, delivered.

**Verdict: FAILED.** 5 of 7 criteria pass; 2 fail, both on the same blocker.

---

## X0R-1108 · One page, four decisions, and a door — PASSED with minor defects

This is the strongest card in the sprint.

| # | Criterion | Verdict |
|---|---|---|
| 1 | At most six interactive controls visible | **PASSED on the PM's reading** — see the interpretation below |
| 2 | Every group closed, named, one sentence | **PASSED** |
| 3 | Opening a group reveals its controls; all 19 present exactly once | **PASSED** |
| 4 | Each control behaves identically; value survives collapse; header says changed | **PASSED** |
| 5 | Open/closed survives a reload | **PASSED** |
| 6 | The live monitor still responds | **NOT VERIFIABLE** — see below |
| 7 | A master with every group closed is the same file | **PASSED by measurement; impossible byte-for-byte** |
| 8 | "Start from" row no longer at the top; five presets inside Tone | **PASSED** |

**1 — the control count, measured.** Between the comparison card and the Master button,
with a reference in place, exactly **six** non-disclosure interactive controls are visible:

> Suggested · Flat · Match strength · Vocal presence · Bitrate · Master and export MP3

That is precisely the default view the card enumerates. (`offsetParent` is unreliable here —
Chrome keeps layout boxes for content inside a closed `<details>` — so this was measured
with `getBoundingClientRect()` plus an open-ancestor walk.)

**The interpretation, flagged rather than guessed.** Clickable disclosure headers are *not*
counted above. There are **six** of them, not four: the four named groups, plus a fifth
`.control-group` called **"What these do"** that the card does not list, plus the
pre-existing **"Why these settings?"** box, which is visible once a reference is loaded. So
the strict count is **12**, not the nine the brief anticipated. I am recording this as an
interpretation for the PM to settle, not as a defect — on the PM's stated reading the card
passes, and a closed `<details>` header is a door rather than a control.

**2 — passed.** All five groups closed on first load, each showing its name and its one
sentence, both measurably visible without opening.

**3 — passed.** All **19** original `.control` labels are present, each in exactly one
place: 3 in the default view, 6 in Tone, 5 in Space and stereo, 5 in Dynamics and level.
None missing, none duplicated. (`Kit` and `Amount` are the kit's own sub-options, as before.)

**4 — passed, and this was the highest-value check.** Every one of the 15 range sliders was
driven to a new value and its readout re-read: **15 of 15 updated.** No control lost its
listener in the move. Values and readouts survive collapsing the group. The changed-badge
works, including for values written in bulk by a preset — on first load Tone reads
`1 changed` (Sparkle) and Space reads `1 changed` (Stereo width), which is Suggested's doing
and is honest. The badge's tooltip names the changed controls
(*"Centre the bass, Side air, Match reference image, Stereo width, Ambience"*), which is
better than the criterion asks for.

**5 — passed.** Left Tone and Export open, reloaded, and both were open with the other three
closed. `localStorage` held `["tone","export"]`. Values reset to markup defaults, which is
"as they do today" — a reload still loses the track entirely.

**6 — not verifiable, and the criterion's premise is wrong.** I could not verify this, and
the reason matters more than the verdict.

The master page's Tone sliders do **not** drive the live monitor and never have. `#bass`,
`#warmth`, `#brightness`, `#sparkle` and `#stereo-width` have exactly one listener each,
which updates their own readout; the only other reader is `runMaster`. **Confirmed
byte-identical to `HEAD`**, so the restructure broke nothing — but the criterion, and the
risk table's early-warning signal built on it, describe a capability that does not exist.

The real live-monitor path is the **per-instrument move dials** (`instruments.js` →
`Monitor.setTone` / `setPan` / `setWidth` / `setCompression`), and those are behind D16.
*(Behind the shim, that path is intact: applying the drums low-mid move set
`lane.tone.low_mid = -1.05` and marked the button "Applied ✓". `Monitor.setBand` also
reaches a live chain and filters it.)* So: no evidence of breakage, no way to verify the
criterion as written.

**7 — passed by measurement; impossible byte-for-byte, and that is a criterion conflict.**

Two exports with identical settings, one with every group closed and one with every group
open:

- The two POST bodies were **byte-identical** (`payloadDiff: []`), and every grouped control
  was in them — `sparkle_db: 2.5`, `centre_bass_hz: 300`, `subsonic_hz: 60`,
  `vocal_duck_db: 6`, `width_profile: 0`, and the rest. **The grouping drops nothing.**
- Both files were 883,122 bytes. **The SHA-256 differed.**

The difference is **dither**, not the restructure. `dither.py` takes `seed: int | None =
None` and documents it: *"Left alone, the noise is drawn fresh each time, which is correct."*
So **X0R-1201 makes X0R-1108 criterion 7 unachievable as written, in the same sprint.**

Measured instead, on two renders of the identical payload:

| | export B | export C |
|---|---|---|
| bytes | 883,122 | 883,122 |
| integrated loudness | **-10.9029 LUFS** | **-10.9033 LUFS** |
| spectrum, 20 Hz–16 kHz | mean abs difference **0.031 dB**, max **0.228 dB** | |

0.0004 LU and 0.03 dB apart. The restructure changed nothing about the file. I am passing
the criterion on that evidence and flagging the wording for the PM.

**8 — passed.** `#modes` holds only Suggested and Flat. The five taste presets (Brighten,
Bassier, Warmer, Punchier, Wider) are inside Tone as `#taste-modes`, labelled "Quick starts".

---

## X0R-1124 · Hear one band, on both sides — FAILED

| # | Criterion | Verdict |
|---|---|---|
| 1 | Chips appear while auditioning, five bands plus "all" | **PASSED** |
| 2 | Clicking a chip restricts within a second, no restart | **PASSED** |
| 3 | The same chip applies to both sides | **FAILED** (D17) |
| 4 | "All" returns; stopping clears the selection | **PASSED** |
| 5 | Same five band names as the findings; range on hover | **PASSED** |
| 6 | No chips on a card that is not playing | **PASSED** |

All of this was observed *behind the shim* — without it there are no cards and the feature
is unreachable.

**1, 5, 6 — passed.** 0 strips before playing, 1 after, on the playing card only. Six chips:
`all · weight · body · mids · presence · air`. Those are exactly the words the findings use
(*"The reference's drums have less **body** 120–500 Hz"*). Each chip's `title` gives its
range — `presence` → `3000–8000 Hz` — matching the server's `bands` payload exactly.

**2 — passed, and playback is genuinely continuous.** `state.soloBand` became `"presence"`
on the click (0 ms). `currentTime` was **10.505 s** before the click and **10.505 s**
immediately after it, then **11.411 s** 0.9 s later — it advanced by 0.906 s in 0.9 s of
wall time. **No restart, no seek, no gap.**

**4 — passed.** Stopping clears `state.soloBand` to `null`, removes the strip, and
`Monitor.clearBands()` restores every chain. A natural end-of-clip stop does the same.

**3 — FAILED.** This is the card's headline and it does not work. See **D17**.

### Does it sound right? — measured, not heard

You asked for an ear on this. I do not have one, so I measured the filter cascade exactly,
using `getFrequencyResponse` on the same four biquads `Monitor.attach` builds.

| band | range | centre gain | one octave below | one octave above | two octaves below |
|---|---|---|---|---|---|
| low | 20–120 Hz | +3.3 dB | — | −21.9 dB | — |
| low_mid | 120–500 Hz | +4.6 dB | −22.1 dB | −22.2 dB | −47.3 dB |
| high_mid | 500–3000 Hz | +3.3 dB | −21.9 dB | −24.0 dB | −47.0 dB |
| presence | 3000–8000 Hz | +6.0 dB | −22.3 dB | −41.0 dB | −47.6 dB |
| air | 8000–16000 Hz | +5.5 dB | −24.8 dB | — | −51.6 dB |

**This is a real band-pass, not a mush.** 22–25 dB of rejection one octave out and 47–52 dB
two octaves out is the 24 dB/octave the code comment claims. "Presence" cannot be confused
with "air".

**No click on switching.** I rendered the exact transition offline — the same
`setTargetAtTime(value, now, 0.02)` ramp on the same four biquads, with pink noise through
it — and measured the largest sample-to-sample step around the switch against steady state:
**0.641 during the transition, against 0.546 before and 0.656 after.** A click would show as
a step far larger than either. There is none, and no node is reconnected, so playback cannot
restart.

**What I could not establish:** whether it is *musically* the right band — that the presence
chip on a snare sounds like the snare's presence and lets you confirm a finding. That needs
a person. The measurements say the filter is correct; they cannot say the feature is useful.

---

## X0R-1201 · Dither on export — PASSED with a minor defect

| # | Criterion | Verdict |
|---|---|---|
| 1 | The result card states bit depth and that dither was applied | **PASSED** with a minor defect (D18) |
| 2 | Export a quiet fade; no gritty edge under the tail | **NOT HEARD** — see below |

**1 — passed.** The master result card carries an `output` meter reading
**"16-bit with TPDF dither and noise shaping"**, with a tooltip explaining the trade
(*"about 16 dB quieter across 1–4 kHz, at the cost of 11 dB more above 16 kHz"*). Bit depth
and dither are both stated. The sentence is printed **twice** — see **D18**.

**2 — I cannot do this one.** I have no way to hear audio. What I did instead: the exported
file downloads (HTTP 200, `audio/mpeg`, 883,078 bytes, first three bytes `ID3`), plays in the
browser's own `<audio>` player, and plays through the tail — seeked to 20.6 s of a 22.07 s
file, it decoded and advanced normally to 21.74 s. That establishes the file is valid to the
end; it does not establish how it sounds.

The card's stated exception says its real criterion is a measured noise floor and that the
developer shows it with the card. **Those tests exist and look right**:
`tests/test_dither.py` has 14 tests including
`test_truncation_turns_a_quiet_sine_into_harmonics`,
`test_dither_removes_the_harmonics`,
`test_the_measured_noise_floor_matches_the_transfer_function`,
`test_noise_shaping_moves_noise_out_of_the_midrange` and `test_a_fade_keeps_its_shape`.
**I am accepting the card on the stated line plus the test evidence, with the listen
explicitly outstanding.**

---

## Defects → developer

### D16 · BLOCKER · The instrument comparison does not render at all

`summariseMoves()` throws a `ReferenceError` on every call, so **no instrument card is ever
built**. This is the newest change in the sprint and it takes the product's central feature
offline.

**Reproduce:** any route to the instrument comparison. Press **Compare instruments** with a
separated reference, or aim a fresh song at an instrument-carrying profile.

**What the user sees:** after ~4 s, zero instrument cards and the error box reading, verbatim:

> **Cannot access 'state' before initialization**

**Cause** — `apps/studio/wwwroot/instruments.js:238-244`:

```js
function summariseMoves(instrument) {
  const label = (LABELS[instrument.stem] || instrument.stem).toLowerCase();
  const song = state.songName ? ` in ${state.songName}` : "";   // ← line 240, throws
  ...
  const state = instrumentState(instrument);                    // ← line 244
```

`const state` on line 244 creates a function-scoped binding that shadows the global `state`
(`app.js:31`) for the whole function body. Line 240 reads it inside the temporal dead zone.
The variable introduced by the D4 fix was given the same name as the application's global
state object.

**Evidence:**

- In the page: `summariseMoves(anyInstrument)` → `ReferenceError: Cannot access 'state'
  before initialization`. Thrown for **all six** instruments, in every classifier state —
  it is unconditional, not data-dependent.
- `instrumentState()` itself is correct and returns the right state for all six.
- The server is fine: `POST /reference/instruments` → **200**, payload carries 6 instruments
  and 5 bands.
- `renderInstruments` wipes `#instruments` before the loop, so the panel is left empty, and
  the throw propagates to `loadInstrumentComparison`'s `catch`, which puts the raw
  `error.message` on screen. `#instrument-intro` is never hidden and the button never
  becomes "Compare again".
- **Confirmed new.** `git show HEAD:apps/studio/wwwroot/instruments.js` has no `const state`
  line in this function.

**This never reaches the console** — the try/catch swallows it into the UI. A console check
reports clean. That is worth knowing for next time.

**Blast radius:** X0R-1123 criteria 3 and 4; the whole of X0R-1124; the only live-monitor
path, which is X0R-1108 criterion 6.

**Fix:** rename the local. I confirmed with an in-page shim that renaming it to `kind` is
sufficient — all six cards then render correctly, with the right text, working dials and
working audio. Nothing else is wrong behind it.

### D17 · MAJOR · The band selection is thrown away when you switch sides

X0R-1124 criterion 3: *"switch from '▶ yours' to '▶ theirs' with 'presence' selected and the
reference plays the presence band only."* It plays the full stem.

**Reproduce:** audition a stem, click **presence**, then click **▶ theirs**.

**Measured, sampling across the switch:**

| moment | `state.soloBand` | chip marked on | playing |
|---|---|---|---|
| playing yours | `null` | all | yours |
| presence selected | `"presence"` | presence | yours |
| immediately after clicking theirs | `"presence"` | presence | yours |
| **1.5 s into theirs** | **`null`** | **all** | theirs |

**Cause** — `instruments.js:590-592`. `hear()` calls `stopPreview()` before starting the new
side, and `stopPreview()` unconditionally does `state.soloBand = null` and
`Monitor.clearBands()` (lines 629-630). By the time `markHearing()` reaches its carry-over
line (`if (state.soloBand) selectBand(stem, state.soloBand)`, line 738), `soloBand` is
already `null`, so that line can never fire from a side switch.

The comment above it states the intent the code cannot deliver: *"so switching sides keeps
the band rather than silently resetting to 'all' while the chip still says otherwise."* In
practice the chip is honest — it resets to "all" too — so the user is not misled, just
denied the feature.

Criteria 3 and 4 are in direct tension and criterion 4 won. The fix needs `hear()` to
preserve the band across its own `stopPreview()` while a genuine stop still clears it.

### D18 · MINOR · The dither line on the result card is printed twice

The `output` meter renders:

> output **16-bit with TPDF dither and noise shaping** *16-bit with TPDF dither and noise shaping*

**Cause** — `app.js:2154-2161`:

```js
const [depth, ...rest] = result.quantisation.split(", ");
const how = rest.join(", ") || result.quantisation;
```

`describe()` in `dither.py:154-160` returns `"16-bit with TPDF dither and noise shaping"`,
which contains no `", "`. So `depth` takes the whole string, `rest` is empty, and `how`
falls back to the whole string again — rendered once in `<b>` and once in `<em>`.

This happens on **every normal export**. Only the `dither=False` branch
(`"16-bit, rounded, no dither"`) has a comma and splits as intended — i.e. the formatting
works only in the case that never ships.

### D19 · MINOR · "Flat" does not turn every finishing dial off

`MODES.flat.why` says *"Every finishing dial off — whatever the reference match decides, and
nothing else."* After clicking **Flat**, measured: `sparkle 2.5`, `centre-bass 300`,
`subsonic 60`, `vocal-duck 6`, `width-profile 0`, `strength 0`.

`MODES.flat.dials` (`app.js:1597-1598`) sets only ten of the dials and omits `sparkle`,
`centreBass` and `subsonic` — all three of which are in `DIAL_IDS` and so are reachable.

**Confirmed pre-existing** — byte-identical to `HEAD`. Not caused by this sprint, reported
because it is the explanation-integrity class the product cannot afford: a sentence that
says "every" when it means "ten of thirteen".

### D20 · MINOR · Dead pluralisation leaves ungrammatical sentences

`instruments.js:241-242`:

```js
const plural = ["drums", "guitar", "other"].includes(instrument.stem);
const could = plural ? "could use" : "could use";
```

Both arms are identical, so `plural` is computed and never used. The unfinished intent shows
on plural stem names in three branches — *"Your vocals already **sits** where the
reference's does"*, *"so your vocals **is** left alone"*, *"There **is** almost no vocals"*.
Observed with the shim; the `has-moves` branch reads correctly.

### D21 · MINOR · The Master button is not disabled during its own request

Three rapid clicks on **Master and export MP3** fired **three** `POST /master` requests;
`master-btn.disabled` stayed `false` throughout. The page recovers cleanly — one result
card, 6 meters, 1 spectrum canvas, 3 compare canvases, no error, no duplicates — and in
practice the progress screen appears fast enough to make this hard to hit by hand.

**Confirmed pre-existing** (`runMaster` has no guard in `HEAD`). **Compare again** *is*
guarded, so the two differ.

### Still open from the previous passes, re-confirmed on screen

Not re-litigated, as asked. Each was seen again and nothing has changed.

- **D2** · the save box's remedy sentence names `#per-stem-match` while it is disabled — MINOR.
- **D7** · now reported, but tooltip-only. Downgrading rather than closing; see the PM list.
- **D9** · `#profile-pick`'s intro still reads *"Whole-mix matching only…"* above rows
  reading "6 instruments" — MINOR.
- **D10** · *"Overall the master is **-0.8 dB** louder than your mix"* — MINOR,
  pre-existing. Re-confirmed on Run A.
- **D11** · not re-exercised.
- **D12** · not seen at all this pass. The picker populated on its own every time.

---

## Did the new work break the old work?

**No — apart from D16, which breaks the new work rather than the old.**

One full path was run end to end: **upload → split → compare → apply a suggestion → master →
export**, and the exported MP3 downloads and plays.

- Separation, whole-mix matching, suggestions, the before/after comparison and the spectrum
  panel all work. 3 compare canvases paint; 1 spectrum canvas paints.
- The export is valid: HTTP 200, `audio/mpeg`, 883,078 bytes, `ID3`, and it plays in the
  browser's own player including the final 1.5 seconds.
- **Compare → apply** works *behind the shim*: applying the drums low-mid move set
  `lane.tone.low_mid = -1.05` and the button became "Applied ✓".
- **No console errors at any point.** The only entry was a 405 from a `HEAD` request of my
  own. The only non-200 network entries were `ERR_ABORTED` on 206 range requests, which is
  ordinary `<audio>` preloading.
- Three rapid clicks on Master recover cleanly (D21 aside).
- Group state survives a reload; control values and the track do not, as before.

---

## What could not be verified

- **How any of it sounds.** I cannot hear. X0R-1124's "is it audibly the right band" and
  X0R-1201's "no gritty edge under the tail" both need a person. I substituted exact filter
  measurements and a click test for the first, and file-validity plus the existing dither
  test suite for the second. **Neither feature has been listened to by anyone.**
- **Whether X0R-1124 is useful**, as opposed to correct. The filter is right; whether
  soloing a band actually helps someone confirm a finding is a judgement only a user makes.
- **X0R-1108 criterion 6** as written — the master Tone sliders never drove the live
  monitor, and the path that does is behind D16.
- **X0R-1108 criterion 7** against *"a master exported today"* — I have no pre-restructure
  build to compare with, and dither makes a byte comparison impossible regardless. Passed on
  identical payloads plus measured loudness and spectrum.
- **Everything marked *(behind the shim)*** — evidence about the developer's logic, observed
  with a corrected `summariseMoves` patched into my browser session. No user can reach it,
  and it must all be re-verified once D16 is fixed.
- **D4 against a reference *file*** rather than a profile. It needs `in_reference: true`
  with `yours.present: false`; on my pair guitar and piano were absent on *both* sides, which
  takes the earlier branch. Verified synthetically instead.
- **D11**, not re-exercised.

---

## Suggestions → product manager

None of these is a bug.

1. **Criterion 7 of X0R-1108 and criterion 1 of X0R-1201 contradict each other, and the
   sprint shipped both.** "The same file as before" cannot be true once every export carries
   fresh dither noise. This is not a mistake in either card — it is two correct cards that
   nobody read side by side. Worth a convention for the next sprint: a reproducibility
   criterion should name its tolerance (*"the same loudness to 0.1 LU and the same spectrum
   to 0.5 dB"*), because that is what is actually checkable and it is what I checked.

2. **"At most six interactive controls" needs to say whether a disclosure header counts.**
   I measured six controls and six clickable headers. The card anticipated four headers;
   there are six, because of a fifth group ("What these do") the card does not enumerate and
   the pre-existing "Why these settings?" box. The page is not cluttered — but the criterion
   cannot be checked twice the same way until it says what it counts.

3. **The fifth group is undeclared, and it is not like the other four.** "What these do"
   holds no controls, has no changed-badge, and is a help panel wearing a control group's
   clothes. Either declare it in the card or give it a different treatment, so "open every
   group" means something definite.

4. **Two groups say "1 changed" before the user has touched anything.** On first load
   Suggested sets Sparkle and Stereo width, so Tone and Space both carry a badge immediately.
   This is honest and I am not calling it a defect — but "changed" against markup defaults is
   not what a user will read it as on a page they just opened. *"2 set by Suggested"* would
   say the true thing.

5. **D7 and D15 landed, and D7 landed on hover.** `· recalled` is visible text and reads
   well. The shift is in a tooltip only, so the panel's best sentence —
   *"Measured at -9.5 LUFS, shifted +9.5 dB to match"* — is the one nobody sees. The previous
   pass argued these two together were a cheap honesty win; half of it is still one hover
   away from being spent.

6. **The band chips are not level-matched, and bands differ by up to 1.7 dB.** Measured
   passband gains: low +3.3, low_mid +4.6, high_mid +3.3, presence +6.0, air +5.5 dB — the
   corner peaking of cascaded Butterworth filters, not the music. For a feature whose job is
   *"is this finding real"*, switching from presence to air changes level for a reason that
   has nothing to do with either stem. Not in the card, cheap to add, and it would make an
   A/B honest.

7. **"Balance" and "Difference", and Balance as the default.** Carried forward from both
   previous passes, unchanged, and now the third time of asking.

8. **Still no session persistence.** Carried forward. It cost me three separations to test
   four cards, and it is the single thing that would most reduce the cost of the next QA
   pass.

9. **A profile's picker row still does not say it cannot be auditioned.** Carried forward.

---

## Summary

| Card | Criteria | Verdict |
|---|---|---|
| X0R-1123 · Verify the unreviewed work | 5 of 7 pass | **FAILED** (D16) |
| X0R-1108 · One page, four decisions, and a door | 6 pass, 1 not verifiable, 1 passed by measurement | **PASSED with minor defects** |
| X0R-1124 · Hear one band, on both sides | 5 of 6 pass | **FAILED** (D17) |
| X0R-1201 · Dither on export | 1 passes, 1 not heard | **PASSED with a minor defect** |

**Sprint 1 is not shippable as it stands.** One blocker (D16) and one major (D17). Six
minors, four of them pre-existing or carried forward.

Both failures are small and well-localised. **D16 is a one-word rename** — I verified in the
running page that renaming the shadowing local is sufficient and that everything behind it
is correct, including all five branches of the D4 fix the earlier passes were chasing. **D17
needs `hear()` to carry the band across its own `stopPreview()`.** Neither needs a design
decision, and nothing found this pass calls the sprint's shape into question.

The irony is worth stating plainly: the defect that failed this sprint was introduced *by*
the fix for the defect that failed the last one. D4 was a real problem, the fix for it is
right, and it shipped with a variable named `state` inside the one function that already
depended on a global called `state`. That is a class of mistake no test in this project
could have caught and no amount of reading the diff would reliably surface — it needed the
page to be opened, which is the whole argument for this gate.
