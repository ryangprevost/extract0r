# Sprint 2 — Your kick against their kick

Second sprint of the loop in [TEAM.md](../TEAM.md). Re-scopes
[proposals/PR0DUCER.md](../proposals/PR0DUCER.md) after X0R-414 shipped; the proposal has
been updated to match rather than left to contradict this.

**Scope decided by Ryan**, on being given the two options: *"do the per-drum comparison,
that sounds more valuable."* It is also what the evidence says, and §1 below is the
reasoning rather than a re-argument. Drum re-production is **not cancelled** — it is
ungated, re-scoped, and in the backlog under EPIC-13.

**19 points · 7 cards · one developer, one QA.**

---

## Status

| Card | Pts | State |
|---|---|---|
| X0R-1127 · Decline to match a stem your own mix does not contain | 2 | **done** |
| X0R-1319 · A grid that survives a live drummer | 5 | **partial** — halving fixed and verified, doubling measured and unsolved |
| X0R-1314 · Your kick against their kick | 5 | **done** |
| X0R-1315 · Take a per-drum suggestion | 3 | **done** |
| X0R-1317 · A profile remembers their kick | 2 | **done** |
| X0R-1316 · The drum panel says which drums it found | 1 | **done** |
| X0R-1318 · Compare instruments without being asked twice | 1 | **done** |

A developer's verification pass is in [qa/SPRINT-2-report.md](../qa/SPRINT-2-report.md),
with three defects found and fixed and two criteria nobody has walked. It is not the
independent QA pass the cadence calls for — the person who wrote the code is the wrong
person to decide what they failed to think of — and the handover for that is at the
bottom of it.

### Where the build differs from the card, and why

Five deliberate departures. Each one is a refinement rather than a reduction, and each is
written here so the next person reads the card and the build as one thing.

**1. X0R-1314 criterion 1 — the expander says the cost first, and the count afterwards.**
The card asks for a closed expander saying how many drums were measured. It cannot say
that before anything has been measured, and measuring costs about half the audio's length
again *per side*. So the expander opens on the cost sentence and a button; once the pass
has run, its summary is exactly the card's wording — "4 drums measured — kick, snare,
cymbals, toms". Criterion 10 (state the cost before it starts) is what lives in the
first state. Folding the pass into the existing comparison would have made every
comparison several times slower for something most runs do not want.

**2. X0R-1314 criterion 9 — `DRUMSEP_ENABLED` is not a second gate.**
The comparison is available whenever the weights are on disk. That flag exists to keep an
unasked-for second separation out of a *master render*; this is a button with its price
written on it, which is its own opt-in. Gating an explicit, costed action behind an
environment variable as well ships a feature nobody can find — and the flag defaults off,
so that is not hypothetical. The other half of criterion 9 is honoured exactly: with no
weights there is no expander, no empty rows and no error text, just one line saying what
is missing in the words `separate.why_unavailable` already produces.

**3. X0R-1314 criterion 8 — the caveat names a drum instead of carrying a figure.**
The card asks for the bleed caveat on every finding "with its own figure". There is no
figure: DrumSep's per-stem bleed has never been measured, which is R2 and which X0R-306
is what turns into a number. What is on each finding instead is the thing a user can act
on — which drum to suspect. A finding about the snare's 20–120 Hz says the kick lives in
that band and that some of what was measured may be the kick in the snare's file; a
finding about its 3–8 kHz does not, because nothing else is up there. The general sentence
is kept for findings that are not about a band. Repeating one paragraph under eight rows
is wallpaper, and wallpaper is not a caveat.

**4. X0R-1315 — the change is applied, not the sum.**
The card describes shaping the four sub-stems and re-summing them with the residual. That
is implemented instead as `shaped − raw`, added to the drums: the residual appears in
neither term and cancels, so it never has to be computed and never has to be right. The
consequence is that criterion 3, the one the card calls non-negotiable, stops being a
tolerance anyone has to maintain and becomes a property of the arithmetic — a shape that
does nothing is *never read off disk*, and there is a test that fails if it ever is.

**5. X0R-1315 criterion 6 — the monitor responds, on the audition.**
The criterion allows either a live monitor or a plain statement that the dial is
render-only. Both are here, because both are true and neither alone is: moving a dial
while that drum is auditioning is audible immediately, and the panel says in so many words
that it is not audible in the mix below, because the monitor plays six stems and a kick is
not one of them — which is the whole reason this feature needs a render.

### Verified on real audio, through the running API

Not only in tests. The pair is Experiment 2's — two programmed electro-house records, 28
seconds each — uploaded, separated, compared, split again and exported through the live
service.

| Step | Result |
|---|---|
| Both drums stems split into four | 29 s for the pair, against an estimate of 30.8 s shown before the button was pressed |
| Findings | kick 6, snare 7, cymbals 9, toms 7 |
| Pan or width offered on kick or snare | none, on either side |
| Findings without a bleed check | none |
| One drum's audio | 200 with the file, 206 with a `Range` header, on both sides |
| A second comparison | `sides: 0`, `cached: true` — instant |
| Profile saved afterwards | carries all four drums, 6.5 KB |
| Export with the kick moved | report reads `drum by drum - kick: +2.0 dB, low +1.5 dB` |
| A pan on a kick | 422, with the reason |

#### X0R-1315 criterion 3, measured

The criterion says a master with every per-drum dial at zero must produce "the same file"
as one exported with the feature off. **Byte equality is not available and never was**:
`mixdown.dither` draws its noise fresh on every render, deliberately, so no two renders of
anything are identical — the first version of this check compared hashes and reported a
failure that was entirely the test's. Re-encoding to MP3 then amplifies that difference,
which is why the floor below is −49 dB rather than a dither floor.

So the question is whether a dial at rest changes the audio by more than the noise that
was going to be there anyway. Four renders of one track, decoded and differenced:

| | full band | 20–120 Hz |
|---|---|---|
| off vs off again — *the control* | −49.3 dB | −61.2 dB |
| off vs every dial at rest | **−49.4 dB** | **−61.6 dB** |
| off vs the kick taken +2 dB | −29.1 dB | −29.9 dB |

A dial at rest is **indistinguishable from re-rendering the same thing twice**, in both
bands, which is the strongest form of the criterion that physically exists. A move that
was taken sits **31 dB above that floor in the kick's own band**, and moves the finished
master's 20–120 Hz by +0.32 dB.

The unit tests make the same point exactly rather than statistically: `_apply_per_drum`
returns the array it was handed when every shape is identity, and a separate test proves
the sub-stem file is **never opened** in that case.

### Found while building, fixed in passing

**`measured` was zero on three kinds of finding.** Punch, pan, and the "already more even"
half of dynamics never set it, so the API returned rows reading "yours 12.1, theirs 14.7,
measured 0.0" — the comparison contradicting itself inside one object. It had gone unread
because nothing displayed it until the drums card did. Fixed for the stem rows too, with
a property test that no row reports a zero gap, since a row only exists when something
crossed a threshold.

**The test suite was reading the developer's `models/` folder.** `conftest`'s settings
fixture takes care to pass `_env_file=None` so the suite does not depend on a local
`.env`, and then inherited `models_dir` pointing at the repo. So whether a route reported
per-drum separation as available depended on whether somebody had downloaded a 167 MB
file, and the tests that would then have exercised it would have shelled out to demucs.
Pointed at an empty temp folder; the one test that wants the real weights names them
itself and skips without them.

---

## Sprint goal

A person can see and hear what that record's **kick** does that their kick does not — and
their snare, cymbals and toms — and take any one of those differences, each a fraction of a
measured gap with the sentence that produced it.

---

## 1. Why per-drum comparison and not drum re-production

### What X0R-414 changed, in both directions

**It removed stage 4's gate.** Stage 4 was gated on X0R-306 because drum identity came from
a band-rise classifier whose accuracy had never been measured. Drum re-performance needs
onset times and which drum; both now come from separation. An onset in the kick file is a
kick. Measured on the 28 s clip: **zero strokes carry more than one drum**, against three
from the classifier, and the kick returns 60 strokes at every gate from −6 to −30 dB — a
programmed four-on-the-floor measuring exactly like one. **The X0R-306 gate on stage 4 is
retracted.** It was a gate on classification, and there is no classifier left on that path.

**It did not make that output worth leading with.** The honest statement of what a user
hears from drum re-production is **"your drums, re-kitted, same groove."** That is
*different drums*, not *produced like that record*, and it is measured:

- `drum_blend` 0.3 → 0.9 moves the mean spectral gap to the reference by **at most
  0.09 dB** (Experiment 2 §2), against this project's own `MEANINGFUL_GAP_DB = 1.2`. Inside
  the noise of the measurement.
- Layering places **zero new grid positions** (Experiment 2 §3). It reinforces strokes that
  are already there. Replacing a kit changes how the drums sound, never where they land.
- Dynamic range moves the **wrong way**: the source started 0.12 dB from the reference's
  dynamic range; the blend-0.9 bounces end 2.8 dB from it.
- Nothing about the reference enters the sound. The kit is one of three synthesised kits
  picked from a dropdown; X0R-1309 would pick one *by* the reference and its ceiling is
  still "one of three".

### Why the comparison is worth more, and not only because it is cheaper

A drum-bus comparison averages a kick, a snare and a cymbal — three instruments playing
different things in different registers — into one number that describes none of them. "The
reference's drums have 2.1 dB more weight" is a sentence about a sum. It cannot say whether
the kick needs sub or the snare is too thin, which is the only form in which the advice can
be taken. That is the argument EPIC-12 makes against Ozone's Master Rebalance, applied one
level further in, and this is the first time the audio exists to make it.

1. **Its audible output points at the reference.** Every other card in this epic makes the
   drums *different*; this one makes them measurably *closer*, by a stated fraction of a
   stated gap. On-brief by construction — no new product rule is needed to keep it honest.
2. **It extends the moat rather than widening the surface.** `instrument.compare` already
   produces level, five tone bands, dynamics, punch, pan and width per instrument with a
   dial and an explanation each. Per-drum reuses all of it.
3. **It is the first time a user can solo one drum** against another record's same drum, at
   the same band, with the chips X0R-1124 already built.

### What is still gated on X0R-306, honestly

| Was gated | Now |
|---|---|
| Stage 4 · drum re-performance (X0R-1309/1310/1311) | **Not gated.** Identity and onsets come from separation. Gated instead on the judgements in R1 and R2 below. |
| Stage 5 · bass re-performance (X0R-1312/1313) | **Still gated, unchanged.** It needs note pitch; nothing about X0R-414 touches pitch. The kill criterion stands. |
| X0R-406's "kick/snare/hi-hat ≥ 80% F1" | **Still gated, and it still matters** — `DRUMSEP_ENABLED` defaults off, so the band-rise classifier is what a fresh clone runs. X0R-306 is how anyone finds out how bad the default path is. |
| — | **New item for X0R-306:** DrumSep's own per-stem bleed, which this sprint measures band energies through. Two thresholds here are judgements because that number does not exist. |

X0R-306 is not in this sprint — 5 points would crowd out the work the sprint exists for —
and it should lead sprint 3, before stage 5 is scoped rather than before it is built.

**X0R-412 does not need doing now.** The path that matters already avoids it:
`separate._onsets` runs `backtrack=False` deliberately, with the reason in its docstring,
and `find_hits`' backtracking is correct for the triggering it was written for. Nothing in
this sprint reads a hit *time* for measurement — the comparison reads continuous band energy
and level from the sub-stem audio. The card stays `TODO` as the tripwire its own text says
it is, for the first card that measures groove.

---

## 2. Three design decisions this sprint turns on

### Decision A — kick, snare, cymbals and toms are **not** `StemKind` members

They are a **second level inside the drums row**. `StemKind` is load-bearing in 21 modules
under `app/` and 35 files counting tests: the separation backends map a model's outputs onto
it, the transcription backends are chosen by it, `domain/tab/x0r.py` writes it into every
export, `StemSetting` is keyed by it, and the Studio's `STEM_ORDER` and `LABELS` enumerate
it. Adding four members asks every one of those what a tab of a kick is.

**One consequence is decisive on its own.** `pipeline.run` builds an `untouched` sum of
*every* separated stem and `_apply_as_correction` subtracts it from the original, so only
separation's own errors are left out of the mix — with a test guarding it, because a stem
left out of that sum silently made its mute do nothing. Sub-drums as `StemKind` members
would put the drums into that sum twice: once as `drums` and once as its four parts. That is
not a migration, it is a different mixdown.

So: a nested level, confined to `instrument.py`, the comparison route and
`instruments.js` — and **zero blast radius** in separation, transcription, tab, export or
mixdown.

**What the screen looks like.** The drums card keeps its own findings and gains a
disclosure: **a Drums card that expands into four**, not four sibling cards.

- The drums-stem findings are still real and still the only ones with a fader behind them
  today. Replacing them with four sub-cards would remove a working feature to add one.
- Four siblings in `STEM_ORDER` would read as nine instruments, on a page that sprint 1
  spent 5 points making less crowded. The epic's own §8 warning about complexity applies to
  this sprint too.
- Disclosure is the pattern X0R-1108 just established and QA just verified: a named group,
  closed by default, that says what is inside before it is opened.

### Decision B — four dimensions per drum, not six

Inheriting all six because the code allows it would offer dials that cannot mean anything.

| Dimension | kick | snare | cymbals | toms | Why |
|---|---|---|---|---|---|
| Level | yes | yes | yes | yes | Relative to the drums stem it came out of, so it reads as balance *inside* the kit — the portable number, same reasoning as `relative_lufs` against the mix. |
| Tone, five bands | yes | yes | yes | yes | With `QUIET_BAND_DB` doing its existing job: a kick holds nothing in the air band and must not be offered a lift there. |
| Dynamics | yes | yes | yes | yes | What compression changes. |
| Punch (crest) | yes | yes | yes | yes | The most diagnostic of the four on a kick — click against thud is exactly a crest difference, and it is the figure a drum-bus comparison destroys by averaging. |
| **Pan** | **no** | **no** | yes | yes | `NEVER_MOVE_SIDEWAYS = (StemKind.BASS,)` exists because a bass belongs in the middle. A kick and a snare belong there for the same reason, and on every record either is centred: a pan finding on them would be reporting separation bleed. Overheads genuinely spread, so cymbals and toms keep it. |
| **Width** | **no** | **no** | yes | yes | Same tuple gates both. And `MIN_MEANINGFUL_WIDTH` already refuses a ratio between two near-mono stems — it was added because a drum stem measured 0.06 against a reference's 0.08 and the comparison offered "widen by 39%" on two hundredths of width. A separated kick is the most mono signal in the application. |

So kick and snare join the never-sideways rule; cymbals and toms do not. Four dimensions
where it is a kick, six where spread is real, and the card says which and why rather than
showing an empty row.

### Decision C — a reference profile carries the sub-drums, and the capture flow is its own card

This needs the **reference's** drums separated too: a second DrumSep pass on that side,
about half the audio's length again on CPU. Paying that on every comparison of every song
against the same reference is the wrong shape, and the mechanism to avoid it already exists
— `snapshot` / `from_snapshot` / `SNAPSHOT_FIELDS`, whose comment says anyone adding a
dimension has to walk past them, and X0R-1125 which put per-stem measurements into a profile
for exactly this reason.

**Split, deliberately:**

- **The format is in X0R-1314.** A snapshot of a per-drum-separated reference carries its
  four sub-drums. That is a criterion of the first card, not a later one, because shipping
  the comparison with a profile format that cannot hold it means two formats in the wild and
  a migration.
- **The capture-and-reuse flow is X0R-1317**, 2 points, mirroring X0R-1125's shape: the save
  box says what will be included, the picker row says what a profile holds, and a song aimed
  at that profile reaches the per-drum comparison with no second separation at all.

That is the strongest version — the cost is paid once, ever, per reference — and splitting it
means that if the sprint runs short the thing dropped is the convenience, not the format.

---

## 3. Why this, now

**The audio exists and nothing reads it.** `drums/separate.py` returns four stems and the
only consumer is `kit.layer`, which uses them to place samples. Four stems' worth of
measurable instrument is produced and discarded on every run.

**The comparison engine is already shaped for it.** See Decision A and B: this is a
fourfold application of machinery that exists, inside one module and one screen.

**The processing path has a live bug that per-drum would multiply by four.** X0R-1127:
`match_stem` asks only whether the *reference* has the instrument, so an absent source stem
against a reference's residue takes a +9 dB lift of nothing — measured on a real pair in
Experiment 2. A toms stem is residue on most records, so the rule gets named once, first,
before it is mirrored four ways.

What this sprint does **not** rest on: the fingerprint (stage 1), a genre label (stage 2),
any transcription, any benchmark, or any new DSP block.

---

## Cards

### X0R-1127 · Decline to match a stem your own mix does not contain · 2

Existing card, pulled into this sprint unchanged in intent. Full reasoning in
[BACKLOG.md](../BACKLOG.md).

**The problem.** `instrument.compare` returns nothing when either side is absent.
`stem_match.has_counterpart` checks only the reference. The two paths disagree, and the
processing one is the one that makes sound.

**Acceptance criteria** — all checkable in a browser:

1. Master a song with no guitar against a reference whose guitar stem is separation
   residue. The "Per-instrument matching" report's guitar row shows **no gain tag** and a
   badge saying your mix has no guitar — distinct from the existing "no reference part"
   badge, because it is the other side that is empty.
2. That row never shows "+9.0 dB" or a "wanted" figure.
3. A song that *does* have a quiet guitar, against the same reference, still matches and
   still shows its gain. The rule is about absence, not about being quiet.
4. The comparison card calling an instrument absent and the match report calling it absent
   never disagree on the same pair — same threshold, same wording, named once in code.

**Out of scope.** Changing the threshold itself. The census half of Experiment 1's finding
(a presence test that tells an instrument from residue) — that arrives for sub-drums only,
in X0R-1314.

---

### X0R-1314 · Your kick against their kick · 5

**The problem.** The drum bus is three instruments averaged into one number. A user is told
"the reference's drums have more presence" and cannot tell whether that is the snare's crack
or the hats. Drums is the one stem in the six where the stem is not an instrument.

**What it is.** Run the per-drum split on both sides, measure each sub-stem the way
`instrument.profile` measures a stem, compare drum to drum, and render the findings as a
second level inside the drums card. Decisions A, B and C above are part of the card.

**Presence is a criterion, not an afterthought.** A record with no toms still yields a toms
stem: 24 tom strokes in 28 seconds were measured on a programmed electro-house record, which
is residue. A sub-drum is called present on its **energy relative to the drums stem**, the
same rule and threshold `ABSENT_BELOW_LU` already applies against the mix — **never on a
stroke count**, because `separate.QUIET_STROKE_DB` has no knee on the snare (R1).

**Acceptance criteria** — all checkable in a browser, by reading the screen and the API
response. QA cannot hear, so no criterion here asks it to:

1. With a reference separated and the per-drum weights present, the Drums card shows a
   closed, named expander that says how many drums were measured before it is opened.
2. Opening it reveals **four** sub-rows — kick, snare, cymbals, toms — each with its own
   findings and its own dials, or its own one-sentence reason for having none. The drums
   stem's own findings and dials are **still present and unchanged** above them.
3. Every number shown on a sub-row matches the value for that sub-drum in the comparison
   job's JSON response: yours, reference, measured and suggested, for every finding.
4. Every finding reads as the stem-level ones do — what was measured on each side, what is
   offered, and that the offer is a fraction of the gap. A gap past the arrangement
   threshold is flagged rather than offered confidently, as today.
5. **No pan or width row appears on kick or snare, under any pair.** Cymbals and toms may
   show them. Verified by opening all four on two different reference pairs.
6. A sub-drum absent on either side shows one sentence naming which side is empty and the
   figure behind it, and offers no dials — not dials at zero. Verified against a record with
   no toms.
7. "▶ yours" plays that drum alone; "▶ theirs" plays that drum alone from the reference.
   Both work on all four, and the X0R-1124 band chips apply to a sub-drum audition exactly
   as they do to a stem. *QA verifies that audio is served and that the chips change the
   filter in the response, not that it sounds right.*
8. Every per-drum finding carries the bleed caveat in its detail text with its own figure:
   the stems are not surgically clean, so a low-band finding on the snare may be the kick
   arriving late. On the finding, not in a help panel.
9. Without the weights, or with per-drum off, the Drums card looks and behaves exactly as it
   does today, plus one line saying what would be available and how to get it. No expander,
   no empty sub-rows, no error text.
10. The comparison states its cost before it is started: that an extra pass runs on both
    sides and roughly how long.
11. A profile captured from a per-drum-separated reference **contains** the four sub-drums'
    measurements — verified by downloading or inspecting the saved profile and seeing the
    same numbers the comparison showed. (The flow that *uses* it is X0R-1317.)

**Out of scope.** Applying any per-drum suggestion — X0R-1315. Any change to the six
stem-level rows. Hi-hat separately from cymbals: DrumSep returns one cymbals stem and the
model that splits them was rejected on its licence (X0R-414). Pattern, timing, swing or
groove figures of any kind.

---

### X0R-1315 · Take a per-drum suggestion · 3

**The problem.** A comparison nobody can act on is half a feature. Taking the kick's weight
means moving the kick inside a drums stem that is summed.

**What it is.** The four sub-stems plus the residual separation left behind. Apply each
sub-drum's accepted move to its own sub-stem with the existing `StemShape`, re-sum with the
residual, and hand the result to the pipeline as the drums stem — the same "apply the
change, not the sum" approach `_apply_as_correction` uses for the six-way split, one level
in.

**Acceptance criteria** — all checkable in a browser:

1. Accept one per-drum suggestion — the kick's weight — and export. The master report's
   drums row names the sub-drum the move was made on and the dB applied.
2. The exported file's drums differ from an export of the same session with that dial at
   zero, and the three other sub-drums' measurements in a fresh comparison of the export are
   unchanged within the stated tolerance. *Checked by reading numbers, not by listening.*
3. **The null case is identical.** A master exported with every per-drum dial at zero
   produces the same file as a master exported today with per-drum off. Reconstruction must
   not change the drums when nothing was asked for. This criterion is not negotiable.
4. Each per-drum dial is clamped by the same limits the stem dials are, and its row says
   what it offered against what it measured, as today.
5. A sub-drum called absent has no dial at all.
6. The live monitor responds to a per-drum dial while that sub-drum is auditioning, **or**
   the card says plainly that this dial is render-only. Either is acceptable; silently doing
   nothing is not.

**Out of scope.** New dimensions. Per-drum reverb, saturation or width beyond what X0R-1314
offers. Replacing a sub-stem with a sample — that is the drum kit, and a different feature
with a different honesty problem.

---

### X0R-1317 · A profile remembers their kick · 2

**The problem.** The reference side of a per-drum comparison costs a second separation pass.
Paying it on every song aimed at the same reference is the wrong shape, and X0R-1125 already
solved this for stems: a profile keeps the measurements, which is all the comparison ever
reads from that side.

**Acceptance criteria** — all checkable in a browser:

1. The save box states, **before** the click, whether the profile will include its per-drum
   measurements, and says how to change that when it will not.
2. A profile holding them reads so in its row in the picker — distinct from "N instruments"
   and from "whole mix only".
3. Start a fresh song, aim it at a per-drum-carrying profile, and reach the per-drum
   comparison **without any separation of the reference**: the extra wait does not appear,
   and all four sub-rows show their findings and dials.
4. On that screen, "▶ theirs" is **absent** on the sub-rows — not present-and-disabled —
   and one line explains that a profile keeps measurements, not music. "▶ yours" still
   plays. Same rule the stem rows already follow.
5. A profile saved before this change drives the whole-mix and per-stem comparison exactly
   as it does today, and the per-drum expander is either absent or refused with a stated
   reason. It never appears empty or broken.

**Out of scope.** Any change to what a profile holds for the six stems. Migrating old
profiles.

---

### X0R-1316 · The drum panel says which drums it found · 1

**The problem.** X0R-414 shipped behind `DRUMSEP_ENABLED` with no surface at all. The panel
still says the kit "finds each kick, snare and hi-hat in the drum stem" — one sentence
describing two mechanisms with different failure modes, separation on Ryan's machine and the
band-rise classifier on a fresh clone.

**And a defect against X0R-414, reported here rather than filed as a card.** The hi-hat
checkbox is dead on the separated path: `kit.DRUMS` is `("kick", "snare", "hihat")`,
`separate.STEM_NAMES` produces `cymbals`, and `kit.layer` renders only names present in
both. A user who ticks hi-hat with per-drum separation on gets silence, and the 56 cymbal and
24 tom strokes found per 28 seconds are all discarded. The fix belongs with this card
because the honest label and the working box are the same question.

**Acceptance criteria** — all checkable in a browser:

1. The panel says which route it took on this machine and one sentence on what that changes.
2. When per-drum separation is unavailable it says what is missing and how to get it, in the
   words `separate.why_unavailable` already produces.
3. The hi-hat box is honestly labelled for what the cymbals stem contains, or disabled with
   the reason. **A ticked box that produces no sound is a defect against this criterion.**
4. The panel states that laying a kit reinforces the strokes already there and moves none of
   them, with the measured figure behind it. A user reading it should not expect the groove
   to change.

**Out of scope.** A tom voice or any new `Voice` — see the non-goals. Turning the per-drum
split into a UI toggle; saying which route ran is the criterion, not exposing the switch.

---

### X0R-1318 · Compare instruments without being asked twice · 1

Added mid-sprint on Ryan's report: *"i want you to compare instruments automatically if i
select it from the first screen. i dont want to have to click the button again on the
second page."* Full diagnosis in [BACKLOG.md](../BACKLOG.md).

**The problem.** It is meant to work already. `upload()` decides whether to auto-run the
comparison by reading `state.referenceSeparated`, and that flag is written ten lines
later, inside `afterReferenceUpload()`. So on the upload path it is always still `false`
when the decision is made. The saved-profile path works, because its flag is set earlier —
which is why nobody caught it.

**Acceptance criteria** — all checkable in a browser:

1. Upload a song and a reference with instrument-by-instrument ticked. On arrival at the
   master page the instrument cards are **already populated**, with no button press, and
   the button reads "Compare again".
2. A saved profile carrying instruments still auto-compares, as it does today.
3. A reference loaded *without* instrument-by-instrument does **not** auto-compare — that
   costs a second separation the user declined.
4. Loading a reference later, from the master page, behaves as it does today.

**Out of scope.** Any change to what the comparison shows. This card is about when it
runs.

Sequenced last: it touches `upload()`, which X0R-1314 and X0R-1315 also pass through, and
it is one point.

---

### X0R-1319 · A grid that survives a live drummer · 5

Pulled into this sprint on Ryan's call, after the Melodyne probe turned up what it was not
looking for. Full card and measurements in [BACKLOG.md](../BACKLOG.md).

**Why it is here and not in EPIC-13.** It was written as a pr0ducer prerequisite. It is
also a live defect in a shipped feature: `ascii_tab.py:59` and `drum_tab.py:59` place
every column with `quantize(start_s - first_beat_s, tempo_bpm, division)`, so a wrong
tempo does not degrade a tab, it rewrites it. Verified on the shipped path — two of three
records wrong, one of them by 3:2 rather than an octave, and the confidence is 0.57–0.61
on all three, so nothing downstream can gate on it.

**Sequenced first.** It touches `domain/timing.py` and nothing the per-drum cards touch,
so it cannot collide with them, and it is the only card in the sprint a user could hit
today.

**Acceptance criteria** — checkable in a browser:

1. Transcribe a live-drummed song. The reported tempo is within 2% of the true tempo, and
   the tab's bar lines fall on the bar.
2. The same for a programmed four-on-the-floor record, which currently comes back halved.
3. Where the grid cannot be trusted, the confidence says so — a figure the UI can gate on,
   rather than 0.57 for both a right answer and a wrong one.
4. A song whose tempo the user sets by hand is unaffected.
5. No regression on the existing timing tests.

**Out of scope.** Tempo *drift* within a song — fitting a changing grid is X0R-1322's
problem and this card only has to put a constant one in the right place. Metre detection
beyond what already exists.

---

## Sequencing

1. **X0R-1127 first.** Small, server-side, a live bug, and — the real reason — it is the
   presence rule the rest of the sprint mirrors four ways. Naming it once before per-drum
   quadruples it is the difference between one rule and five implementations of it.
2. **X0R-1314 second.** The sprint's reason for existing and the card needing the most QA
   time. Its audition is the audible result; starting it in week one puts that in front of
   Ryan mid-sprint.
3. **X0R-1315 third.** Needs X0R-1314's sub-stem measurement and X0R-1127's rule.
4. **X0R-1317 fourth.** Needs X0R-1314's snapshot format (criterion 11) and nothing else.
5. **X0R-1316 last.** Browser-only and independent; it can overlap the tail of X0R-1314
   since it touches the drum panel rather than the instrument cards.

**Drops, in order: X0R-1316 (1), then X0R-1317 (2).** Dropping X0R-1317 costs the
convenience and not the format, which is why Decision C put the format in X0R-1314. What
does **not** happen is shipping X0R-1315 without X0R-1314: a dial with no sentence behind it
is off-brief.

**On wanting something audible in the first two days.** The only candidate is a tom voice,
and it would trigger 24 synthesised toms on a record with no toms until X0R-1314's presence
test exists. I recommend against it; the mid-sprint audition is the better answer, and it is
the first time in this app's history that one drum can be soloed against another record's
same drum.

---

## What is deliberately not in this sprint

| Not now | Pts | Why |
|---|---|---|
| **X0R-1309 · kit chosen by the reference** | 2 | Needs the fingerprint, which is stage 1, which this sprint does not build. Ungated now; its ceiling is one of three synthesised kits, so it moves the measured gap by ~0.09 dB. |
| **X0R-1310 · a tom voice** | 2 | Re-scoped down from 3 (see the retraction below) and parked behind X0R-1314's presence test. Built first, it puts synthesised toms on records that have none. First card in sprint 3 if the presence test lands clean. |
| **X0R-1311 · pattern hits the reference has and you do not** | 2 | Newly *buildable* — the kick returns 60 strokes at every gate. Still out: it is the only card in the epic that places a drum where the user did not play one, and it needs both files read against **one** grid (Experiment 2 §3) or it measures the ruler. That is a decision about composing someone's song and should be taken on its own. |
| **Cymbal re-voicing (crash, ride)** | — | **Retracted outright.** One cymbals stem holds hats, rides and crashes together, so they cannot be voiced apart; and a filtered noise burst is a credible closed hat and not a credible crash. The proposal's own synthesised-guitar argument, applied to cymbals. |
| **Stage 1 · the fingerprint** | 5 | Slips again, for a new reason: per-drum comparison reads none of it. Experiment 2 already made stage 1 conditional on X0R-1307/1308 being sprinted; they are not. |
| **Stage 2 · genre** | 5 | Dead, three documents running. |
| **Stage 5 · bass re-performance** | 6 | Gated on X0R-306, unchanged, and the gate is doing its job. |
| **X0R-306 · the benchmark** | 5 | Should lead sprint 3. It no longer gates drums and it has gained a reason: it is what turns `QUIET_STROKE_DB` and DrumSep's bleed from judgements into numbers. |
| **X0R-412 · sample-accurate hit times** | 2 | Not needed by anything here. Stays as the tripwire for the first card that measures groove. |
| **X0R-1308 · sidechain duck** | 3 | Gets better kick times from the separated kick. That is not why it abstained — it abstained because the per-kick bass dips varied by 8–18 dB, which is about the bass envelope and the control measurement. Improved, not fixed. |
| **X0R-1306 · the clamp budget** | 3 | Experiment 2's best-measured headroom in the processing half (1.07 dB at ×2 clamps against 0.56 dB for the whole strength sweep). A whole-mix card in a sprint about one instrument; top of sprint 3's list with X0R-306. |

---

## Risks

| Risk | Early signal | Mitigation |
|---|---|---|
| **R1 · `QUIET_STROKE_DB` is a judgement, not a discovery.** The module says so: the kick has no knee because every stroke is identical, the cymbals have one at about −14 dB, and **the snare has none at all** — it slopes smoothly from backbeat into bleed, so snare counts run 4 → 45 across the gate's range. Any card resting on stroke counts rests on that. | The developer reaching for a stroke count to decide whether a drum is present, or QA seeing a presence verdict that changes when the clip changes. | Nothing in this sprint may read a stroke count. Presence is energy relative to the drums stem; findings are continuous band energy and level. Written into X0R-1314 criterion 6 as the rule, not as advice. |
| **R2 · bleed is unmeasured.** A kick leaves a trace in the snare file. A finding "your snare has more weight than theirs" may be a louder kick on your record. | A snare low-band gap that tracks the kick's level gap across different pairs. | `QUIET_BAND_DB` already withholds lifts into near-empty bands. X0R-1314 criterion 8 puts the caveat on every finding with its figure. X0R-306 turns this into a number; until then the product says so rather than implying clean stems. |
| **R3 · cost.** The per-drum pass is about half the audio's length again, per side, on CPU — minutes on a 3½-minute song, on top of a comparison that already reads twelve stems end to end. | The comparison job passing two minutes on a 30-second clip. | Opt-in, following the `DRUMSEP_ENABLED` precedent; cached per track; and carried in profiles (X0R-1317) so the reference side is paid once ever. The job states its cost before it starts. |
| **R4 · QA setup cost, carried forward.** QA's sprint-1 report named this as the single thing that would most reduce the next pass: nothing persists, and four cards cost three separations. This sprint adds two more separations per verification. | QA's first report leading with setup time again. | The developer hands QA one short clip pair, the 167 MB weights already in place, and a note saying which criteria can be checked on one separation. A handover obligation, not a card. |
| **R5 · it lands on the screen that failed QA last sprint.** Every card here renders into the instrument comparison, which sprint 1's final pass failed on a blocker (D16) and a major (D17). | The instrument comparison not rendering on day one. | Confirm the sprint-1 retest is green before X0R-1314 starts. A precondition, not a mitigation. |
| **R6 · reconstruction changes the drums when nothing was asked for.** Four sub-stems plus residual re-summed is not automatically the file you started with, and `_apply_as_correction` already has a test guarding the analogous mistake one level up. | A null-move export differing from today's. | X0R-1315 criterion 3, and it is the one criterion on that card that is not negotiable. |
| **R7 · the output disappoints because it is not "remix".** Tone moves, groove does not, and this sprint moves tone on four drums instead of one bus. | Ryan asking why the drums do not feel like the reference's drums. | Say it in the product, not only here: X0R-1316 criterion 4 puts "this reinforces the strokes already there and moves none of them" on screen. Sold as *your kick compared to their kick*, never as *their drums*. |
| **R8 · the nested card makes a crowded screen worse**, one sprint after 5 points were spent on exactly that. | QA or Ryan describing the drums card as busy. | Decision A: one named expander, closed by default, saying what is inside before it is opened — the pattern X0R-1108 established and QA verified. Four sibling cards would read as nine instruments and are explicitly rejected. |

---

## What a user will be able to say at the end of this sprint

> "That record's kick sits 2.3 dB further forward than mine and has 1.8 dB more weight under
> 120 Hz; its snare is 2 dB brighter and 3 dB less compressed than mine. I took the kick's
> weight and half its level, left the snare alone, and I heard both kicks on their own
> before I decided."

Not available anywhere, in any product, at any price.

And the sentence this sprint is **not** for, so nobody is surprised: *"my drums now sound
like that record's drums."* They will not. Tone moves by a measured fraction; the groove is
the one Ryan played.
