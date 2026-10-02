# Sprint 1 — Fewer things on screen, each one explained

First sprint of the three-role loop set up in [TEAM.md](../TEAM.md) on 2026-10-01. Not the
same thing as "Sprint 1" in [ROADMAP.md](../ROADMAP.md), which was the Phase 1 ML sprint
and is long finished. The roadmap's numbering is historical; sprint plans live here now.

**11 points · 4 cards · one developer, one QA.**

---

## Sprint goal

A person can reach a finished master from the mastering page by making four decisions
instead of scanning nineteen sliders — with nothing removed, and everything that moved
findable by name.

---

## Why this, now

Ryan's most-repeated piece of feedback in the project's history is that the tool is getting
harder to use: *"I want this to be simple and user friendly and i feel as if its getting
more and more complicated. i feel like i am leading you down a path of churn."* The backlog
has 47 TODO cards and not one of them is that. X0R-1108 is the closest and it has sat
untouched since Phase 2 planning.

The complaint is measurable. Counted in `apps/studio/wwwroot/index.html`, the mastering
page between the comparison card and the export button holds:

| | count |
|---|---|
| labelled controls in one flat `.controls` grid | **19** |
| sliders | 16 |
| dropdowns | 5 |
| checkboxes | 9 |
| buttons (incl. 7 "Start from" presets) | 17 |

Every one of those was added for a real reason, and several have two- and three-sentence
`title` tooltips explaining the physics. The problem is not that any single control is
wrong. It is that they arrive all at once, in one undifferentiated grid, with no statement
of which four matter and which fifteen are for the day you want them.

Competitor research (below) found this to be the one thing the whole category agrees on,
and extract0r is the outlier by an order of magnitude.

Second reason for this sprint's shape: about 1,080 lines of good work are sitting
uncommitted, five of the fifteen touched files are browser-facing, and none of it has been
opened in a browser by anyone except the developer who wrote it. The sprint starts by
closing that out, because every other card in the sprint edits the same files.

---

## Decision 1 — the uncommitted work gets a card, and goes first

**It gets a card. 2 points, first in the sprint.**

The argument for skipping it is real: 759 tests pass, the suite exits clean, and the
module docstrings are unusually careful. Spending QA on work that already has tests looks
like overhead.

It does not survive contact with what the diff actually contains.

- **The riskiest changes are the ones unit tests structurally cannot reach.**
  `apps/studio/wwwroot/instruments.js` now unhides the instrument panel on
  `state.usingProfile && state.profileHasInstruments`, and omits the "▶ theirs" button
  when `instrument.reference_audio === false`. Those are conditional UI paths. A green
  pytest run says nothing about either.
- **There is a backward-compatibility path nobody has walked.** Profiles saved before this
  change carry no per-stem data. A profile saved last week, loaded today, must drive the
  whole-mix match and must *not* offer an instrument comparison it cannot deliver. One
  minute in a browser settles it; a test suite only settles it if someone thought to write
  that test.
- **The spectrum panel is a canvas with auto-scaling and a hover readout.** That is exactly
  the class of feature that is green in tests and wrong on screen — curves off the top of
  the viewport, a readout one pixel out, a legend that does not match the lines.
- **It unblocks the commit.** Ryan commits when he asks, and he will ask about this work.
  A browser pass is what turns "yes, commit it" into a decision rather than a hope.

Scoped tightly so it cannot eat the sprint: two features and one compatibility path.
**Not** a regression sweep of the whole application, and **not** the pytest segfault fix —
that one has no user-visible surface and the suite exiting clean *is* its verification.

---

## Decision 2 — usability wins this sprint, outright

Ryan has asked for two things that pull against each other: more power (he asked what the
app lacks versus Ozone, which produced EPIC-12) and less complexity. **Usability wins, and
not as a compromise — it is the higher-value capability work right now.**

Four reasons.

**1. EPIC-12 as written would make the stated problem worse.** Dither, true-peak limiting,
dynamic EQ, multiband dynamics, time-varying metering, genre curves and mid/side are
twenty-three points that, built as specified, add between four and ten new controls to the
same flat grid the user is already complaining about. The sprint that shipped them would
close the Ozone gap and widen the one Ryan actually named.

**2. The whole category disagrees with the current design.** Matchering ships zero
controls. LANDR's online tool ships a Style choice, an Intensity choice and a Loudness
target; its SE plugin ships one knob. eMastered ships three. Ozone — the most capable
mastering product that exists — opens on six match macros and a genre dropdown, and puts
*everything else* behind a single button. extract0r opens on nineteen. Nobody who has
solved this problem commercially solved it the way this page is built.

**3. The capability Ryan keeps asking for is already built and buried.** His most-repeated
*sonic* request is *"more up front and less verby... tight, concise, and focused. not muddy
and spread out."* That is already measured, honestly, in two places:
`app/services/mastering/clarity.py` measures per-band congestion and contrast (and its
docstring records the measurement that disproved the obvious theory — the professional mix
overlapped *more*, 0.616 against 0.406; what differed was 3.0 stems' worth of energy
crowding 2–4 kHz against the reference's 1.3). `app/services/mastering/space.py` estimates
per-instrument wetness and `critique.py:428` renders it as "your vocal sounds wetter than
the reference's". The tool can already tell him the thing he keeps asking about. The gap is
not measurement. It is that the finding is one row among dozens on a page he finds
overwhelming. Building more DSP does not help a user who cannot find the DSP that exists.

**4. The thing this product is actually better at is explanation, and explanation is
rationed by attention.** The governing brief is a *nudge* — every suggestion is a fraction
of a measured gap, stated with what was measured and why. A user who skims nineteen sliders
reads none of those sentences. Each control added past the point of comprehension does not
just fail to help; it costs the ones already there.

**Where the position is not absolute.** One EPIC-12 card ships this sprint: **X0R-1201,
dither, 1 point, zero new controls.** Thirty lines, fixes a genuinely audible defect in the
quiet passages of every export, and costs nothing from the complexity budget. That is the
shape capability work should take while this is going on — sonic improvement with no new
surface. X0R-1202 (true-peak limiting) is the same shape and the best remaining card on
the list, deferred only because three points would crowd out the restructure.

---

## Cards

### X0R-1123 · Verify the unreviewed work in a browser · 2

**The problem.** Two user-visible features and one backward-compatibility path exist only
as code that passes tests. Nobody has used them.

The two features are now recorded in the backlog as `PARTIAL` cards whose one remaining
criterion is this one: **X0R-1125** (per-instrument measurements in a profile) and
**X0R-808** (three songs on one axis). They were built without cards; the cards exist now so
the work is traceable and so the next person does not have to read a diff to find out what
shipped.

**Acceptance criteria** — all checkable in a browser:

1. Capture a profile from a reference that **was** separated. The save box states, before
   the click, that the profile will include its instruments. After saving, the profile's
   row in the picker reads "N instruments" rather than "whole mix only".
2. Capture a profile from a reference that was **not** separated. The save box states that
   its instruments will not be included and says how to change that. Its row reads "whole
   mix only".
3. Start a fresh song, aim it at an instrument-carrying profile, and arrive at the
   instrument comparison **without a second split**: the "Reading every stem on both sides"
   wait does not appear, and every instrument shows its findings and dials.
4. On that screen, "▶ theirs" is **absent** (not present-and-disabled) on every instrument,
   and a line above the cards explains that a profile keeps measurements, not music.
   "▶ yours" still plays.
5. Aim a song at a profile saved **before** this change — one with no per-stem data. The
   whole-mix match still works end to end to a downloadable MP3, and the instrument
   comparison is either absent or refused with a stated reason. It never appears empty or
   broken.
6. Export a master with a reference loaded. The "How the tone lines up" panel draws three
   named curves. Every curve stays inside the chart at both ends. The Balance / Difference
   chips both change what is drawn. Hovering reports a frequency and a value per curve that
   track the pointer.
7. The key names each curve, and the panel states that levels were matched before
   comparison and reports the shift applied per curve.

**Out of scope.** A regression sweep of the rest of the app. The pytest segfault fix.
Judgements about whether the spectrum panel should be designed differently — that is
X0R-809 and deliberately not this sprint.

---

### X0R-1108 · One page, four decisions, and a door · 5 *(re-scoped)*

**The problem.** The mastering page presents 19 controls in one flat grid with no
hierarchy. A user who wants the match and the export has to read all of it to find out that
15 of them are optional. The card previously specified two *modes*; that is re-scoped —
see below.

**What changes.** The page opens on the short list. Everything else moves into named,
collapsed groups on the same page. Nothing is removed and nothing changes what it does.

Default view, above the export button:
- **Start from** — "Suggested" and "Flat" only. The two real choices: take the measured
  suggestion, or take nothing.
- **Match strength**
- **Vocal presence**
- **Bitrate**
- **Master and export MP3**

Collapsed groups, each with a name and one line saying what it is for:
- **Tone** — bass, warmth, brightness, brightness-from, sparkle, sparkle-focus, and the
  five taste presets (Brighten, Bassier, Warmer, Punchier, Wider) moved off the top row.
- **Space and stereo** — centre the bass, side air, match reference image, stereo width,
  ambience.
- **Dynamics and level** — duck under vocal, saturation, parallel glue, extra headroom, cut
  subsonics.
- **Export options** — keep the original underneath, lay a kit over the drums.

**Acceptance criteria** — all checkable in a browser:

1. On a freshly loaded mastering page with a reference in place, **at most six interactive
   controls** are visible between the comparison card and the Master button. The rest are
   inside collapsed groups.
2. Every group is closed on first load, shows its name, and shows one sentence saying what
   it is for without being opened.
3. Opening a group reveals the controls listed for it above. Every one of the 19 original
   controls is inside the default view or exactly one group — none is missing, none appears
   twice.
4. Each control behaves identically to before: same range, same readout text, same tooltip.
   A value set inside a group and then collapsed is still in effect, and the group's header
   says that it has been changed from default.
5. Which groups are open survives a page reload. Values survive a page reload as they do
   today.
6. The live monitor still responds. With a reference separated, move a tone slider inside
   the Tone group while a stem is auditioning and the change is audible without a
   re-render, as it is today.
7. A master exported with every group left closed produces the same file as a master
   exported today with every control at its default.
8. The seven-button "Start from" row no longer sits at the top; "Suggested" and "Flat" do,
   and the other five are inside Tone.

**Out of scope — and a change from the card as written.** No second mode, no "basic /
advanced" toggle, no separate code path. The original card asked for two modes with
persistence and "switching does not silently discard settings"; that criterion exists
because two modes are a trap. Progressive disclosure on one page delivers the same outcome
without a second rendering path and without a state-loss bug to prevent. Also out of
scope: changing any control's range, default, wording or DSP. This card moves DOM and adds
disclosure. Nothing else.

---

### X0R-1124 · Hear one band, on both sides · 3

**The problem.** A tone finding says "the reference's drums have more presence" and offers
a dial. The user can play their drums and can play the reference's drums, but presence is
one of five bands inside each, and the whole stem is what plays. Deciding whether a finding
is real means hearing the band the finding is about.

Borrowed directly from Metric AB, whose filter bank solos Sub / Bass / Low Mid / Mid /
High on the mix *and* the reference simultaneously — the one feature competitor research
turned up that this product does not have and clearly should.

**Acceptance criteria** — all checkable in a browser:

1. While an audition is playing (either side), a strip of band chips appears on that
   instrument's card: the five bands the comparison already uses, plus "all".
2. Clicking a band chip restricts what is playing to that band, within a second, without
   restarting playback from the beginning.
3. The same chip applies to both sides: switch from "▶ yours" to "▶ theirs" with
   "presence" selected and the reference plays the presence band only.
4. "All" returns to the full stem. Stopping the audition clears the band selection, so the
   next thing played is not silently filtered.
5. The chips are labelled with the same five band names used in the findings text, and each
   states its frequency range on hover.
6. The strip is only present while something is auditioning. A card that is not playing
   shows no band chips.

**Out of scope.** Adjustable crossovers or filter slopes — Metric AB has them and they are
a mastering engineer's control, not a "is this finding real" control. Band soloing on the
whole-mix stage or on the finished master. Any change to what the dials do.

---

### X0R-1201 · Dither on export · 1

Taken from EPIC-12 unchanged. See the card in [BACKLOG.md](../BACKLOG.md) for the reasoning
and the full criteria. It ships this sprint because it improves the sound of every export
and adds no control to the screen.

**Acceptance criteria that QA verifies in a browser:**

1. The master result card states the output bit depth and that dither was applied.
2. Export a quiet fade-out and play it back in the browser's own player: no gritty edge
   under the tail.

**Honestly stated exception.** The card's real criterion — a measured noise floor on a
dithered fade against a truncated one — cannot be checked in a browser. That one is a
test, and the developer shows it with the card. QA accepts this card on the stated line and
the listen, not on the measurement. It is the only card in the sprint with that caveat, and
it is why the card is one point rather than three.

---

## Sequencing

1. **X0R-1123 first.** Everything else edits `app.js`, `index.html` and `styles.css`.
   Verify the unreviewed work *before* restructuring, or a defect found in week two cannot
   be attributed to either change.
2. **X0R-1108 second.** The sprint's reason for existing, and the card needing the most QA
   time. Starting it in week one leaves room for a second QA pass.
3. **X0R-1124 third.** Touches the instrument card, which X0R-1108 does not, so it can
   overlap the tail of the restructure safely.
4. **X0R-1201 last.** Server-side and independent of all three. This is the designated card
   to drop if the sprint runs short.

---

## What is deliberately not in this sprint

**From EPIC-12:**

| Card | Points | Why not now |
|---|---|---|
| X0R-1202 true-peak limiting | 3 | The best remaining card on the list and the first one into sprint 2. It buys back a decibel the current limiter gives away. Deferred because it adds a decibel, not a decision, and this sprint is about decisions. |
| X0R-1203 dynamic EQ | 5 | The biggest sonic gap, and a serious build. It also adds a per-band control set to a page being rebuilt. Build the shelf before the thing that goes on it. |
| X0R-1204 multiband dynamics | 5 | Same per-band detector as X0R-1203; building them separately builds it twice. Pair them in a later sprint. |
| X0R-1205 metering | 3 | Adds a second time-varying display to the master card before the first one (the spectrum panel) has been through QA. That is the definition of churn. |
| X0R-1206 genre target curves | 3 | Solves "I have no reference to hand", which is not Ryan's problem — X0R-1121 already picks one from his own library, and a profile from a song he admires beats a published average. Tonal Balance Control's 12 curves are averages of decades of records; EPIC-12 already says this app has something better in kind. |
| X0R-1207 mid/side everywhere | 3 | A third place in the app to think about stereo width, on the page being simplified. |

**Priority order disagreement with EPIC-12, stated plainly.** The epic lists dither first
and I agree — it is the smallest real gap and the only one that costs nothing in
complexity. I disagree with nothing in the epic's ordering except its implicit premise that
the list should be worked top to bottom starting now. X0R-1203 is correctly identified as
the biggest sonic gap; it is still the wrong card for a sprint whose goal is fewer things
on screen.

**Other open cards left out:**

- **X0R-1110 American spelling (1)** — renames identifiers in the public API
  (`centre_bass_hz`) and the browser code in the same sprint that is restructuring the
  browser code. Low value, non-trivial chance of silently breaking the live monitor. Do it
  in a sprint that is not touching these files.
- **X0R-1111 dead-code audit (2)**, **X0R-1112 naming in export metadata (1)** —
  housekeeping with no user-visible outcome. They will keep.
- **X0R-1120 narrated walkthrough (3)** — blocked on tooling that does not exist in this
  environment, by its own card. The captioned tour from X0R-1109 covers the same ground.
- **EPIC-07 entirely** (Postgres, Redis, object storage, accounts — 21 points) — this is a
  local-first personal tool. No user has asked, and the constraint in the role definition
  says profiles and audio stay local. These cards should probably be marked as non-goals
  rather than left sitting as TODO; that is a backlog-hygiene job for next sprint.
- **A target-range view on the spectrum panel (new card X0R-809)** — Tonal Balance
  Control's Broad View draws the target as a *range* and asks only whether your line is
  inside it, which is easier to read than three overlapping curves. It is a genuinely
  better idea than what was just built. It is also a redesign of a panel Ryan asked for by
  name last week and that QA has not yet seen. Backlogged, not sprinted. Rebuilding
  something a week after shipping it is precisely the churn he described.

---

## Risks

| Risk | Early signal | Mitigation |
|---|---|---|
| The restructure breaks the Web Audio monitor. X0R-1107 wires the live monitor to control ids in `app.js`; moving controls in the DOM can silently desync it. | A tone slider inside the Tone group no longer changes what is playing. | Keep every control's `id` unchanged — this card moves DOM and adds disclosure, nothing more. Criterion 6 on X0R-1108 tests exactly this. |
| The first QA pass returns a long defect list and consumes the sprint. This is the first sprint with a real QA gate; there is no baseline for how much it returns. | More than five defects from X0R-1123. | X0R-1201 is the designated drop. If the list runs past ten, X0R-1124 goes too and the sprint becomes two cards that finish. |
| Decluttering reads as a regression. A control Ryan uses every session disappears into a group he does not think to open. | Ryan asking where something went. | Nothing is removed; groups are named for what is in them; a changed-from-default group says so on its header; open/closed state persists, so a group he uses stays open after the first time. |
| 11 points is under the historical 20 and the sprint finishes early. | Both usability cards verified by the end of week one. | Pull X0R-1202 (true-peak limiting, 3) forward. It is independent and server-side. |

---

## Competitor research

Ozone was already covered in EPIC-12. This covers the six that were not, and the question
they were asked: **how does each one handle "simple by default, deep when you want it"?**

The answer is uncannily consistent.

| Product | Controls in front of the user | The door to more |
|---|---|---|
| Matchering (open source) | **0.** The reference is the only control. | None. Load a different reference. |
| LANDR Mastering SE | **1** — a Loudness knob, plus input level and bypass. | Upgrade to Pro. |
| LANDR online | **3** — Style (3 choices), Intensity (low/med/high), Loudness target. | The Pro plugin: 3-band EQ, presence, de-esser, stereo field, compression, character, saturation, loudness. |
| eMastered | **3** — intensity, EQ, stereo width, applied after the master. | None. |
| iZotope Ozone 12 | **~8** — Tonal Balance, Loudness, Dynamic Match, Width Match, Clarity Amount, Stabilizer Amount, Vocal Balance, and a genre/reference dropdown. | One button — "Enter the Ozone" — to the full module chain. |
| Tonal Balance Control 2 | A display, not controls. 12 target curves. | Broad View (4 bands) ⇄ Fine View (full spectrum). |
| REFERENCE 2 | A display. Up to 12 references, level-matched. | "Trinity Display": level line, stereo width, punch dots. |
| Metric AB | A display. Up to 16 references, 4 loudness-match modes. | 5 metering modes; a filter bank soloing Sub/Bass/LowMid/Mid/High on mix and reference at once. |
| **extract0r today** | **19** labelled controls, 16 of them sliders, in one flat grid. | — there is no door; it is all door. |

**Worth borrowing.**

1. **Ozone's shape, which is the single most important finding.** Its macros are not DSP
   parameters — they are named as *how much of the match to take*: Tonal Balance, Dynamic
   Match, Width Match. Then one button to everything else. extract0r already has the macro
   (Match strength) and the taste presets; what it lacks is the door, so the macros sit in
   the middle of the thing they were meant to replace. This is X0R-1108 and it is why that
   card is re-scoped to disclosure rather than modes.
2. **Metric AB's band solo on both sides at once.** The best concrete feature found. This
   product already has five bands, already has per-side auditions, and already starts each
   audition at its own busiest stretch (X0R-1116). Making the audition band-filterable
   turns a number into something a user can confirm by ear before applying it, which is
   exactly what a nudge-not-copy tool should let them do. → **X0R-1124**.
3. **Tonal Balance Control's target as a range, not a line.** Broad View shows four bands
   with the target as a blue band and your mix as a white line, and the instruction is
   simply "move until the line is inside the band". That is a far lower reading cost than
   three overlapping curves. → **X0R-809**, backlogged, deliberately not this sprint.
4. **Loudness matching before any comparison, unconditionally.** REFERENCE 2 and Metric AB
   both treat it as non-negotiable, and REFERENCE 2 offers exactly the choice between "the
   curve needed to match" and "the inverted difference". The uncommitted
   `spectrum_view.py` already matches levels per curve, reports the shift applied, and
   ships a Balance / Difference toggle. That is independent convergence on the category
   standard. **No work needed — it is already right.**

**Not worth borrowing.**

- **Genre target curves as a priority.** TBC's 12 curves are averages across decades of
  records. A profile captured from a specific song Ryan admires is better in kind, and
  X0R-1121 already finds candidates in his own library. X0R-1206 is for a user who has no
  reference; that user is not this user.
- **Multiple simultaneous references** (REFERENCE 2's 12, Metric AB's 16). Feature count.
  Nobody has asked, and the per-instrument comparison does not get better by comparing
  against four songs at once — it gets harder to explain.
- **Ozone 12's Stem EQ, and this is worth saying clearly.** Ozone now splits a stereo mix
  into Vocal / Drums / Bass / Other — four stems — and offers an 8-band EQ per stem. That
  is the closest any competitor has come to this product's territory, and it stops well
  short: four stems against six, EQ only against level/tone/dynamics/width/placement, and
  no comparison with a reference's corresponding stem at all. Ozone still cannot tell you
  what *their* snare does that *your* snare does not. **The moat is intact.** It does not
  need defending this sprint.
- **eMastered's and LANDR's post-hoc shape sliders.** Both bolt taste controls onto an
  opaque decision. This product's advantage is that the decision is explained; adding taste
  sliders on top of explained suggestions is, structurally, how the current 19-control page
  came to exist. Resist the pattern even though it is everywhere.

**Headline.** Every tool in this category puts between zero and eight controls in front of
the user and hides the rest behind one door. extract0r puts nineteen in front and has no
door. Its real advantage — per-instrument comparison with explanations, which none of these
products has in any form — is spent on a page too dense for anyone to read the explanations
on.
