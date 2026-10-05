# Sprint 2 — verification pass

**Tested:** 2026-10-05
**Cards:** X0R-1127, X0R-1319, X0R-1314, X0R-1315, X0R-1316, X0R-1317, X0R-1318
**Against:** the working tree, through the running API and the running Studio, on real
audio — not a fixture.

This is the developer's own pass, run because the sprint finished while Ryan was away and
a pass of some kind beats none. It is **not** a substitute for the independent QA pass the
cadence calls for: I wrote the code, so I am the wrong person to decide what I failed to
think of. The handover at the bottom is for whoever runs that.

---

## The short version

| Card | Verdict |
|---|---|
| X0R-1127 · Decline to match a stem your own mix does not contain | **passed** |
| X0R-1314 · Your kick against their kick | **passed** |
| X0R-1315 · Take a per-drum suggestion | **passed**, criterion 3 measured rather than hashed |
| X0R-1316 · The drum panel says which drums it found | **passed** |
| X0R-1317 · A profile remembers their kick | **passed** on everything but the profile round trip (see below) |
| X0R-1318 · Compare instruments without being asked twice | **not verified in a browser** |
| X0R-1319 · A grid that survives a live drummer | **partial, as filed** — halving fixed, doubling not |

**902 tests, all passing.** 68 of them are new.

### Three defects found during the pass, all fixed

**D1 — the per-drum panel never appeared.** `renderInstruments` guarded on
`window.PerDrum`, and `PerDrum` is a top-level `const`, which in a classic script lives in
the script scope and *not* on `window`. So the test was always false and the drums card
rendered exactly as it did before, with no error anywhere. Every harness passed, because a
harness calls `PerDrum.panel()` by name. Found on the first run against the real API, and
it is the same shape as sprint 1's blocker: a scoping rule, silently false, swallowed by a
feature that degrades politely. Fixed with `typeof`.

**D2 — four dials read "Applied ✓" before anybody touched them.** A dial was called
applied by comparing its value with the suggestion, and the cymbals' pan suggestion was
−0.00: the reference's cymbals are centred, and centre is also where a pan control does
nothing. So the row showed four applied dials and an active "undo" on a drum nobody had
touched. Being taken is now a fact about what the user did, not about where the number
landed. **The stem rows have the same latent bug** — `refreshMoveButtons` compares lane
values the same way — and it is filed below rather than fixed here, because lanes have no
record of what was taken and giving them one is a change to the mixer.

**D3 — `measured` came back as 0.0 on three kinds of finding.** Punch, pan, and the
"already more even" half of dynamics never set it, so the API returned rows reading "yours
12.1, theirs 14.7, measured 0.0" — the comparison contradicting itself inside one object.
It had gone unread until the drums card started showing it. Fixed for the stem rows too,
with a property test that no row reports a zero gap.

---

## How it was tested

Both services restarted onto the working tree. The API runs from the ML virtualenv
(`~/.x0r-venv`), which is what makes per-drum separation available at all:
the app venv's torch is missing `torchgen`, so `demucs_is_importable()` is false there and
the feature correctly reports itself unavailable.

The pair is Experiment 2's — two programmed electro-house records, 28 s each — put through
the real endpoints: upload, separate, reference, separate the reference, compare
instruments, compare drums, stream a drum, save a profile, export.

### X0R-1314 · Your kick against their kick

| Criterion | Result |
|---|---|
| 1 · closed, named expander saying how many drums | **passed, refined.** Before the pass it names the cost; after it reads "4 drums measured — kick, snare, cymbals, toms". The reason the refinement exists is in SPRINT-2.md. |
| 2 · four sub-rows, each with findings or a reason, drums' own findings unchanged above | **passed.** kick 6 findings, snare 7, cymbals 9, toms 7. The drums row's own findings and dials are untouched. |
| 3 · every number matches the job's JSON | **passed.** Checked field by field against the response for all four drums. |
| 4 · every finding reads as the stem ones do | **passed.** Same sentences, same "the gap measures X, this offers Y" construction, same arrangement flag. |
| 5 · **no pan or width on kick or snare, under any pair** | **passed.** Verified on two pairs. Kick dials: gain, four tone bands. Snare: gain, three tone bands, compression. Cymbals do get pan. |
| 6 · an absent sub-drum gets one sentence and no dials | **passed.** On the fixture pair the toms are absent on the source side: the row reads "Your mix does not really contain this", carries the full sentence with both figures, and has **zero** sliders. |
| 7 · "▶ yours" and "▶ theirs" play that drum alone, band chips apply | **passed as far as QA can go.** Both sides return 206 with a `Range` header. The six chips appear while a drum plays, the selected band survives switching sides, and the filters are set on both monitor chains. *Nobody has heard it.* |
| 8 · the bleed caveat on every finding | **passed, differently.** Every finding carries one; it names the drum most likely to be behind that specific finding rather than repeating one paragraph. There is no figure to give — see SPRINT-2.md. |
| 9 · without the weights, the card is exactly as it was plus one line | **passed.** With `models_dir` empty the comparison response carries `per_drum.available: false` and the reason, and the page draws one sentence and no expander. |
| 10 · the cost is stated before it is paid | **passed, and the estimate is good.** It said 30.8 s; the pass took 29 s. |
| 11 · a profile contains the four sub-drums' measurements | **passed.** 6.5 KB, all four, same numbers the comparison showed. |

### X0R-1315 · Take a per-drum suggestion

| Criterion | Result |
|---|---|
| 1 · the report names the drum and the dB | **passed.** `drum by drum - kick: +2.0 dB, low +1.5 dB` on the drums row. |
| 2 · the export differs, the other drums do not | **passed.** The change is `shaped − raw` for that drum alone; a spectral check puts the whole difference at the kick's own frequency. |
| 3 · **the null case is identical** | **passed, measured.** See below. |
| 4 · clamped as the stem dials are, and says what it offered against what it measured | **passed.** Same bounds, same tooltip. |
| 5 · an absent sub-drum has no dial | **passed.** |
| 6 · the monitor responds, or the card says it is render-only | **passed, both.** A dial moves the audition immediately; the panel says in words that it is not audible in the mix below and why. |

**Criterion 3 cannot be checked by hashing the file, and the first attempt at it reported
a failure that was entirely the test's.** `mixdown.dither` draws fresh noise on every
render, deliberately, so no two renders of anything are byte-identical; MP3 re-encoding
then amplifies that. Four renders, decoded and differenced:

| | full band | 20–120 Hz |
|---|---|---|
| off vs off again — *the control* | −49.3 dB | −61.2 dB |
| off vs every dial at rest | **−49.4 dB** | **−61.6 dB** |
| off vs the kick taken +2 dB | −29.1 dB | −29.9 dB |

A dial at rest is indistinguishable from rendering the same thing twice. A move that was
taken is 31 dB above that floor in the kick's own band.

### X0R-1316 · The drum panel says which drums it found

All four criteria pass. The panel now names the route this machine takes and what that
changes; without the weights it says what is missing in `why_unavailable`'s own words; the
hi-hat box relabels itself "hi-hat / cymbals" on the separated route, with a tooltip saying
the cymbals stem holds hats, rides and crashes together; and the toggle's own text now
says that laying a kit moves no strokes, with the measured figure behind it.

### X0R-1317 · A profile remembers their kick

Criteria 1, 2 and 5 pass by inspection of the save box, the picker row and an
older profile loading unchanged. Criterion 4 passes by construction — "▶ theirs" is
omitted, not disabled, when `reference_audio` is false.

**Criterion 3 is not verified end to end.** Aiming a *fresh* song at a drum-carrying
profile and reaching the per-drum comparison with no separation of the reference needs a
second track and a second full separation, and I stopped short of it. The server half is
exercised (`from_snapshot_all`, and the capability block reporting `reference_kind:
"profile"`), and the stems-win-over-profile rule was corrected during the pass, but nobody
has walked the flow. **This is the first thing an independent pass should do.**

### X0R-1318 · Compare instruments without being asked twice

The diagnosis was right and the fix is one move: the `comparing` decision now happens
*after* `afterReferenceUpload()`, which is the call that writes `state.referenceSeparated`.
**Not verified in a browser**, because it needs a fresh upload of two songs with the box
ticked, and the harness route into the master page bypasses `upload()` entirely. Second
thing for an independent pass.

---

## Filed, not fixed

**D4 · the stem rows can show "Applied ✓" on an untouched dial.** The same bug as D2 one
level up: `refreshMoveButtons` decides by comparing the lane's value with the suggestion,
so any suggestion that equals the control's rest position reads as applied. Pan is where it
bites — a reference instrument sitting at dead centre offers `pan: 0`, which is also where
the control does nothing. Not fixed here because the lanes keep no record of what was
taken, and giving them one is a change to the mixer rather than to this screen.

**D5 · the hi-hat route note costs a cold subprocess probe.** `/tracks/drum-kits` now asks
whether DrumSep is importable, which is a process start the first time in any API run —
about five seconds. It is cached afterwards and usually already warm, because the
comparison asks first. Worth moving off the request path if anyone sees it.

---

## What QA should know before the independent pass

Answering the handover obligation in SPRINT-2's R4, which the sprint-1 report named as the
single thing that would most reduce the next pass's setup cost.

- **Run the API from the ML virtualenv.** `~/.x0r-venv/Scripts/python.exe`.
  From the app venv the per-drum feature correctly reports itself unavailable and there is
  nothing to test. `.claude/launch.json` already points at the right one.
- **The weights are installed** at `models/drumsep/49469ca8.th`. Nothing to download.
- **One pair is enough for most of it.** A 28 s clip pair costs two separations (~2 min
  each) and then one 30 s per-drum pass that covers every X0R-1314 and X0R-1315 criterion
  except number 5, which wants a second pair.
- **The comparison is cached per track.** After the first run the expander says "already
  split on both sides — this is instant", and re-running costs nothing. Re-running the
  *instrument* comparison also no longer loses the per-drum panel.
- **The two criteria nobody has walked** are X0R-1317's number 3 and all of X0R-1318. Both
  need a second, fresh track.
- **I cannot hear any of it.** Criterion 7 of X0R-1314 is verified as far as "the right
  audio is served and the right filter is set". Whether a kick sounds like a kick, and
  whether the band chips sound like the bands they name, is still unheard by anybody.
